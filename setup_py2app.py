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
    APP_BUNDLE_ID = 'com.benroeck.transcriptrecorder.sourcebuild'
else:
    APP_NAME = 'Transcript Recorder'
    APP_BUNDLE_ID = 'com.benroeck.transcriptrecorder.app'

APP_VERSION = __version__

# Main script
APP_SCRIPT = 'gui_app.py'

# Additional files to include (flat files go into Resources/)
DATA_FILES = [
    'config.json',
    'appicon.icns',
]

# --- Bundle manifest ---
# bundle.json at the repo root controls which rules and tools are shipped
# inside the .app.  Only explicitly listed items are included.
import json as _json

_bundle_manifest_path = Path(__file__).parent / 'bundle.json'
_bundle_rules: list = []
_bundle_tools: list = []

if _bundle_manifest_path.exists():
    with open(_bundle_manifest_path, 'r', encoding='utf-8') as _bf:
        _manifest = _json.load(_bf)
    _bundle_rules = _manifest.get('rules', [])
    _bundle_tools = _manifest.get('tools', [])
    print(f"Bundle manifest: {len(_bundle_rules)} rules, {len(_bundle_tools)} tools")
else:
    print("WARNING: bundle.json not found — no rules or tools will be bundled")

# Collect bundled rules — only those listed in the manifest
_rules_base = Path(__file__).parent / 'rules'
for _rule_name in _bundle_rules:
    _rule_dir = _rules_base / _rule_name
    if not _rule_dir.is_dir():
        print(f"WARNING: bundled rule '{_rule_name}' not found at {_rule_dir}")
        continue
    rule_files = [str(_f) for _f in sorted(_rule_dir.iterdir()) if _f.is_file()]
    if rule_files:
        DATA_FILES.append((f'rules/{_rule_name}', rule_files))
        print(f"  bundle rule: {_rule_name} ({len(rule_files)} files)")

# Collect bundled tools — only those listed in the manifest
# Walks recursively to capture subdirectories (e.g. data/corrections.json)
_tools_base = Path(__file__).parent / 'tools'
for _tool_name in _bundle_tools:
    _tool_dir = _tools_base / _tool_name
    if not _tool_dir.is_dir():
        print(f"WARNING: bundled tool '{_tool_name}' not found at {_tool_dir}")
        continue
    # Files directly in the tool root
    root_files = [str(_f) for _f in sorted(_tool_dir.iterdir()) if _f.is_file()]
    if root_files:
        DATA_FILES.append((f'tools/{_tool_name}', root_files))
    # Walk subdirectories (e.g. data/)
    for _dirpath in sorted(_tool_dir.rglob('*')):
        if _dirpath.is_dir():
            sub_files = [str(_f) for _f in sorted(_dirpath.iterdir()) if _f.is_file()]
            if sub_files:
                rel = _dirpath.relative_to(_tools_base.parent)
                DATA_FILES.append((str(rel), sub_files))
    file_count = sum(1 for _ in _tool_dir.rglob('*') if _.is_file())
    print(f"  bundle tool: {_tool_name} ({file_count} files)")

# py2app options
OPTIONS = {
    'py2app': {
        'argv_emulation': False,
        'includes': [
            'transcript_recorder',
            'transcript_utils',
            'version',
            'gui',
            'gui.constants',
            'gui.styles',
            'gui.workers',
            'gui.dialogs',
            'gui.tool_dialogs',
            'gui.data_editors',
            'gui.rule_dialogs',
            'gui.rule_editor',
            'gui.versioning',
            'gui.main_window',
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
            'gui',
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
        'iconfile': 'appicon.icns',
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
)
