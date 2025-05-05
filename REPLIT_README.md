# Screen Whisper on Replit

This is a real-time speech recognition and translation application that:
1. Uses Deepgram API for speech recognition
2. Uses DeepL API for translation
3. Has a Python backend with aiohttp and Socket.IO
4. Has a web frontend with HTML/CSS/JavaScript

## Setup Instructions for Replit

### 1. Set up API Keys as Secrets

This application requires API keys to function. Add them as Replit Secrets:

1. Click on the lock icon (🔒) in the left sidebar or go to the "Secrets" tab in your Repl
2. Add the following secrets:
   - `DEEPL_API_KEY`: Your DeepL API key
   - `DEEPGRAM_API_KEY`: Your Deepgram API key
   - `USE_DEEPL_PRO`: Set to "true" if using DeepL Pro, "false" for free tier

### 2. Run the Application

The application should start automatically when you run the Repl. If not:

1. Make sure you're in the main directory
2. Click the "Run" button or execute `python app.py` in the Shell

### 3. Using the Application

1. Once running, click on the webview tab to see the application
2. Select your source and target languages
3. Click "Start Listening" to begin speech recognition and translation
4. Speak into your microphone
5. View real-time transcriptions and translations

## Troubleshooting

- If you see a "server rejected WebSocket connection: HTTP 401" error, your Deepgram API key is invalid or expired
- If no transcription appears, check that your microphone is working and browser permissions are granted
- If you want to test without API keys, set the `USE_MOCK_SPEECH` secret to "true"

## Credits

Screen Whisper - Real-time speech recognition and translation application
