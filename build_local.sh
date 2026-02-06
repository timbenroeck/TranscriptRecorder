#!/bin/bash
# Local build script for Transcript Recorder
# Mirrors the GitHub Actions workflow as closely as possible

set -e  # Exit on error

echo "=== Transcript Recorder Local Build ==="
echo ""

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "Working directory: $SCRIPT_DIR"
echo ""

# --- Check for virtual environment ---
if [ ! -d "$SCRIPT_DIR/.venv" ]; then
    echo "ERROR: No .venv found in $SCRIPT_DIR"
    echo ""
    echo "Please run full_rebuild_local.sh first to create the virtual environment:"
    echo "  ./full_rebuild_local.sh"
    exit 1
fi

echo "Activating virtual environment..."
source "$SCRIPT_DIR/.venv/bin/activate"
echo "Python version: $(python --version)"
echo "Python path: $(which python)"
echo ""

# --- Step 1: Clean everything ---
echo "=== Step 1: Cleaning build artifacts ==="
python setup_py2app.py clean

# --- Step 2: Build the application ---
echo "=== Step 2: Building application ==="
python setup_py2app.py py2app

# --- Step 3: Verify build ---
echo ""
echo "=== Step 3: Verifying build ==="
if [ -d "dist/Transcript Recorder.app" ]; then
    echo "SUCCESS: dist/Transcript Recorder.app created"
    ls -la dist/
else
    echo "ERROR: Application not found in dist/"
    exit 1
fi

# --- Step 4: Test launch (optional) ---
echo ""
echo "=== Build Complete ==="
echo ""
echo "To test the app from terminal:"
echo "  \"dist/Transcript Recorder.app/Contents/MacOS/Transcript Recorder\""
echo ""
echo "To open the app normally:"
echo "  open \"dist/Transcript Recorder.app\""
echo ""
