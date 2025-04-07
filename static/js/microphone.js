// Microphone handling for the application
class MicrophoneHandler {
    constructor(socket) {
        this.socket = socket;
        this.mediaRecorder = null;
        this.audioChunks = [];
        this.isRecording = false;
        this.stream = null;
    }

    async startRecording() {
        try {
            // Request microphone access
            this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            
            // Create a MediaRecorder to capture audio
            this.mediaRecorder = new MediaRecorder(this.stream);
            
            // Set up event handlers
            this.mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    // Convert the audio data to base64 and send it to the server
                    const reader = new FileReader();
                    reader.onloadend = () => {
                        const base64Audio = reader.result.split(',')[1];
                        this.socket.emit('audio_data', base64Audio);
                    };
                    reader.readAsDataURL(event.data);
                }
            };
            
            // Start recording
            this.mediaRecorder.start(100); // Capture in 100ms chunks
            this.isRecording = true;
            
            return true;
        } catch (error) {
            console.error('Error accessing microphone:', error);
            return false;
        }
    }
    
    stopRecording() {
        if (this.mediaRecorder && this.isRecording) {
            this.mediaRecorder.stop();
            this.isRecording = false;
            
            // Stop all tracks in the stream
            if (this.stream) {
                this.stream.getTracks().forEach(track => track.stop());
            }
        }
    }
}

// Initialize when the page loads
document.addEventListener('DOMContentLoaded', () => {
    // Connect to the Socket.IO server
    const socket = io();
    
    // Create the microphone handler
    const micHandler = new MicrophoneHandler(socket);
    
    // Set up UI elements
    const startButton = document.getElementById('start-button');
    const stopButton = document.getElementById('stop-button');
    const statusElement = document.getElementById('status');
    
    // Handle start button click
    startButton.addEventListener('click', async () => {
        const success = await micHandler.startRecording();
        if (success) {
            statusElement.textContent = 'Recording...';
            startButton.disabled = true;
            stopButton.disabled = false;
            
            // Notify the server that we're starting to listen
            socket.emit('start_listening');
        } else {
            statusElement.textContent = 'Failed to access microphone. Please check permissions.';
        }
    });
    
    // Handle stop button click
    stopButton.addEventListener('click', () => {
        micHandler.stopRecording();
        statusElement.textContent = 'Stopped recording';
        startButton.disabled = false;
        stopButton.disabled = true;
        
        // Notify the server that we're stopping
        socket.emit('stop_listening');
    });
    
    // Handle server events
    socket.on('connected', (data) => {
        console.log('Connected to server with ID:', data.sid);
    });
    
    socket.on('listening_started', () => {
        console.log('Server acknowledged listening started');
    });
    
    socket.on('transcription', (data) => {
        // Display the transcribed text
        const transcriptionElement = document.getElementById('transcription');
        transcriptionElement.textContent = data.text;
    });
    
    socket.on('translation', (data) => {
        // Display the translated text
        const translationElement = document.getElementById('translation');
        translationElement.textContent = data.text;
    });
    
    socket.on('error', (data) => {
        console.error('Server error:', data.message);
        statusElement.textContent = 'Error: ' + data.message;
    });
}); 