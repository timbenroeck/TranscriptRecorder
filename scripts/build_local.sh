#!/bin/bash
# Local build script for Transcript Recorder
# Mirrors the GitHub Actions workflow as closely as possible
#
# Usage:
#   scripts/build_local.sh                    # build, prompt to sign, prompt to launch
#   scripts/build_local.sh --sign             # build, auto-sign, auto-launch
#   scripts/build_local.sh --sign --no-run    # build, auto-sign, don't launch
#   scripts/build_local.sh --loop             # build, prompt to sign, launch loop
#   scripts/build_local.sh --sign --loop      # build, auto-sign, auto-launch, launch loop

set -e  # Exit on error

# --- Parse arguments ---
AUTO_SIGN=false
LOOP_LAUNCH=false
NO_RUN=false

for arg in "$@"; do
    case "$arg" in
        --sign) AUTO_SIGN=true ;;
        --loop) LOOP_LAUNCH=true ;;
        --no-run) NO_RUN=true ;;
        *)
            echo "Unknown argument: $arg"
            echo "Usage: $0 [--sign] [--loop] [--no-run]"
            exit 1
            ;;
    esac
done

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

# --- Step 4: Code Sign ---
echo ""
echo "=== Step 4: Code Signing ==="
if [ "$AUTO_SIGN" = true ]; then
    echo "Auto-signing enabled (--sign)..."
    "$SCRIPT_DIR/sign_app.sh" "dist/$APP_NAME.app"
else
    read -p "Would you like to code sign the app? (y/n): " SIGN_CHOICE
    if [[ "$SIGN_CHOICE" =~ ^[Yy]$ ]]; then
        "$SCRIPT_DIR/sign_app.sh" "dist/$APP_NAME.app"
    else
        echo "Skipping code signing."
    fi
fi

# --- Step 5: Launch ---
echo ""
echo "=== Build Complete ==="

if [ "$NO_RUN" = true ]; then
    echo ""
    echo "Skipping launch (--no-run)."
    echo ""
    echo "To launch from terminal (with stderr visible):"
    echo "  \"dist/$APP_NAME.app/Contents/MacOS/$APP_NAME\""
elif [ "$AUTO_SIGN" = true ]; then
    # --sign implies auto-launch after build+sign
    echo ""
    echo "Launching $APP_NAME..."
    open "dist/$APP_NAME.app"
    echo "App launched."
elif [ "$LOOP_LAUNCH" = true ]; then
    # --loop enables the interactive launch loop
    while true; do
        echo ""
        read -p "Would you like to (re)launch the app now? (y/n): " LAUNCH_CHOICE

        if [[ "$LAUNCH_CHOICE" =~ ^[Yy]$ ]]; then
            echo "Launching $APP_NAME..."
            open "dist/$APP_NAME.app"
            echo "App opened. Loop continuing..."
        else
            echo "Exiting loop."
            break
        fi
    done
else
    # No flags: single prompt to launch
    echo ""
    read -p "Would you like to launch the app now? (y/n): " LAUNCH_CHOICE
    if [[ "$LAUNCH_CHOICE" =~ ^[Yy]$ ]]; then
        echo "Launching $APP_NAME..."
        open "dist/$APP_NAME.app"
    fi
fi

# echo ""
# echo "Launch error? Run:"
# echo "  \"dist/$APP_NAME.app/Contents/MacOS/$APP_NAME\" 2>&1 | head -50"