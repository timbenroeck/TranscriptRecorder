#!/bin/bash
# Patch version and commit script for Transcript Recorder

set -e  # Exit on error

# Get the project root directory (parent of the scripts/ folder)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
cd "$PROJECT_ROOT"

echo "=== Transcript Recorder ==="
echo ""
git status

echo ""
read -p "Continue with patch version bump and commit? (y/n): " confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "Aborted."
    exit 0
fi

python bump_version.py patch   # or minor/major

# 3. Commit the version bump
git add version.py
git commit -m "Bump version to $(python -c 'from version import __version__; print(__version__)')"

# 4. Create a version tag
git tag -a "v$(python -c 'from version import __version__; print(__version__)')" -m "Release v$(python -c 'from version import __version__; print(__version__)')"

# 5. Push changes and tag
git push origin main
git push origin --tags