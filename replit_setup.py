"""
Replit Setup Helper for Screen Whisper

This script checks if the required environment variables are set in Replit.
If not, it provides instructions on how to set them up.

Run this script with: python replit_setup.py
"""

import os
import sys

def check_env_vars():
    """Check if required environment variables are set."""
    required_vars = {
        'DEEPL_API_KEY': 'Your DeepL API key for translation',
        'DEEPGRAM_API_KEY': 'Your Deepgram API key for speech recognition'
    }
    
    optional_vars = {
        'USE_DEEPL_PRO': 'Set to "true" if using DeepL Pro, "false" for free tier',
        'USE_MOCK_SPEECH': 'Set to "true" to use mock speech recognition (no API key needed)'
    }
    
    missing_required = []
    missing_optional = []
    
    for var, description in required_vars.items():
        if not os.environ.get(var):
            missing_required.append((var, description))
    
    for var, description in optional_vars.items():
        if not os.environ.get(var):
            missing_optional.append((var, description))
    
    return missing_required, missing_optional

def print_instructions(missing_required, missing_optional):
    """Print instructions for setting up environment variables in Replit."""
    if not missing_required and not missing_optional:
        print("✅ All environment variables are set correctly!")
        print("You can run the application with: python app.py")
        return
    
    print("\n" + "="*50)
    print("Screen Whisper - Replit Setup Instructions")
    print("="*50)
    
    if missing_required:
        print("\n⚠️  Required environment variables missing:")
        for var, description in missing_required:
            print(f"  - {var}: {description}")
    
    if missing_optional:
        print("\n📝 Optional environment variables missing:")
        for var, description in missing_optional:
            print(f"  - {var}: {description}")
    
    print("\nTo set these variables in Replit:")
    print("1. Click on the lock icon (🔒) in the left sidebar")
    print("2. Click on 'Secrets' tab")
    print("3. Add each missing variable as a key-value pair")
    print("4. Click 'Add new secret' for each one")
    
    if any(var[0] == 'USE_MOCK_SPEECH' for var in missing_optional):
        print("\nTip: If you don't have API keys, you can set USE_MOCK_SPEECH=true")
        print("     This will use simulated speech recognition for testing.")
    
    print("\nAfter setting up the variables, run this script again to verify.")
    print("="*50)

def main():
    """Main function."""
    print("Checking environment variables for Screen Whisper...")
    missing_required, missing_optional = check_env_vars()
    print_instructions(missing_required, missing_optional)

if __name__ == "__main__":
    main()
