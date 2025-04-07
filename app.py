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
from flask import Flask, render_template, request
from flask_socketio import SocketIO
import wave
import speech_recognition as sr
from googletrans import Translator

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

class MicrophoneStream:
    """Opens a recording stream as a generator yielding the audio chunks."""
    def __init__(self, rate=RATE, chunk=CHUNK):
        self._rate = rate
        self._chunk = chunk
        self.loop = asyncio.get_event_loop()
        
        # Create a thread-safe buffer of audio data
        self._buff = asyncio.Queue()
        self.closed = True
        self._audio_interface = None
        self._audio_stream = None

    async def __aenter__(self):
        try:
            self._audio_interface = pyaudio.PyAudio()
            
            # Open the audio stream
            self._audio_stream = self._audio_interface.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self._rate,
                input=True,
                frames_per_buffer=self._chunk,
                stream_callback=self._fill_buffer,
            )
            self.closed = False
            self._audio_stream.start_stream()
            return self
        except Exception as e:
            if self._audio_interface:
                self._audio_interface.terminate()
            raise RuntimeError(f"Failed to initialize audio stream: {str(e)}")

    async def __aexit__(self, *args):
        """Closes the stream, regardless of whether the connection was lost or not."""
        if self._audio_stream:
            self._audio_stream.stop_stream()
            self._audio_stream.close()
        self.closed = True
        # Signal the generator to terminate
        await self._buff.put(None)
        if self._audio_interface:
            self._audio_interface.terminate()

    def _fill_buffer(self, in_data, *_):
        """Continuously collect data from the audio stream, into the buffer."""
        if not self.closed:
            self.loop.call_soon_threadsafe(self._buff.put_nowait, in_data)
        return (in_data, pyaudio.paContinue)

    async def generator(self):
        """Generates audio chunks from the stream of audio data."""
        while not self.closed:
            # Use a blocking get() to ensure there's at least one chunk of data
            chunk = await self._buff.get()
            if chunk is None:
                return
            data = [chunk]

            # Now consume whatever other data's still buffered
            while True:
                try:
                    chunk = self._buff.get_nowait()
                    if chunk is None:
                        return
                    data.append(chunk)
                except asyncio.QueueEmpty:
                    break

            yield b"".join(data)
            
    async def read(self):
        """Read a single chunk of audio data."""
        try:
            chunk = await self._buff.get()
            if chunk is None:
                return None
            return chunk
        except Exception as e:
            logger.error(f"Error reading audio data: {str(e)}")
            raise

# Initialize Flask and SocketIO
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key')
sio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*")

# Store active streams and tasks
streams = {}
listen_tasks = {}

async def consumer(queue, sid, source_lang, target_lang):
    """Process transcripts and translations."""
    # Process source and target languages for DeepL
    deepl_source = deepl_language(source_lang.split("-")[0])  # Get base language code
    deepl_target = deepl_language(target_lang)
    
    logger.info(f"Original languages - Source: {source_lang}, Target: {target_lang}")
    logger.info(f"DeepL languages - Source: {deepl_source}, Target: {deepl_target}")
    
    if deepl_source is None:
        logger.warning(f"Source language '{source_lang}' not supported by DeepL")
        logger.info("Using source language as is for transcription")
        deepl_source = source_lang.split("-")[0].upper()
    
    if deepl_target is None:
        logger.warning(f"Target language '{target_lang}' not supported by DeepL")
        logger.info("Using source language for output (no translation)")
        deepl_target = target_lang
    
    source_lang = deepl_source
    target_lang = deepl_target
    
    logger.info(f"Final languages - Source: {source_lang}, Target: {target_lang}")
    
    context = deque(maxlen=3)  # Keep last 3 transcripts for context
    
    while True:
        try:
            logger.info(f"Waiting for transcript from queue for {sid}")
            speaker, transcript, is_final = await queue.get()
            
            if not transcript:
                logger.info(f"Empty transcript received for {sid}, continuing")
                continue
                
            logger.info(f"Received transcript for {sid}: '{transcript}' (final: {is_final})")
                
            # Emit the transcript immediately
            await sio.emit('recognition', {
                'text': transcript,
                'is_final': is_final
            }, room=sid)
            
            # If it's a final transcript and languages are different, translate it
            if is_final:
                try:
                    logger.info(f"Attempting translation - Text: {transcript}, Source: {source_lang}, Target: {target_lang}")
                    translation = await translate_text_deepl(
                        transcript,
                        source_lang,
                        target_lang,
                        " ".join(context)
                    )
                    
                    if translation:
                        logger.info(f"Translation successful - Original: {transcript}, Translated: {translation}")
                        await sio.emit('translation', {
                            'original': transcript,
                            'translated': translation,
                            'source_lang': source_lang,
                            'target_lang': target_lang
                        }, room=sid)
                        context.append(transcript)
                    else:
                        logger.error("Translation returned empty result")
                        await sio.emit('error', {'message': "Translation failed - empty result"}, room=sid)
                except Exception as e:
                    logger.error(f"Translation error: {e}")
                    await sio.emit('error', {'message': f"Translation error: {str(e)}"}, room=sid)
            elif is_final:
                # If source and target languages are the same, just emit the original text
                logger.info(f"No translation needed (same languages) - Text: {transcript}")
                await sio.emit('translation', {
                    'original': transcript,
                    'translated': transcript,
                    'source_lang': source_lang,
                    'target_lang': target_lang
                }, room=sid)
                context.append(transcript)
                    
        except Exception as e:
            logger.error(f"Error in consumer: {e}")
            await sio.emit('error', {'message': f"Processing error: {str(e)}"}, room=sid)
            break

