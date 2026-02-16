#!/bin/bash
# Code-signs a built .app bundle for Transcript Recorder
#
# Usage:
#   scripts/sign_app.sh                                          # defaults to SourceBuild app
#   scripts/sign_app.sh "dist/Transcript Recorder.app"           # specify a different app
#   scripts/sign_app.sh "dist/Transcript Recorder.app" "Developer ID Application: ..."
#
# Prerequisites:
#   - Developer ID Application certificate installed in Keychain
#   - entitlements.plist in the project root

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

APP_PATH="${1:-dist/Transcript Recorder SourceBuild.app}"
IDENTITY="${2:-Developer ID Application: Tim Benroeck (Q6YV5V6UR9)}"
ENTITLEMENTS="$PROJECT_ROOT/entitlements.plist"

# --- Validation ---
if [ ! -d "$APP_PATH" ]; then
    echo "ERROR: App bundle not found at: $APP_PATH"
    echo "Usage: $0 [path-to-app] [signing-identity]"
    exit 1
fi

if [ ! -f "$ENTITLEMENTS" ]; then
    echo "ERROR: Entitlements file not found at: $ENTITLEMENTS"
    exit 1
fi

echo "=== Code Signing ==="
echo "App:          $APP_PATH"
echo "Identity:     $IDENTITY"
echo "Entitlements: $ENTITLEMENTS"
echo ""

# --- Step 1: Sign all .so files (Python extensions) ---
echo "Signing .so files..."
SO_COUNT=$(find "$APP_PATH" -name "*.so" | wc -l | tr -d ' ')
find "$APP_PATH" -name "*.so" -exec \
    codesign --force --options runtime --timestamp \
    --entitlements "$ENTITLEMENTS" \
    --sign "$IDENTITY" {} \;
echo "  Signed $SO_COUNT .so files"

# --- Step 2: Sign all .dylib files ---
echo "Signing .dylib files..."
DYLIB_COUNT=$(find "$APP_PATH" -name "*.dylib" | wc -l | tr -d ' ')
find "$APP_PATH" -name "*.dylib" -exec \
    codesign --force --options runtime --timestamp \
    --entitlements "$ENTITLEMENTS" \
    --sign "$IDENTITY" {} \;
echo "  Signed $DYLIB_COUNT .dylib files"

# --- Step 3: Sign all embedded frameworks (recursive) ---
# py2app places Qt6 frameworks in Resources/lib/ rather than Contents/Frameworks/.
# These frameworks from pip wheels have a non-standard bundle structure (no
# Current symlink, no top-level Info.plist), so codesigning the .framework
# directory alone does NOT sign the binary inside Versions/A/.  We must sign
# the inner executables explicitly, then sign each .framework directory.
echo "Signing framework binaries..."
FW_BIN_COUNT=0
find "$APP_PATH" -path "*.framework/Versions/*/[A-Z]*" -type f -perm +111 ! -name "*.plist" ! -path "*/_CodeSignature/*" | while IFS= read -r fw_bin; do
    echo "  Signing $(echo "$fw_bin" | sed "s|.*\.framework/|...|")..."
    codesign --force --options runtime --timestamp \
        --entitlements "$ENTITLEMENTS" \
        --sign "$IDENTITY" "$fw_bin"
    FW_BIN_COUNT=$((FW_BIN_COUNT + 1))
done
echo "Signing framework bundles..."
FW_COUNT=0
while IFS= read -r framework; do
    case "$framework" in */Versions/*|*/_CodeSignature/*) continue ;; esac
    echo "  Signing $(basename "$framework")..."
    codesign --force --options runtime --timestamp \
        --entitlements "$ENTITLEMENTS" \
        --sign "$IDENTITY" "$framework"
    FW_COUNT=$((FW_COUNT + 1))
done < <(find "$APP_PATH" -name "*.framework" -type d | awk '{print length, $0}' | sort -rn | cut -d' ' -f2-)
echo "  Signed $FW_COUNT framework bundles"

# --- Step 4: Sign all executables in MacOS/ ---
echo "Signing executables in Contents/MacOS/..."
for exec_file in "$APP_PATH"/Contents/MacOS/*; do
    if [ -f "$exec_file" ]; then
        echo "  Signing $(basename "$exec_file")..."
        codesign --force --options runtime --timestamp \
            --entitlements "$ENTITLEMENTS" \
            --sign "$IDENTITY" "$exec_file"
    fi
done

# --- Step 5: Sign the entire .app bundle ---
echo "Signing .app bundle..."
codesign --force --options runtime --timestamp \
    --entitlements "$ENTITLEMENTS" \
    --sign "$IDENTITY" "$APP_PATH"

echo ""
echo "=== Signing Complete ==="

# --- Verify ---
echo ""
echo "=== Verifying Signature ==="
codesign --verify --deep --strict --verbose=2 "$APP_PATH"
echo ""
echo "Signature details:"
codesign -dv "$APP_PATH" 2>&1
echo ""
echo "=== Gatekeeper Assessment ==="
spctl --assess --type execute --verbose=2 "$APP_PATH" 2>&1 || echo "(Will pass after notarization)"
echo ""
