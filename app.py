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
        self._audio_interface = None
        self._stream = None
        self._audio_buffer = None
        self._closed = True
        self._initialized = False
        self._mock_mode = False
        self._mock_data = None
        self._file_mode = False
        self._audio_file = None
        self._file_chunks = []

    async def __aenter__(self):
        try:
            # Initialize PyAudio
            self._audio_interface = pyaudio.PyAudio()
            
            # Create a buffer for audio data
            self._audio_buffer = asyncio.Queue()
            
            # Find available input devices
            input_devices = []
            for i in range(self._audio_interface.get_device_count()):
                try:
                    device_info = self._audio_interface.get_device_info_by_index(i)
                    if device_info and device_info.get('maxInputChannels', 0) > 0:
                        input_devices.append((i, device_info.get('name', f'Device {i}')))
                except Exception as e:
                    logger.warning(f"Error getting device info for index {i}: {str(e)}")
                    continue
            
            logger.info(f"Available input devices: {input_devices}")
            
            # If no input devices found, use demo audio file
            if not input_devices:
                logger.warning("No input devices found, using demo audio file")
                self._file_mode = True
                await self._load_demo_audio()
                self._closed = False
                self._initialized = True
                return self
            
            # Try to open the stream with the first available input device
            input_device_index = input_devices[0][0]
            logger.info(f"Using input device: {input_devices[0][1]} (index: {input_device_index})")
            
            # Open the audio stream with error handling
            try:
                self._stream = self._audio_interface.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=self._rate,
                    input=True,
                    frames_per_buffer=self._chunk,
                    stream_callback=self._fill_buffer,
                    input_device_index=input_device_index,
                    start=False  # Don't start immediately
                )
                
                if not self._stream:
                    raise RuntimeError("Failed to open audio stream")
                
                # Start the stream
                self._stream.start_stream()
                
                # Verify stream is running
                if not self._stream.is_active():
                    raise RuntimeError("Stream failed to start")
                
                self._closed = False
                self._initialized = True
                logger.info("Audio stream started successfully")
                return self
                
            except Exception as e:
                logger.error(f"Error opening audio stream: {str(e)}")
                if self._stream:
                    try:
                        self._stream.close()
                    except:
                        pass
                # Fall back to demo audio file
                logger.warning("Falling back to demo audio file")
                self._file_mode = True
                await self._load_demo_audio()
                self._closed = False
                self._initialized = True
                return self
                
        except Exception as e:
            logger.error(f"Error initializing audio stream: {str(e)}")
            await self.__aexit__(None, None, None)
            raise RuntimeError(f"Failed to initialize audio stream: {str(e)}")

    async def _load_demo_audio(self):
        """Load a demo audio file for testing."""
        try:
            # Use existing MP3 file
            demo_file_path = os.path.join('static', 'audio', 'hello-what-you-doing-42455.mp3')
            
            if not os.path.exists(demo_file_path):
                logger.error(f"Demo audio file not found at {demo_file_path}")
                raise FileNotFoundError(f"Demo audio file not found at {demo_file_path}")
            
            logger.info(f"Loading demo audio file from {demo_file_path}")
            
            try:
                # Convert MP3 to WAV format in memory
                import pydub
                audio = pydub.AudioSegment.from_mp3(demo_file_path)
                
                # Set the frame rate to match our requirements
                if audio.frame_rate != self._rate:
                    audio = audio.set_frame_rate(self._rate)
                
                # Convert to mono if stereo
                if audio.channels > 1:
                    audio = audio.set_channels(1)
                
                # Get raw audio data
                audio_data = audio.raw_data
                
                # Split into chunks
                chunk_size = self._chunk * 2  # 2 bytes per sample for 16-bit audio
                for i in range(0, len(audio_data), chunk_size):
                    chunk = audio_data[i:i+chunk_size]
                    if len(chunk) == chunk_size:  # Only add complete chunks
                        self._file_chunks.append(chunk)
                
                logger.info(f"Loaded {len(self._file_chunks)} chunks from demo audio file")
                
            except Exception as e:
                logger.error(f"Error processing demo audio file: {str(e)}")
                raise
            
        except Exception as e:
            logger.error(f"Error loading demo audio: {str(e)}")
            # Fall back to silence if file loading fails
            self._mock_mode = True
            self._mock_data = b'\x00\x00' * self._chunk

    async def __aexit__(self, type, value, traceback):
        self._closed = True
        if self._stream:
            try:
                if self._stream.is_active():
                    self._stream.stop_stream()
                self._stream.close()
            except Exception as e:
                logger.error(f"Error closing audio stream: {str(e)}")
        if self._audio_interface:
            try:
                self._audio_interface.terminate()
            except Exception as e:
                logger.error(f"Error terminating audio interface: {str(e)}")
        self._initialized = False
        logger.info("Audio stream closed")

    def _fill_buffer(self, in_data, frame_count, time_info, status_flags):
        """Continuously collect data from the audio stream into the buffer."""
        if not self._closed and self._audio_buffer and self._initialized:
            try:
                self._audio_buffer.put_nowait(in_data)
            except asyncio.QueueFull:
                logger.warning("Audio buffer is full, dropping oldest chunk")
                try:
                    self._audio_buffer.get_nowait()  # Remove oldest chunk
                    self._audio_buffer.put_nowait(in_data)  # Add new chunk
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass
        return (in_data, pyaudio.paContinue)

    async def generator(self):
        """Generates audio chunks from the stream."""
        if not self._initialized:
            raise RuntimeError("Audio stream not initialized")
            
        if self._file_mode:
            # In file mode, yield chunks from the file
            logger.info("Using demo audio file for streaming")
            for chunk in self._file_chunks:
                if self._closed:
                    break
                yield chunk
                await asyncio.sleep(0.1)  # Simulate real-time audio
            # Loop the file
            while not self._closed:
                for chunk in self._file_chunks:
                    if self._closed:
                        break
                    yield chunk
                    await asyncio.sleep(0.1)  # Simulate real-time audio
        elif self._mock_mode:
            # In mock mode, generate silence data
            while not self._closed:
                await asyncio.sleep(0.1)  # Simulate real-time audio
                yield self._mock_data
        else:
            # Normal mode with real microphone
            while not self._closed:
                try:
                    if not self._stream or not self._stream.is_active():
                        logger.error("Stream is not active")
                        break
                        
                    chunk = await self._audio_buffer.get()
                    if chunk:
                        yield chunk
                except Exception as e:
                    logger.error(f"Error in audio generator: {str(e)}")
                    break

