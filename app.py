import os
import asyncio
import json
import websockets
from urllib.parse import urlencode
import pyaudio
import socketio
from dotenv import load_dotenv
from collections import deque, Counter
import logging
import time
from translate import translate_text_deepl, deepl_language
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import wave
import speech_recognition as sr
from googletrans import Translator
import numpy as np
import uuid
from deepgram import Deepgram
from queue import Queue
import threading

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# Get port from environment variable with fallback to 5002
PORT = int(os.getenv('PORT', 5002))
HOST = os.getenv('HOST', '0.0.0.0')

# Audio settings
RATE = 16000
CHUNK = RATE // 10  # 100ms chunks

# Initialize Deepgram client
DEEPGRAM_API_KEY = os.getenv('DEEPGRAM_API_KEY')
dg_client = Deepgram(DEEPGRAM_API_KEY) if DEEPGRAM_API_KEY else None

# Initialize translator
translator = Translator()

# Store active sessions
active_sessions = {}

class MicrophoneStream:
    """Opens a recording stream as a generator yielding the audio chunks."""
    def __init__(self, rate=RATE, chunk=CHUNK):
        self._rate = rate
        self._chunk = chunk
        self._audio_interface = None
        self._audio_stream = None
        self._stream = None
        self._audio_buffer = asyncio.Queue()  # Initialize the buffer in __init__
        self._is_simulated = False
        self._fallback_audio = None
        self._fallback_position = 0
        self._fallback_chunk_size = chunk
        self._fallback_sample_rate = rate

    async def __aenter__(self):
        try:
            self._audio_interface = pyaudio.PyAudio()
            self._audio_stream = self._audio_interface.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self._rate,
                input=True,
                frames_per_buffer=self._chunk,
                stream_callback=self._fill_buffer,
            )
            self._audio_stream.start_stream()
            logger.info("Audio stream started successfully")
            return self
        except (ValueError, SystemError, OSError) as e:
            logger.warning(f"Failed to initialize audio stream: {str(e)}")
            logger.info("Falling back to simulated audio")
            self._is_simulated = True
            self._load_fallback_audio()
            return self

    def _load_fallback_audio(self):
        """Load the fallback audio file for simulation"""
        try:
            fallback_path = os.path.join("static", "audio", "hello_world.wav")
            if os.path.exists(fallback_path):
                with wave.open(fallback_path, 'rb') as wf:
                    self._fallback_audio = wf.readframes(wf.getnframes())
                    self._fallback_sample_rate = wf.getframerate()
                    logger.info(f"Loaded fallback audio file: {fallback_path}")
            else:
                logger.warning(f"Fallback audio file not found: {fallback_path}")
                self._simulate_audio()
        except Exception as e:
            logger.error(f"Error loading fallback audio: {str(e)}")
            self._simulate_audio()

    def _simulate_audio(self):
        """Generate simulated audio data when no real audio device is available"""
        logger.info("Generating simulated audio data")
        # Generate a simple sine wave as a last resort
        t = np.linspace(0, 1, self._fallback_sample_rate, False)
        audio = np.sin(2 * np.pi * 440 * t)  # 440 Hz tone
        audio = (audio * 32767).astype(np.int16)
        self._fallback_audio = audio.tobytes()
        logger.info("Generated simulated audio data")

    async def _fill_buffer(self, in_data, frame_count, time_info, status):
        """Callback for the audio stream to fill the buffer"""
        if self._is_simulated:
            # Use the fallback audio file
            if self._fallback_audio:
                chunk_size = self._fallback_chunk_size * 2  # 2 bytes per sample (16-bit)
                if self._fallback_position + chunk_size <= len(self._fallback_audio):
                    chunk = self._fallback_audio[self._fallback_position:self._fallback_position + chunk_size]
                    self._fallback_position += chunk_size
                else:
                    # Loop back to the beginning
                    self._fallback_position = 0
                    chunk = self._fallback_audio[self._fallback_position:self._fallback_position + chunk_size]
                    self._fallback_position += chunk_size
                
                await self._audio_buffer.put(chunk)
            return (None, pyaudio.paContinue)
        else:
            await self._audio_buffer.put(in_data)
            return (None, pyaudio.paContinue)

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if not self._is_simulated and self._audio_stream:
            self._audio_stream.stop_stream()
            self._audio_stream.close()
            self._audio_interface.terminate()
            logger.info("Audio stream closed")
        else:
            logger.info("Simulated audio stream closed")

    async def generator(self):
        """Generate audio data from the buffer"""
        while True:
            try:
                data = await self._audio_buffer.get()
                yield data
            except Exception as e:
                logger.error(f"Error in audio generator: {str(e)}")
                break

