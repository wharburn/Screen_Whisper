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
import random
from aiohttp import web

from livetranslate.translate import deepl_language, translate_text_deepl

# Only import DeepgramLiveClient if we're not using mock speech
USE_MOCK_SPEECH = os.environ.get('USE_MOCK_SPEECH', 'false').lower() == 'true'
deepgram_client = None

if not USE_MOCK_SPEECH:
    try:
        from deepgram_client import DeepgramLiveClient
        deepgram_client = DeepgramLiveClient()
    except ImportError:
        print("Warning: Deepgram SDK not found. Falling back to mock mode.")
        USE_MOCK_SPEECH = True
        os.environ['USE_MOCK_SPEECH'] = 'true'

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

# Set up Socket.IO with explicit CORS configuration
sio = socketio.AsyncServer(
    async_mode='aiohttp',
    cors_allowed_origins='*',
    logger=True,  # Enable Socket.IO logging
    engineio_logger=True  # Enable Engine.IO logging
)
sio.attach(app)

# Add CORS headers to all responses
@web.middleware
async def cors_middleware(request, handler):
    resp = await handler(request)
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    return resp

app.middlewares.append(cors_middleware)

# Store active streams and tasks
streams = {}
listen_tasks = {}

# Store per-client audio queues and Deepgram tasks
client_audio_queues = {}
client_deepgram_ws = {}

# Deepgram client is initialized above

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

            # Check if the chunk has actual data
            if chunk and len(chunk) > 0:
                try:
                    await ws.send(chunk)
                except Exception as e:
                    logger.error(f"Error sending chunk to Deepgram: {e}")
                    # If we encounter an error, wait a bit before continuing
                    await asyncio.sleep(0.1)
            else:
                logger.warning("Received empty chunk, skipping")
    except Exception as e:
        logger.error(f"Error in sender: {e}")


async def receiver(ws, queue):
    """Receive transcriptions from Deepgram WebSocket."""
    try:
        async for msg in ws:
            try:
                res = json.loads(msg)

                # Log the full response for debugging
                logger.debug(f"Deepgram response: {json.dumps(res, indent=2)}")

                # Check if this is a valid transcription result
                if res.get("type") != "Results":
                    logger.debug(f"Skipping non-Results message type: {res.get('type')}")
                    continue

                # Get the transcript from the response
                transcript = res.get("channel", {}).get("alternatives", [{}])[0].get("transcript", "")

                # Skip empty transcripts
                if not transcript or transcript.strip() == "":
                    logger.debug("Skipping empty transcript")
                    continue

                # Determine the speaker if available
                speaker = "unknown"
                try:
                    words = res.get("channel", {}).get("alternatives", [{}])[0].get("words", [])
                    if words and "speaker" in words[0]:
                        counter = Counter([x.get("speaker") for x in words if "speaker" in x])
                        if counter:
                            speaker = counter.most_common(1)[0][0]
                except Exception as e:
                    logger.warning(f"Error determining speaker: {e}")

                # Check if the queue is full
                if queue.full():
                    _ = await queue.get()
                    queue.task_done()

                # Put the transcript in the queue
                is_final = bool(res.get("is_final", False))
                logger.info(f"Queuing transcript: '{transcript}' (is_final: {is_final})")
                await queue.put((speaker, transcript, is_final))

            except json.JSONDecodeError as e:
                logger.error(f"Error decoding JSON from Deepgram: {e}")
            except Exception as e:
                logger.error(f"Error processing Deepgram message: {e}")

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
        logger.info(f"Received audio chunk from {sid}, size: {len(data)} bytes")
        # Check if the audio chunk has actual data (not just silence)
        if len(data) > 0:
            # Log the first few bytes for debugging
            logger.info(f"Audio chunk first 10 bytes: {data[:10]}")
            await client_audio_queues[sid].put(data)
        else:
            logger.warning(f"Received empty audio chunk from {sid}")
    else:
        logger.warning(f"Received audio chunk from {sid} but no queue exists")


