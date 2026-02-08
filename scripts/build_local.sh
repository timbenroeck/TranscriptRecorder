#!/bin/bash
# Local build script for Transcript Recorder
# Mirrors the GitHub Actions workflow as closely as possible

set -e  # Exit on error

echo "=== Transcript Recorder Local Build ==="
echo ""

# Get the project root directory (parent of the scripts/ folder)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
cd "$PROJECT_ROOT"

echo "Working directory: $PROJECT_ROOT"
echo ""

# --- Check for virtual environment ---
if [ ! -d "$PROJECT_ROOT/.venv" ]; then
    echo "ERROR: No .venv found in $PROJECT_ROOT"
    echo ""
    echo "Please run full_rebuild_local.sh first to create the virtual environment:"
    echo "  scripts/full_rebuild_local.sh"
    exit 1
fi

echo "Activating virtual environment..."
source "$PROJECT_ROOT/.venv/bin/activate"
echo "Python version: $(python --version)"
echo "Python path: $(which python)"
echo ""

# --- Source build flag ---
# This produces "Transcript Recorder SourceBuild.app" with a distinct bundle
# identifier so macOS accessibility permissions don't collide with the
# installed release version in /Applications.
export SOURCE_BUILD=1
APP_NAME="Transcript Recorder SourceBuild"
echo "Building as: $APP_NAME (source build)"
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
if [ -d "dist/$APP_NAME.app" ]; then
    echo "SUCCESS: dist/$APP_NAME.app created"
    ls -la dist/
else
    echo "ERROR: Application not found in dist/"
    exit 1
fi

# --- Step 4: Launch prompt (Looping) ---
echo ""
echo "=== Build Complete ==="

while true; do
    echo ""
    read -p "Would you like to launch the app now? (y/n): " LAUNCH_CHOICE
    
    if [[ "$LAUNCH_CHOICE" =~ ^[Yy]$ ]]; then
        echo "Launching $APP_NAME..."
        open "dist/$APP_NAME.app"
        echo "App opened. Loop continuing..."
    else
        echo "Exiting. You can open it later with:"
        echo "  open \"dist/$APP_NAME.app\""
        break  # This exits the loop
    fi
done

echo ""


echo " Launch error? Run" 
echo "cd /Users/tbenroeck/Documents/code/TranscriptRecorder && source .venv/bin/activate && python gui_app.py 2>&1 | head -50"