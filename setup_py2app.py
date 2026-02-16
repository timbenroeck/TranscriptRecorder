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
# bundle.json at the repo root controls which sources and tools are shipped
# inside the .app.  Only explicitly listed items are included.
import json as _json

_bundle_manifest_path = Path(__file__).parent / 'bundle.json'
_bundle_sources: list = []
_bundle_tools: list = []

if _bundle_manifest_path.exists():
    with open(_bundle_manifest_path, 'r', encoding='utf-8') as _bf:
        _manifest = _json.load(_bf)
    _bundle_sources = _manifest.get('sources', [])
    _bundle_tools = _manifest.get('tools', [])
    print(f"Bundle manifest: {len(_bundle_sources)} sources, {len(_bundle_tools)} tools")
else:
    print("WARNING: bundle.json not found — no sources or tools will be bundled")

# Collect bundled sources — only those listed in the manifest
_sources_base = Path(__file__).parent / 'sources'
for _source_name in _bundle_sources:
    _source_dir = _sources_base / _source_name
    if not _source_dir.is_dir():
        print(f"WARNING: bundled source '{_source_name}' not found at {_source_dir}")
        continue
    source_files = [str(_f) for _f in sorted(_source_dir.iterdir()) if _f.is_file()]
    if source_files:
        DATA_FILES.append((f'sources/{_source_name}', source_files))
        print(f"  bundle source: {_source_name} ({len(source_files)} files)")

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
            # --- Application modules ---
            'transcript_recorder',
            'transcript_utils',
            'version',
            'gui',
            'gui.constants',
            'gui.styles',
            'gui.icons',
            'gui.workers',
            'gui.dialogs',
            'gui.tool_dialogs',
            'gui.data_editors',
            'gui.source_dialogs',
            'gui.source_editor',
            'gui.versioning',
            'gui.main_window',
            'gui.calendar_integration',
            'gui.calendar_dialogs',
            # --- PyQt6: only the 4 modules actually imported ---
            'PyQt6.QtCore',
            'PyQt6.QtGui',
            'PyQt6.QtWidgets',
            'PyQt6.QtSvg',
            # --- Standard library ---
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
            're',
            'subprocess',
            'collections',
            'functools',
            'os',
            'signal',
            'threading',
            # --- Google Calendar integration ---
            'google.auth',
            'google.auth.transport',
            'google.auth.transport.requests',
            'google.oauth2',
            'google.oauth2.credentials',
            'google_auth_oauthlib',
            'google_auth_oauthlib.flow',
            'googleapiclient',
            'googleapiclient.discovery',
        ],
        'packages': [
            'psutil',
            'aiofiles',
            'gui',
            # cryptography has a native Rust .so extension; must be a
            # full package so py2app keeps the .so alongside its Python
            # code instead of splitting them between the zip and lib-dynload.
            'cryptography',
        ],
        'excludes': [
            # --- Build / packaging tools ---
            'tkinter',
            'pip',
            'setuptools',
            'pkg_resources',
            'wheel',
            '_distutils_hack',
            # --- Heavy scientific / media libraries ---
            'matplotlib',
            'numpy',
            'scipy',
            'PIL',
            # --- Unused PyQt6 sub-modules ---
            'PyQt6.QtNetwork',
            'PyQt6.QtSql',
            'PyQt6.QtXml',
            'PyQt6.QtBluetooth',
            'PyQt6.QtMultimedia',
            'PyQt6.QtMultimediaWidgets',
            'PyQt6.QtWebEngine',
            'PyQt6.QtWebEngineCore',
            'PyQt6.QtWebEngineWidgets',
            'PyQt6.QtWebSockets',
            'PyQt6.QtWebChannel',
            'PyQt6.QtPositioning',
            'PyQt6.QtSerialPort',
            'PyQt6.QtNfc',
            'PyQt6.Qt3DCore',
            'PyQt6.Qt3DRender',
            'PyQt6.Qt3DInput',
            'PyQt6.Qt3DExtras',
            'PyQt6.QtTest',
            'PyQt6.QtDesigner',
            'PyQt6.QtHelp',
            'PyQt6.QtDBus',
            'PyQt6.QtOpenGL',
            'PyQt6.QtOpenGLWidgets',
            'PyQt6.QtPdf',
            'PyQt6.QtPdfWidgets',
            'PyQt6.QtRemoteObjects',
            'PyQt6.QtSensors',
            'PyQt6.QtTextToSpeech',
            'PyQt6.QtQuick',
            'PyQt6.QtQml',
            'PyQt6.QtSpatialAudio',
            # --- Unused standard library modules ---
            'test',
            # Note: unittest is needed by google-auth at runtime
            'pydoc',
            'doctest',
            'idlelib',
            'lib2to3',
            'ensurepip',
            'venv',
            'distutils',
            'curses',
            'turtledemo',
            'turtle',
            'xmlrpc',
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

# ---------------------------------------------------------------------------
# Post-build: strip unused Qt6 / PyQt6 files from the app bundle
# ---------------------------------------------------------------------------
# py2app's 'excludes' only prevents Python module *tracing*.  The PyQt6 and
# PyQt6-Qt6 binary wheels ship ALL shared libraries, QML plugins, and Python
# binding .so files in a single directory tree, so they all get copied into
# the bundle.  We remove the ones we don't need to shrink the bundle and
# drastically reduce the number of files that need code-signing.
#
# Three layers are cleaned:
#   1. Qt6/qml/*        — QML plugin modules
#   2. Qt6/plugins/*     — native plugin directories
#   3. Qt6/lib/*.framework — Qt6 C++ framework bundles
#   4. PyQt6/*.abi3.so   — Python binding .so files
# ---------------------------------------------------------------------------
if len(sys.argv) > 1 and sys.argv[1] == 'py2app':
    _dist_dir = Path('dist')
    _app_dir = _dist_dir / f'{APP_NAME}.app'
    _resources = _app_dir / 'Contents' / 'Resources'

    # ------------------------------------------------------------------
    # Pre-cleanup: extract native extensions from the Python zip
    # ------------------------------------------------------------------
    # py2app sometimes packs .so/.dylib files inside python3XX.zip.
    # Native extensions cannot be code-signed inside a zip, which causes
    # Apple notarization to reject the app.  Extract them to the
    # corresponding site-packages directory so codesign can reach them.
    import zipfile as _zipfile

    _lib_dir_res = _resources / 'lib'
    _native_exts = ('.so', '.dylib')
    for _zip_path in sorted(_lib_dir_res.glob('python*.zip')):
        # Determine the matching lib directory (e.g. python3.13/)
        # python313.zip → python3.13
        _zip_stem = _zip_path.stem  # "python313"
        _ver_digits = _zip_stem.replace('python', '')  # "313"
        if len(_ver_digits) >= 2:
            _ver_dotted = f"python{_ver_digits[0]}.{_ver_digits[1:]}"
        else:
            _ver_dotted = f"python{_ver_digits}"
        _extract_base = _lib_dir_res / _ver_dotted

        _extracted = []
        with _zipfile.ZipFile(_zip_path, 'r') as _zf:
            for _member in _zf.namelist():
                if any(_member.endswith(ext) for ext in _native_exts):
                    _extracted.append(_member)

        if _extracted:
            # Extract the native files to the lib directory
            with _zipfile.ZipFile(_zip_path, 'r') as _zf:
                for _member in _extracted:
                    _dest = _extract_base / _member
                    _dest.parent.mkdir(parents=True, exist_ok=True)
                    _dest.write_bytes(_zf.read(_member))
                    # Ensure __init__.py exists for each parent package
                    _pkg = _dest.parent
                    while _pkg != _extract_base:
                        _init = _pkg / '__init__.py'
                        if not _init.exists():
                            _init.write_text('')
                        _pkg = _pkg.parent
                    print(f"  Extracted from zip: {_member}")

            # Rewrite the zip without the native extensions
            _tmp_zip = _zip_path.with_suffix('.tmp')
            with _zipfile.ZipFile(_zip_path, 'r') as _zf_in, \
                 _zipfile.ZipFile(_tmp_zip, 'w', _zipfile.ZIP_DEFLATED) as _zf_out:
                for _item in _zf_in.infolist():
                    if _item.filename not in _extracted:
                        _zf_out.writestr(_item, _zf_in.read(_item.filename))
            _tmp_zip.replace(_zip_path)
            print(f"  Rewrote {_zip_path.name} without {len(_extracted)} native extension(s)")

    removed_count = 0

    # ------------------------------------------------------------------
    # Locate the PyQt6 and Qt6 directories inside the bundle
    # ------------------------------------------------------------------
    _pyqt6_candidates = list(_resources.rglob('PyQt6'))
    _pyqt6_dir = None
    for _c in _pyqt6_candidates:
        if _c.is_dir() and (_c / 'Qt6').is_dir():
            _pyqt6_dir = _c
            break
    _qt6_dir = _pyqt6_dir / 'Qt6' if _pyqt6_dir else None

    # ------------------------------------------------------------------
    # Layer 1 & 2: Strip unused QML modules and plugin directories
    # ------------------------------------------------------------------
    if _qt6_dir and _qt6_dir.is_dir():
        # --- QML modules to remove (under Qt6/qml/) ---
        _unwanted_qml = [
            'QtQml',
            'QtQuick',
            'QtQuick3D',
            'QtWebSockets',
            'QtWebChannel',
            'QtMultimedia',
            'QtPositioning',
            'QtRemoteObjects',
            'QtSensors',
            'QtTextToSpeech',
            'QtTest',
        ]

        # --- Plugin directories to remove (under Qt6/plugins/) ---
        # Keep: platforms, styles, iconengines, imageformats, tls,
        #       sqldrivers, networkinformation, generic, permissions
        _unwanted_plugins = [
            'renderers',          # Qt3D
            'sceneparsers',       # Qt3D
            'assetimporters',     # Qt3D
            'geometryloaders',    # Qt3D
            'renderplugins',      # Qt3D
            'sensors',            # QtSensors
            'position',           # QtPositioning
            'texttospeech',       # QtTextToSpeech
            'webview',            # QtWebEngine
            'multimedia',         # QtMultimedia
            'qmllint',            # QML tooling
        ]

        _qml_dir = _qt6_dir / 'qml'
        if _qml_dir.is_dir():
            for name in _unwanted_qml:
                target = _qml_dir / name
                if target.is_dir():
                    fc = sum(1 for _ in target.rglob('*') if _.is_file())
                    shutil.rmtree(target)
                    removed_count += fc
                    print(f"  Stripped QML module: {name} ({fc} files)")

        _plugins_dir = _qt6_dir / 'plugins'
        if _plugins_dir.is_dir():
            for name in _unwanted_plugins:
                target = _plugins_dir / name
                if target.is_dir():
                    fc = sum(1 for _ in target.rglob('*') if _.is_file())
                    shutil.rmtree(target)
                    removed_count += fc
                    print(f"  Stripped plugin dir: {name} ({fc} files)")

        # ------------------------------------------------------------------
        # Layer 3: Strip unused Qt6 lib/*.framework bundles
        # ------------------------------------------------------------------
        # Whitelist: only frameworks needed at C++ runtime for
        # QtCore + QtGui + QtWidgets + QtSvg on macOS.
        _keep_frameworks = {
            'QtCore',
            'QtGui',
            'QtWidgets',
            'QtSvg',
            'QtSvgWidgets',       # SVG widget rendering
            'QtDBus',             # macOS runtime dependency of QtCore
            'QtOpenGL',           # RHI rendering backend for QtGui
            'QtNetwork',          # internal Qt networking
            'QtPrintSupport',     # widget print support
        }

        _lib_dir = _qt6_dir / 'lib'
        if _lib_dir.is_dir():
            for fw_path in sorted(_lib_dir.iterdir()):
                if fw_path.is_dir() and fw_path.suffix == '.framework':
                    fw_name = fw_path.stem  # e.g. "QtQuick3D"
                    if fw_name not in _keep_frameworks:
                        fc = sum(1 for _ in fw_path.rglob('*') if _.is_file())
                        shutil.rmtree(fw_path)
                        removed_count += fc
                        print(f"  Stripped framework:  {fw_name}.framework ({fc} files)")

    # ------------------------------------------------------------------
    # Layer 4: Strip unused PyQt6 Python binding .abi3.so files
    # ------------------------------------------------------------------
    # Whitelist: only the .so files for modules actually imported.
    if _pyqt6_dir and _pyqt6_dir.is_dir():
        _keep_so = {
            'sip',          # SIP binding layer (not .abi3.so but .cpython-*.so)
            'QtCore',
            'QtGui',
            'QtWidgets',
            'QtSvg',
        }

        for so_path in sorted(_pyqt6_dir.glob('*.abi3.so')):
            # Filename like "QtWebSockets.abi3.so" → module name "QtWebSockets"
            module_name = so_path.name.split('.')[0]
            if module_name not in _keep_so:
                so_path.unlink()
                removed_count += 1
                print(f"  Stripped binding:   {so_path.name}")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    if removed_count:
        print(f"Post-build cleanup: removed {removed_count} unused Qt6/PyQt6 files")
    else:
        print("Post-build cleanup: no unused files found (already clean)")
