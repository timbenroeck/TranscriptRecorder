#!/bin/bash
# Minor version and commit script for Transcript Recorder

set -e  # Exit on error

# Get the project root directory (parent of the scripts/ folder)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
cd "$PROJECT_ROOT"

echo "=== Transcript Recorder ==="
echo ""
git status

echo ""
read -p "Continue with minor version bump and commit? (y/n): " confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "Aborted."
    exit 0
fi

# 1. Pull latest changes to avoid push rejection
echo ""
echo "Pulling latest changes from origin..."
git pull --rebase origin main

# 2. Bump version
python bump_version.py minor

# 3. Commit the version bump
git add version.py
VERSION=$(python -c 'from version import __version__; print(__version__)')
git commit -m "Bump version to ${VERSION}"

# 4. Create a version tag
git tag -a "v${VERSION}" -m "Release v${VERSION}"

# 5. Push changes and tag
git push origin main
git push origin --tags