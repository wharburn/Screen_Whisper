# Use official Python image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        libasound2-dev \
        portaudio19-dev \
        libportaudio2 \
        libportaudiocpp0 \
        ffmpeg \
        && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app.py ./
COPY static ./static
COPY templates ./templates
# Copy any other necessary directories/files
COPY livetranslate ./livetranslate

# Expose the port Render will use
EXPOSE 10000

# Set environment variable for host and port (Render sets $PORT)
ENV HOST=0.0.0.0
ENV PORT=10000

# Start the app with gunicorn and aiohttp worker
CMD ["gunicorn", "app:app", "--worker-class", "aiohttp.GunicornWebWorker", "--bind", "0.0.0.0:10000"] 