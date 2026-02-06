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

# --- Step 1: Clean everything ---
echo "=== Step 1: Cleaning build artifacts ==="

# Remove virtual environment
if [ -d ".venv" ]; then
    echo "Removing .venv..."
    rm -rf .venv
fi

# Remove build directories
for dir in build dist .eggs *.egg-info dmg_contents; do
    if [ -d "$dir" ] || ls $dir 1> /dev/null 2>&1; then
        echo "Removing $dir..."
        rm -rf $dir 2>/dev/null || true
    fi
done

# Remove __pycache__ directories
echo "Removing __pycache__ directories..."
find . -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true

# Remove .pyc files
echo "Removing .pyc files..."
find . -type f -name '*.pyc' -delete 2>/dev/null || true

# Remove .DS_Store files
echo "Removing .DS_Store files..."
find . -type f -name '.DS_Store' -delete 2>/dev/null || true

echo "Clean complete."
echo ""

# --- Step 2: Create virtual environment ---
echo "=== Step 2: Creating virtual environment ==="
python3 -m venv .venv
source .venv/bin/activate

echo "Python version: $(python --version)"
echo "Python path: $(which python)"
echo ""

# --- Step 3: Install dependencies (mirrors GitHub Action) ---
echo "=== Step 3: Installing dependencies ==="
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install py2app

echo ""
echo "Installed packages:"
pip list
echo ""

# --- Step 4: Build the application ---
echo "=== Step 4: Building application ==="
python setup_py2app.py py2app

# --- Step 5: Verify build ---
echo ""
echo "=== Step 5: Verifying build ==="
if [ -d "dist/Transcript Recorder.app" ]; then
    echo "SUCCESS: dist/Transcript Recorder.app created"
    ls -la dist/
else
    echo "ERROR: Application not found in dist/"
    exit 1
fi

# --- Step 6: Test launch (optional) ---
echo ""
echo "=== Build Complete ==="
echo ""
echo "To test the app from terminal:"
echo "  \"dist/Transcript Recorder.app/Contents/MacOS/Transcript Recorder\""
echo ""
echo "To open the app normally:"
echo "  open \"dist/Transcript Recorder.app\""
echo ""
