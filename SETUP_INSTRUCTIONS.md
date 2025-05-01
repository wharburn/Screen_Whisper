# Setup Instructions for Screen Whisper

## Deepgram API Key Setup

The application is currently failing with a "server rejected WebSocket connection: HTTP 401" error. This means the Deepgram API key is invalid, expired, or doesn't have the necessary permissions.

To fix this issue:

1. Go to [Deepgram's website](https://console.deepgram.com/) and sign up for an account
2. Create a new API key in your Deepgram dashboard with "Member" permissions
3. Make sure to select a key that allows "Streaming" capabilities
4. Copy the API key (it should start with something like "dg_...")
5. Open the `.env` file in the project root directory
6. Replace `YOUR_DEEPGRAM_API_KEY` with your actual Deepgram API key:

```
DEEPGRAM_API_KEY=dg_your_actual_api_key_here
```

**Important Notes:**
- Deepgram API keys typically start with `dg_` prefix
- The key must have permissions for streaming audio
- If you're using a free tier account, there may be limitations on usage

## Audio Format

Make sure your browser supports the audio format being used. The application is configured to use:
- Sample rate: 16000 Hz
- Encoding: linear16
- Channels: 1 (mono)

## Running the Application

After setting up the API key:

1. Start the server:
```
python app.py
```

2. Open your browser to http://localhost:5002
3. Allow microphone access when prompted
4. Click the "Start" button to begin recording
5. Speak into your microphone
6. The transcription and translation should appear in the respective boxes

## Troubleshooting

If you continue to experience issues:

1. Check the server logs for detailed error messages
2. Verify that your Deepgram API key is valid and has the necessary permissions
3. Make sure your microphone is working properly
4. Try using a different browser (Chrome is recommended)
