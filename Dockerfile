FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    portaudio19-dev \
    python3-pyaudio \
    libasound2 \
    libasound2-dev \
    && rm -rf /var/lib/apt/lists/*

# Create ALSA configuration
RUN echo "pcm.!default { type null }" > /etc/asound.conf && \
    echo "ctl.!default { type null }" >> /etc/asound.conf

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Create and set working directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose port
EXPOSE 8000

# Command to run the application
CMD ["python", "app.py"] 