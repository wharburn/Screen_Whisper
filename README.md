# ScreenWhisper

![ScreenWhisper Logo](/static/images/SWlogo.png)

ScreenWhisper is a powerful real-time speech translation application that enables seamless communication across language barriers. With its sleek dark-themed interface and instant translation capabilities, it provides a professional solution for multilingual conversations and presentations.

## Features

- **Real-time Speech Recognition**: Instantly converts spoken words into text
- **Live Translation**: Translates between 30+ languages in real-time
- **Professional Dark Theme**: Easy on the eyes with a modern black and white interface
- **Translation History**: Keeps track of previous translations for reference
- **Source Language Detection**: Automatically detects and transcribes the source language
- **Context-Aware Translation**: Uses previous conversation context for more accurate translations
- **Cross-Platform Compatibility**: Works on any modern web browser

## Supported Languages

ScreenWhisper supports a wide range of languages including:
- English (US/UK)
- Spanish
- French
- German
- Russian
- Chinese
- Japanese
- Korean
- And many more...

## Technology Stack

- **Backend**: Python with aiohttp and Socket.IO
- **Speech Recognition**: Deepgram API with Nova-2/Nova-3 models
- **Translation**: DeepL API for high-quality translations
- **Frontend**: Modern HTML/CSS with Tailwind CSS
- **Real-time Communication**: WebSocket for instant updates

## Setup and Installation

### Prerequisites
- Python 3.11.5 or higher
- DeepL API key
- Deepgram API key
- Working microphone

### Local Development

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd screenwhisper
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Set up environment variables:
   Create a `.env` file with:
   ```
   DEEPL_API_KEY=your_deepl_key
   DEEPGRAM_API_KEY=your_deepgram_key
   USE_DEEPL_PRO=false
   ```

4. Run the application:
   ```bash
   python app.py
   ```

5. Open your browser and navigate to:
   ```
   http://localhost:5002
   ```

### Deployment

ScreenWhisper is configured for easy deployment on Render:

1. Fork this repository
2. Create a new Web Service on Render
3. Connect your repository
4. Add the required environment variables:
   - `DEEPL_API_KEY`
   - `DEEPGRAM_API_KEY`
   - `USE_DEEPL_PRO`

The application will automatically deploy using the configuration in `render.yaml`.

## Usage

1. Open ScreenWhisper in your browser
2. Select your source and target languages
3. Click the "Start Listening" button
4. Speak clearly into your microphone
5. Watch as your speech is transcribed and translated in real-time
6. View translation history in the bottom panel

## Privacy and Security

- All audio processing is done in real-time with no storage of voice data
- API keys are securely handled through environment variables
- No personal data is collected or stored

## Support

For issues, questions, or contributions, please:
1. Open an issue in the GitHub repository
2. Provide detailed information about your problem
3. Include steps to reproduce any bugs

## License

This project is licensed under the MIT License - see the LICENSE file for details.
