#!/usr/bin/env python3
"""
Version bumping script for Transcript Recorder.

Usage:
    python bump_version.py major    # 1.0.0 -> 2.0.0
    python bump_version.py minor    # 1.0.0 -> 1.1.0
    python bump_version.py patch    # 1.0.0 -> 1.0.1
    python bump_version.py          # Shows current version
    python bump_version.py set X.Y.Z  # Set specific version
"""
import re
import sys
from pathlib import Path


VERSION_FILE = Path(__file__).parent / "version.py"


def read_version():
    """Read the current version from version.py."""
    content = VERSION_FILE.read_text()
    
    major = int(re.search(r'VERSION_MAJOR = (\d+)', content).group(1))
    minor = int(re.search(r'VERSION_MINOR = (\d+)', content).group(1))
    patch = int(re.search(r'VERSION_PATCH = (\d+)', content).group(1))
    
    return major, minor, patch


def write_version(major: int, minor: int, patch: int):
    """Write the new version to version.py."""
    content = VERSION_FILE.read_text()
    
    content = re.sub(r'VERSION_MAJOR = \d+', f'VERSION_MAJOR = {major}', content)
    content = re.sub(r'VERSION_MINOR = \d+', f'VERSION_MINOR = {minor}', content)
    content = re.sub(r'VERSION_PATCH = \d+', f'VERSION_PATCH = {patch}', content)
    
    VERSION_FILE.write_text(content)


def bump_version(bump_type: str):
    """Bump the version based on the type."""
    major, minor, patch = read_version()
    old_version = f"{major}.{minor}.{patch}"
    
    if bump_type == "major":
        major += 1
        minor = 0
        patch = 0
    elif bump_type == "minor":
        minor += 1
        patch = 0
    elif bump_type == "patch":
        patch += 1
    else:
        raise ValueError(f"Unknown bump type: {bump_type}")
    
    new_version = f"{major}.{minor}.{patch}"
    write_version(major, minor, patch)
    
    print(f"Bumped version: {old_version} -> {new_version}")
    return new_version


def set_version(version_str: str):
    """Set a specific version."""
    parts = version_str.split(".")
    if len(parts) != 3:
        raise ValueError("Version must be in X.Y.Z format")
    
    major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
    old_major, old_minor, old_patch = read_version()
    old_version = f"{old_major}.{old_minor}.{old_patch}"
    
    write_version(major, minor, patch)
    new_version = f"{major}.{minor}.{patch}"
    
    print(f"Set version: {old_version} -> {new_version}")
    return new_version


def main():
    if len(sys.argv) < 2:
        major, minor, patch = read_version()
        print(f"Current version: {major}.{minor}.{patch}")
        print("\nUsage:")
        print("  python bump_version.py major    # Bump major version")
        print("  python bump_version.py minor    # Bump minor version")
        print("  python bump_version.py patch    # Bump patch version")
        print("  python bump_version.py set X.Y.Z  # Set specific version")
        return
    
    action = sys.argv[1].lower()
    
    if action in ("major", "minor", "patch"):
        bump_version(action)
    elif action == "set" and len(sys.argv) >= 3:
        set_version(sys.argv[2])
    else:
        print(f"Unknown action: {action}")
        sys.exit(1)


if __name__ == "__main__":
    main()
