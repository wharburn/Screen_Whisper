FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    portaudio19-dev \
    python3-pyaudio \
    libasound2 \
    libasound2-dev \
    build-essential \
    python3-dev \
    gcc \
    make \
    pkg-config \
    alsa-utils \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Create ALSA configuration for Docker environment
RUN mkdir -p /etc/alsa && \
    echo "pcm.!default { type null }" > /etc/asound.conf && \
    echo "ctl.!default { type null }" >> /etc/asound.conf && \
    echo "defaults.pcm.device null" >> /etc/asound.conf && \
    echo "defaults.ctl.device null" >> /etc/asound.conf && \
    echo "defaults.pcm.nonblock 1" >> /etc/asound.conf && \
    echo "defaults.pcm.period_time 0" >> /etc/asound.conf && \
    echo "defaults.pcm.period_size 1024" >> /etc/asound.conf && \
    echo "defaults.pcm.buffer_size 4096" >> /etc/asound.conf && \
    echo "pcm.null { type null }" >> /etc/asound.conf && \
    echo "ctl.null { type null }" >> /etc/asound.conf

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV ALSA_CARD=null
ENV ALSA_DEVICE=null
ENV ALSA_CONFIG_PATH=/etc/asound.conf
ENV PYTHONPATH=/app

# Set working directory
WORKDIR /app

# Create static directory for demo audio
RUN mkdir -p /app/static/audio

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python packages
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir PyAudio==0.2.11
RUN pip install --no-cache-dir werkzeug==2.0.3

# Copy application files
COPY . .

# Expose port
EXPOSE 8000

# Run the application
CMD ["python", "app.py"] 