# Initialize Flask and SocketIO
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key')
sio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*")

# Store active streams and tasks
streams = {}
listen_tasks = {}

async def consumer(transcript_queue, session_id, source_lang, target_lang):
    """Process transcripts and translate them"""
    try:
        # Keep track of the last few transcripts for context
        transcript_history = []
        
        while True:
            # Get the next transcript
            transcript, is_final = await transcript_queue.get()
            
            # Log the source and target languages
            logger.info(f"Processing transcript with source_lang: {source_lang}, target_lang: {target_lang}")
            
            # Check if the source language is supported
            if source_lang not in ['en', 'es', 'fr', 'de', 'it', 'pt', 'nl', 'pl', 'ru', 'ja', 'ko', 'zh']:
                logger.warning(f"Unsupported source language: {source_lang}, defaulting to 'en'")
                source_lang = 'en'
            
            # Check if the target language is supported
            if target_lang not in ['en', 'es', 'fr', 'de', 'it', 'pt', 'nl', 'pl', 'ru', 'ja', 'ko', 'zh']:
                logger.warning(f"Unsupported target language: {target_lang}, defaulting to 'es'")
                target_lang = 'es'
            
            # Add to history if it's a final transcript
            if is_final and transcript.strip():
                transcript_history.append(transcript)
                if len(transcript_history) > 3:  # Keep only the last 3 transcripts
                    transcript_history.pop(0)
            
            # Emit the recognition result
            sio.emit('recognition', {
                'text': transcript,
                'is_final': is_final
            }, room=session_id)
            
            # If it's a final transcript, translate it
            if is_final and transcript.strip():
                try:
                    # Get the context from previous transcripts
                    context = " ".join(transcript_history)
                    
                    # Translate the text
                    translation = translator.translate(transcript, src=source_lang, dest=target_lang)
                    
                    # Emit the translation
                    sio.emit('translation', {
                        'text': translation.text,
                        'source_lang': source_lang,
                        'target_lang': target_lang
                    }, room=session_id)
                    
                    logger.info(f"Translated: '{transcript}' -> '{translation.text}'")
                except Exception as e:
                    logger.error(f"Translation error: {str(e)}")
                    sio.emit('error', {'message': f'Translation error: {str(e)}'}, room=session_id)
            
            # Mark the task as done
            transcript_queue.task_done()
    except asyncio.CancelledError:
        logger.info(f"Consumer task for session {session_id} was cancelled")
    except Exception as e:
        logger.error(f"Error in consumer: {str(e)}")
        sio.emit('error', {'message': f'Error in transcript processing: {str(e)}'}, room=session_id)

async def sender(ws, stream):
    """Send audio data to Deepgram WebSocket."""
    try:
        logger.info("Starting sender task")
        chunk_count = 0
        async for chunk in stream.generator():
            if stream._stream.is_stopped():
                logger.info("Stream closed, stopping sender")
                break
            chunk_count += 1
            if chunk_count % 10 == 0:  # Log every 10th chunk to avoid flooding logs
                logger.info(f"Sent {chunk_count} audio chunks to Deepgram")
            await ws.send(chunk)
        logger.info(f"Sender task completed after sending {chunk_count} chunks")
    except Exception as e:
        logger.error(f"Error in sender: {e}")
        import traceback
        logger.error(traceback.format_exc())

