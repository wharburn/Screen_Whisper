FROM ubuntu:22.04

# Avoid prompts from apt
ENV DEBIAN_FRONTEND=noninteractive

# Install Python and system dependencies
RUN apt-get update && \
    apt-get install -y \
    python3.11 \
    python3-pip \
    python3-dev \
    libportaudio2 \
    portaudio19-dev \
    gcc \
    make \
    pkg-config \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip3 install --no-cache-dir -r requirements.txt

# Install PyAudio using pip with specific options
RUN pip3 install --no-cache-dir --global-option='build_ext' --global-option='-I/usr/include' PyAudio==0.2.11

# Copy the rest of the application
COPY . .

# Expose the port the app runs on
EXPOSE 8000

# Command to run the application
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000"] 