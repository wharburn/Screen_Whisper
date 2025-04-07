FROM python:3.11-slim

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

# Set working directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose the port the app runs on
EXPOSE 8000

# Command to run the application
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000"] 