# Initialize Flask and SocketIO
app = Flask(__name__, static_folder='static')
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
            sio.emit('recognition', {
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
                        sio.emit('translation', {
                            'original': transcript,
                            'translated': translation,
                            'source_lang': source_lang,
                            'target_lang': target_lang
                        }, room=sid)
                        context.append(transcript)
                    else:
                        logger.error("Translation returned empty result")
                        sio.emit('error', {'message': "Translation failed - empty result"}, room=sid)
                except Exception as e:
                    logger.error(f"Translation error: {e}")
                    sio.emit('error', {'message': f"Translation error: {str(e)}"}, room=sid)
            elif is_final:
                # If source and target languages are the same, just emit the original text
                logger.info(f"No translation needed (same languages) - Text: {transcript}")
                sio.emit('translation', {
                    'original': transcript,
                    'translated': transcript,
                    'source_lang': source_lang,
                    'target_lang': target_lang
                }, room=sid)
                context.append(transcript)
                    
        except Exception as e:
            logger.error(f"Error in consumer: {e}")
            sio.emit('error', {'message': f"Processing error: {str(e)}"}, room=sid)
            break

async def sender(ws, stream):
    """Send audio data to Deepgram WebSocket."""
    try:
        logger.info("Starting sender task")
        chunk_count = 0
        
        # Check if we're in file mode
        if stream._file_mode:
            logger.info("Sender is using demo audio file")
        
        async for chunk in stream.generator():
            if stream._closed:
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
        # Cancel all asyncio tasks
        for task in listen_tasks[request.sid]['tasks']:
            if not task.done():
                task.cancel()
        # Clean up the thread
        if 'thread' in listen_tasks[request.sid]:
            listen_tasks[request.sid]['thread'].join(timeout=1.0)
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
    def run_async():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(handle_listening(sid, source_lang, target_lang))
        except Exception as e:
            logger.error(f"Error in async handler: {str(e)}")
            # Use emit directly instead of awaiting it
            sio.emit('error', {'message': str(e)}, room=sid)
        finally:
            loop.close()
    
    sio.start_background_task(run_async)
    
    return True

async def handle_listening(sid, source_lang, target_lang):
    """Handle the async listening operations in a background task."""
    try:
        # Create a queue for processing transcripts
        queue = asyncio.Queue(maxsize=10)
        
        # Start the consumer task to process transcripts and translations
        consumer_task = asyncio.create_task(consumer(queue, sid, source_lang, target_lang))
        if sid not in listen_tasks:
            listen_tasks[sid] = {'tasks': []}
        listen_tasks[sid]['tasks'].append(consumer_task)
        
        # Initialize the microphone stream
        stream = None
        try:
            stream = MicrophoneStream()
            await stream.__aenter__()
            logger.info(f"Successfully initialized audio stream for {sid}")
        except Exception as e:
            logger.error(f"Failed to initialize microphone stream: {str(e)}")
            sio.emit('error', {'message': "Failed to initialize microphone. Using demo audio instead."}, room=sid)
            # Try to use demo audio file
            try:
                stream = MicrophoneStream()
                stream._file_mode = True
                await stream._load_demo_audio()
                stream._closed = False
                stream._initialized = True
                logger.info(f"Successfully initialized demo audio for {sid}")
            except Exception as demo_error:
                logger.error(f"Failed to initialize demo audio: {str(demo_error)}")
                sio.emit('error', {'message': "Failed to initialize audio. Please try again later."}, room=sid)
                return

        try:
            # Create a WebSocket connection to Deepgram for speech recognition
            deepgram_api_key = os.getenv("DEEPGRAM_API_KEY")
            if not deepgram_api_key:
                logger.error("Deepgram API key not found")
                sio.emit('error', {'message': "Speech recognition service not configured"}, room=sid)
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
                    if not ws:
                        raise ConnectionError("Failed to establish WebSocket connection")
                        
                    logger.info(f"Connected to Deepgram WebSocket for {sid}")
                    
                    # Start sender and receiver tasks
                    sender_task = asyncio.create_task(sender(ws, stream))
                    receiver_task = asyncio.create_task(receiver(ws, queue))
                    
                    # Add tasks to the list for this session
                    listen_tasks[sid]['tasks'].extend([sender_task, receiver_task])
                    
                    # Wait for any task to complete (which would indicate an error or completion)
                    done, pending = await asyncio.wait(
                        [sender_task, receiver_task, consumer_task],
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    
                    # Cancel any pending tasks
                    for task in pending:
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                        
                    # Check if any task completed with an exception
                    for task in done:
                        try:
                            await task
                        except Exception as e:
                            logger.error(f"Task completed with error: {str(e)}")
                            sio.emit('error', {'message': f"Processing error: {str(e)}"}, room=sid)
                            
            except (websockets.WebSocketException, ConnectionError) as e:
                logger.error(f"WebSocket connection error: {str(e)}")
                sio.emit('error', {'message': "Failed to connect to speech recognition service"}, room=sid)
            except Exception as e:
                logger.error(f"Unexpected error in WebSocket handling: {str(e)}")
                sio.emit('error', {'message': "An unexpected error occurred"}, room=sid)
                
        finally:
            # Clean up the stream
            if stream:
                try:
                    await stream.__aexit__(None, None, None)
                except Exception as e:
                    logger.error(f"Error closing stream: {str(e)}")
                
    except Exception as e:
        logger.error(f"Error in handle_listening: {str(e)}")
        sio.emit('error', {'message': f"Error: {str(e)}"}, room=sid)
    finally:
        # Clean up tasks
        if sid in listen_tasks:
            for task in listen_tasks[sid]['tasks']:
                if not task.done():
                    task.cancel()
            del listen_tasks[sid]

@sio.on('stop_stream')
def stop_listening():
    sid = request.sid
    logger.info(f"Stopping listening session for {sid}")
    
    if sid in listen_tasks:
        for task in listen_tasks[sid]['tasks']:
            if isinstance(task, asyncio.Task):
                if not task.done():
                    task.cancel()
        del listen_tasks[sid]
    
    return True

if __name__ == '__main__':
    logger.info("Starting application...")
    sio.run(app, host=HOST, port=PORT, debug=True) 