FROM python:3.11-bullseye

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libportaudio2 \
    libportaudiocore1 \
    portaudio19-dev \
    python3-dev \
    gcc \
    make \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Create symbolic links for PortAudio headers
RUN ln -s /usr/include/portaudio.h /usr/local/include/portaudio.h && \
    ln -s /usr/include/pa_linux_alsa.h /usr/local/include/pa_linux_alsa.h && \
    ln -s /usr/include/pa_unix_oss.h /usr/local/include/pa_unix_oss.h

# Set working directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies with specific PyAudio version
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir PyAudio==0.2.11

# Copy the rest of the application
COPY . .

# Expose the port the app runs on
EXPOSE 8000

# Command to run the application
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000"] 