"""
py2app setup script for Transcript Recorder

To build the application:
    python setup_py2app.py py2app

To clean build artifacts:
    python setup_py2app.py clean

The built application will be in the 'dist' folder.
"""
import sys
import shutil
from pathlib import Path

# Handle clean command before importing setuptools
if len(sys.argv) > 1 and sys.argv[1] == 'clean':
    dirs_to_clean = ['build', 'dist', '.eggs', '*.egg-info']
    files_to_clean = ['.DS_Store']
    
    root = Path(__file__).parent
    
    for pattern in dirs_to_clean:
        for path in root.glob(pattern):
            if path.is_dir():
                print(f"Removing directory: {path}")
                shutil.rmtree(path, ignore_errors=True)
    
    for pattern in files_to_clean:
        for path in root.glob(f"**/{pattern}"):
            if path.is_file():
                print(f"Removing file: {path}")
                path.unlink(missing_ok=True)
    
    # Also clean __pycache__ directories
    for path in root.glob("**/__pycache__"):
        if path.is_dir():
            print(f"Removing directory: {path}")
            shutil.rmtree(path, ignore_errors=True)
    
    print("Clean complete.")
    sys.exit(0)

import os
from setuptools import setup
from version import __version__

# Determine if this is a local source build or a release build.
# Set SOURCE_BUILD=1 environment variable (used by build_local.sh) to produce
# "Transcript Recorder SourceBuild.app" with a distinct bundle identifier so
# macOS accessibility permissions don't collide with the installed release app.
IS_SOURCE_BUILD = os.environ.get('SOURCE_BUILD', '0') == '1'

# App information
if IS_SOURCE_BUILD:
    APP_NAME = 'Transcript Recorder SourceBuild'
    APP_BUNDLE_ID = 'com.transcriptrecorder.sourcebuild'
else:
    APP_NAME = 'Transcript Recorder'
    APP_BUNDLE_ID = 'com.transcriptrecorder.app'

APP_VERSION = __version__

# Main script
APP_SCRIPT = 'gui_app.py'

# Additional files to include
DATA_FILES = [
    'config.json',
    'transcriber.icns',
]

# py2app options
OPTIONS = {
    'py2app': {
        'argv_emulation': False,
        'includes': [
            'transcript_recorder',
            'transcript_utils',
            'version',
            'asyncio',
            'json',
            'logging',
            'pathlib',
            'datetime',
            'time',
            'difflib',
            'shutil',
            'urllib',
            'urllib.request',
            'urllib.error',
            'tempfile',
        ],
        'packages': [
            'PyQt6',
            'psutil',
            'aiofiles',
        ],
        'excludes': [
            'tkinter',
            'matplotlib',
            'numpy',
            'scipy',
            'PIL',
            'pip',
            'setuptools',
            'pkg_resources',
            'wheel',
            '_distutils_hack',
        ],
        'resources': DATA_FILES,
        'iconfile': 'transcriber.icns',
        'plist': {
            'CFBundleName': APP_NAME,
            'CFBundleDisplayName': APP_NAME,
            'CFBundleGetInfoString': f'{APP_NAME} {APP_VERSION}',
            'CFBundleIdentifier': APP_BUNDLE_ID,
            'CFBundleVersion': APP_VERSION,
            'CFBundleShortVersionString': APP_VERSION,
            'NSPrincipalClass': 'NSApplication',
            'NSRequiresAquaSystemAppearance': False,
            'LSMinimumSystemVersion': '12.0',
            'NSHighResolutionCapable': True,
            'LSApplicationCategoryType': 'public.app-category.productivity',
            'NSHumanReadableCopyright': 'Copyright © 2024 Transcript Recorder',
            'NSAccessibilityUsageDescription': (
                'Transcript Recorder needs accessibility access to read '
                'meeting transcripts from supported applications.'
            ),
            'CFBundleDocumentTypes': [],
            'LSEnvironment': {
                'PATH': '/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin'
            }
        },
    }
}

setup(
    name=APP_NAME,
    version=APP_VERSION,
    description='Automated transcript capture from meeting applications',
    app=[APP_SCRIPT],
    data_files=DATA_FILES,
    options=OPTIONS,
    setup_requires=['py2app'],
)
