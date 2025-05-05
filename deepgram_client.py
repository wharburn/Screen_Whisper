"""
Deepgram client implementation using the Deepgram SDK.
This module provides a wrapper around the Deepgram SDK for live transcription.
"""

import os
import json
import logging
import asyncio
import ssl
from typing import Dict, Any, Optional, Callable, Coroutine

# Create an SSL context that doesn't verify certificates (for development only)
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# Import the Deepgram SDK
try:
    # Try importing DeepgramClient (newer SDK version)
    from deepgram import DeepgramClient
    USE_NEW_SDK = True
except ImportError:
    try:
        # Fall back to Deepgram (older SDK version)
        from deepgram import Deepgram
        USE_NEW_SDK = False
    except ImportError:
        raise ImportError("Failed to import Deepgram SDK. Please install it with 'pip install deepgram-sdk'.")

# Set up logging
logger = logging.getLogger(__name__)

class DeepgramLiveClient:
    """A wrapper around the Deepgram SDK for live transcription."""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize the Deepgram client.

        Args:
            api_key: The Deepgram API key. If not provided, it will be read from the environment.
        """
        self.api_key = api_key or os.environ.get('DEEPGRAM_API_KEY')
        if not self.api_key:
            raise ValueError("Deepgram API key not found. Please set the DEEPGRAM_API_KEY environment variable.")

        # Initialize the Deepgram client based on the available SDK version
        if USE_NEW_SDK:
            self.client = DeepgramClient(api_key=self.api_key)
            logger.info("Using new Deepgram SDK with DeepgramClient")
        else:
            self.client = Deepgram(self.api_key)
            logger.info("Using older Deepgram SDK with Deepgram")

        # Store the connection for each session
        self.connections: Dict[str, Any] = {}

        logger.info("Deepgram client initialized")

    async def start_connection(self,
                              session_id: str,
                              language: str = 'en-US',
                              interim_results: bool = True,
                              smart_format: bool = True,
                              model: str = 'nova-2') -> bool:
        """Start a new Deepgram connection for a session.

        Args:
            session_id: A unique identifier for the session
            language: The language code for speech recognition
            interim_results: Whether to return interim results
            smart_format: Whether to use smart formatting
            model: The Deepgram model to use

        Returns:
            True if the connection was successfully started, False otherwise
        """
        try:
            # Set up the connection options
            options = {
                "model": model,
                "language": language,
                "smart_format": smart_format,
                "interim_results": interim_results,
                "punctuate": True,
                "diarize": True,
                "encoding": "linear16",
                "sample_rate": 16000,
                "channels": 1,
            }

            # Create a new connection based on SDK version
            try:
                if USE_NEW_SDK:
                    # For newer SDK with DeepgramClient
                    from deepgram import LiveOptions

                    # Convert options dict to LiveOptions
                    live_options = LiveOptions(
                        model=options["model"],
                        language=options["language"],
                        smart_format=options["smart_format"],
                        interim_results=options["interim_results"],
                        punctuate=options["punctuate"],
                        diarize=options["diarize"],
                        encoding=options["encoding"],
                        sample_rate=options["sample_rate"],
                        channels=options["channels"]
                    )

                    # Get the connection
                    connection = self.client.listen.websocket.v("1")

                    # Set the SSL context to disable certificate verification
                    connection.options.ssl_context = ssl_context

                    # Start the connection
                    if not connection.start(live_options):
                        logger.error(f"Failed to start Deepgram connection for session {session_id}")
                        return False
                else:
                    # For older SDK with Deepgram
                    connection = await self.client.transcription.live(options, ssl_context=ssl_context)

                logger.info(f"Successfully created Deepgram live transcription for session {session_id}")
            except Exception as e:
                logger.error(f"Could not open Deepgram socket: {e}")
                return False

            # Store the connection
            self.connections[session_id] = connection

            logger.info(f"Started Deepgram connection for session {session_id} with language {language}")
            return True

        except Exception as e:
            logger.error(f"Error starting Deepgram connection for session {session_id}: {e}")
            return False

    def register_transcript_callback(self,
                                    session_id: str,
                                    callback: Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]) -> bool:
        """Register a callback for transcript events.

        Args:
            session_id: The session ID
            callback: A coroutine function that will be called with the transcript data

        Returns:
            True if the callback was registered successfully, False otherwise
        """
        if session_id not in self.connections:
            logger.error(f"No Deepgram connection found for session {session_id}")
            return False

        socket = self.connections[session_id]

        # Define the event handler for the transcript
        async def on_transcript(transcript_data):
            try:
                # Extract the transcript
                if not transcript_data or 'channel' not in transcript_data:
                    return

                alternatives = transcript_data.get('channel', {}).get('alternatives', [])
                if not alternatives:
                    return

                transcript = alternatives[0].get('transcript', '')
                if not transcript:
                    # Skip empty transcripts
                    return

                # Determine if this is a final result
                is_final = transcript_data.get('is_final', False)

                # Create a simplified result object
                result_data = {
                    'text': transcript,
                    'is_final': is_final
                }

                # Call the user-provided callback
                await callback(result_data)

            except Exception as e:
                logger.error(f"Error processing transcript for session {session_id}: {e}")

        # Register the event handlers based on SDK version
        if USE_NEW_SDK:
            # For newer SDK with DeepgramClient
            try:
                from deepgram import LiveTranscriptionEvents
                socket.on(LiveTranscriptionEvents.Transcript, on_transcript)
                socket.on(LiveTranscriptionEvents.Close, lambda c:
                         logger.info(f"Deepgram connection closed for session {session_id} with code {c}"))
            except Exception as e:
                logger.error(f"Error registering handlers for new SDK: {e}")
                return False
        else:
            # For older SDK with Deepgram
            try:
                socket.registerHandler(socket.event.TRANSCRIPT_RECEIVED, on_transcript)
                socket.registerHandler(socket.event.CLOSE, lambda c:
                                      logger.info(f"Deepgram connection closed for session {session_id} with code {c}"))
            except Exception as e:
                logger.error(f"Error registering handlers for old SDK: {e}")
                return False

        logger.info(f"Registered transcript callback for session {session_id}")
        return True

    async def send_audio(self, session_id: str, audio_data: bytes) -> bool:
        """Send audio data to Deepgram.

        Args:
            session_id: The session ID
            audio_data: The audio data to send

        Returns:
            True if the audio was sent successfully, False otherwise
        """
        if session_id not in self.connections:
            logger.error(f"No Deepgram connection found for session {session_id}")
            return False

        try:
            socket = self.connections[session_id]
            socket.send(audio_data)
            return True
        except Exception as e:
            logger.error(f"Error sending audio data for session {session_id}: {e}")
            return False

    async def close_connection(self, session_id: str) -> bool:
        """Close the Deepgram connection for a session.

        Args:
            session_id: The session ID

        Returns:
            True if the connection was closed successfully, False otherwise
        """
        if session_id not in self.connections:
            logger.warning(f"No Deepgram connection found for session {session_id}")
            return False

        try:
            # Finish the connection
            socket = self.connections[session_id]
            socket.finish()

            # Clean up
            del self.connections[session_id]

            logger.info(f"Closed Deepgram connection for session {session_id}")
            return True
        except Exception as e:
            logger.error(f"Error closing Deepgram connection for session {session_id}: {e}")
            return False

    async def close_all_connections(self) -> None:
        """Close all Deepgram connections."""
        for session_id in list(self.connections.keys()):
            await self.close_connection(session_id)

        logger.info("Closed all Deepgram connections")
