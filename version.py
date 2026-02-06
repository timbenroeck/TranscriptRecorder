"""
Version information for Transcript Recorder.

This file is the single source of truth for the application version.
It can be auto-updated by build scripts.
"""

# Version components
VERSION_MAJOR = 1
VERSION_MINOR = 0
VERSION_PATCH = 0

# Full version string
__version__ = f"{VERSION_MAJOR}.{VERSION_MINOR}.{VERSION_PATCH}"

# GitHub repository information (for update checking)
GITHUB_OWNER = "YOUR_GITHUB_USERNAME"  # TODO: Update with your GitHub username
GITHUB_REPO = "tr_v3"  # TODO: Update with your repository name

def get_version() -> str:
    """Return the full version string."""
    return __version__

def get_version_tuple() -> tuple:
    """Return version as a tuple of integers."""
    return (VERSION_MAJOR, VERSION_MINOR, VERSION_PATCH)