async def sender(ws, stream):
    """Send audio data to Deepgram WebSocket."""
    try:
        logger.info("Starting sender task")
        chunk_count = 0
        async for chunk in stream.generator():
            if stream.closed:
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
    return render_template('index.html')

@sio.on('connect')
def handle_connect():
    logger.info(f"Client connected: {request.sid}")

@sio.on('disconnect')
def handle_disconnect():
    logger.info(f"Client disconnected: {request.sid}")
    if request.sid in listen_tasks:
        for task in listen_tasks[request.sid]:
            if not task.done():
                task.cancel()
        del listen_tasks[request.sid]

@sio.on('start_stream')
def start_listening(data=None):
    sid = request.sid
    logger.info(f"Starting listening session for {sid}")
    
    # Get language preferences from the client
    source_lang = data.get('source_lang', 'en-US') if data else 'en-US'
    target_lang = data.get('target_lang', 'EN') if data else 'EN'
    
    logger.info(f"Language preferences - Source: {source_lang}, Target: {target_lang}")
    
    # Create a background task to handle the async operations
    sio.start_background_task(handle_listening, sid, source_lang, target_lang)
    
    return True

async def handle_listening(sid, source_lang, target_lang):
    """Handle the async listening operations in a background task."""
    try:
        # Create a queue for processing transcripts
        queue = asyncio.Queue(maxsize=10)
        
        # Start the consumer task to process transcripts and translations
        consumer_task = asyncio.create_task(consumer(queue, sid, source_lang, target_lang))
        listen_tasks[sid] = [consumer_task]
        
        # Initialize the microphone stream
        async with MicrophoneStream() as stream:
            # Create a WebSocket connection to Deepgram for speech recognition
            deepgram_api_key = os.getenv("DEEPGRAM_API_KEY")
            if not deepgram_api_key:
                logger.error("Deepgram API key not found")
                await sio.emit('error', {'message': "Speech recognition service not configured"}, room=sid)
                return
                
            # Construct the Deepgram WebSocket URL
            deepgram_url = f"wss://api.deepgram.com/v1/listen?encoding=linear16&sample_rate={RATE}&channels=1&language={source_lang.split('-')[0]}"
            
            # Set up headers for authentication
            headers = {
                "Authorization": f"Token {deepgram_api_key}"
            }
            
            try:
                # Connect to Deepgram WebSocket
                async with websockets.connect(deepgram_url, extra_headers=headers) as ws:
                    logger.info(f"Connected to Deepgram WebSocket for {sid}")
                    
                    # Start sender and receiver tasks
                    sender_task = asyncio.create_task(sender(ws, stream))
                    receiver_task = asyncio.create_task(receiver(ws, queue))
                    
                    # Add tasks to the list for this session
                    listen_tasks[sid].extend([sender_task, receiver_task])
                    
                    # Wait for any task to complete (which would indicate an error or completion)
                    done, pending = await asyncio.wait(
                        [sender_task, receiver_task, consumer_task],
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    
                    # Cancel any pending tasks
                    for task in pending:
                        task.cancel()
                        
                    # Check if any task completed with an exception
                    for task in done:
                        try:
                            await task
                        except Exception as e:
                            logger.error(f"Task completed with error: {str(e)}")
                            
            except Exception as e:
                logger.error(f"Error with Deepgram WebSocket: {str(e)}")
                await sio.emit('error', {'message': f"Speech recognition error: {str(e)}"}, room=sid)
                
    except Exception as e:
        logger.error(f"Error starting listening session for {sid}: {str(e)}")
        await sio.emit('error', {'message': str(e)}, room=sid)
    finally:
        # Clean up tasks if they exist
        if sid in listen_tasks:
            for task in listen_tasks[sid]:
                if not task.done():
                    task.cancel()
            del listen_tasks[sid]

@sio.on('stop_stream')
def stop_listening():
    sid = request.sid
    logger.info(f"Stopping listening session for {sid}")
    if sid in listen_tasks:
        for task in listen_tasks[sid]:
            if not task.done():
                task.cancel()
        del listen_tasks[sid]
        sio.emit('status', {'message': 'Listening stopped'}, room=sid)

if __name__ == '__main__':
    logger.info("Starting application...")
    sio.run(app, host=HOST, port=PORT, debug=True) 