async def receiver(ws, queue):
    """Receive transcriptions from Deepgram WebSocket."""
    try:
        logger.info("Starting receiver task")
        async for msg in ws:
            logger.info(f"Received message from Deepgram: {msg[:100]}...")  # Log first 100 chars
            res = json.loads(msg)
            
            transcript = res.get("channel", {}).get("alternatives", [{}])[0].get("transcript", "")
            
            if not transcript:
                logger.info("Empty transcript received from Deepgram")
                continue
                
            logger.info(f"Extracted transcript: '{transcript}'")
            
            # Check if we have words with speaker information
            words = res.get("channel", {}).get("alternatives", [{}])[0].get("words", [])
            if not words:
                logger.info("No words with speaker information found")
                # Use a default speaker if none is found
                speaker = "unknown"
            else:
                counter = Counter([x.get("speaker", "unknown") for x in words])
                speaker = counter.most_common(1)[0][0]
                logger.info(f"Speaker identified: {speaker}")
            
            is_final = bool(res.get("is_final", False))
            logger.info(f"Is final: {is_final}")
            
            if queue.full():
                logger.info("Queue is full, removing oldest item")
                _ = await queue.get()
                queue.task_done()
                
            logger.info(f"Putting transcript in queue: '{transcript}' (speaker: {speaker}, final: {is_final})")
            await queue.put((speaker, transcript, is_final))
            
    except Exception as e:
        logger.error(f"Error in receiver: {e}")
        import traceback
        logger.error(traceback.format_exc())

@app.route('/')
def index():
    """Render the main page"""
    return render_template('index.html')

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok'})

@sio.on('connect')
def handle_connect():
    """Handle client connection"""
    logger.info(f"Client connected: {request.sid}")
    emit('connected', {'data': 'Connected'})

@sio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    logger.info(f"Client disconnected: {request.sid}")
    
    # Clean up the session if it exists
    if request.sid in active_sessions:
        session_data = active_sessions[request.sid]
        
        # Cancel the consumer task
        if 'consumer_task' in session_data and not session_data['consumer_task'].done():
            session_data['consumer_task'].cancel()
        
        # Close the Deepgram WebSocket
        if 'deepgram_socket' in session_data and session_data['deepgram_socket']:
            asyncio.create_task(session_data['deepgram_socket'].finish())
        
        # Close the microphone stream
        if 'stream' in session_data:
            asyncio.create_task(session_data['stream'].__aexit__(None, None, None))
        
        # Remove the session
        del active_sessions[request.sid]
        logger.info(f"Cleaned up session {request.sid}")

@sio.on('start_listening')
def start_listening(data=None):
    """Start listening for audio and processing it"""
    session_id = request.sid
    logger.info(f"Starting listening session for {session_id}")
    
    # Get language preferences from the data
    source_lang = data.get('source_lang', 'en') if data else 'en'
    target_lang = data.get('target_lang', 'es') if data else 'es'
    
    logger.info(f"Language preferences - Source: {source_lang}, Target: {target_lang}")
    
    # Start a background task to handle the async operations
    sio.start_background_task(handle_listening, session_id, source_lang, target_lang)

