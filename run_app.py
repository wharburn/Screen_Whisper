#!/usr/bin/env python3
"""
Run Script for Screen Whisper

This script helps run the Screen Whisper application with a custom port
if the default port is already in use.

Usage:
    python run_app.py [port]
"""

import os
import sys
import subprocess

def main():
    """Run the Screen Whisper application."""
    # Check if a port was provided as an argument
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
            print(f"Using port {port} from command line argument")
            os.environ['PORT'] = str(port)
        except ValueError:
            print(f"Error: '{sys.argv[1]}' is not a valid port number")
            print("Usage: python run_app.py [port]")
            return 1
    
    # Run the application
    print("Starting Screen Whisper application...")
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
