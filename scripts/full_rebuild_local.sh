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

# --- Build type selection ---
# SourceBuild produces "Transcript Recorder SourceBuild.app" with a distinct
# bundle identifier so macOS accessibility permissions don't collide with the
# installed release version in /Applications.
# Release mirrors the GitHub CI pipeline and produces a signed DMG.
echo "Select build type:"
echo "  1) SourceBuild  — local dev, separate accessibility permissions"
echo "  2) Release      — mirrors GitHub CI, produces signed DMG"
echo ""
read -p "Choice [1/2]: " BUILD_TYPE_CHOICE

case "$BUILD_TYPE_CHOICE" in
    2)
        export SOURCE_BUILD=0
        APP_NAME="Transcript Recorder"
        IS_RELEASE=true
        echo "Building as: $APP_NAME (release)"
        ;;
    *)
        export SOURCE_BUILD=1
        APP_NAME="Transcript Recorder SourceBuild"
        IS_RELEASE=false
        echo "Building as: $APP_NAME (source build)"
        ;;
esac
echo ""

# --- Step 3: Install dependencies (mirrors GitHub Action) ---
echo "=== Step 3: Installing dependencies ==="
python -m pip install --upgrade pip "setuptools<81"
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
if [ -d "dist/$APP_NAME.app" ]; then
    echo "SUCCESS: dist/$APP_NAME.app created"
    ls -la dist/
else
    echo "ERROR: Application not found in dist/"
    exit 1
fi

# --- Step 6: Code Sign ---
echo ""
echo "=== Step 6: Code Signing ==="
if [ "$IS_RELEASE" = true ]; then
    # Release builds must be signed for DMG/notarization
    echo "Release build — code signing is required."
    "$SCRIPT_DIR/sign_app.sh" "dist/$APP_NAME.app"
else
    read -p "Would you like to code sign the app? (y/n): " SIGN_CHOICE
    if [[ "$SIGN_CHOICE" =~ ^[Yy]$ ]]; then
        "$SCRIPT_DIR/sign_app.sh" "dist/$APP_NAME.app"
    else
        echo "Skipping code signing."
    fi
fi

# --- Release-only: DMG creation, signing, and notarization ---
if [ "$IS_RELEASE" = true ]; then

    # --- Step 7: Create DMG (mirrors build-release.yml) ---
    VERSION=$(python -c "from version import __version__; print(__version__)")
    DMG_NAME="TranscriptRecorder-${VERSION}.dmg"

    echo ""
    echo "=== Step 7: Creating DMG ==="
    rm -rf dmg_contents
    mkdir -p dmg_contents
    cp -R "dist/$APP_NAME.app" dmg_contents/
    ln -s /Applications dmg_contents/Applications

    hdiutil create -volname "$APP_NAME" \
        -srcfolder dmg_contents \
        -ov -format UDZO \
        "dist/$DMG_NAME"

    rm -rf dmg_contents
    echo "  Created: dist/$DMG_NAME"

    # --- Step 8: Sign DMG ---
    IDENTITY="Developer ID Application: Tim Benroeck (Q6YV5V6UR9)"

    echo ""
    echo "=== Step 8: Signing DMG ==="
    codesign --force --timestamp \
        --sign "$IDENTITY" "dist/$DMG_NAME"

    codesign --verify --verbose=2 "dist/$DMG_NAME"
    echo "  DMG signed successfully"

    # --- Step 9: Notarize ---
    echo ""
    echo "=== Step 9: Notarization ==="
    read -p "Would you like to notarize the DMG? (y/n): " NOTARIZE_CHOICE
    if [[ "$NOTARIZE_CHOICE" =~ ^[Yy]$ ]]; then
        "$SCRIPT_DIR/notarize_app.sh" "dist/$DMG_NAME"
    else
        echo "Skipping notarization."
        echo ""
        echo "You can notarize later with:"
        echo "  scripts/notarize_app.sh \"dist/$DMG_NAME\""
    fi

    # --- Done (release) ---
    echo ""
    echo "=== Release Build Complete ==="
    echo ""
    echo "Artifacts:"
    echo "  App: dist/$APP_NAME.app"
    echo "  DMG: dist/$DMG_NAME"
    echo ""
    echo "To test the DMG:"
    echo "  open \"dist/$DMG_NAME\""
    echo ""

else

    # --- Step 7: Launch prompt (SourceBuild only) ---
    echo ""
    echo "=== Build Complete ==="
    echo ""
    read -p "Would you like to launch the app now? (y/n): " LAUNCH_CHOICE
    if [[ "$LAUNCH_CHOICE" =~ ^[Yy]$ ]]; then
        echo "Launching $APP_NAME..."
        open "dist/$APP_NAME.app"
    else
        echo "Skipping launch. You can open it later with:"
        echo "  open \"dist/$APP_NAME.app\""
    fi
    echo ""

fi
