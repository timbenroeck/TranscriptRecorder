#!/bin/bash
# Local RELEASE build for Transcript Recorder
# Mirrors the full GitHub Actions pipeline: build → sign → DMG → sign DMG → notarize
#
# This builds as "Transcript Recorder" (not SourceBuild) with the release
# bundle identifier, exactly matching what CI produces.
#
# Use this to validate the entire release pipeline before pushing a tag.

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
cd "$PROJECT_ROOT"

IDENTITY="Developer ID Application: Tim Benroeck (Q6YV5V6UR9)"

echo "============================================"
echo "  Transcript Recorder — Local Release Build"
echo "============================================"
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
echo "Python: $(python --version) ($(which python))"
echo ""

# NOTE: SOURCE_BUILD is NOT set — this produces the release app name and bundle ID
APP_NAME="Transcript Recorder"
VERSION=$(python -c "from version import __version__; print(__version__)")
DMG_NAME="TranscriptRecorder-${VERSION}.dmg"

echo "App name: $APP_NAME"
echo "Version:  $VERSION"
echo "DMG:      $DMG_NAME"
echo ""

# --- Confirmation ---
echo "WARNING: This builds the RELEASE variant (not SourceBuild)."
echo "         The release app has bundle ID 'com.transcriptrecorder.app'"
echo "         and will share accessibility permissions with your installed copy."
echo ""
read -p "Continue with release build? (y/n): " CONFIRM
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi
echo ""

# --- Step 1: Clean ---
echo "=== Step 1: Cleaning build artifacts ==="
python setup_py2app.py clean
echo ""

# --- Step 2: Build ---
echo "=== Step 2: Building application ==="
python setup_py2app.py py2app

if [ ! -d "dist/$APP_NAME.app" ]; then
    echo "ERROR: Application not found in dist/"
    exit 1
fi
echo ""
echo "SUCCESS: dist/$APP_NAME.app created"
echo ""

# --- Step 3: Sign the .app ---
echo "=== Step 3: Signing application ==="
"$SCRIPT_DIR/sign_app.sh" "dist/$APP_NAME.app" "$IDENTITY"
echo ""

# --- Step 4: Create DMG ---
echo "=== Step 4: Creating DMG ==="
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
echo ""

# --- Step 5: Sign the DMG ---
echo "=== Step 5: Signing DMG ==="
codesign --force --timestamp \
    --sign "$IDENTITY" "dist/$DMG_NAME"

codesign --verify --verbose=2 "dist/$DMG_NAME"
echo "  DMG signed successfully"
echo ""

# --- Step 6: Notarize ---
echo "=== Step 6: Notarization ==="
read -p "Would you like to notarize the DMG? (y/n): " NOTARIZE_CHOICE
if [[ "$NOTARIZE_CHOICE" =~ ^[Yy]$ ]]; then
    "$SCRIPT_DIR/notarize_app.sh" "dist/$DMG_NAME"
else
    echo "Skipping notarization."
    echo ""
    echo "You can notarize later with:"
    echo "  scripts/notarize_app.sh \"dist/$DMG_NAME\""
fi

# --- Done ---
echo ""
echo "============================================"
echo "  Release Build Complete!"
echo "============================================"
echo ""
echo "Artifacts:"
echo "  App: dist/$APP_NAME.app"
echo "  DMG: dist/$DMG_NAME"
echo ""
echo "To test the DMG:"
echo "  open \"dist/$DMG_NAME\""
echo ""
