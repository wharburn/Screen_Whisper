import os
import asyncio
import json
import websockets
from urllib.parse import urlencode
import socketio
from dotenv import load_dotenv
from collections import deque, Counter
import logging
import io
from aiohttp import web

from livetranslate.translate import deepl_language, translate_text_deepl

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

# Buffer to store incoming audio per client
client_audio_buffers = {}

# Create a new aiohttp web application
app = web.Application()
sio = socketio.AsyncServer(async_mode='aiohttp', cors_allowed_origins='*')
sio.attach(app)

# Store active streams and tasks
streams = {}
listen_tasks = {}

# Store per-client audio queues and Deepgram tasks
client_audio_queues = {}
client_deepgram_ws = {}

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
            await asyncio.create_task(sio.emit('recognition', {
                'text': transcript,
                'is_final': is_final
            }, room=sid))

            # If it's a final transcript and languages are different, translate it
            if is_final:
                try:
                    logger.info(
                        f"Attempting translation - Text: {transcript}, Source: {source_lang}, Target: {target_lang}")
                    translation = await translate_text_deepl(
                        transcript,
                        source_lang,
                        target_lang,
                        " ".join(context)
                    )

                    if translation:
                        logger.info(f"Translation successful - Original: {transcript}, Translated: {translation}")
                        await asyncio.create_task(sio.emit('translation', {
                            'original': transcript,
                            'translated': translation,
                            'source_lang': source_lang,
                            'target_lang': target_lang
                        }, room=sid))
                        context.append(transcript)
                    else:
                        logger.error("Translation returned empty result")
                        await asyncio.create_task(
                            sio.emit('error', {'message': "Translation failed - empty result"}, room=sid))
                except Exception as e:
                    logger.error(f"Translation error: {e}")
                    await asyncio.create_task(sio.emit('error', {'message': f"Translation error: {str(e)}"}, room=sid))
            elif is_final:
                # If source and target languages are the same, just emit the original text
                logger.info(f"No translation needed (same languages) - Text: {transcript}")
                await asyncio.create_task(sio.emit('translation', {
                    'original': transcript,
                    'translated': transcript,
                    'source_lang': source_lang,
                    'target_lang': target_lang
                }, room=sid))
                context.append(transcript)

        except Exception as e:
            logger.error(f"Error in consumer: {e}")
            await asyncio.create_task(sio.emit('error', {'message': f"Processing error: {str(e)}"}, room=sid))
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
    await stop_listening(sid)


@sio.on('audio_chunk')
async def handle_audio_chunk(sid, data):
    # Put audio data into the client's queue for streaming to Deepgram
    if sid in client_audio_queues:
        await client_audio_queues[sid].put(data)


@sio.event
async def start_listening(sid, data):
    if sid in listen_tasks and not listen_tasks[sid].done():
        logger.warning(f"Client {sid} already has an active listening session")
        return
    try:
        key = os.getenv('DEEPGRAM_API_KEY')
        if not key:
            raise RuntimeError("DEEPGRAM_API_KEY not found in environment")
        params = {
            'diarize': 'true',
            'punctuate': 'true',
            'filler_words': 'true',
            'interim_results': 'true',
            'language': data.get('source_lang', 'en-US'),
            'encoding': 'linear16',
            'sample_rate': str(RATE),
        }
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
        # Create per-client audio queue
        audio_queue = asyncio.Queue(maxsize=10)
        client_audio_queues[sid] = audio_queue
        # Connect to Deepgram
        ws = await websockets.connect(
            deepgram_url,
            extra_headers={"Authorization": f"Token {key}"}
        )
        client_deepgram_ws[sid] = ws
        # Start sender and receiver tasks
        async def sender():
            try:
                while True:
                    chunk = await audio_queue.get()
                    await ws.send(chunk)
            except asyncio.CancelledError:
                logger.info(f"Sender task cancelled for {sid}")
                return
            except Exception as e:
                logger.error(f"Sender error for {sid}: {e}")
        async def receiver():
            try:
                async for msg in ws:
                    res = json.loads(msg)
                    transcript = res.get("channel", {}).get("alternatives", [{}])[0].get("transcript", "")
                    is_final = res.get("is_final", False)
                    if transcript:
                        await sio.emit('recognition', {'text': transcript, 'is_final': is_final}, room=sid)
                        if is_final:
                            # Translate and emit
                            translation = await translate_text_deepl(
                                transcript,
                                deepl_language(data.get('source_lang', 'en').split('-')[0]),
                                deepl_language(data.get('target_lang', 'EN')),
                                ""
                            )
                            await sio.emit('translation', {
                                'original': transcript,
                                'translated': translation or transcript,
                                'source_lang': data.get('source_lang', 'en-US'),
                                'target_lang': data.get('target_lang', 'EN')
                            }, room=sid)
            except asyncio.CancelledError:
                logger.info(f"Receiver task cancelled for {sid}")
                return
            except Exception as e:
                logger.error(f"Receiver error for {sid}: {e}")
        listen_tasks[sid] = asyncio.gather(sender(), receiver())
        await sio.emit('status', {'message': 'Ready to receive audio'}, room=sid)
    except Exception as e:
        logger.error(f"Error starting listening session for {sid}: {e}")
        await sio.emit('error', {'message': str(e)}, room=sid)
        if sid in client_audio_queues:
            del client_audio_queues[sid]
        if sid in client_deepgram_ws:
            await client_deepgram_ws[sid].close()
            del client_deepgram_ws[sid]


@sio.event
async def stop_listening(sid):
    logger.info(f"Stopping listening session for {sid}")
    if sid in listen_tasks:
        listen_tasks[sid].cancel()
        del listen_tasks[sid]
    if sid in client_audio_queues:
        del client_audio_queues[sid]
    if sid in client_deepgram_ws:
        await client_deepgram_ws[sid].close()
        del client_deepgram_ws[sid]


if __name__ == '__main__':
    logger.info("Starting application...")
    web.run_app(app, host=HOST, port=PORT)