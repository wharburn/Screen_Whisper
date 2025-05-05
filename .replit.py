"""
Replit initialization script for Screen Whisper

This script is automatically run by Replit when the environment is created.
It ensures all dependencies are installed and the environment is set up correctly.
"""

import os
import sys
import subprocess

def install_dependencies():
    """Install Python dependencies from requirements.txt."""
    print("Installing Python dependencies...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
    print("Dependencies installed successfully!")

def setup_environment():
    """Set up environment variables if not already set."""
    env_vars = {
        "PORT": "8080",
        "HOST": "0.0.0.0"
    }
    
    for var, value in env_vars.items():
        if not os.environ.get(var):
            os.environ[var] = value
            print(f"Set environment variable {var}={value}")

def main():
    """Main initialization function."""
    print("Initializing Screen Whisper for Replit...")
    install_dependencies()
    setup_environment()
    print("Initialization complete!")
    print("You can now run the application with: python run_app.py")

if __name__ == "__main__":
    main()
