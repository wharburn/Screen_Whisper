# Screen Whisper on Replit

This is a real-time speech recognition and translation application that runs directly in your browser.

## Features

- **Real-time Speech Recognition**: Using Deepgram's advanced API
- **High-quality Translation**: Powered by DeepL API
- **Multiple Languages**: Support for many languages
- **Web-based Interface**: No installation required, works in your browser

## Setup Instructions

### 1. First-time Setup

When you first open this Repl, follow these steps:

1. Run the setup helper script:
   ```
   python replit_setup.py
   ```

2. Set up your API keys as Replit Secrets:
   - Click on the lock icon (🔒) in the left sidebar
   - Add the following secrets:
     - `DEEPL_API_KEY`: Your DeepL API key
     - `DEEPGRAM_API_KEY`: Your Deepgram API key
     - `USE_DEEPL_PRO`: Set to "true" if using DeepL Pro, "false" for free tier

   If you don't have API keys, you can use mock mode for testing:
   - Add a secret `USE_MOCK_SPEECH` with value "true"

3. Check if your setup is ready:
   ```
   python check_replit_ready.py
   ```

### 2. Running the Application

Once set up, you can run the application by:

1. Clicking the "Run" button at the top of the Replit interface
2. Or typing `python app.py` in the Shell

The application will start and be available in the Webview tab.

### 3. Using the Application

1. Select your source language (the language you'll speak in)
2. Select your target language (the language for translation)
3. Click "Start Listening" and allow microphone access when prompted
4. Speak into your microphone
5. View real-time transcriptions and translations

## Troubleshooting

- **No transcription appears**: Check that your microphone is working and browser permissions are granted
- **"WebSocket connection error"**: Your Deepgram API key might be invalid or expired
- **Application crashes**: Try using mock mode by setting `USE_MOCK_SPEECH=true` in Secrets

## Getting API Keys

- **DeepL API**: Sign up at [DeepL API](https://www.deepl.com/pro-api)
- **Deepgram API**: Sign up at [Deepgram Console](https://console.deepgram.com/)

Both services offer free tiers that are sufficient for testing and personal use.

## Credits

Screen Whisper - Real-time speech recognition and translation application
