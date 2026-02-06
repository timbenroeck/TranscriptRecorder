"""
Transcript Recorder - macOS GUI Application

A user-friendly application for recording meeting transcripts using macOS 
accessibility APIs. Supports Zoom, Microsoft Teams, WebEx, and Slack.
"""
import asyncio
import json
import logging
import logging.handlers
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import (
    Qt, QTimer, QThread, pyqtSignal, QSize
)
from PyQt6.QtGui import (
    QAction, QActionGroup, QFont, QIcon, QPalette, QColor
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QTextEdit, QProgressBar,
    QMessageBox, QFileDialog, QStatusBar, QGroupBox, QSpinBox,
    QSplitter, QFrame, QSizePolicy, QSystemTrayIcon, QMenu,
    QTabWidget, QLineEdit, QStyle
)

from transcript_recorder import TranscriptRecorder, AXIsProcessTrusted
from transcript_utils import smart_merge
from version import __version__, GITHUB_OWNER, GITHUB_REPO

# --- Configuration Constants ---
APP_NAME = "Transcript Recorder"
APP_VERSION = __version__
DEFAULT_CONFIG_DIR = Path.home() / "Documents" / "transcriptrecorder"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.json"
DEFAULT_LOG_DIR = DEFAULT_CONFIG_DIR / ".logs"
DEFAULT_LOG_FILE = DEFAULT_LOG_DIR / "tr_gui_client.log"

# --- Logging Setup ---
LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
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
    
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    tr_lib_logger.addHandler(console_handler)
    
    # File handler (rotating: 2 MB max, keep 3 backups)
    if log_to_file:
        try:
            DEFAULT_LOG_DIR.mkdir(parents=True, exist_ok=True)
            current_log_file_path = DEFAULT_LOG_DIR / log_file_name
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
        base_path = Path(__file__).parent
    return base_path / relative_path


def get_dialog_button_styles():
    """Get button styles for dialog windows."""
    primary_style = """
        QPushButton {
            background-color: #007AFF;
            color: white;
            border: none;
            border-radius: 6px;
            padding: 6px 14px;
            font-weight: 500;
        }
        QPushButton:hover {
            background-color: #0A84FF;
        }
        QPushButton:pressed {
            background-color: #0066CC;
        }
    """
    
    secondary_style = """
        QPushButton {
            background-color: #FFFFFF;
            color: #1D1D1F;
            border: 1px solid #D2D2D7;
            border-radius: 6px;
            padding: 6px 14px;
            font-weight: 500;
        }
        QPushButton:hover {
            background-color: #F0F0F0;
        }
        QPushButton:pressed {
            background-color: #E0E0E0;
        }
    """
    
    danger_style = """
        QPushButton {
            background-color: #FF3B30;
            color: white;
            border: none;
            border-radius: 6px;
            padding: 6px 14px;
            font-weight: 500;
        }
        QPushButton:hover {
            background-color: #FF453A;
        }
        QPushButton:pressed {
            background-color: #D62D20;
        }
    """
    
    success_style = """
        QPushButton {
            background-color: #34C759;
            color: white;
            border: none;
            border-radius: 6px;
            padding: 6px 14px;
            font-weight: 500;
        }
        QPushButton:hover {
            background-color: #30D158;
        }
        QPushButton:pressed {
            background-color: #28A745;
        }
    """
    
    return primary_style, secondary_style, danger_style, success_style