@sio.event
async def start_listening(sid, data):
    logger.info(f"Start listening request from {sid} with data: {data}")
    if sid in listen_tasks and not listen_tasks[sid].done():
        logger.warning(f"Client {sid} already has an active listening session")
        return

    # Check if we should use mock speech recognition
    if USE_MOCK_SPEECH or deepgram_client is None:
        logger.info(f"Using mock speech recognition for {sid}")
        asyncio.create_task(handle_mock_listening_session(sid, data))
        return
    try:
        # Determine language from data
        language = data.get('source_lang', 'en-US')

        # Map language codes to Deepgram supported formats
        if language.startswith('en'):
            language = 'en-US'
        elif language.startswith('ru') or language.upper() == 'RU':
            language = 'ru'  # Deepgram supports Russian

        logger.info(f"Setting up Deepgram with language: {language}")

        # Create per-client audio queue
        audio_queue = asyncio.Queue(maxsize=10)
        client_audio_queues[sid] = audio_queue

        # Start the Deepgram connection
        success = await deepgram_client.start_connection(
            session_id=sid,
            language=language,
            interim_results=True,
            smart_format=True,
            model='nova-2'  # Use nova-2 model for all languages
        )

        if not success:
            raise RuntimeError("Failed to start Deepgram connection")

        # Define the transcript callback
        async def handle_transcript(result_data):
            try:
                transcript = result_data.get('text', '')
                is_final = result_data.get('is_final', False)

                if not transcript:
                    return

                logger.info(f"Transcript for {sid}: '{transcript}', is_final: {is_final}")

                # Emit the transcript to the client
                await sio.emit('recognition', {'text': transcript, 'is_final': is_final}, room=sid)
                logger.info(f"Emitted recognition event to {sid}")

                # If it's a final transcript, translate it
                if is_final:
                    logger.info(f"Processing final transcript for {sid}: '{transcript}'")

                    # Get the source and target languages
                    source_lang = deepl_language(data.get('source_lang', 'en').split('-')[0])
                    target_lang = deepl_language(data.get('target_lang', 'EN'))
                    logger.info(f"Translating from {source_lang} to {target_lang}")

                    # Translate the transcript
                    translation = await translate_text_deepl(
                        transcript,
                        source_lang,
                        target_lang,
                        ""
                    )

                    logger.info(f"Translation result for {sid}: '{translation}'")

                    # Emit the translation to the client
                    await sio.emit('translation', {
                        'original': transcript,
                        'translated': translation or transcript,
                        'source_lang': data.get('source_lang', 'en-US'),
                        'target_lang': data.get('target_lang', 'EN')
                    }, room=sid)
                    logger.info(f"Emitted translation event to {sid}")
            except Exception as e:
                logger.error(f"Error handling transcript for {sid}: {e}")

        # Register the transcript callback
        deepgram_client.register_transcript_callback(sid, handle_transcript)

        # Start a task to send audio chunks to Deepgram
        async def audio_sender():
            try:
                logger.info(f"Audio sender task started for {sid}")
                chunk_count = 0
                while True:
                    chunk = await audio_queue.get()
                    chunk_count += 1
                    logger.info(f"Sending chunk #{chunk_count} to Deepgram for {sid}, size: {len(chunk)} bytes")
                    await deepgram_client.send_audio(sid, chunk)
            except asyncio.CancelledError:
                logger.info(f"Audio sender task cancelled for {sid}")
                return
            except Exception as e:
                logger.error(f"Audio sender error for {sid}: {e}")

        # Start the audio sender task
        sender_task = asyncio.create_task(audio_sender())

        # Create the gather task with return_exceptions=True to prevent unhandled CancelledError
        listen_tasks[sid] = asyncio.gather(sender_task, return_exceptions=True)

        # Add a done callback to handle any exceptions that might occur
        listen_tasks[sid].add_done_callback(
            lambda task: logger.info(f"Listening task for {sid} completed")
            if not task.cancelled() else None
        )

        await sio.emit('status', {'message': 'Ready to receive audio'}, room=sid)
    except Exception as e:
        logger.error(f"Error starting listening session for {sid}: {e}")
        await sio.emit('error', {'message': str(e)}, room=sid)
        if sid in client_audio_queues:
            del client_audio_queues[sid]
        # Close the Deepgram connection if it was created
        await deepgram_client.close_connection(sid)