async def handle_listening(session_id, source_lang, target_lang):
    """Handle the listening session asynchronously"""
    try:
        # Create a queue for processing transcripts
        transcript_queue = asyncio.Queue()
        
        # Start a consumer task to process transcripts
        consumer_task = asyncio.create_task(consumer(transcript_queue, session_id, source_lang, target_lang))
        
        # Initialize the microphone stream
        stream = MicrophoneStream(RATE, CHUNK)
        await stream.__aenter__()
        
        # Connect to Deepgram WebSocket
        if not dg_client:
            logger.error("Deepgram API key not found")
            sio.emit('error', {'message': 'Deepgram API key not found'}, room=session_id)
            return
        
        # Create a WebSocket connection to Deepgram
        deepgram_socket = await dg_client.transcription.live({
            'encoding': 'linear16',
            'sample_rate': RATE,
            'channels': 1,
            'language': source_lang,
            'model': 'nova',
            'smart_format': True,
            'interim_results': True,
        })
        
        # Store the session information
        active_sessions[session_id] = {
            'stream': stream,
            'deepgram_socket': deepgram_socket,
            'consumer_task': consumer_task,
            'transcript_queue': transcript_queue,
            'source_lang': source_lang,
            'target_lang': target_lang
        }
        
        # Set up the message handler for Deepgram
        async def process_message(msg):
            try:
                data = json.loads(msg)
                if 'channel' in data and 'alternatives' in data['channel']:
                    transcript = data['channel']['alternatives'][0]['transcript']
                    is_final = data.get('is_final', False)
                    
                    if transcript.strip():
                        logger.info(f"Transcript: '{transcript}' (final: {is_final})")
                        await transcript_queue.put((transcript, is_final))
            except Exception as e:
                logger.error(f"Error processing Deepgram message: {str(e)}")
        
        # Set up the message handler
        deepgram_socket.registerHandler(process_message)
        
        # Start sending audio data to Deepgram
        async for audio_chunk in stream.generator():
            if deepgram_socket and deepgram_socket.is_connected():
                await deepgram_socket.send(audio_chunk)
            else:
                logger.error("Deepgram WebSocket disconnected")
                break
        
    except Exception as e:
        logger.error(f"Error in handle_listening: {str(e)}")
        sio.emit('error', {'message': f'Error in audio processing: {str(e)}'}, room=session_id)
    finally:
        # Clean up resources
        if session_id in active_sessions:
            session_data = active_sessions[session_id]
            
            # Cancel the consumer task
            if 'consumer_task' in session_data and not session_data['consumer_task'].done():
                session_data['consumer_task'].cancel()
                try:
                    await session_data['consumer_task']
                except asyncio.CancelledError:
                    pass
            
            # Close the Deepgram WebSocket
            if 'deepgram_socket' in session_data and session_data['deepgram_socket']:
                await session_data['deepgram_socket'].finish()
            
            # Close the microphone stream
            if 'stream' in session_data:
                await session_data['stream'].__aexit__(None, None, None)
            
            # Remove the session
            del active_sessions[session_id]
            logger.info(f"Cleaned up session {session_id}")

@sio.on('stop_listening')
def stop_listening():
    """Stop listening for audio"""
    session_id = request.sid
    logger.info(f"Stopping listening session for {session_id}")
    
    # Clean up the session
    if session_id in active_sessions:
        session_data = active_sessions[session_id]
        
        # Cancel the consumer task
        if 'consumer_task' in session_data and not session_data['consumer_task'].done():
            session_data['consumer_task'].cancel()
        
        # Close the Deepgram WebSocket
        if 'deepgram_socket' in session_data and session_data['deepgram_socket']:
            asyncio.create_task(session_data['deepgram_socket'].finish())
        
        # Close the microphone stream
        if 'stream' in session_data:
            asyncio.create_task(session_data['stream'].__aexit__(None, None, None))
        
        # Remove the session
        del active_sessions[session_id]
        logger.info(f"Stopped listening session for {session_id}")
    else:
        logger.warning(f"No active session found for {session_id}")

if __name__ == '__main__':
    # Check if the fallback audio file exists, if not, generate it
    fallback_path = os.path.join("static", "audio", "hello_world.wav")
    if not os.path.exists(fallback_path):
        os.makedirs(os.path.dirname(fallback_path), exist_ok=True)
        from generate_hello_world import generate_hello_world_audio
        generate_hello_world_audio(fallback_path)
        logger.info(f"Generated fallback audio file: {fallback_path}")
    
    # Run the application
    sio.run(app, host='0.0.0.0', port=8000, debug=True) 