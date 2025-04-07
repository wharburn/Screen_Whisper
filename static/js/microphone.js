// Microphone handling for the application
class AudioHandler {
    constructor() {
        this.socket = io();
        this.mediaRecorder = null;
        this.audioContext = null;
        this.isRecording = false;
        this.hasAudioPermission = false;
        this.setupSocketListeners();
        this.setupUIElements();
        this.checkBrowserCompatibility();
        console.log('AudioHandler initialized');
    }

    checkBrowserCompatibility() {
        const isSecure = window.location.protocol === 'https:';
        const hasGetUserMedia = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
        const hasAudioContext = !!(window.AudioContext || window.webkitAudioContext);
        
        if (!isSecure) {
            this.updateStatus('Warning: Microphone access requires HTTPS');
        }
        
        if (!hasGetUserMedia) {
            this.updateStatus('Error: Your browser does not support microphone access');
            this.disableRecording();
        }
        
        if (!hasAudioContext) {
            this.updateStatus('Error: Your browser does not support audio processing');
            this.disableRecording();
        }
    }

    disableRecording() {
        const startButton = document.getElementById('start-button');
        const stopButton = document.getElementById('stop-button');
        startButton.disabled = true;
        stopButton.disabled = true;
    }

    setupSocketListeners() {
        this.socket.on('connect', () => {
            console.log('Connected to server');
            this.updateStatus('Connected to server');
        });

        this.socket.on('disconnect', () => {
            console.log('Disconnected from server');
            this.updateStatus('Disconnected from server');
            this.stopRecording();
        });

        this.socket.on('recognition_result', (data) => {
            console.log('Received recognition result:', data);
            if (data.text) {
                document.getElementById('transcription').textContent = data.text;
            }
            if (data.translation) {
                document.getElementById('translation').textContent = data.translation;
            }
        });

        this.socket.on('status', (data) => {
            console.log('Status update:', data.message);
            this.updateStatus(data.message);
        });

        this.socket.on('error', (data) => {
            console.error('Error:', data.message);
            this.updateStatus(`Error: ${data.message}`);
        });
    }

    setupUIElements() {
        const startButton = document.getElementById('start-button');
        const stopButton = document.getElementById('stop-button');

        // Add touch event handlers for better mobile experience
        startButton.addEventListener('touchstart', (e) => {
            e.preventDefault(); // Prevent double-tap zoom
            this.startRecording();
        });
        
        stopButton.addEventListener('touchstart', (e) => {
            e.preventDefault();
            this.stopRecording();
        });

        // Keep click handlers for desktop
        startButton.addEventListener('click', () => this.startRecording());
        stopButton.addEventListener('click', () => this.stopRecording());

        // Initially disable stop button
        stopButton.disabled = true;
    }

    async startRecording() {
        if (!this.hasAudioPermission) {
            try {
                console.log('Requesting microphone access...');
                const stream = await navigator.mediaDevices.getUserMedia({
                    audio: {
                        channelCount: 1,
                        sampleRate: 44100,
                        sampleSize: 16,
                        echoCancellation: true,
                        noiseSuppression: true,
                        autoGainControl: true
                    }
                });
                
                this.hasAudioPermission = true;
                console.log('Microphone access granted');
                
                // Initialize audio context only after user interaction (mobile requirement)
                this.audioContext = new (window.AudioContext || window.webkitAudioContext)({
                    sampleRate: 44100,
                    latencyHint: 'interactive'
                });
                
                const source = this.audioContext.createMediaStreamSource(stream);
                const processor = this.audioContext.createScriptProcessor(4096, 1, 1);

                source.connect(processor);
                processor.connect(this.audioContext.destination);

                this.isRecording = true;
                this.socket.emit('start_stream');
                console.log('Started recording');

                processor.onaudioprocess = (e) => {
                    if (!this.isRecording) return;

                    const inputData = e.inputBuffer.getChannelData(0);
                    // Convert float32 to int16
                    const int16Data = new Int16Array(inputData.length);
                    for (let i = 0; i < inputData.length; i++) {
                        const s = Math.max(-1, Math.min(1, inputData[i]));
                        int16Data[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
                    }

                    // Send audio data to server
                    const base64Data = this.arrayBufferToBase64(int16Data.buffer);
                    this.socket.emit('audio_data', base64Data);
                };

                this.updateUIForRecording(true);
                this.updateStatus('Recording...');

            } catch (error) {
                console.error('Error starting recording:', error);
                let errorMessage = 'Error accessing microphone: ';
                
                if (error.name === 'NotAllowedError') {
                    errorMessage += 'Permission denied. Please allow microphone access.';
                } else if (error.name === 'NotFoundError') {
                    errorMessage += 'No microphone found.';
                } else if (error.name === 'NotReadableError') {
                    errorMessage += 'Microphone is already in use by another application.';
                } else {
                    errorMessage += error.message;
                }
                
                this.updateStatus(errorMessage);
                this.hasAudioPermission = false;
            }
        }
    }

    stopRecording() {
        if (this.isRecording) {
            console.log('Stopping recording');
            this.isRecording = false;
            this.socket.emit('stop_stream');
            
            if (this.audioContext) {
                this.audioContext.close();
                this.audioContext = null;
            }

            this.updateUIForRecording(false);
            this.updateStatus('Recording stopped');
        }
    }

    updateUIForRecording(isRecording) {
        const startButton = document.getElementById('start-button');
        const stopButton = document.getElementById('stop-button');
        
        startButton.disabled = isRecording;
        stopButton.disabled = !isRecording;
        
        // Add visual feedback for mobile
        if (isRecording) {
            startButton.classList.add('recording');
            stopButton.classList.remove('recording');
        } else {
            startButton.classList.remove('recording');
            stopButton.classList.add('recording');
        }
    }

    updateStatus(message) {
        console.log('Status update:', message);
        const statusElement = document.getElementById('status');
        if (statusElement) {
            statusElement.textContent = message;
            // Add visual feedback for errors
            if (message.toLowerCase().includes('error')) {
                statusElement.classList.add('error');
            } else {
                statusElement.classList.remove('error');
            }
        }
    }

    arrayBufferToBase64(buffer) {
        const bytes = new Uint8Array(buffer);
        const binary = bytes.reduce((data, byte) => data + String.fromCharCode(byte), '');
        return btoa(binary);
    }
}

// Initialize the audio handler when the page loads
document.addEventListener('DOMContentLoaded', () => {
    console.log('Initializing AudioHandler');
    window.audioHandler = new AudioHandler();
}); 