@sio.event
async def stop_listening(sid):
    logger.info(f"Stopping listening session for {sid}")
    if sid in listen_tasks:
        # Cancel the task and properly handle the CancelledError
        task = listen_tasks[sid]
        task.cancel()
        try:
            # Wait for the task to be cancelled and handle any exceptions
            await task
        except asyncio.CancelledError:
            logger.info(f"Successfully cancelled listening tasks for {sid}")
        except Exception as e:
            logger.error(f"Error while cancelling listening tasks for {sid}: {e}")
        finally:
            del listen_tasks[sid]

    if sid in client_audio_queues:
        del client_audio_queues[sid]

    # Close the Deepgram connection if available
    if deepgram_client is not None:
        await deepgram_client.close_connection(sid)


async def handle_mock_listening_session(sid, data):
    """Handle a mock listening session for testing without Deepgram."""
    logger.info(f"Starting mock listening session for {sid}")

    # Create a queue for audio chunks
    audio_queue = asyncio.Queue(maxsize=10)
    client_audio_queues[sid] = audio_queue

    # Sample phrases with translations for different languages
    sample_phrases = [
        {
            "en": "Hello, this is a test of the speech recognition system.",
            "fr": "Bonjour, ceci est un test du système de reconnaissance vocale.",
            "es": "Hola, esta es una prueba del sistema de reconocimiento de voz.",
            "de": "Hallo, dies ist ein Test des Spracherkennungssystems.",
            "it": "Ciao, questo è un test del sistema di riconoscimento vocale.",
            "ja": "こんにちは、これは音声認識システムのテストです。",
            "zh": "你好，这是语音识别系统的测试。",
            "ru": "Здравствуйте, это тест системы распознавания речи."
        },
        {
            "en": "The quick brown fox jumps over the lazy dog.",
            "fr": "Le rapide renard brun saute par-dessus le chien paresseux.",
            "es": "El rápido zorro marrón salta sobre el perro perezoso.",
            "de": "Der schnelle braune Fuchs springt über den faulen Hund.",
            "it": "La veloce volpe marrone salta sopra il cane pigro.",
            "ja": "素早い茶色のキツネは怠け者の犬を飛び越えます。",
            "zh": "快速的棕色狐狸跳过懒狗。",
            "ru": "Быстрая коричневая лиса прыгает через ленивую собаку."
        },
        {
            "en": "Welcome to the live translation service.",
            "fr": "Bienvenue au service de traduction en direct.",
            "es": "Bienvenido al servicio de traducción en vivo.",
            "de": "Willkommen beim Live-Übersetzungsdienst.",
            "it": "Benvenuti al servizio di traduzione dal vivo.",
            "ja": "ライブ翻訳サービスへようこそ。",
            "zh": "欢迎使用实时翻译服务。",
            "ru": "Добро пожаловать в сервис живого перевода."
        },
        {
            "en": "This is a simulated speech recognition response.",
            "fr": "Ceci est une réponse simulée de reconnaissance vocale.",
            "es": "Esta es una respuesta simulada de reconocimiento de voz.",
            "de": "Dies ist eine simulierte Spracherkennungsantwort.",
            "it": "Questa è una risposta simulata di riconoscimento vocale.",
            "ja": "これはシミュレートされた音声認識の応答です。",
            "zh": "这是一个模拟的语音识别响应。",
            "ru": "Это симулированный ответ распознавания речи."
        },
        {
            "en": "Testing one two three four five.",
            "fr": "Test un deux trois quatre cinq.",
            "es": "Probando uno dos tres cuatro cinco.",
            "de": "Test eins zwei drei vier fünf.",
            "it": "Test uno due tre quattro cinque.",
            "ja": "テスト 1、2、3、4、5。",
            "zh": "测试一二三四五。",
            "ru": "Тестирование один два три четыре пять."
        },
        {
            "en": "Speech recognition is working without Deepgram API.",
            "fr": "La reconnaissance vocale fonctionne sans l'API Deepgram.",
            "es": "El reconocimiento de voz funciona sin la API de Deepgram.",
            "de": "Die Spracherkennung funktioniert ohne die Deepgram-API.",
            "it": "Il riconoscimento vocale funziona senza l'API Deepgram.",
            "ja": "音声認識はDeepgram APIなしで動作しています。",
            "zh": "语音识别在没有Deepgram API的情况下工作。",
            "ru": "Распознавание речи работает без API Deepgram."
        },
        {
            "en": "This is a mock implementation for testing purposes.",
            "fr": "Il s'agit d'une implémentation simulée à des fins de test.",
            "es": "Esta es una implementación simulada para fines de prueba.",
            "de": "Dies ist eine Mock-Implementierung für Testzwecke.",
            "it": "Questa è un'implementazione fittizia per scopi di test.",
            "ja": "これはテスト目的のためのモック実装です。",
            "zh": "这是用于测试目的的模拟实现。",
            "ru": "Это имитационная реализация для целей тестирования."
        },
        {
            "ru": "Привет, это тест системы перевода.",
            "en": "Hello, this is a test of the translation system.",
            "fr": "Bonjour, ceci est un test du système de traduction.",
            "es": "Hola, esta es una prueba del sistema de traducción.",
            "de": "Hallo, dies ist ein Test des Übersetzungssystems.",
            "it": "Ciao, questo è un test del sistema di traduzione.",
            "ja": "こんにちは、これは翻訳システムのテストです。",
            "zh": "你好，这是翻译系统的测试。"
        },
        {
            "ru": "Я говорю по-русски, и система меня понимает.",
            "en": "I speak Russian, and the system understands me.",
            "fr": "Je parle russe, et le système me comprend.",
            "es": "Hablo ruso, y el sistema me entiende.",
            "de": "Ich spreche Russisch, und das System versteht mich.",
            "it": "Parlo russo, e il sistema mi capisce.",
            "ja": "私はロシア語を話し、システムは私を理解しています。",
            "zh": "我说俄语，系统能理解我。"
        },
        {
            "ru": "Система распознавания речи работает с русским языком.",
            "en": "The speech recognition system works with the Russian language.",
            "fr": "Le système de reconnaissance vocale fonctionne avec la langue russe.",
            "es": "El sistema de reconocimiento de voz funciona con el idioma ruso.",
            "de": "Das Spracherkennungssystem funktioniert mit der russischen Sprache.",
            "it": "Il sistema di riconoscimento vocale funziona con la lingua russa.",
            "ja": "音声認識システムはロシア語で動作します。",
            "zh": "语音识别系统适用于俄语。"
        }
    ]

    # Language code mapping
    lang_code_map = {
        "FR": "fr",
        "ES": "es",
        "DE": "de",
        "IT": "it",
        "JA": "ja",
        "ZH": "zh",
        "EN": "en",
        "RU": "ru"
    }

    try:
        # Send status message to client
        await sio.emit('status', {'message': 'Ready to receive audio (MOCK MODE)'}, room=sid)

        # Create a task to process incoming audio chunks
        async def mock_processor():
            try:
                phrase_index = 0
                while True:
                    # Wait for an audio chunk (we don't actually use it)
                    chunk = await audio_queue.get()
                    logger.info(f"Received audio chunk in mock mode, size: {len(chunk)} bytes")

                    # Every few chunks, emit a recognition event with a sample phrase
                    if random.random() < 0.3:  # 30% chance to emit a phrase
                        phrase_data = sample_phrases[phrase_index % len(sample_phrases)]
                        phrase_index += 1

                        # Determine source language
                        source_lang = data.get('source_lang', 'en-US')
                        source_code = "en"  # Default to English

                        # Check if source language is Russian
                        if source_lang.startswith("ru") or source_lang.upper() == "RU":
                            source_code = "ru"
                            # For Russian source, use phrases that start with Russian
                            if phrase_index >= 7:  # Use the Russian-first phrases (indices 7-9)
                                phrase = phrase_data["ru"]
                            else:
                                # For earlier indices, still use English phrases to mix it up
                                phrase = phrase_data["en"]
                        else:
                            # For non-Russian source, use English phrases
                            phrase = phrase_data["en"]

                        # Emit interim result
                        logger.info(f"Emitting mock recognition: '{phrase}' (interim)")
                        await sio.emit('recognition', {'text': phrase, 'is_final': False}, room=sid)

                        # Wait a bit then emit final result
                        await asyncio.sleep(0.5)
                        logger.info(f"Emitting mock recognition: '{phrase}' (final)")
                        await sio.emit('recognition', {'text': phrase, 'is_final': True}, room=sid)

                        # Translate the phrase
                        target_lang = data.get('target_lang', 'EN')

                        if source_lang != target_lang:
                            # Get the target language code in lowercase
                            target_code = lang_code_map.get(target_lang, "en").lower()

                            # Determine the source language code for lookup
                            source_code = "en"  # Default
                            if source_lang.startswith("ru") or source_lang.upper() == "RU":
                                source_code = "ru"

                            # Get the translation for the target language
                            translation = phrase_data.get(target_code, phrase)

                            logger.info(f"Emitting mock translation from {source_code} to {target_code}: '{translation}'")
                            await sio.emit('translation', {
                                'original': phrase,
                                'translated': translation,
                                'source_lang': source_lang,
                                'target_lang': target_lang
                            }, room=sid)
                        else:
                            # If source and target are the same, just echo the original
                            logger.info(f"No translation needed (same languages) - Text: {phrase}")
                            await sio.emit('translation', {
                                'original': phrase,
                                'translated': phrase,
                                'source_lang': source_lang,
                                'target_lang': target_lang
                            }, room=sid)

                        # Wait a bit before processing the next phrase
                        await asyncio.sleep(2)
            except asyncio.CancelledError:
                logger.info(f"Mock processor task cancelled for {sid}")
                return
            except Exception as e:
                logger.error(f"Error in mock processor for {sid}: {e}")

        # Start the mock processor task
        mock_task = asyncio.create_task(mock_processor())
        listen_tasks[sid] = asyncio.gather(mock_task, return_exceptions=True)

        # Add a done callback
        listen_tasks[sid].add_done_callback(
            lambda task: logger.info(f"Mock listening task for {sid} completed")
            if not task.cancelled() else None
        )
    except Exception as e:
        logger.error(f"Error starting mock listening session for {sid}: {e}")
        await sio.emit('error', {'message': f"Mock session error: {str(e)}"}, room=sid)
        if sid in client_audio_queues:
            del client_audio_queues[sid]


async def cleanup_background_tasks(app):
    """Cleanup function to handle any remaining tasks when the application shuts down."""
    logger.info("Cleaning up background tasks...")

    # Cancel all listening tasks
    for sid, task in list(listen_tasks.items()):
        logger.info(f"Cancelling task for {sid}")
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error while cancelling task for {sid}: {e}")

    # Close all Deepgram connections if available
    if deepgram_client is not None:
        await deepgram_client.close_all_connections()

    # Clear all dictionaries
    listen_tasks.clear()
    client_audio_queues.clear()

    logger.info("Cleanup completed")


if __name__ == '__main__':
    logger.info("Starting application...")

    # Register cleanup function to be called on shutdown
    app.on_shutdown.append(cleanup_background_tasks)

    web.run_app(app, host=HOST, port=PORT)