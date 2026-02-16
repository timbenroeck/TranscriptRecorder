"""
Application constants, logging setup, and utility functions.
"""
import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Dict, Optional

from version import __version__, GITHUB_OWNER, GITHUB_REPO

# macOS-native window privacy (hide from screen sharing / recording)
try:
    from AppKit import NSApp
    _HAS_APPKIT = True
except ImportError:
    _HAS_APPKIT = False

# --- Configuration Constants ---
APP_NAME = "Transcript Recorder"
APP_VERSION = __version__
APP_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "TranscriptRecorder"
CONFIG_PATH = APP_SUPPORT_DIR / "config.json"
LOG_DIR = APP_SUPPORT_DIR / ".logs"
DEFAULT_EXPORT_DIR = Path.home() / "Documents" / "TranscriptRecordings"  # suggestion only (shown in file dialogs)

# --- Built-in Manual Recording Source ---
# This is a virtual source that does not live on disk.  It allows the user to
# paste a transcript manually without needing any capture sources or accessibility
# permissions.  The key is never written to the sources directory.
MANUAL_RECORDING_KEY = "manual"
MANUAL_RECORDING_SOURCE = {
    "display_name": "Manual Recording",
    "description": "Paste or type a transcript manually — no live capture needed.",
}

# --- Logging Setup ---
LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
    "NONE": None,  # Disables logging entirely
}

# Create logger
logger = logging.getLogger("TranscriptRecorder")
tr_lib_logger = logging.getLogger("transcript_recorder")

# Track current log file path (set by setup_logging)
current_log_file_path: Optional[Path] = None

def setup_logging(config: Optional[Dict] = None):
    """Configure logging based on config file settings."""
    global current_log_file_path
    
    log_cfg = config.get("logging", {}) if config else {}
    log_level_str = log_cfg.get("level", "INFO").upper()
    log_level = LOG_LEVELS.get(log_level_str, logging.INFO)
    log_to_file = log_cfg.get("log_to_file", True)
    log_file_name = log_cfg.get("log_file_name", "tr_client.log")
    
    # Clear existing handlers
    logger.handlers.clear()
    tr_lib_logger.handlers.clear()
    
    # If logging is disabled (NONE), set to highest level and skip handlers
    if log_level is None:
        logger.setLevel(logging.CRITICAL + 10)
        tr_lib_logger.setLevel(logging.CRITICAL + 10)
        current_log_file_path = None
        return
    
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    tr_lib_logger.addHandler(console_handler)
    
    # File handler (rotating: 2 MB max, keep 3 backups)
    if log_to_file:
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            current_log_file_path = LOG_DIR / log_file_name
            file_handler = logging.handlers.RotatingFileHandler(
                current_log_file_path,
                maxBytes=2 * 1024 * 1024,  # 2 MB
                backupCount=3,
                encoding='utf-8'
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
            tr_lib_logger.addHandler(file_handler)
        except OSError as e:
            print(f"Failed to create log file: {e}")
            current_log_file_path = None
    else:
        current_log_file_path = None
    
    logger.setLevel(log_level)
    tr_lib_logger.setLevel(log_level)

# Initial basic setup (will be reconfigured after config is loaded)
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger.setLevel(logging.INFO)


def resource_path(relative_path: str) -> Path:
    """Get absolute path to resource, works for dev and for py2app bundle."""
    if hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS) / relative_path
    elif getattr(sys, 'frozen', False):
        base_path = Path(sys.executable).parent.parent / 'Resources'
    else:
        base_path = Path(__file__).parent.parent
    return base_path / relative_path


def ensure_ssl_certs() -> None:
    """Ensure a valid TLS CA certificate bundle is available.

    py2app bundles extract certifi's ``cacert.pem`` to a temp file that
    macOS may clean up between launches.  When the temp file is gone,
    any HTTPS call (Google Calendar API, update checks, etc.) fails with
    "Could not find a suitable TLS CA certificate bundle".

    This function detects the stale path and writes the cert data to a
    stable location inside App Support, then sets the environment
    variables that ``requests`` / ``urllib3`` / ``ssl`` honour.
    """
    import os

    try:
        import certifi
    except ImportError:
        return  # certifi not installed; nothing to fix

    cert_path = certifi.where()
    if os.path.isfile(cert_path):
        return  # cert file is accessible — nothing to do

    # Cert file is missing (temp dir cleaned up).  Write it to App Support.
    stable_cert = str(APP_SUPPORT_DIR / "cacert.pem")

    if not os.path.isfile(stable_cert):
        try:
            cert_data = certifi.contents()
        except AttributeError:
            # certifi < 2023 — fall back to reading the package data
            try:
                from importlib import resources as _res
                cert_data = _res.read_text("certifi", "cacert.pem")
            except Exception:
                logger.warning("ensure_ssl_certs: could not read certifi data")
                return

        APP_SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with open(stable_cert, "w", encoding="utf-8") as f:
                f.write(cert_data)
            logger.info(f"ensure_ssl_certs: wrote CA bundle to {stable_cert}")
        except OSError as exc:
            logger.warning(f"ensure_ssl_certs: failed to write CA bundle: {exc}")
            return

    os.environ["SSL_CERT_FILE"] = stable_cert
    os.environ["REQUESTS_CA_BUNDLE"] = stable_cert
    logger.info(f"ensure_ssl_certs: set SSL_CERT_FILE={stable_cert}")
