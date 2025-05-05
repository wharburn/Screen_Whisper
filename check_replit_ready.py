"""
Replit Readiness Check for Screen Whisper

This script checks if the application is ready to run on Replit.
It verifies:
1. Required files exist
2. Environment variables are set up
3. Dependencies are installed

Run this script with: python check_replit_ready.py
"""

import os
import sys
import importlib
import subprocess

def check_file_exists(file_path, required=True):
    """Check if a file exists."""
    exists = os.path.exists(file_path)
    if required and not exists:
        return False, f"❌ Required file {file_path} is missing"
    elif not required and not exists:
        return True, f"⚠️ Optional file {file_path} is missing"
    return True, f"✅ File {file_path} exists"

def check_module_installed(module_name):
    """Check if a Python module is installed."""
    try:
        importlib.import_module(module_name)
        return True, f"✅ Module {module_name} is installed"
    except ImportError:
        return False, f"❌ Module {module_name} is not installed"

def check_env_var(var_name, required=True):
    """Check if an environment variable is set."""
    value = os.environ.get(var_name)
    if required and not value:
        return False, f"❌ Required environment variable {var_name} is not set"
    elif not required and not value:
        return True, f"⚠️ Optional environment variable {var_name} is not set"
    return True, f"✅ Environment variable {var_name} is set"

def run_checks():
    """Run all checks and return results."""
    results = []
    
    # Check required files
    results.append(check_file_exists("app.py"))
    results.append(check_file_exists("templates/index.html"))
    results.append(check_file_exists("static/images/SWlogo.png"))
    results.append(check_file_exists("livetranslate/translate.py"))
    results.append(check_file_exists(".replit"))
    results.append(check_file_exists("replit.nix"))
    
    # Check environment variables
    if os.environ.get("USE_MOCK_SPEECH") == "true":
        results.append((True, "✅ Using mock speech recognition (no API keys needed)"))
    else:
        results.append(check_env_var("DEEPGRAM_API_KEY"))
    
    results.append(check_env_var("DEEPL_API_KEY"))
    results.append(check_env_var("USE_DEEPL_PRO", required=False))
    
    # Check required modules
    required_modules = [
        "aiohttp", 
        "socketio", 
        "dotenv", 
        "websockets"
    ]
    
    for module in required_modules:
        results.append(check_module_installed(module))
    
    return results

def print_results(results):
    """Print check results in a formatted way."""
    print("\n" + "="*50)
    print("Screen Whisper - Replit Readiness Check")
    print("="*50 + "\n")
    
    all_passed = True
    warnings = []
    errors = []
    
    for success, message in results:
        print(message)
        if not success:
            all_passed = False
            errors.append(message)
        elif message.startswith("⚠️"):
            warnings.append(message)
    
    print("\n" + "="*50)
    if all_passed and not warnings:
        print("✅ All checks passed! Your app is ready to run on Replit.")
        print("   Run the app with: python app.py")
    elif all_passed:
        print("✅ All required checks passed, but there are some warnings.")
        print("   The app should still run, but you might want to address these:")
        for warning in warnings:
            print(f"   {warning}")
    else:
        print("❌ Some checks failed. Please fix the following issues:")
        for error in errors:
            print(f"   {error}")
    print("="*50)

def main():
    """Main function."""
    results = run_checks()
    print_results(results)
    
    # Return exit code based on results
    for success, _ in results:
        if not success:
            return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
