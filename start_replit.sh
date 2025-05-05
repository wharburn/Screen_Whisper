#!/bin/bash

# Start script for Screen Whisper on Replit
echo "Starting Screen Whisper on Replit..."

# Install Python dependencies if not already installed
if [ ! -d ".venv" ]; then
  echo "Setting up virtual environment..."
  python -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt
else
  source .venv/bin/activate
fi

# Run the application
echo "Starting application..."
python app.py
