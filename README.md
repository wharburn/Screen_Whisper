# Audio Translation App

A real-time audio translation application that uses speech recognition and translation services to convert spoken language from one language to another.

## Features

- Real-time speech recognition using Deepgram
- Translation between multiple languages using Google Translate
- Fallback audio simulation when no microphone is available
- Web-based interface with Socket.IO for real-time communication

## Requirements

- Python 3.11+
- PyAudio
- Flask and Flask-SocketIO
- Deepgram SDK
- Google Translate API
- Other dependencies listed in requirements.txt

## Installation

1. Clone the repository
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Create a `.env` file with your API keys:
   ```
   DEEPGRAM_API_KEY=your_deepgram_api_key
   ```

## Usage

1. Start the application:
   ```
   python app.py
   ```
2. Open a web browser and navigate to `http://localhost:8000`
3. Select source and target languages
4. Click "Start Listening" to begin audio translation
5. Speak into your microphone (or the app will use simulated audio if no microphone is available)
6. View the transcription and translation in real-time

## How It Works

1. The application captures audio from the microphone (or uses simulated audio)
2. Audio is sent to Deepgram for speech recognition
3. Recognized text is translated using Google Translate
4. Results are displayed in the web interface in real-time

## Fallback Audio

When no microphone is available, the application uses a pre-generated "Hello World" audio file as a fallback. This allows testing the translation functionality without a real audio device.

## License

MIT
