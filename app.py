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
from flask_socketio import SocketIO, emit
import base64
import numpy as np
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

# Create a new aiohttp web application
app = web.Application()
app.router.add_static('/static', 'static')
app.router.add_get('/', handle_index)

# Create a Socket.IO server
sio = socketio.AsyncServer(async_mode='aiohttp', cors_allowed_origins='*')
sio.attach(app)

# Store active streams and tasks
streams = {}
listen_tasks = {}

# Initialize speech recognizer and translator
recognizer = sr.Recognizer()
translator = Translator()

async def handle_index(request):
    """Serve the main page."""
    return web.FileResponse('templates/index.html')

@sio.event
async def connect(sid, environ):
    """Handle client connection."""
    logger.info(f"Client connected: {sid}")
    await sio.emit('connected', {'sid': sid}, room=sid)

@sio.event
async def disconnect(sid):
    """Handle client disconnection."""
    logger.info(f"Client disconnected: {sid}")
    if sid in streams:
        del streams[sid]
    if sid in listen_tasks:
        for task in listen_tasks[sid]:
            task.cancel()
        del listen_tasks[sid]

@sio.event
async def start_listening(sid):
    """Start the listening session for a client."""
    logger.info(f"Starting listening session for {sid}")
    
    try:
        # Initialize a queue for audio data
        audio_queue = asyncio.Queue()
        streams[sid] = audio_queue
        
        # Create a task to process audio data
        task = asyncio.create_task(process_audio(sid, audio_queue))
        listen_tasks[sid] = [task]
        
        await sio.emit('listening_started', room=sid)
    except Exception as e:
        logger.error(f"Error starting listening session for {sid}: {e}")
        await sio.emit('error', {'message': str(e)}, room=sid)
        if sid in streams:
            del streams[sid]

@sio.event
async def audio_data(sid, data):
    """Receive audio data from the client."""
    if sid in streams:
        await streams[sid].put(data)

async def process_audio(sid, audio_queue):
    """Process audio data from the queue."""
    try:
        while True:
            # Get audio data from the queue
            audio_data = await audio_queue.get()
            
            # Process the audio data (e.g., convert to text, translate)
            # This is where you would implement your audio processing logic
            
            # For now, just acknowledge receipt
            await sio.emit('audio_processed', {'status': 'ok'}, room=sid)
    except asyncio.CancelledError:
        logger.info(f"Audio processing task cancelled for {sid}")
    except Exception as e:
        logger.error(f"Error processing audio for {sid}: {e}")
        await sio.emit('error', {'message': str(e)}, room=sid)
        if sid in streams:
            del streams[sid]

@sio.event
async def stop_listening(sid):
    """Stop the listening session for a client."""
    logger.info(f"Stopping listening session for {sid}")
    if sid in listen_tasks:
        for task in listen_tasks[sid]:
            task.cancel()
        del listen_tasks[sid]

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def handle_connect():
    logger.info('Client connected')

@socketio.on('disconnect')
def handle_disconnect():
    logger.info('Client disconnected')

@socketio.on('audio_data')
def handle_audio_data(data):
    try:
        # Decode base64 audio data
        audio_bytes = base64.b64decode(data['audio'])
        
        # Convert to numpy array
        audio_array = np.frombuffer(audio_bytes, dtype=np.int16)
        
        # Convert to audio data format expected by speech recognition
        audio_data = sr.AudioData(audio_array.tobytes(), 
                                sample_rate=16000, 
                                sample_width=2)
        
        # Perform speech recognition
        text = recognizer.recognize_google(audio_data)
        logger.info(f"Recognized text: {text}")
        
        # Translate the text
        translation = translator.translate(text, dest='es').text
        logger.info(f"Translation: {translation}")
        
        # Emit results back to client
        emit('recognition_result', {
            'text': text,
            'translation': translation
        })
        
    except sr.UnknownValueError:
        logger.warning("Speech recognition could not understand audio")
        emit('error', {'message': 'Could not understand audio'})
    except sr.RequestError as e:
        logger.error(f"Speech recognition error: {str(e)}")
        emit('error', {'message': 'Speech recognition service error'})
    except Exception as e:
        logger.error(f"Error processing audio: {str(e)}")
        emit('error', {'message': 'Error processing audio'})

if __name__ == '__main__':
    logger.info("Starting application...")
    web.run_app(app, host=HOST, port=PORT) 