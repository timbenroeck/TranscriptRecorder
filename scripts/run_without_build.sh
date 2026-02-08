#!/bin/bash
# Run Transcript Recorder directly from source (no build step)
# Useful for quick testing without rebuilding the .app bundle

set -e  # Exit on error

echo "=== Transcript Recorder - Run From Source ==="
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

echo "=== Launching gui_app.py ==="
echo ""
python gui_app.py
