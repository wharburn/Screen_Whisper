import os
import asyncio
import json
import websockets
from urllib.parse import urlencode
import pyaudio
from aiohttp import web
import socketio
from dotenv import load_dotenv
from collections import deque, Counter
import logging
import time
from translate import translate_text_deepl, deepl_language
from flask import Flask, render_template
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

class AudioStream:
    def __init__(self):
        self._audio_interface = pyaudio.PyAudio()
        self._stream = None

    async def __aenter__(self):
        try:
            self._stream = self._audio_interface.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=RATE,
                input=True,
                frames_per_buffer=CHUNK
            )
            return self
        except Exception as e:
            logger.error(f"Failed to initialize audio stream: {str(e)}")
            raise RuntimeError(f"Failed to initialize audio stream: {str(e)}")

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
        self._audio_interface.terminate()

    async def read(self):
        try:
            data = self._stream.read(CHUNK, exception_on_overflow=False)
            return data
        except Exception as e:
            logger.error(f"Error reading audio data: {str(e)}")
            raise

# Create a new aiohttp web application
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
            speaker, transcript, is_final = await queue.get()
            
            if not transcript:
                continue
                
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
        async for chunk in stream.generator():
            if stream.closed:
                break
            await ws.send(chunk)
    except Exception as e:
        logger.error(f"Error in sender: {e}")

async def receiver(ws, queue):
    """Receive transcriptions from Deepgram WebSocket."""
    try:
        async for msg in ws:
            res = json.loads(msg)
            
            transcript = res.get("channel", {}).get("alternatives", [{}])[0].get("transcript", "")
            
            if not transcript:
                continue
                
            counter = Counter([x["speaker"] for x in res["channel"]["alternatives"][0]["words"]])
            
            if not counter:
                continue
                
            speaker = counter.most_common(1)[0][0]
            
            if queue.full():
                _ = await queue.get()
                queue.task_done()
            await queue.put((speaker, transcript, bool(res.get("is_final", False))))
            
    except Exception as e:
        logger.error(f"Error in receiver: {e}")

@app.route('/')
def index():
    return render_template('index.html')

@sio.on('connect')
async def handle_connect():
    logger.info(f"Client connected: {request.sid}")

@sio.on('disconnect')
async def handle_disconnect():
    logger.info(f"Client disconnected: {request.sid}")
    if request.sid in listen_tasks:
        for task in listen_tasks[request.sid]:
            task.cancel()
        del listen_tasks[request.sid]

@sio.on('start_stream')
async def start_listening(sid):
    try:
        logger.info(f"Starting listening session for {sid}")
        async with AudioStream() as stream:
            while True:
                try:
                    data = await stream.read()
                    # Process audio data here
                    await sio.emit('audio_data', {'data': data}, room=sid)
                except Exception as e:
                    logger.error(f"Error processing audio: {str(e)}")
                    await sio.emit('error', {'message': str(e)}, room=sid)
                    break
    except Exception as e:
        logger.error(f"Error starting listening session for {sid}: {str(e)}")
        await sio.emit('error', {'message': str(e)}, room=sid)

@sio.on('stop_stream')
async def stop_listening(sid):
    logger.info(f"Stopping listening session for {sid}")
    if sid in listen_tasks:
        for task in listen_tasks[sid]:
            task.cancel()
        del listen_tasks[sid]

if __name__ == '__main__':
    logger.info("Starting application...")
    sio.run(app, host=HOST, port=PORT, debug=True) 