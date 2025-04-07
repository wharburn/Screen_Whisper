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
    && rm -rf /var/lib/apt/lists/*

# Create ALSA configuration
RUN mkdir -p /etc/alsa && \
    echo "pcm.!default { type null }" > /etc/asound.conf && \
    echo "ctl.!default { type null }" >> /etc/asound.conf && \
    echo "defaults.pcm.card 0" >> /etc/asound.conf && \
    echo "defaults.ctl.card 0" >> /etc/asound.conf && \
    echo "defaults.pcm.device 0" >> /etc/asound.conf && \
    echo "defaults.ctl.device 0" >> /etc/asound.conf

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV ALSA_CARD=0
ENV ALSA_DEVICE=0
ENV PYTHONPATH=/app

# Set working directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python packages
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir PyAudio==0.2.11
RUN pip install --no-cache-dir werkzeug==2.0.3
RUN pip install --no-cache-dir numpy scipy

# Copy application files
COPY . .

# Generate fallback audio file
RUN python generate_hello_world.py

# Expose port
EXPOSE 8000

# Run the application
CMD ["python", "app.py"] 