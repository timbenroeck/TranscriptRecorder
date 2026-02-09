#!/bin/bash
# Notarizes a signed .app bundle or .dmg via Apple's notary service.
#
# Usage:
#   scripts/notarize_app.sh                                              # defaults to SourceBuild app
#   scripts/notarize_app.sh "dist/Transcript Recorder SourceBuild.app"   # specify an .app
#   scripts/notarize_app.sh "dist/TranscriptRecorder-1.2.3.dmg"         # specify a .dmg
#
# Prerequisites:
#   - The app/dmg must already be code-signed with your Developer ID
#   - Notarization credentials stored in Keychain via:
#       xcrun notarytool store-credentials "TranscriptRecorder" \
#         --apple-id "tim@benroeck.com" --team-id "Q6YV5V6UR9" --password "..."

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
cd "$PROJECT_ROOT"

TARGET="${1:-dist/Transcript Recorder SourceBuild.app}"
KEYCHAIN_PROFILE="TranscriptRecorder"

# --- Validation ---
if [ ! -e "$TARGET" ]; then
    echo "ERROR: Target not found: $TARGET"
    echo ""
    echo "Usage: $0 [path-to-.app-or-.dmg]"
    exit 1
fi

echo "=== Notarization ==="
echo "Target:           $TARGET"
echo "Keychain profile: $KEYCHAIN_PROFILE"
echo ""

# --- Determine if we're notarizing an .app or a .dmg ---
if [[ "$TARGET" == *.dmg ]]; then
    # DMG can be submitted directly
    SUBMIT_PATH="$TARGET"
    STAPLE_PATH="$TARGET"
    echo "Submitting DMG directly..."
elif [[ -d "$TARGET" && "$TARGET" == *.app ]]; then
    # .app needs to be zipped first for notarytool
    ZIP_PATH="${TARGET%.app}.zip"
    echo "Creating zip for notarization..."
    ditto -c -k --keepParent "$TARGET" "$ZIP_PATH"
    echo "  Created: $ZIP_PATH"
    SUBMIT_PATH="$ZIP_PATH"
    STAPLE_PATH="$TARGET"
else
    echo "ERROR: Target must be a .app bundle or .dmg file"
    exit 1
fi

# --- Submit to Apple ---
echo ""
echo "Submitting to Apple notary service (this may take a few minutes)..."
echo ""
xcrun notarytool submit "$SUBMIT_PATH" \
    --keychain-profile "$KEYCHAIN_PROFILE" \
    --wait \
    --timeout 30m

NOTARY_EXIT=$?

# --- Clean up the zip if we created one ---
if [[ -n "$ZIP_PATH" && -f "$ZIP_PATH" ]]; then
    echo ""
    echo "Cleaning up temporary zip..."
    rm "$ZIP_PATH"
fi

if [ $NOTARY_EXIT -ne 0 ]; then
    echo ""
    echo "ERROR: Notarization failed!"
    echo ""
    echo "To see the detailed log, run:"
    echo "  xcrun notarytool log <submission-id> --keychain-profile \"$KEYCHAIN_PROFILE\""
    echo ""
    echo "(The submission ID is shown in the output above)"
    exit 1
fi

# --- Staple the ticket ---
echo ""
echo "Stapling notarization ticket..."
xcrun stapler staple "$STAPLE_PATH"

# --- Verify ---
echo ""
echo "=== Verification ==="
if [[ -d "$STAPLE_PATH" ]]; then
    # .app verification
    echo "Checking Gatekeeper assessment..."
    spctl --assess --type execute --verbose=2 "$STAPLE_PATH" 2>&1
    echo ""
    echo "Checking staple..."
    stapler validate "$STAPLE_PATH" 2>&1
else
    # .dmg verification
    echo "Checking DMG assessment..."
    spctl --assess --type open --context context:primary-signature --verbose=2 "$STAPLE_PATH" 2>&1
    echo ""
    echo "Checking staple..."
    stapler validate "$STAPLE_PATH" 2>&1
fi

echo ""
echo "=== Notarization Complete ==="
echo ""
