FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    python3-dev \
    libportaudio2 \
    portaudio19-dev \
    gcc \
    make \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install PyAudio with specific options
RUN pip install --no-cache-dir --global-option='build_ext' --global-option='-I/usr/include' PyAudio==0.2.11

# Copy the rest of the application
COPY . .

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=8000
ENV HOST=0.0.0.0

# Expose the port
EXPOSE 8000

# Run the application directly with Python
CMD ["python", "app.py"] 