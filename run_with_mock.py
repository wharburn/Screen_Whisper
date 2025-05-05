#!/usr/bin/env python3
"""
Run Script for Screen Whisper with Mock Mode

This script helps run the Screen Whisper application in mock mode
when API keys are not available.

Usage:
    python run_with_mock.py
"""

import os
import sys
import subprocess

def main():
    """Run the Screen Whisper application in mock mode."""
    # Set environment variables for mock mode
    os.environ['USE_MOCK_SPEECH'] = 'true'
    
    print("Starting Screen Whisper in mock mode (no API keys needed)...")
    print("This mode will use simulated speech recognition for testing.")
    
    # Run the application
    try:
        subprocess.run([sys.executable, "app.py"], check=True)
        return 0
    except subprocess.CalledProcessError as e:
        print(f"Error running application: {e}")
        return e.returncode
    except KeyboardInterrupt:
        print("\nApplication stopped by user")
        return 0

if __name__ == "__main__":
    sys.exit(main())