class LogViewerDialog(QMainWindow):
    """A window for viewing the application log file."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Log Viewer")
        self.setMinimumSize(600, 400)
        self.resize(800, 500)
        
        primary_style, secondary_style, danger_style, _ = get_dialog_button_styles()
        
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        
        # Log text area
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Menlo", 11))
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #FFFFFF;
                color: #1D1D1F;
                border: 1px solid #D2D2D7;
                border-radius: 6px;
                padding: 8px;
            }
        """)
        layout.addWidget(self.log_text)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setStyleSheet(primary_style)
        self.refresh_btn.clicked.connect(self._load_log)
        btn_layout.addWidget(self.refresh_btn)
        
        self.clear_btn = QPushButton("Clear Log")
        self.clear_btn.setStyleSheet(danger_style)
        self.clear_btn.clicked.connect(self._clear_log)
        btn_layout.addWidget(self.clear_btn)
        
        btn_layout.addStretch()
        
        self.close_btn = QPushButton("Close")
        self.close_btn.setStyleSheet(secondary_style)
        self.close_btn.clicked.connect(self.close)
        btn_layout.addWidget(self.close_btn)
        
        layout.addLayout(btn_layout)
        
        # Load initial content
        self._load_log()
    
    def _load_log(self):
        """Load the last 200 lines of the log file."""
        log_path = current_log_file_path
        if log_path is None:
            self.log_text.setPlainText("File logging is disabled in configuration.")
            return
            
        try:
            if log_path.exists():
                max_lines = 200
                with open(log_path, 'r', encoding='utf-8') as f:
                    all_lines = f.readlines()
                if not all_lines:
                    self.log_text.setPlainText("(Log file is empty)")
                    return
                tail_lines = all_lines[-max_lines:]
                truncated = len(all_lines) > max_lines
                header = f"--- Showing last {len(tail_lines)} of {len(all_lines)} lines ---\n\n" if truncated else ""
                self.log_text.setPlainText(header + "".join(tail_lines))
                # Scroll to bottom
                cursor = self.log_text.textCursor()
                cursor.movePosition(cursor.MoveOperation.End)
                self.log_text.setTextCursor(cursor)
            else:
                self.log_text.setPlainText(f"Log file not found at:\n{log_path}")
        except Exception as e:
            self.log_text.setPlainText(f"Error loading log file: {e}")
    
    def _clear_log(self):
        """Clear the log file."""
        log_path = current_log_file_path
        if log_path is None:
            return
            
        reply = QMessageBox.question(
            self, "Clear Log",
            "Are you sure you want to clear the log file?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                if log_path.exists():
                    with open(log_path, 'w', encoding='utf-8') as f:
                        f.write("")
                    self._load_log()
                    logger.info("Log viewer: log file cleared by user")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to clear log file: {e}")


class ConfigEditorDialog(QMainWindow):
    """A window for viewing and editing the configuration file."""
    
    config_saved = pyqtSignal()  # Signal emitted when config is saved
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuration Editor")
        self.setMinimumSize(600, 500)
        self.resize(700, 600)
        self._is_modified = False
        
        primary_style, secondary_style, _, success_style = get_dialog_button_styles()
        
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        
        # Info label
        info_label = QLabel(f"Editing: {DEFAULT_CONFIG_PATH}")
        info_label.setStyleSheet("color: #86868B; font-size: 11px;")
        layout.addWidget(info_label)
        
        # Config text area
        self.config_text = QTextEdit()
        self.config_text.setFont(QFont("Menlo", 11))
        self.config_text.setStyleSheet("""
            QTextEdit {
                background-color: #FFFFFF;
                color: #1D1D1F;
                border: 1px solid #D2D2D7;
                border-radius: 6px;
                padding: 8px;
            }
        """)
        self.config_text.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.config_text)
        
        # Status label for validation
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("font-size: 12px;")
        layout.addWidget(self.status_label)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        
        self.reload_btn = QPushButton("Reload")
        self.reload_btn.setStyleSheet(secondary_style)
        self.reload_btn.clicked.connect(self._load_config)
        btn_layout.addWidget(self.reload_btn)
        
        self.download_btn = QPushButton("Download from URL")
        self.download_btn.setStyleSheet(secondary_style)
        self.download_btn.clicked.connect(self._download_from_url)
        btn_layout.addWidget(self.download_btn)
        
        self.restore_btn = QPushButton("Restore Packaged Config")
        self.restore_btn.setStyleSheet(secondary_style)
        self.restore_btn.clicked.connect(self._restore_packaged_config)
        btn_layout.addWidget(self.restore_btn)
        
        btn_layout.addStretch()
        
        self.save_btn = QPushButton("Save")
        self.save_btn.setStyleSheet(success_style)
        self.save_btn.clicked.connect(self._save_config)
        btn_layout.addWidget(self.save_btn)
        
        self.validate_btn = QPushButton("Validate JSON")
        self.validate_btn.setStyleSheet(primary_style)
        self.validate_btn.clicked.connect(self._validate_json)
        btn_layout.addWidget(self.validate_btn)
        
        self.close_btn = QPushButton("Close")
        self.close_btn.setStyleSheet(secondary_style)
        self.close_btn.clicked.connect(self.close)
        btn_layout.addWidget(self.close_btn)
        
        layout.addLayout(btn_layout)
        
        # Load initial content
        self._load_config()
    
    def _on_text_changed(self):
        """Track modifications."""
        self._is_modified = True
        self.status_label.setText("")
    
    def _load_config(self):
        """Load config file contents."""
        try:
            if DEFAULT_CONFIG_PATH.exists():
                with open(DEFAULT_CONFIG_PATH, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.config_text.setPlainText(content)
                self._is_modified = False
                self.status_label.setText("")
            else:
                self.config_text.setPlainText("{}")
                self.status_label.setText("Config file not found, starting with empty config.")
                self.status_label.setStyleSheet("color: #FF9500; font-size: 12px;")
        except Exception as e:
            self.config_text.setPlainText("")
            self.status_label.setText(f"Error loading config: {e}")
            self.status_label.setStyleSheet("color: #FF3B30; font-size: 12px;")
    
    def _validate_json(self) -> bool:
        """Validate the JSON in the text area."""
        try:
            json.loads(self.config_text.toPlainText())
            self.status_label.setText("✓ Valid JSON")
            self.status_label.setStyleSheet("color: #34C759; font-size: 12px;")
            return True
        except json.JSONDecodeError as e:
            self.status_label.setText(f"✗ Invalid JSON: {e}")
            self.status_label.setStyleSheet("color: #FF3B30; font-size: 12px;")
            return False
    
    def _save_config(self):
        """Save the config file after validating JSON."""
        if not self._validate_json():
            QMessageBox.warning(
                self, "Invalid JSON",
                "The configuration contains invalid JSON and cannot be saved.\n\n"
                "Please fix the errors and try again."
            )
            return
        
        try:
            # Parse and re-format with indentation
            config_data = json.loads(self.config_text.toPlainText())
            formatted = json.dumps(config_data, indent=2)
            
            with open(DEFAULT_CONFIG_PATH, 'w', encoding='utf-8') as f:
                f.write(formatted)
            
            self.config_text.setPlainText(formatted)
            self._is_modified = False
            self.status_label.setText("✓ Configuration saved")
            self.status_label.setStyleSheet("color: #34C759; font-size: 12px;")
            logger.info(f"Config editor: saved to {DEFAULT_CONFIG_PATH}")
            self.config_saved.emit()
            
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save configuration:\n{e}")
    
    def _download_from_url(self):
        """Download configuration from a URL."""
        # Construct default URL from version.py constants
        default_url = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/refs/heads/main/config.json"
        
        # Show input dialog for URL
        from PyQt6.QtWidgets import QInputDialog
        url, ok = QInputDialog.getText(
            self,
            "Download Configuration from URL",
            "Enter the URL to download configuration from:",
            QLineEdit.EchoMode.Normal,
            default_url
        )
        
        if not ok or not url.strip():
            return
        
        url = url.strip()
        
        try:
            self.status_label.setText("Downloading...")
            self.status_label.setStyleSheet("color: #007AFF; font-size: 12px;")
            QApplication.processEvents()
            
            req = urllib.request.Request(url, headers={'User-Agent': f'{APP_NAME}/{APP_VERSION}'})
            with urllib.request.urlopen(req, timeout=30) as response:
                content = response.read().decode('utf-8')
            
            # Validate JSON
            try:
                json.loads(content)
            except json.JSONDecodeError as e:
                self.status_label.setText(f"✗ Downloaded file is not valid JSON: {e}")
                self.status_label.setStyleSheet("color: #FF3B30; font-size: 12px;")
                QMessageBox.critical(
                    self, "Invalid Configuration",
                    f"The downloaded file is not valid JSON:\n{e}"
                )
                return
            
            # Update the text area with the downloaded content
            self.config_text.setPlainText(content)
            self._is_modified = True
            self.status_label.setText(f"✓ Downloaded from URL (click Save to apply)")
            self.status_label.setStyleSheet("color: #34C759; font-size: 12px;")
            logger.info(f"Config editor: downloaded config from {url}")
            
        except urllib.error.HTTPError as e:
            self.status_label.setText(f"✗ HTTP Error {e.code}")
            self.status_label.setStyleSheet("color: #FF3B30; font-size: 12px;")
            QMessageBox.critical(
                self, "Download Error",
                f"HTTP Error {e.code}: {e.reason}\n\nURL: {url}"
            )
        except urllib.error.URLError as e:
            self.status_label.setText("✗ Download failed")
            self.status_label.setStyleSheet("color: #FF3B30; font-size: 12px;")
            QMessageBox.critical(
                self, "Download Error",
                f"Failed to download configuration:\n{e.reason}\n\nURL: {url}"
            )
        except Exception as e:
            self.status_label.setText("✗ Download failed")
            self.status_label.setStyleSheet("color: #FF3B30; font-size: 12px;")
            logger.error("Config editor: failed to download config from URL", exc_info=True)
            QMessageBox.critical(
                self, "Download Error",
                f"Failed to download configuration:\n{e}"
            )
    
    def _restore_packaged_config(self):
        """Restore the bundled/packaged config into the editor."""
        bundled_config = resource_path("config.json")
        if not bundled_config.exists():
            self.status_label.setText("✗ Packaged config not found")
            self.status_label.setStyleSheet("color: #FF3B30; font-size: 12px;")
            QMessageBox.warning(
                self, "Restore Error",
                "Could not find the packaged configuration file.\n\n"
                "This may happen if the application was not installed properly."
            )
            return
        
        reply = QMessageBox.question(
            self, "Restore Packaged Config",
            "This will replace the editor contents with the packaged default configuration.\n\n"
            "Your current config will NOT be overwritten until you click Save.\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        try:
            with open(bundled_config, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Validate the bundled config is valid JSON
            try:
                json.loads(content)
            except json.JSONDecodeError as e:
                self.status_label.setText(f"✗ Packaged config is not valid JSON: {e}")
                self.status_label.setStyleSheet("color: #FF3B30; font-size: 12px;")
                return
            
            self.config_text.setPlainText(content)
            self._is_modified = True
            self.status_label.setText("✓ Packaged config restored (click Save to apply)")
            self.status_label.setStyleSheet("color: #34C759; font-size: 12px;")
            logger.info("Config editor: restored packaged config into editor")
            
        except Exception as e:
            self.status_label.setText("✗ Failed to restore packaged config")
            self.status_label.setStyleSheet("color: #FF3B30; font-size: 12px;")
            logger.error("Config editor: failed to restore packaged config", exc_info=True)
            QMessageBox.critical(
                self, "Restore Error",
                f"Failed to read packaged configuration:\n{e}"
            )
    
    def closeEvent(self, event):
        """Warn if there are unsaved changes."""
        if self._is_modified:
            reply = QMessageBox.question(
                self, "Unsaved Changes",
                "You have unsaved changes. Close anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
        event.accept()


class RecordingWorker(QThread):
    """Background worker thread for continuous transcript recording."""
    
    snapshot_completed = pyqtSignal(bool, str, int, int)  # success, merged_path, line_count, overlap
    countdown_tick = pyqtSignal(int)  # seconds remaining
    error_occurred = pyqtSignal(str)
    
    def __init__(self, recorder: TranscriptRecorder, interval_seconds: int, 
                 recording_path: Path, merged_transcript_path: Path, parent=None):
        super().__init__(parent)
        self.recorder = recorder
        self.interval_seconds = interval_seconds
        self.recording_path = recording_path
        self.merged_transcript_path = merged_transcript_path
        self._is_running = True
        self.snapshot_count = 0
        
    def run(self):
        """Main recording loop."""
        logger.info(f"Auto capture started (interval={self.interval_seconds}s, app={self.recorder.app_identifier})")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            while self._is_running:
                # Countdown
                for i in range(self.interval_seconds, 0, -1):
                    if not self._is_running:
                        break
                    self.countdown_tick.emit(i)
                    self.msleep(1000)
                
                if not self._is_running:
                    break
                    
                # Export snapshot
                self.countdown_tick.emit(0)
                try:
                    logger.debug(f"Auto capture: taking snapshot #{self.snapshot_count + 1}")
                    success, file_path, line_count = loop.run_until_complete(
                        self.recorder.export_transcript_text()
                    )
                    
                    if success and file_path:
                        self.snapshot_count += 1
                        overlap_count = 0
                        
                        # Merge snapshots into meeting_transcript.txt
                        if self.snapshot_count == 1:
                            # First snapshot - just copy to merged location
                            shutil.copy(file_path, str(self.merged_transcript_path))
                            logger.info(f"Auto capture: first snapshot saved ({line_count} lines)")
                        else:
                            # Merge with existing transcript
                            merge_success, _, overlap_count = smart_merge(
                                str(self.merged_transcript_path),
                                file_path,
                                str(self.merged_transcript_path)
                            )
                            logger.info(f"Auto capture: snapshot #{self.snapshot_count} merged ({line_count} lines, {overlap_count} overlap)")
                        
                        # Always return the merged transcript path for display
                        self.snapshot_completed.emit(True, str(self.merged_transcript_path), line_count or 0, overlap_count)
                    else:
                        logger.debug("Auto capture: snapshot returned no data")
                        self.snapshot_completed.emit(False, "", 0, 0)
                        
                except Exception as e:
                    logger.error(f"Auto capture: snapshot failed: {e}", exc_info=True)
                    self.error_occurred.emit(str(e))
                    
        except Exception as e:
            logger.error(f"Auto capture: worker thread error: {e}", exc_info=True)
            self.error_occurred.emit(str(e))
        finally:
            logger.info(f"Auto capture stopped after {self.snapshot_count} snapshots")
            loop.close()
    
    def stop(self):
        """Signal the worker to stop."""
        logger.debug("Auto capture: stop requested")
        self._is_running = False


class UpdateCheckWorker(QThread):
    """Background worker to check for application updates without blocking the UI."""
    
    update_available = pyqtSignal(str, str, str, list)  # version, release_url, notes, assets
    check_finished = pyqtSignal()  # emitted when check completes (no update or error)
    
    def run(self):
        """Check GitHub releases for a newer version."""
        try:
            if GITHUB_OWNER == "YOUR_GITHUB_USERNAME":
                logger.debug("Startup update check: skipped (GITHUB_OWNER not configured)")
                self.check_finished.emit()
                return
            
            url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
            logger.debug(f"Startup update check: querying GitHub API")
            
            request = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": f"{APP_NAME}/{APP_VERSION}",
                }
            )
            
            with urllib.request.urlopen(request, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
            
            latest_version = data.get("tag_name", "").lstrip("v")
            release_url = data.get("html_url", "")
            release_notes = data.get("body", "No release notes available.")
            assets = data.get("assets", [])
            
            # Compare versions
            current_parts = [int(x) for x in APP_VERSION.split(".")]
            latest_parts = [int(x) for x in latest_version.split(".")]
            
            while len(current_parts) < len(latest_parts):
                current_parts.append(0)
            while len(latest_parts) < len(current_parts):
                latest_parts.append(0)
            
            if latest_parts > current_parts:
                logger.info(f"Startup update check: new version available ({latest_version}, current {APP_VERSION})")
                self.update_available.emit(latest_version, release_url, release_notes, assets)
            else:
                logger.debug(f"Startup update check: already on latest version ({APP_VERSION})")
                self.check_finished.emit()
                
        except Exception as e:
            logger.debug(f"Startup update check failed silently: {e}")
            self.check_finished.emit()


class TranscriptRecorderApp(QMainWindow):
    """Main application window for Transcript Recorder."""
    
    def __init__(self):
        super().__init__()
        
        # State
        self.config: Optional[Dict[str, Any]] = None
        self.selected_app_key: Optional[str] = None
        self.recorder_instance: Optional[TranscriptRecorder] = None
        self.recording_worker: Optional[RecordingWorker] = None
        self.current_recording_path: Optional[Path] = None
        self.snapshots_path: Optional[Path] = None  # Hidden .snapshots folder
        self.merged_transcript_path: Optional[Path] = None  # meeting_transcript.txt
        self.export_base_dir: Path = DEFAULT_CONFIG_DIR
        self.is_recording = False
        self.snapshot_count = 0
        self.capture_interval = 30  # Default capture interval in seconds
        self.theme_mode = "system"  # "light", "dark", or "system"
        self.meeting_details_dirty = False  # Track if meeting details need saving
        
        # Setup UI
        self._setup_window()
        self._setup_ui()
        self._setup_menubar()
        self._setup_tray()
        self._load_config()
        self._update_button_states()  # Set initial disabled state before permission check
        self._check_permissions()
        
        # Resize to fit content at minimum size
        self.resize(self.minimumSizeHint())
        
        # Start non-blocking update check in the background
        self._startup_update_worker = UpdateCheckWorker()
        self._startup_update_worker.update_available.connect(self._on_startup_update_available)
        self._startup_update_worker.start()
        
    def _setup_window(self):
        """Configure main window properties."""
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(450, 350)
        # Will be adjusted to fit content after UI is built
        
        # Try to load app icon
        icon_path = resource_path("transcriber.icns")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        
        # macOS specific settings
        if sys.platform == "darwin":
            self.setUnifiedTitleAndToolBarOnMac(True)
    
    def _setup_ui(self):
        """Build the user interface."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(12, 8, 12, 12)
        main_layout.setSpacing(8)
        
        # === Application Selection Section ===
        app_group = QWidget()
        app_layout = QHBoxLayout(app_group)
        app_layout.setContentsMargins(0, 0, 0, 0)
        app_layout.setSpacing(8)
        
        self.app_combo = QComboBox()
        self.app_combo.setMinimumWidth(180)
        self.app_combo.currentIndexChanged.connect(self._on_app_changed)
        app_layout.addWidget(self.app_combo)
        
        self.new_btn = QPushButton("New Recording")
        self.new_btn.setToolTip("Start a new recording session")
        self.new_btn.clicked.connect(self._on_new_recording)
        app_layout.addWidget(self.new_btn)
        
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setEnabled(False)
        self.reset_btn.setToolTip("Reset the current recording session")
        self.reset_btn.clicked.connect(self._on_reset_recording)
        app_layout.addWidget(self.reset_btn)
        
        app_layout.addStretch()
        
        main_layout.addWidget(app_group)
        
        # === Recording Controls Section ===
        controls_group = QWidget()
        controls_layout = QHBoxLayout(controls_group)
        controls_layout.setContentsMargins(0, 4, 0, 4)
        controls_layout.setSpacing(8)
        
        self.capture_btn = QPushButton("Capture Now")
        self.capture_btn.setEnabled(False)
        self.capture_btn.setToolTip("Take a single transcript snapshot")
        self.capture_btn.clicked.connect(self._on_capture_now)
        controls_layout.addWidget(self.capture_btn)
        
        self.auto_capture_btn = QPushButton("Start Auto Capture")
        self.auto_capture_btn.setEnabled(False)
        self.auto_capture_btn.setToolTip("Toggle continuous transcript capture")
        self.auto_capture_btn.clicked.connect(self._on_toggle_auto_capture)
        controls_layout.addWidget(self.auto_capture_btn)
        
        main_layout.addWidget(controls_group)
        
        # Add spacing before tab panel
        main_layout.addSpacing(8)
        
        # === Tabbed Section (Meeting Details & Transcript) ===
        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(False)
        self.tab_widget.tabBar().setExpanding(False)  # Left-align tabs
        self.tab_widget.tabBar().setDrawBase(False)  # Remove the line under tabs
        self.tab_widget.tabBar().setAutoFillBackground(False)
        self.tab_widget.setAutoFillBackground(False)
        
        # --- Meeting Details Tab (first/default) ---
        details_tab = QWidget()
        details_tab.setAutoFillBackground(False)
        details_layout = QVBoxLayout(details_tab)
        details_layout.setContentsMargins(0, 8, 0, 0)
        details_layout.setSpacing(8)
        
        # Meeting Name
        name_layout = QHBoxLayout()
        name_label = QLabel("Meeting Name:")
        name_label.setFixedWidth(110)
        name_layout.addWidget(name_label)
        
        self.meeting_name_input = QLineEdit()
        self.meeting_name_input.setPlaceholderText("Enter meeting name...")
        self.meeting_name_input.textChanged.connect(self._on_meeting_details_changed)
        name_layout.addWidget(self.meeting_name_input)
        
        details_layout.addLayout(name_layout)
        
        # Meeting Date/Time
        datetime_layout = QHBoxLayout()
        datetime_layout.setSpacing(4)
        datetime_label = QLabel("Date/Time:")
        datetime_label.setFixedWidth(110)
        datetime_layout.addWidget(datetime_label)
        
        self.meeting_datetime_input = QLineEdit()
        self.meeting_datetime_input.textChanged.connect(self._on_meeting_details_changed)
        datetime_layout.addWidget(self.meeting_datetime_input, stretch=1)
        
        # 1. Grab the native system icons once
        style = self.style()
        icon_up = style.standardIcon(QStyle.StandardPixmap.SP_ArrowUp)
        icon_down = style.standardIcon(QStyle.StandardPixmap.SP_ArrowDown)

        # Round time buttons (right-aligned)
        self.time_down_btn = QPushButton()
        self.time_down_btn.setIcon(icon_down)
        self.time_down_btn.setFixedWidth(36)
        self.time_down_btn.setToolTip("Round time down by 5 minutes")
        self.time_down_btn.clicked.connect(self._on_round_time_down)
        datetime_layout.addWidget(self.time_down_btn)
        
        self.time_up_btn = QPushButton()
        self.time_up_btn.setIcon(icon_up)
        self.time_up_btn.setFixedWidth(36)
        self.time_up_btn.setToolTip("Round time up by 5 minutes")
        self.time_up_btn.clicked.connect(self._on_round_time_up)
        datetime_layout.addWidget(self.time_up_btn)
        
        details_layout.addLayout(datetime_layout)
        
        # Meeting Notes
        notes_label = QLabel("Meeting Notes:")
        details_layout.addWidget(notes_label)
        
        self.meeting_notes_input = QTextEdit()
        self.meeting_notes_input.setPlaceholderText("Enter meeting notes, attendees, action items, etc...")
        self.meeting_notes_input.setFont(QFont("SF Pro", 12))
        self.meeting_notes_input.textChanged.connect(self._on_meeting_details_changed)
        details_layout.addWidget(self.meeting_notes_input)
        
        # Meeting Details actions
        details_actions_layout = QHBoxLayout()
        details_actions_layout.setSpacing(8)
        
        self.save_details_btn = QPushButton("Save Details")
        self.save_details_btn.setEnabled(False)
        self.save_details_btn.clicked.connect(self._on_save_details_clicked)
        details_actions_layout.addWidget(self.save_details_btn)
        
        self.open_folder_btn2 = QPushButton("Open Folder")
        self.open_folder_btn2.setEnabled(False)
        self.open_folder_btn2.clicked.connect(self._on_open_folder)
        details_actions_layout.addWidget(self.open_folder_btn2)
        
        details_actions_layout.addStretch()
        
        details_layout.addLayout(details_actions_layout)
        
        self.tab_widget.addTab(details_tab, "Meeting Details")
        
        # --- Meeting Transcript Tab ---
        transcript_tab = QWidget()
        transcript_tab.setAutoFillBackground(False)
        transcript_layout = QVBoxLayout(transcript_tab)
        transcript_layout.setContentsMargins(0, 8, 0, 0)
        
        self.transcript_text = QTextEdit()
        self.transcript_text.setReadOnly(True)
        self.transcript_text.setPlaceholderText(
            "Transcript will appear here after recording starts...\n\n"
            "To begin:\n"
            "1. Select your meeting application above\n"
            "2. Make sure your meeting has captions/transcript enabled\n"
            "3. Click 'New Recording' then 'Capture Now' or 'Start Auto Capture'"
        )
        self.transcript_text.setFont(QFont("SF Pro", 12))
        transcript_layout.addWidget(self.transcript_text)
        
        # Transcript actions
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(8)
        
        self.copy_btn = QPushButton("Copy Transcript")
        self.copy_btn.setEnabled(False)
        self.copy_btn.clicked.connect(self._on_copy_transcript)
        actions_layout.addWidget(self.copy_btn)
        
        self.open_folder_btn = QPushButton("Open Folder")
        self.open_folder_btn.setEnabled(False)
        self.open_folder_btn.clicked.connect(self._on_open_folder)
        actions_layout.addWidget(self.open_folder_btn)
        
        actions_layout.addStretch()
        
        self.line_count_label = QLabel("Lines: 0")
        actions_layout.addWidget(self.line_count_label)
        
        transcript_layout.addLayout(actions_layout)
        
        self.tab_widget.addTab(transcript_tab, "Meeting Transcript")
        
        main_layout.addWidget(self.tab_widget, stretch=1)
        
        # === Apply Modern Styling ===
        self._apply_styles()
        
        # === Status Bar ===
        self.statusBar().showMessage("Ready")
        
        # Add version label to the right side of the status bar
        self.version_label = QLabel(f"v{APP_VERSION}")
        self.version_label.setStyleSheet("color: gray; padding-right: 8px;")
        self.statusBar().addPermanentWidget(self.version_label)
    
    def _is_dark_mode(self) -> bool:
        """Determine if dark mode should be used based on theme setting."""
        if self.theme_mode == "dark":
            return True
        elif self.theme_mode == "light":
            return False
        else:  # "system"
            palette = QApplication.palette()
            return palette.window().color().lightness() < 128
    
    def _set_theme(self, mode: str):
        """Change the application theme."""
        self.theme_mode = mode
        self._apply_styles()
        self.statusBar().showMessage(f"Appearance: {mode.capitalize()}")
    
    def _apply_styles(self):
        """Apply full theme styling including backgrounds, text, and buttons."""
        is_dark = self._is_dark_mode()
        
        if is_dark:
            # Dark mode - dark backgrounds, light text
            window_bg = "#1E1E1E"
            group_bg = "#2D2D2D"
            group_border = "#3D3D3D"
            text_primary = "#FFFFFF"
            text_secondary = "#98989D"
            text_edit_bg = "#1A1A1A"
            text_edit_text = "#FFFFFF"
            text_edit_border = "#3D3D3D"
            disabled_bg = "#3A3A3C"
            disabled_text = "#636366"
            secondary_btn_bg = "#3A3A3C"
            secondary_btn_text = "#FFFFFF"
            secondary_btn_border = "#4A4A4C"
            secondary_btn_hover = "#4A4A4C"
            combo_bg = "#2D2D2D"
            combo_text = "#FFFFFF"
            combo_border = "#3D3D3D"
        else:
            # Light mode - light backgrounds, dark text
            window_bg = "#F5F5F7"
            group_bg = "#FFFFFF"
            group_border = "#E0E0E0"
            text_primary = "#1D1D1F"
            text_secondary = "#86868B"
            text_edit_bg = "#FFFFFF"
            text_edit_text = "#1D1D1F"
            text_edit_border = "#D2D2D7"
            disabled_bg = "#E5E5EA"
            disabled_text = "#8E8E93"
            secondary_btn_bg = "#FFFFFF"
            secondary_btn_text = "#1D1D1F"
            secondary_btn_border = "#D2D2D7"
            secondary_btn_hover = "#F0F0F0"
            combo_bg = "#FFFFFF"
            combo_text = "#1D1D1F"
            combo_border = "#D2D2D7"
        
        # Main window style - unified background, no section boxes
        window_style = f"""
            QMainWindow {{
                background-color: {window_bg};
            }}
            QWidget {{
                background-color: {window_bg};
                color: {text_primary};
            }}
            QGroupBox {{
                background-color: transparent;
                border: none;
                margin-top: 8px;
                padding-top: 4px;
                font-weight: 600;
                color: {text_primary};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 2px;
                color: {text_primary};
            }}
            QLabel {{
                background-color: transparent;
                color: {text_primary};
            }}
            QStatusBar {{
                background-color: {window_bg};
                color: {text_secondary};
            }}
        """
        self.setStyleSheet(window_style)
        
        # Text edit (transcript area)
        text_edit_style = f"""
            QTextEdit {{
                background-color: {text_edit_bg};
                color: {text_edit_text};
                border: 1px solid {text_edit_border};
                border-radius: 6px;
                padding: 8px;
                selection-background-color: #007AFF;
                selection-color: white;
            }}
        """
        self.transcript_text.setStyleSheet(text_edit_style)
        
        # Combo box
        combo_style = f"""
            QComboBox {{
                background-color: {combo_bg};
                color: {combo_text};
                border: 1px solid {combo_border};
                border-radius: 6px;
                padding: 5px 10px;
                min-height: 20px;
            }}
            QComboBox:hover {{
                border-color: #007AFF;
            }}
            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}
            QComboBox::down-arrow {{
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 6px solid {text_secondary};
                margin-right: 8px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {combo_bg};
                color: {combo_text};
                selection-background-color: #007AFF;
                selection-color: white;
            }}
        """
        self.app_combo.setStyleSheet(combo_style)
        
        # Primary button (blue)
        primary_style = f"""
            QPushButton {{
                background-color: #007AFF;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: #0A84FF;
            }}
            QPushButton:pressed {{
                background-color: #0066CC;
            }}
            QPushButton:disabled {{
                background-color: {disabled_bg};
                color: {disabled_text};
            }}
        """
        
        # Success button (green) - stored for toggle button
        self._success_style = f"""
            QPushButton {{
                background-color: #34C759;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: #30D158;
            }}
            QPushButton:pressed {{
                background-color: #28A745;
            }}
            QPushButton:disabled {{
                background-color: {disabled_bg};
                color: {disabled_text};
            }}
        """
        
        # Danger button (red) - stored for toggle button
        self._danger_style = f"""
            QPushButton {{
                background-color: #FF3B30;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: #FF453A;
            }}
            QPushButton:pressed {{
                background-color: #D62D20;
            }}
            QPushButton:disabled {{
                background-color: {disabled_bg};
                color: {disabled_text};
            }}
        """
        
        # Secondary button
        secondary_style = f"""
            QPushButton {{
                background-color: {secondary_btn_bg};
                color: {secondary_btn_text};
                border: 1px solid {secondary_btn_border};
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: {secondary_btn_hover};
            }}
            QPushButton:pressed {{
                background-color: {secondary_btn_hover};
            }}
            QPushButton:disabled {{
                background-color: {disabled_bg};
                color: {disabled_text};
                border-color: {disabled_bg};
            }}
        """
        
        # Apply button styles
        self.new_btn.setStyleSheet(primary_style)
        self.reset_btn.setStyleSheet(secondary_style)
        self.capture_btn.setStyleSheet(primary_style)
        self._update_auto_capture_btn_style()
        self.copy_btn.setStyleSheet(secondary_style)
        self.open_folder_btn.setStyleSheet(secondary_style)
        self.save_details_btn.setStyleSheet(secondary_style)
        self.open_folder_btn2.setStyleSheet(secondary_style)
        self.time_down_btn.setStyleSheet(secondary_style)
        self.time_up_btn.setStyleSheet(secondary_style)
        
        # Secondary text color
        self.line_count_label.setStyleSheet(f"background-color: transparent; color: {text_secondary};")
        
        # Tab widget - button-like tabs, completely flat
        tab_style = f"""
            QTabWidget {{
                background: {window_bg};
                border: 0;
                padding: 0;
                margin: 0;
            }}
            QTabWidget::pane {{
                background: {window_bg};
                border: 0;
                padding: 0;
                margin: 0;
                top: 0;
            }}
            QTabWidget::tab-bar {{
                background: {window_bg};
                border: 0;
                left: 0;
            }}
            QTabBar {{
                background: {window_bg};
                border: 0;
                qproperty-drawBase: 0;
            }}
            QTabBar::scroller {{
                width: 0;
            }}
            QTabBar::tear {{
                width: 0;
                border: 0;
            }}
            QTabBar::tab {{
                background: transparent;
                color: {text_secondary};
                padding: 6px 14px;
                margin-right: 8px;
                margin-bottom: 4px;
                border: 1px solid {text_edit_border};
                border-radius: 6px;
            }}
            QTabBar::tab:selected {{
                background: #007AFF;
                color: white;
                border: 1px solid #007AFF;
                font-weight: 500;
            }}
            QTabBar::tab:hover:!selected {{
                background: {secondary_btn_hover};
                color: {text_primary};
            }}
            QTabBar::tab:disabled {{
                background: transparent;
                color: {disabled_text};
                border: 1px solid {disabled_bg};
            }}
            QTabBar::tab:selected:disabled {{
                background: {disabled_bg};
                color: {disabled_text};
                border: 1px solid {disabled_bg};
                font-weight: 500;
            }}
        """
        self.tab_widget.setStyleSheet(tab_style)
        
        # Line edit (meeting name)
        line_edit_style = f"""
            QLineEdit {{
                background-color: {text_edit_bg};
                color: {text_edit_text};
                border: 1px solid {text_edit_border};
                border-radius: 6px;
                padding: 6px 10px;
                selection-background-color: #007AFF;
                selection-color: white;
            }}
            QLineEdit:focus {{
                border-color: #007AFF;
            }}
        """
        self.meeting_name_input.setStyleSheet(line_edit_style)
        self.meeting_datetime_input.setStyleSheet(line_edit_style)
        
        # Meeting notes text edit
        self.meeting_notes_input.setStyleSheet(text_edit_style)
        
    def _setup_menubar(self):
        """Create the application menu bar."""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("File")
        
        new_action = QAction("New Recording", self)
        new_action.setShortcut("Cmd+N")
        new_action.triggered.connect(self._on_new_recording)
        file_menu.addAction(new_action)
        
        reset_action = QAction("Reset", self)
        reset_action.setShortcut("Cmd+R")
        reset_action.triggered.connect(self._on_reset_recording)
        file_menu.addAction(reset_action)
        
        file_menu.addSeparator()
        
        open_folder_action = QAction("Open Export Folder", self)
        open_folder_action.setShortcut("Cmd+O")
        open_folder_action.triggered.connect(self._on_open_export_folder)
        file_menu.addAction(open_folder_action)
        
        # Edit menu
        edit_menu = menubar.addMenu("Edit")
        
        copy_action = QAction("Copy Transcript", self)
        copy_action.setShortcut("Cmd+C")
        copy_action.triggered.connect(self._on_copy_transcript)
        edit_menu.addAction(copy_action)
        
        # View menu
        view_menu = menubar.addMenu("View")
        
        appearance_menu = view_menu.addMenu("Appearance")
        
        # Create action group for exclusive selection
        appearance_group = QActionGroup(self)
        appearance_group.setExclusive(True)
        
        self.theme_system_action = QAction("System", self)
        self.theme_system_action.setCheckable(True)
        self.theme_system_action.setChecked(True)
        self.theme_system_action.triggered.connect(lambda: self._set_theme("system"))
        appearance_group.addAction(self.theme_system_action)
        appearance_menu.addAction(self.theme_system_action)
        
        self.theme_light_action = QAction("Light", self)
        self.theme_light_action.setCheckable(True)
        self.theme_light_action.triggered.connect(lambda: self._set_theme("light"))
        appearance_group.addAction(self.theme_light_action)
        appearance_menu.addAction(self.theme_light_action)
        
        self.theme_dark_action = QAction("Dark", self)
        self.theme_dark_action.setCheckable(True)
        self.theme_dark_action.triggered.connect(lambda: self._set_theme("dark"))
        appearance_group.addAction(self.theme_dark_action)
        appearance_menu.addAction(self.theme_dark_action)
        
        view_menu.addSeparator()
        
        log_action = QAction("Log File...", self)
        log_action.setShortcut("Cmd+L")
        log_action.triggered.connect(self._show_log_viewer)
        view_menu.addAction(log_action)
        
        # Also add to macOS app menu as Preferences (standard location for Cmd+,)
        self.prefs_action = QAction("Preferences...", self)
        self.prefs_action.setShortcut("Cmd+,")
        self.prefs_action.setMenuRole(QAction.MenuRole.PreferencesRole)
        self.prefs_action.triggered.connect(self._show_config_editor)
        view_menu.addAction(self.prefs_action)  # Qt will move this to app menu on macOS
        
        # Maintenance menu
        maint_menu = menubar.addMenu("Maintenance")
        
        self.config_action = QAction("Edit Configuration...", self)
        self.config_action.setMenuRole(QAction.MenuRole.NoRole)  # Prevent macOS from moving it
        self.config_action.triggered.connect(self._show_config_editor)
        maint_menu.addAction(self.config_action)
        
        reload_config_action = QAction("Reload Configuration", self)
        reload_config_action.triggered.connect(self._reload_configuration)
        maint_menu.addAction(reload_config_action)
        
        maint_menu.addSeparator()
        
        clear_log_action = QAction("Clear Log File", self)
        clear_log_action.triggered.connect(self._clear_log_file)
        maint_menu.addAction(clear_log_action)
        
        clear_snapshots_action = QAction("Clear All Snapshots", self)
        clear_snapshots_action.triggered.connect(self._clear_all_snapshots)
        maint_menu.addAction(clear_snapshots_action)
        
        clear_empty_action = QAction("Clear Empty Recordings", self)
        clear_empty_action.triggered.connect(self._clear_empty_recordings)
        maint_menu.addAction(clear_empty_action)
        
        maint_menu.addSeparator()
        
        permissions_action = QAction("Check Permissions", self)
        permissions_action.triggered.connect(self._check_permissions)
        maint_menu.addAction(permissions_action)
        
        update_action = QAction("Check for Updates...", self)
        update_action.triggered.connect(self._check_for_updates)
        maint_menu.addAction(update_action)
        
        maint_menu.addSeparator()
        
        about_action = QAction(f"About {APP_NAME}", self)
        about_action.setMenuRole(QAction.MenuRole.AboutRole)
        about_action.triggered.connect(self._show_about)
        maint_menu.addAction(about_action)
        
    def _setup_tray(self):
        """Setup system tray icon (optional)."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
            
        icon_path = resource_path("transcriber.icns")
        if not icon_path.exists():
            return
            
        self.tray_icon = QSystemTrayIcon(QIcon(str(icon_path)), self)
        
        tray_menu = QMenu()
        show_action = tray_menu.addAction("Show Window")
        show_action.triggered.connect(self.show)
        
        tray_menu.addSeparator()
        
        quit_action = tray_menu.addAction("Quit")
        quit_action.triggered.connect(self.close)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()
        
    def _load_config(self):
        """Load application configuration."""
        config_path = DEFAULT_CONFIG_PATH
        config_dir = config_path.parent
        
        try:
            config_dir.mkdir(parents=True, exist_ok=True)
            
            if not config_path.exists():
                # Copy bundled config
                bundled_config = resource_path("config.json")
                if bundled_config.exists():
                    shutil.copy(bundled_config, config_path)
                    logger.info(f"Config: copied bundled config to {config_path}")
                else:
                    logger.error("Config: bundled config not found; cannot initialize")
                    QMessageBox.critical(
                        self, "Configuration Error",
                        "Could not find configuration file. Please reinstall the application."
                    )
                    return
                    
            with open(config_path, 'r') as f:
                self.config = json.load(f)
                
            # Set export directory
            tui_settings = self.config.get("client_settings", {}).get("tui", {})
            export_dir = tui_settings.get("export_directory", str(DEFAULT_CONFIG_DIR))
            self.export_base_dir = Path(export_dir).expanduser().resolve()
            self.export_base_dir.mkdir(parents=True, exist_ok=True)
            
            # Configure logging from config
            setup_logging(self.config)
            
            # Populate app selection
            self._populate_app_combo()
            
            app_count = self.config.get("application_settings", {})
            log_level = self.config.get("logging", {}).get("level", "INFO")
            logger.info(f"Config: loaded from {config_path} ({len(app_count)} apps, log_level={log_level})")
            self.statusBar().showMessage(f"Configuration loaded")
            
        except json.JSONDecodeError as e:
            QMessageBox.critical(
                self, "Configuration Error",
                f"Invalid configuration file:\n{e}"
            )
        except Exception as e:
            QMessageBox.critical(
                self, "Configuration Error",
                f"Failed to load configuration:\n{e}"
            )
            logger.error(f"Config load error: {e}", exc_info=True)
    
    def _populate_app_combo(self):
        """Fill the application dropdown from config."""
        if not self.config:
            return
            
        self.app_combo.clear()
        app_settings = self.config.get("application_settings", {})
        
        for app_key, app_data in app_settings.items():
            display_name = app_data.get("display_name", app_key)
            self.app_combo.addItem(display_name, app_key)
            
        if self.app_combo.count() > 0:
            self._on_app_changed(0)
            
    def _check_permissions(self):
        """Check and warn about accessibility permissions."""
        try:
            if not AXIsProcessTrusted():
                QMessageBox.warning(
                    self, "Accessibility Permission Required",
                    "This application requires accessibility permissions to read "
                    "meeting transcripts.\n\n"
                    "Please grant access in:\n"
                    "System Settings → Privacy & Security → Accessibility\n\n"
                    "You may need to restart the application after granting permission."
                )
                self.new_btn.setEnabled(False)
                self.statusBar().showMessage("⚠️ Accessibility permission required")
            else:
                self.new_btn.setEnabled(True)
                logger.info("Permissions: accessibility access granted")
        except Exception as e:
            logger.error(f"Permissions: check failed: {e}")
            
    def _on_startup_update_available(self, version: str, release_url: str, notes: str, assets: list):
        """Handle notification that a new version is available (from background check)."""
        QMessageBox.information(
            self,
            "Update Available",
            f"A new version of {APP_NAME} is available!\n\n"
            f"Current version: {APP_VERSION}\n"
            f"Latest version: {version}\n\n"
            f"You can download it from the Maintenance menu → Check for Updates."
        )
    
    def _on_app_changed(self, index: int):
        """Handle application selection change."""
        if index < 0:
            return
            
        self.selected_app_key = self.app_combo.currentData()
        if self.selected_app_key and self.config:
            app_config = self.config.get("application_settings", {}).get(self.selected_app_key, {})
            self.capture_interval = app_config.get("monitor_interval_seconds", 30)
            logger.debug(f"App selection changed: {self.selected_app_key} (capture interval: {self.capture_interval}s)")
            
    def _on_new_recording(self):
        """Start a new recording session."""
        if not self.selected_app_key or not self.config:
            logger.warning("New session: no application selected")
            QMessageBox.warning(self, "No Application", "Please select a meeting application first.")
            return
            
        app_config = self.config.get("application_settings", {}).get(self.selected_app_key, {})
        if not app_config:
            logger.error(f"New session: no config found for {self.selected_app_key}")
            QMessageBox.warning(self, "Configuration Error", f"No configuration found for {self.selected_app_key}")
            return
            
        # Reset state
        if self.is_recording:
            self._on_stop_recording()
            
        # Create recording directory with new structure:
        # /recordings/recording_{timestamp}_{app_name}/
        #   - meeting_transcript.txt (merged transcript)
        #   - .snapshots/ (created on-demand when first snapshot is taken)
        timestamp = datetime.now()
        folder_name = f"recording_{timestamp.strftime('%Y-%m-%d_%H%M')}_{self.selected_app_key}"
        self.current_recording_path = self.export_base_dir / "recordings" / folder_name
        self.snapshots_path = self.current_recording_path / ".snapshots"
        self.merged_transcript_path = self.current_recording_path / "meeting_transcript.txt"
        
        try:
            self.current_recording_path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"New session: failed to create recording folder: {e}")
            QMessageBox.critical(self, "Error", f"Failed to create recording folder:\n{e}")
            return
            
        # Create recorder instance - snapshots go to the hidden .snapshots folder
        tr_config = app_config.copy()
        tr_config["base_transcript_directory"] = str(self.snapshots_path)
        tr_config["name"] = self.selected_app_key
        
        try:
            self.recorder_instance = TranscriptRecorder(app_config=tr_config, logger=logger)
        except Exception as e:
            logger.error(f"New session: failed to initialize recorder: {e}", exc_info=True)
            QMessageBox.critical(self, "Error", f"Failed to initialize recorder:\n{e}")
            return
            
        # Update UI
        self.snapshot_count = 0
        self.transcript_text.clear()
        self.line_count_label.setText("Lines: 0")
        
        # Set default meeting date/time and clear other fields
        self.meeting_datetime_input.setText(timestamp.strftime("%m/%d/%Y %I:%M %p"))
        self.meeting_name_input.clear()
        self.meeting_notes_input.clear()
        self.meeting_details_dirty = False
        
        self._update_button_states()
        self.statusBar().showMessage(f"Ready to record — {folder_name}")
        self._set_status("Session ready", "green")
        logger.info(f"New session: created for {self.selected_app_key} at {self.current_recording_path}")
    
    def _on_reset_recording(self):
        """Reset the current recording session."""
        if self.is_recording:
            self._on_stop_recording()
            
        self.recorder_instance = None
        self.current_recording_path = None
        self.snapshots_path = None
        self.merged_transcript_path = None
        self.snapshot_count = 0
        self.transcript_text.clear()
        self.line_count_label.setText("Lines: 0")
        
        # Clear meeting details
        self.meeting_name_input.clear()
        self.meeting_datetime_input.clear()
        self.meeting_notes_input.clear()
        self.meeting_details_dirty = False
        
        self._update_button_states()
        self._set_status("Ready", "gray")
        self.statusBar().showMessage("Session reset")
        logger.info("Session reset")
        
    def _on_start_recording(self):
        """Start continuous recording."""
        if not self.recorder_instance:
            logger.warning("Start recording: no active session")
            return
        
        # Switch to transcript tab
        self.tab_widget.setCurrentIndex(1)  # Meeting Transcript tab
            
        self.recording_worker = RecordingWorker(
            self.recorder_instance,
            self.capture_interval,
            self.current_recording_path,
            self.merged_transcript_path
        )
        self.recording_worker.snapshot_completed.connect(self._on_snapshot_completed)
        self.recording_worker.countdown_tick.connect(self._on_countdown_tick)
        self.recording_worker.error_occurred.connect(self._on_recording_error)
        
        self.recording_worker.start()
        self.is_recording = True
        self._update_button_states()
        self._set_status("Auto capturing...", "#2ecc71")
        self.statusBar().showMessage(f"Auto capture running (every {self.capture_interval}s)")
        logger.info(f"Recording started: auto capture every {self.capture_interval}s")
        
    def _on_stop_recording(self):
        """Stop continuous recording."""
        logger.info(f"Recording stopped (snapshots taken: {self.snapshot_count})")
        if self.recording_worker:
            self.recording_worker.stop()
            self.recording_worker.wait(5000)  # Wait up to 5 seconds
            self.recording_worker = None
            
        self.is_recording = False
        self._update_button_states()
        self._set_status("Stopped", "orange")
        
        # Export index file to the .snapshots folder
        if self.recorder_instance and self.recorder_instance.snapshots:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(self.recorder_instance.export_snapshots_index())
                logger.debug("Snapshots index file exported")
            finally:
                loop.close()
                
        self.statusBar().showMessage("Auto capture stopped")
        
    def _on_capture_now(self):
        """Take a single snapshot and merge into meeting transcript."""
        if not self.recorder_instance:
            logger.warning("Manual capture: no active session")
            return
        
        # Switch to transcript tab
        self.tab_widget.setCurrentIndex(1)  # Meeting Transcript tab
            
        self._set_status("Capturing...", "blue")
        self.statusBar().showMessage("Capturing transcript...")
        logger.debug("Manual capture: starting")
        
        loop = asyncio.new_event_loop()
        try:
            success, file_path, line_count = loop.run_until_complete(
                self.recorder_instance.export_transcript_text()
            )
            
            if success and file_path:
                self.snapshot_count += 1
                
                # Merge into meeting_transcript.txt
                if self.snapshot_count == 1:
                    # First snapshot - just copy to merged location
                    shutil.copy(file_path, str(self.merged_transcript_path))
                    logger.info(f"Manual capture: first snapshot saved ({line_count} lines)")
                else:
                    # Merge with existing transcript
                    smart_merge(
                        str(self.merged_transcript_path),
                        file_path,
                        str(self.merged_transcript_path)
                    )
                    logger.info(f"Manual capture: snapshot #{self.snapshot_count} merged ({line_count} lines)")
                
                # Save meeting details if modified
                self._save_meeting_details()
                
                # Display the merged transcript
                self._update_transcript_display(str(self.merged_transcript_path), line_count or 0)
                self.statusBar().showMessage(f"Captured {line_count} lines")
                self._set_status("Captured", "green")
            else:
                logger.warning("Manual capture: no transcript data returned")
                QMessageBox.warning(
                    self, "Capture Failed",
                    "Could not capture transcript. Make sure:\n"
                    "• The meeting application is running\n"
                    "• Captions/transcript is enabled\n"
                    "• The transcript window is visible"
                )
                self._set_status("Capture failed", "red")
        except Exception as e:
            logger.error(f"Manual capture: failed: {e}", exc_info=True)
            QMessageBox.critical(self, "Error", f"Capture failed:\n{e}")
        finally:
            loop.close()
            
    def _on_snapshot_completed(self, success: bool, file_path: str, line_count: int, overlap: int):
        """Handle completed snapshot from worker."""
        if success:
            self.snapshot_count += 1
            self._save_meeting_details()  # Save meeting details if modified
            self._update_transcript_display(file_path, line_count)
            
    def _on_countdown_tick(self, seconds: int):
        """Update countdown display in status bar."""
        if seconds == 0:
            self.statusBar().showMessage("Capturing...")
        else:
            self.statusBar().showMessage(f"Next capture in {seconds}s")
            
    def _on_recording_error(self, error: str):
        """Handle recording error."""
        self._set_status("Error", "red")
        self.statusBar().showMessage(f"Error: {error}")
        
    def _update_transcript_display(self, file_path: str, line_count: int = 0):
        """Update the transcript preview from the merged transcript file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            self.transcript_text.setText(content)
            
            # Count actual lines in the merged file
            actual_lines = len(content.splitlines())
            self.line_count_label.setText(f"Lines: {actual_lines}")
            
            # Scroll to bottom
            scrollbar = self.transcript_text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
            
            self.copy_btn.setEnabled(True)
            self.open_folder_btn.setEnabled(True)
            logger.debug(f"Transcript display updated ({actual_lines} lines)")
        except Exception as e:
            logger.error(f"Failed to update transcript display: {e}")
            
    def _on_copy_transcript(self):
        """Copy transcript to clipboard."""
        text = self.transcript_text.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.statusBar().showMessage("Transcript copied to clipboard")
            
    def _on_open_folder(self):
        """Open the current recording folder."""
        if self.current_recording_path and self.current_recording_path.exists():
            import subprocess
            subprocess.run(["open", str(self.current_recording_path)])
            
    def _on_open_export_folder(self):
        """Open the main export folder."""
        if self.export_base_dir.exists():
            import subprocess
            subprocess.run(["open", str(self.export_base_dir)])
            
    def _update_button_states(self):
        """Update button enabled states based on current state."""
        has_recorder = self.recorder_instance is not None
        has_content = self.snapshot_count > 0
        
        # Top-level controls (always accessible)
        self.app_combo.setEnabled(not has_recorder)
        self.new_btn.setEnabled(not has_recorder)
        self.reset_btn.setEnabled(has_recorder and not self.is_recording)
        
        # Recording controls — require an active session
        self.capture_btn.setEnabled(has_recorder)
        self.auto_capture_btn.setEnabled(has_recorder)
        
        # Tab widget — disabled entirely when no active session
        self.tab_widget.setEnabled(has_recorder)
        
        # Transcript tab controls (explicit state within enabled tab)
        self.copy_btn.setEnabled(has_content)
        self.open_folder_btn.setEnabled(has_content)
        
        # Meeting Details tab controls
        self.save_details_btn.setEnabled(has_recorder)
        self.open_folder_btn2.setEnabled(has_recorder)
        
        # Update auto capture button text and style
        self._update_auto_capture_btn_style()
    
    def _update_auto_capture_btn_style(self):
        """Update the auto capture button text and color based on recording state."""
        if self.is_recording:
            self.auto_capture_btn.setText("Stop Auto Capture")
            self.auto_capture_btn.setStyleSheet(self._danger_style)
        else:
            self.auto_capture_btn.setText("Start Auto Capture")
            self.auto_capture_btn.setStyleSheet(self._success_style)
    
    def _on_toggle_auto_capture(self):
        """Toggle auto capture on/off."""
        if self.is_recording:
            self._on_stop_recording()
        else:
            self._on_start_recording()
    
    def _on_meeting_details_changed(self):
        """Mark meeting details as modified."""
        self.meeting_details_dirty = True
    
    def _on_round_time_down(self):
        """Round the time down to the nearest 5 minutes."""
        self._round_time(-1)
    
    def _on_round_time_up(self):
        """Round the time up to the nearest 5 minutes."""
        self._round_time(1)
    
    def _round_time(self, direction: int):
        """Round the time in the datetime input by 5 minutes.
        
        Args:
            direction: -1 for down, 1 for up
        """
        text = self.meeting_datetime_input.text().strip()
        if not text:
            return
        
        try:
            # Parse the datetime - expected format: MM/DD/YYYY hh:mm AM/PM
            dt = datetime.strptime(text, "%m/%d/%Y %I:%M %p")
            
            # Get current minutes
            current_minutes = dt.minute
            
            if direction < 0:
                # Round down: floor to nearest 5
                new_minutes = (current_minutes // 5) * 5
                if new_minutes == current_minutes:
                    # Already on a 5-minute boundary, go down another 5
                    new_minutes -= 5
            else:
                # Round up: ceiling to nearest 5
                new_minutes = ((current_minutes + 4) // 5) * 5
                if new_minutes == current_minutes:
                    # Already on a 5-minute boundary, go up another 5
                    new_minutes += 5
            
            # Handle minute overflow/underflow
            if new_minutes >= 60:
                dt = dt.replace(minute=0) + timedelta(hours=1)
            elif new_minutes < 0:
                dt = dt.replace(minute=55) - timedelta(hours=1)
            else:
                dt = dt.replace(minute=new_minutes)
            
            # Update the input field
            self.meeting_datetime_input.setText(dt.strftime("%m/%d/%Y %I:%M %p"))
            
        except ValueError:
            # Invalid format, ignore
            pass
    
    def _save_meeting_details(self, force: bool = False):
        """Save meeting details to file if modified."""
        if not self.current_recording_path:
            return
        
        if not force and not self.meeting_details_dirty:
            return
        
        meeting_name = self.meeting_name_input.text().strip()
        meeting_datetime = self.meeting_datetime_input.text().strip()
        meeting_notes = self.meeting_notes_input.toPlainText().strip()
        
        # Only save if there's content
        if not meeting_name and not meeting_datetime and not meeting_notes:
            return
        
        details_path = self.current_recording_path / "meeting_details.txt"
        try:
            with open(details_path, 'w', encoding='utf-8') as f:
                if meeting_name:
                    f.write(f"Meeting Name: {meeting_name}\n")
                    f.write("=" * (len(meeting_name) + 14) + "\n\n")
                if meeting_datetime:
                    f.write(f"Date/Time: {meeting_datetime}\n\n")
                if meeting_notes:
                    f.write("Notes:\n")
                    f.write("-" * 40 + "\n")
                    f.write(meeting_notes + "\n")
            
            self.meeting_details_dirty = False
            logger.debug(f"Meeting details saved to {details_path}")
        except Exception as e:
            logger.error(f"Failed to save meeting details: {e}")
    
    def _on_save_details_clicked(self):
        """Handle save details button click."""
        self._save_meeting_details(force=True)
        self.statusBar().showMessage("Meeting details saved")
        
    def _set_status(self, text: str, color: str = "gray"):
        """Update the status bar message."""
        self.statusBar().showMessage(text)
        
    def _show_about(self):
        """Show about dialog with GitHub repository link."""
        github_url = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"<h3>{APP_NAME}</h3>"
            f"<p>Version {APP_VERSION}</p>"
            f"<p>A user-friendly application for recording meeting transcripts "
            f"using macOS accessibility APIs.</p>"
            f"<p>Supports:</p>"
            f"<ul>"
            f"<li>Zoom</li>"
            f"<li>Microsoft Teams</li>"
            f"<li>WebEx</li>"
            f"<li>Slack</li>"
            f"</ul>"
            f'<p>GitHub: <a href="{github_url}">{github_url}</a></p>'
        )
    
    def _show_log_viewer(self):
        """Open the log viewer window."""
        self.log_viewer = LogViewerDialog(self)
        self.log_viewer.show()
    
    def _show_config_editor(self):
        """Open the configuration editor window."""
        self.config_editor = ConfigEditorDialog(self)
        self.config_editor.config_saved.connect(self._reload_configuration)
        self.config_editor.show()
    
    def _reload_configuration(self):
        """Reload the configuration file."""
        try:
            with open(DEFAULT_CONFIG_PATH, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
            
            # Reconfigure logging
            setup_logging(self.config)
            
            # Repopulate app selection
            self._populate_app_combo()
            
            app_count = len(self.config.get("application_settings", {}))
            logger.info(f"Config: reloaded from {DEFAULT_CONFIG_PATH} ({app_count} apps)")
            self.statusBar().showMessage("Configuration reloaded")
            
        except json.JSONDecodeError as e:
            QMessageBox.critical(
                self, "Configuration Error",
                f"Invalid JSON in configuration file:\n{e}"
            )
        except Exception as e:
            QMessageBox.critical(
                self, "Configuration Error",
                f"Failed to reload configuration:\n{e}"
            )
    
    def _clear_log_file(self):
        """Clear the log file."""
        if current_log_file_path is None:
            QMessageBox.information(self, "Logging Disabled", "File logging is disabled in configuration.")
            return
            
        reply = QMessageBox.question(
            self, "Clear Log File",
            "Are you sure you want to clear the log file?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                if current_log_file_path.exists():
                    with open(current_log_file_path, 'w', encoding='utf-8') as f:
                        f.write("")
                    logger.info("Maintenance: log file cleared")
                    self.statusBar().showMessage("Log file cleared")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to clear log file: {e}")
    
    def _clear_all_snapshots(self):
        """Remove all .snapshots folders from recordings."""
        recordings_dir = self.export_base_dir / "recordings"
        
        if not recordings_dir.exists():
            QMessageBox.information(self, "No Recordings", "No recordings folder found.")
            return
        
        # Count snapshots folders
        snapshots_folders = list(recordings_dir.glob("*/.snapshots"))
        
        if not snapshots_folders:
            QMessageBox.information(self, "No Snapshots", "No snapshot folders found to clear.")
            return
        
        reply = QMessageBox.question(
            self, "Clear All Snapshots",
            f"This will remove {len(snapshots_folders)} snapshot folder(s) from your recordings.\n\n"
            "The merged transcripts (meeting_transcript.txt) will be preserved.\n\n"
            "This action cannot be undone. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            removed = 0
            errors = 0
            for folder in snapshots_folders:
                try:
                    shutil.rmtree(folder)
                    removed += 1
                except Exception as e:
                    logger.error(f"Maintenance: failed to remove snapshot folder {folder}: {e}")
                    errors += 1
            
            if errors > 0:
                QMessageBox.warning(
                    self, "Partial Success",
                    f"Removed {removed} snapshot folder(s).\n{errors} folder(s) could not be removed."
                )
            else:
                QMessageBox.information(
                    self, "Success",
                    f"Removed {removed} snapshot folder(s)."
                )
            
            logger.info(f"Maintenance: cleared {removed} snapshot folders ({errors} errors)")
            self.statusBar().showMessage(f"Cleared {removed} snapshot folders")
    
    def _clear_empty_recordings(self):
        """Remove recording folders that contain no files (only empty subdirectories)."""
        recordings_dir = self.export_base_dir / "recordings"
        
        if not recordings_dir.exists():
            QMessageBox.information(self, "No Recordings", "No recordings folder found.")
            return
        
        # Find recording folders that are effectively empty (no files anywhere inside)
        empty_folders: List[Path] = []
        for folder in sorted(recordings_dir.iterdir()):
            if not folder.is_dir():
                continue
            # Skip the currently active recording folder
            if self.current_recording_path and folder.resolve() == self.current_recording_path.resolve():
                continue
            # Check if the folder contains any files (recursively)
            has_files = any(f.is_file() for f in folder.rglob("*"))
            if not has_files:
                empty_folders.append(folder)
        
        if not empty_folders:
            QMessageBox.information(
                self, "No Empty Recordings",
                "No empty recording folders found."
            )
            return
        
        reply = QMessageBox.question(
            self, "Clear Empty Recordings",
            f"Found {len(empty_folders)} empty recording folder(s):\n\n"
            + "\n".join(f"  • {f.name}" for f in empty_folders[:10])
            + ("\n  ..." if len(empty_folders) > 10 else "")
            + "\n\nThese folders contain no files. Remove them?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            removed = 0
            errors = 0
            for folder in empty_folders:
                try:
                    shutil.rmtree(folder)
                    removed += 1
                except Exception as e:
                    logger.error(f"Maintenance: failed to remove empty folder {folder}: {e}")
                    errors += 1
            
            if errors > 0:
                QMessageBox.warning(
                    self, "Partial Success",
                    f"Removed {removed} empty folder(s).\n{errors} folder(s) could not be removed."
                )
            else:
                QMessageBox.information(
                    self, "Success",
                    f"Removed {removed} empty recording folder(s)."
                )
            
            logger.info(f"Maintenance: cleared {removed} empty recording folders ({errors} errors)")
            self.statusBar().showMessage(f"Cleared {removed} empty recording folders")
    
    def _check_for_updates(self):
        """Check GitHub releases for a newer version."""
        self.statusBar().showMessage("Checking for updates...")
        
        # Check if GitHub info is configured
        if GITHUB_OWNER == "YOUR_GITHUB_USERNAME":
            logger.warning("Update check: skipped (GITHUB_OWNER not configured)")
            QMessageBox.information(
                self, "Update Check",
                "Update checking is not configured.\n\n"
                "Please update GITHUB_OWNER and GITHUB_REPO in version.py "
                "with your GitHub repository information."
            )
            self.statusBar().showMessage("Ready")
            return
        
        # Build the API URL
        url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
        logger.debug(f"Update check: querying {url} (current version: {APP_VERSION})")
        
        try:
            # Query GitHub releases API
            request = urllib.request.Request(
                url,
                headers={"Accept": "application/vnd.github.v3+json", "User-Agent": f"{APP_NAME}/{APP_VERSION}"}
            )
            
            logger.debug("Update check: sending request to GitHub API")
            with urllib.request.urlopen(request, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
            
            latest_version = data.get("tag_name", "").lstrip("v")
            release_url = data.get("html_url", "")
            release_notes = data.get("body", "No release notes available.")
            assets = data.get("assets", [])
            
            logger.debug(f"Update check: latest release={latest_version}, assets={len(assets)}")
            
            # Compare versions
            current_parts = [int(x) for x in APP_VERSION.split(".")]
            latest_parts = [int(x) for x in latest_version.split(".")]
            
            # Pad to same length
            while len(current_parts) < len(latest_parts):
                current_parts.append(0)
            while len(latest_parts) < len(current_parts):
                latest_parts.append(0)
            
            logger.debug(f"Update check: comparing versions current={current_parts} vs latest={latest_parts}")
            
            if latest_parts > current_parts:
                logger.info(f"Update check: new version available ({latest_version}, current: {APP_VERSION})")
                # Newer version available
                # Find the .dmg or .zip asset
                download_asset = None
                for asset in assets:
                    name = asset.get("name", "").lower()
                    logger.debug(f"Update check: found asset: {name}")
                    if name.endswith(".dmg") or name.endswith(".zip"):
                        download_asset = asset
                        break
                
                msg = (
                    f"A new version is available!\n\n"
                    f"Current version: {APP_VERSION}\n"
                    f"Latest version: {latest_version}\n\n"
                    f"Release notes:\n{release_notes[:500]}{'...' if len(release_notes) > 500 else ''}"
                )
                
                if download_asset:
                    logger.debug(f"Update check: downloadable asset found: {download_asset.get('name')}")
                    reply = QMessageBox.question(
                        self, "Update Available",
                        f"{msg}\n\nWould you like to download and install the update?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    )
                    
                    if reply == QMessageBox.StandardButton.Yes:
                        self._download_and_install_update(download_asset, latest_version)
                else:
                    logger.debug("Update check: no downloadable asset (.dmg or .zip) found")
                    # No downloadable asset, just show the release page
                    reply = QMessageBox.question(
                        self, "Update Available",
                        f"{msg}\n\nWould you like to open the release page in your browser?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    )
                    if reply == QMessageBox.StandardButton.Yes:
                        subprocess.run(["open", release_url])
            else:
                logger.info(f"Update check: already on latest version ({APP_VERSION})")
                QMessageBox.information(
                    self, "No Updates",
                    f"You're running the latest version ({APP_VERSION})."
                )
            
            self.statusBar().showMessage("Ready")
            
        except urllib.error.HTTPError as e:
            if e.code == 404:
                logger.warning(f"Update check: no releases found (HTTP 404)")
                QMessageBox.information(
                    self, "No Releases",
                    f"No releases have been published yet.\n\n"
                    f"You're running version {APP_VERSION}.\n\n"
                    f"Checked: {url}"
                )
            else:
                logger.error(f"Update check: HTTP error {e.code} {e.reason} ({url})")
                QMessageBox.warning(
                    self, "Update Check Failed",
                    f"HTTP Error {e.code}: {e.reason}\n\nURL: {url}"
                )
            self.statusBar().showMessage("Ready")
        except urllib.error.URLError as e:
            logger.error(f"Update check: connection failed: {e} ({url})")
            QMessageBox.warning(
                self, "Update Check Failed",
                f"Could not connect to GitHub to check for updates.\n\nError: {e}\n\nURL: {url}"
            )
            self.statusBar().showMessage("Update check failed")
        except Exception as e:
            logger.error(f"Update check: unexpected error: {e} ({url})", exc_info=True)
            QMessageBox.warning(
                self, "Update Check Failed",
                f"An error occurred while checking for updates.\n\nError: {e}\n\nURL: {url}"
            )
            self.statusBar().showMessage("Update check failed")
    
    def _download_and_install_update(self, asset: dict, version: str):
        """Download and install an update from GitHub releases."""
        download_url = asset.get("browser_download_url")
        filename = asset.get("name")
        
        if not download_url or not filename:
            logger.error("Update download: missing download URL or filename")
            QMessageBox.warning(self, "Download Failed", "Could not get download URL.")
            return
        
        try:
            self.statusBar().showMessage(f"Downloading {filename}...")
            
            # Download to temp directory
            temp_dir = Path(tempfile.gettempdir()) / "TranscriptRecorderUpdate"
            temp_dir.mkdir(exist_ok=True)
            download_path = temp_dir / filename
            
            # Download the file
            request = urllib.request.Request(
                download_url,
                headers={"User-Agent": APP_NAME}
            )
            
            with urllib.request.urlopen(request, timeout=60) as response:
                with open(download_path, 'wb') as f:
                    f.write(response.read())
            
            logger.info(f"Update download: saved {filename} to {download_path}")
            
            if filename.endswith(".dmg"):
                # Mount DMG and open it
                self.statusBar().showMessage("Opening installer...")
                subprocess.run(["open", str(download_path)])
                
                QMessageBox.information(
                    self, "Update Downloaded",
                    f"The update has been downloaded and opened.\n\n"
                    f"Please drag the new version to your Applications folder "
                    f"to complete the update, then restart the application."
                )
            elif filename.endswith(".zip"):
                # Extract and open containing folder
                self.statusBar().showMessage("Extracting update...")
                extract_dir = temp_dir / f"TranscriptRecorder-{version}"
                shutil.unpack_archive(str(download_path), str(extract_dir))
                subprocess.run(["open", str(extract_dir)])
                
                QMessageBox.information(
                    self, "Update Downloaded",
                    f"The update has been downloaded and extracted.\n\n"
                    f"Please move the new application to your Applications folder "
                    f"to complete the update, then restart the application."
                )
            
            self.statusBar().showMessage("Update ready to install")
            
        except Exception as e:
            logger.error(f"Update download: failed to download {filename}: {e}", exc_info=True)
            QMessageBox.warning(
                self, "Download Failed",
                f"Failed to download the update.\n\nError: {e}"
            )
            self.statusBar().showMessage("Update download failed")
        
    def closeEvent(self, event):
        """Handle window close."""
        if self.is_recording:
            reply = QMessageBox.question(
                self,
                "Recording in Progress",
                "Recording is still in progress. Stop and exit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
            self._on_stop_recording()
            
        if hasattr(self, 'tray_icon'):
            self.tray_icon.hide()
        
        logger.info("Application window closed")
        event.accept()


def main():
    """Application entry point."""
    if sys.platform != "darwin":
        print("This application only runs on macOS.")
        sys.exit(1)
        
    app = QApplication(sys.argv)
    
    # macOS-specific settings
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("TranscriptRecorder")
    
    # Set app icon
    icon_path = resource_path("transcriber.icns")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    
    logger.info(f"Application starting (version {APP_VERSION})")
    
    # Create and show main window
    window = TranscriptRecorderApp()
    window.show()
    
    exit_code = app.exec()
    logger.info(f"Application exiting (code {exit_code})")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
