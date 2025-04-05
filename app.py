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
from livetranslate.translate import translate_text_deepl, deepl_language

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

# Create a new aiohttp web application
app = web.Application()
sio = socketio.AsyncServer(async_mode='aiohttp', cors_allowed_origins='*')
sio.attach(app)

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

# Routes
async def index(request):
    """Serve the index page."""
    with open('templates/index.html') as f:
        return web.Response(text=f.read(), content_type='text/html')

# Register routes
app.router.add_get('/', index)
app.router.add_static('/static', 'static')  # Add static file serving

@sio.event
async def connect(sid, environ):
    """Handle client connection."""
    logger.info(f'Client connected: {sid}')

@sio.event
async def disconnect(sid):
    """Handle client disconnection."""
    logger.info(f'Client disconnected: {sid}')
    if sid in listen_tasks:
        for task in listen_tasks[sid]:
            task.cancel()
        del listen_tasks[sid]

@sio.event
async def start_listening(sid, data):
    """Start the listening session for a client."""
    if sid in listen_tasks and not listen_tasks[sid].done():
        logger.warning(f"Client {sid} already has an active listening session")
        return

    try:
        # Check for Deepgram API key
        key = os.getenv('DEEPGRAM_API_KEY')
        if not key:
            raise RuntimeError("DEEPGRAM_API_KEY not found in environment")
        
        # Set up Deepgram connection parameters
        params = {
            'diarize': 'true',
            'punctuate': 'true',
            'filler_words': 'true',
            'interim_results': 'true',
            'language': data.get('source_lang', 'en-US'),
            'encoding': 'linear16',
            'sample_rate': str(RATE),
        }
        
        # Select model based on language
        if params['language'].split("-")[0] in ("en"):
            params["model"] = "nova-3"
        elif params['language'].split("-")[0] in (
            "bg", "ca", "cs", "da", "de", "el", "es", "et", "fi", "fr", "hi", "hu",
            "id", "it", "ja", "ko", "lt", "lv", "ms", "nl", "no", "pl", "pt", "ro",
            "ru", "sk", "sv", "th", "tr", "uk", "vi", "zh"
        ):
            params["model"] = "nova-2"
        else:
            params["model"] = "enhanced"
        
        query_string = urlencode(params)
        deepgram_url = f"wss://api.deepgram.com/v1/listen?{query_string}"
        
        # Create queue for communication between tasks
        queue = asyncio.Queue(maxsize=1)
        
        # Start the microphone stream
        logger.info(f"Initializing microphone for client {sid}")
        try:
            stream = MicrophoneStream()
            streams[sid] = stream
            async with stream:
                logger.info(f"Microphone initialized successfully for client {sid}")
                
                # Connect to Deepgram
                logger.info(f"Connecting to Deepgram for client {sid}")
                async with websockets.connect(
                    deepgram_url,
                    extra_headers={"Authorization": f"Token {key}"}
                ) as ws:
                    logger.info(f"Connected to Deepgram for client {sid}")
                    
                    # Create tasks for the three main components
                    consumer_task = asyncio.create_task(
                        consumer(queue, sid, data.get('source_lang', 'auto'), data.get('target_lang', 'EN'))
                    )
                    sender_task = asyncio.create_task(sender(ws, stream))
                    receiver_task = asyncio.create_task(receiver(ws, queue))
                    
                    # Store tasks
                    listen_tasks[sid] = asyncio.gather(consumer_task, sender_task, receiver_task)
                    
                    try:
                        await listen_tasks[sid]
                    except asyncio.CancelledError:
                        logger.info(f"Listening session cancelled for client {sid}")
                    except Exception as e:
                        logger.error(f"Error in listening session for {sid}: {e}")
                        await sio.emit('error', {'message': f"Listening session error: {str(e)}"}, room=sid)
                    finally:
                        # Clean up
                        if sid in streams:
                            del streams[sid]
                        if sid in listen_tasks:
                            del listen_tasks[sid]
        except Exception as e:
            logger.error(f"Failed to initialize microphone for client {sid}: {e}")
            await sio.emit('error', {'message': f"Microphone initialization failed: {str(e)}"}, room=sid)
            if sid in streams:
                del streams[sid]
            return

    except Exception as e:
        logger.error(f"Error starting listening session for {sid}: {e}")
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

if __name__ == '__main__':
    logger.info("Starting application...")
    web.run_app(app, host=HOST, port=PORT) 