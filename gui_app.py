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
import time
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
    QTabWidget, QLineEdit, QStyle, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QCheckBox, QInputDialog
)

from transcript_recorder import TranscriptRecorder, AXIsProcessTrusted
from transcript_utils import smart_merge
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


def get_application_stylesheet(is_dark: bool) -> str:
    """Return a single, comprehensive QSS stylesheet for the entire application.
    
    Uses Apple's Semantic Colors to ensure a native macOS look in both
    Light and Dark modes. Applied once on the QApplication so that every
    window, dialog, and popup inherits the theme automatically.
    """
    # --- Palette definition ---
    bg_window = "#1E1E1E" if is_dark else "#F5F5F7"
    bg_widget = "#2D2D2D" if is_dark else "#FFFFFF"
    text_main = "#FFFFFF" if is_dark else "#1D1D1F"
    text_sec  = "#98989D" if is_dark else "#86868B"
    border    = "#3D3D3D" if is_dark else "#D2D2D7"
    input_bg  = "#1A1A1A" if is_dark else "#FFFFFF"
    hover_bg  = "#3A3A3C" if is_dark else "#F0F0F0"
    pressed_bg    = "#2C2C2E" if is_dark else "#E0E0E0"
    disabled_bg   = "#3A3A3C" if is_dark else "#E5E5EA"
    disabled_text = "#636366" if is_dark else "#8E8E93"
    scrollbar_handle = "#4D4D4D" if is_dark else "#C1C1C1"

    return f"""
        /* ========== Global Defaults ========== */
        QWidget {{
            background-color: {bg_window};
            color: {text_main};
            font-family: "SF Pro", "SF Compact", "Helvetica Neue", sans-serif;
            font-size: 13px;
        }}

        QMainWindow {{
            background-color: {bg_window};
        }}

        QLabel {{
            background-color: transparent;
        }}

        /* Secondary label (info / caption text) */
        QLabel#secondary_label {{
            color: {text_sec};
            font-size: 11px;
        }}

        QStatusBar {{
            background-color: {bg_window};
            color: {text_sec};
        }}

        QGroupBox {{
            background-color: transparent;
            border: none;
            margin-top: 20px;
            padding-top: 4px;
            font-weight: 600;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 0 4px;
            top: 4px;
        }}

        /* ========== Inputs & Text Areas ========== */
        QLineEdit, QTextEdit, QPlainTextEdit {{
            background-color: {input_bg};
            color: {text_main};
            border: 1px solid {border};
            border-radius: 6px;
            padding: 6px;
            selection-background-color: #007AFF;
            selection-color: white;
        }}
        QLineEdit:focus, QTextEdit:focus {{
            border-color: #007AFF;
        }}

        QComboBox {{
            background-color: {bg_widget};
            color: {text_main};
            border: 1px solid {border};
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
            border-top: 6px solid {text_sec};
            margin-right: 8px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {bg_widget};
            color: {text_main};
            selection-background-color: #007AFF;
            selection-color: white;
        }}

        /* ========== Modern macOS Scrollbars ========== */
        QScrollBar:vertical {{
            border: none;
            background: transparent;
            width: 8px;
            margin: 0px;
        }}
        QScrollBar::handle:vertical {{
            background: {scrollbar_handle};
            min-height: 20px;
            border-radius: 4px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {text_sec};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: transparent;
        }}

        QScrollBar:horizontal {{
            border: none;
            background: transparent;
            height: 8px;
            margin: 0px;
        }}
        QScrollBar::handle:horizontal {{
            background: {scrollbar_handle};
            min-width: 20px;
            border-radius: 4px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: {text_sec};
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0px;
        }}
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
            background: transparent;
        }}

        /* ========== Tab Bar Styling ========== */
        QTabWidget {{
            background: {bg_window};
            border: 0;
            padding: 0;
            margin: 0;
        }}
        QTabWidget::pane {{
            background: {bg_window};
            border: 0;
            border-top: 1px solid {border};
            padding: 0;
            margin: 0;
            top: 0;
        }}
        QTabWidget::tab-bar {{
            background: {bg_window};
            border: 0;
            left: 0;
        }}
        QTabBar {{
            background: {bg_window};
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
            color: {text_sec};
            padding: 6px 14px;
            margin-right: 8px;
            margin-bottom: 4px;
            border: 1px solid {border};
            border-radius: 6px;
        }}
        QTabBar::tab:selected {{
            background-color: #007AFF;
            color: white;
            border-color: #007AFF;
            font-weight: 500;
        }}
        QTabBar::tab:hover:!selected {{
            background: {hover_bg};
            color: {text_main};
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

        /* ========== BUTTON STATES ========== */

        /* Default (Secondary) Button */
        QPushButton {{
            background-color: {bg_widget};
            border: 1px solid {border};
            border-radius: 6px;
            padding: 6px 14px;
            font-weight: 500;
        }}
        QPushButton:hover {{
            background-color: {hover_bg};
        }}
        QPushButton:pressed {{
            background-color: {pressed_bg};
        }}

        /* Primary Blue Button */
        QPushButton[class="primary"] {{
            background-color: #007AFF;
            color: white;
            border: none;
        }}
        QPushButton[class="primary"]:hover {{
            background-color: #0A84FF;
        }}
        QPushButton[class="primary"]:pressed {{
            background-color: #0062CC;
        }}

        /* Success Green Button */
        QPushButton[class="success"] {{
            background-color: #34C759;
            color: white;
            border: none;
        }}
        QPushButton[class="success"]:hover {{
            background-color: #30D158;
        }}
        QPushButton[class="success"]:pressed {{
            background-color: #248A3D;
        }}

        /* Danger Red Button */
        QPushButton[class="danger"] {{
            background-color: #FF3B30;
            color: white;
            border: none;
        }}
        QPushButton[class="danger"]:hover {{
            background-color: #FF453A;
        }}
        QPushButton[class="danger"]:pressed {{
            background-color: #C93028;
        }}

        /* Pink Button */
        QPushButton[class="pink"] {{
            background-color: #FF2D55;
            color: white;
            border: none;
        }}
        QPushButton[class="pink"]:hover {{
            background-color: #FF375F;
        }}
        QPushButton[class="pink"]:pressed {{
            background-color: #D12549;
        }}
        QPushButton[class="pink"]:disabled {{
            background-color: {"#4A2A33" if is_dark else "#F0C4CE"};
            color: {"#8A5060" if is_dark else "#C08090"};
            border: none;
        }}

        /* Round Time Buttons — stacked stepper style */
        QPushButton#time_btn {{
            border-radius: 4px;
            padding: 0px;
            icon-size: 10px;
            min-width: 0px;
            min-height: 0px;
        }}

        /* Disabled State for all buttons */
        QPushButton:disabled {{
            background-color: {disabled_bg};
            color: {disabled_text};
            border: none;
        }}
    """


class LogViewerDialog(QMainWindow):
    """A window for viewing the application log file."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Log Viewer")
        self.setMinimumSize(600, 400)
        self.resize(800, 500)
        
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        
        # Log text area
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Menlo", 11))
        layout.addWidget(self.log_text)
        
        # Buttons — styled via global stylesheet class properties
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setProperty("class", "primary")
        self.refresh_btn.clicked.connect(self._load_log)
        btn_layout.addWidget(self.refresh_btn)
        
        self.clear_btn = QPushButton("Clear Log")
        self.clear_btn.setProperty("class", "danger")
        self.clear_btn.clicked.connect(self._clear_log)
        btn_layout.addWidget(self.clear_btn)
        
        btn_layout.addStretch()
        
        self.close_btn = QPushButton("Close")
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
        
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        
        # Info label
        info_label = QLabel(f"Editing: {DEFAULT_CONFIG_PATH}")
        info_label.setObjectName("secondary_label")
        layout.addWidget(info_label)
        
        # Config text area
        self.config_text = QTextEdit()
        self.config_text.setFont(QFont("Menlo", 11))
        self.config_text.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.config_text)
        
        # Status label for validation
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)
        
        # Buttons — styled via global stylesheet class properties
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        
        self.reload_btn = QPushButton("Reload")
        self.reload_btn.clicked.connect(self._load_config)
        btn_layout.addWidget(self.reload_btn)
        
        self.download_btn = QPushButton("Download from URL")
        self.download_btn.clicked.connect(self._download_from_url)
        btn_layout.addWidget(self.download_btn)
        
        self.restore_btn = QPushButton("Restore Packaged Config")
        self.restore_btn.clicked.connect(self._restore_packaged_config)
        btn_layout.addWidget(self.restore_btn)
        
        btn_layout.addStretch()
        
        self.save_btn = QPushButton("Save")
        self.save_btn.setProperty("class", "success")
        self.save_btn.clicked.connect(self._save_config)
        btn_layout.addWidget(self.save_btn)
        
        self.validate_btn = QPushButton("Validate JSON")
        self.validate_btn.setProperty("class", "primary")
        self.validate_btn.clicked.connect(self._validate_json)
        btn_layout.addWidget(self.validate_btn)
        
        self.close_btn = QPushButton("Close")
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
    """Background countdown timer that signals the main thread to capture.
    
    All capture and merge logic lives on the main thread so that manual
    and auto captures share a single code-path and a single snapshot
    counter.  This worker is only responsible for the timed countdown.
    """
    
    capture_requested = pyqtSignal()   # Emitted when the countdown expires
    countdown_tick = pyqtSignal(int)   # Seconds remaining until next capture
    
    def __init__(self, interval_seconds: int, parent=None):
        super().__init__(parent)
        self.interval_seconds = interval_seconds
        self._is_running = True
        
    def run(self):
        """Countdown loop — emits capture_requested each time the timer expires."""
        logger.info(f"Auto capture timer started (interval={self.interval_seconds}s)")
        
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
                
                # Request a capture on the main thread
                self.countdown_tick.emit(0)
                self.capture_requested.emit()
                
                # Brief pause so the main thread can begin the capture
                # before the next countdown restarts
                self.msleep(500)
        finally:
            logger.info("Auto capture timer stopped")
    
    def stop(self):
        """Signal the timer to stop."""
        logger.debug("Auto capture timer: stop requested")
        self._is_running = False


class ToolRunnerWorker(QThread):
    """Background worker for executing tool scripts without blocking the UI.
    
    Uses ``subprocess.Popen`` so the process can be cancelled mid-run via
    ``cancel()``.
    """
    
    output_ready = pyqtSignal(str, str, int)  # stdout, stderr, exit_code
    
    def __init__(self, command: List[str], cwd: str = None, parent=None):
        super().__init__(parent)
        self.command = command
        self.cwd = cwd
        self._process: Optional[subprocess.Popen] = None
        self._cancelled = False
    
    def run(self):
        try:
            self._process = subprocess.Popen(
                self.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=self.cwd,
            )
            stdout, stderr = self._process.communicate()
            
            if self._cancelled:
                self.output_ready.emit(stdout or "", "Cancelled by user.", -2)
            else:
                self.output_ready.emit(stdout or "", stderr or "", self._process.returncode)
        except Exception as e:
            if self._cancelled:
                self.output_ready.emit("", "Cancelled by user.", -2)
            else:
                self.output_ready.emit("", f"Error running tool: {e}", -1)
    
    def cancel(self):
        """Kill the running subprocess."""
        self._cancelled = True
        if self._process and self._process.poll() is None:
            self._process.kill()
            logger.info("Tools: process killed by user")


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


# ---------------------------------------------------------------------------
# Tool Import / Management
# ---------------------------------------------------------------------------

class ToolFetchWorker(QThread):
    """Background worker to list available tools from a GitHub repo's tools/ directory.

    Uses the GitHub Contents API to enumerate sub-directories, then for each
    directory fetches its file listing so we know what will be downloaded.
    """

    # Signals
    listing_ready = pyqtSignal(list)     # list of dicts: [{name, url, files_url, ...}, ...]
    error = pyqtSignal(str)              # error message
    download_progress = pyqtSignal(str)  # status string while downloading
    download_finished = pyqtSignal(list, list)  # (installed_names, error_messages)

    def __init__(self, api_url: str, parent=None):
        super().__init__(parent)
        self.api_url = api_url
        self._tools_to_download: List[dict] = []
        self._local_tools_dir: Optional[Path] = None
        self._mode = "list"  # "list" or "download"

    # -- public helpers to configure a download pass --
    def start_download(self, tools: List[dict], local_tools_dir: Path):
        """Configure and start a download run."""
        self._tools_to_download = tools
        self._local_tools_dir = local_tools_dir
        self._mode = "download"
        self.start()

    def run(self):
        if self._mode == "download":
            self._run_download()
        else:
            self._run_list()

    # -- listing --
    def _run_list(self):
        try:
            req = urllib.request.Request(
                self.api_url,
                headers={
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": f"{APP_NAME}/{APP_VERSION}",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            if not isinstance(data, list):
                self.error.emit("Unexpected response from GitHub API (expected a list).")
                return

            tool_dirs = [
                {
                    "name": item["name"],
                    "url": item["url"],          # API URL for the directory contents
                    "html_url": item.get("html_url", ""),
                }
                for item in data
                if item.get("type") == "dir"
            ]
            self.listing_ready.emit(tool_dirs)

        except urllib.error.HTTPError as e:
            self.error.emit(f"HTTP {e.code}: {e.reason}\n\nURL: {self.api_url}")
        except urllib.error.URLError as e:
            self.error.emit(f"Connection error: {e.reason}")
        except Exception as e:
            self.error.emit(str(e))

    # -- downloading --
    def _run_download(self):
        installed: List[str] = []
        errors: List[str] = []

        for tool in self._tools_to_download:
            name = tool["name"]
            self.download_progress.emit(f"Downloading {name}...")
            try:
                self._download_tool(tool)
                installed.append(name)
            except Exception as e:
                logger.error(f"Tool import: failed to download {name}: {e}", exc_info=True)
                errors.append(f"{name}: {e}")

        self.download_finished.emit(installed, errors)

    def _download_tool(self, tool: dict):
        """Download all files for a single tool directory."""
        name = tool["name"]
        contents_url = tool["url"]

        # Fetch file listing for this tool directory
        req = urllib.request.Request(
            contents_url,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": f"{APP_NAME}/{APP_VERSION}",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            files = json.loads(resp.read().decode("utf-8"))

        if not isinstance(files, list):
            raise ValueError(f"Unexpected response listing files for {name}")

        local_dir = self._local_tools_dir / name
        local_dir.mkdir(parents=True, exist_ok=True)

        # Backup existing tool.json before overwriting
        local_tool_json = local_dir / "tool.json"
        if local_tool_json.exists():
            _backup_tool_json(local_tool_json)

        for item in files:
            if item.get("type") != "file":
                continue
            download_url = item.get("download_url")
            if not download_url:
                continue

            file_name = item["name"]
            self.download_progress.emit(f"  {name}/{file_name}")

            file_req = urllib.request.Request(
                download_url,
                headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"},
            )
            with urllib.request.urlopen(file_req, timeout=30) as file_resp:
                content = file_resp.read()

            dest = local_dir / file_name
            with open(dest, "wb") as f:
                f.write(content)

            # Make scripts executable
            if file_name.endswith(".sh"):
                dest.chmod(dest.stat().st_mode | 0o111)


def _backup_tool_json(tool_json_path: Path, max_backups: int = 3):
    """Create a timestamped backup of tool.json, keeping at most *max_backups*."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = tool_json_path.parent / f"tool.json.bak.{timestamp}"
    shutil.copy2(tool_json_path, backup_path)
    logger.info(f"Tool import: backed up {tool_json_path} -> {backup_path.name}")

    # Prune old backups (keep newest max_backups)
    backups = sorted(
        tool_json_path.parent.glob("tool.json.bak.*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in backups[max_backups:]:
        try:
            old.unlink()
            logger.debug(f"Tool import: pruned old backup {old.name}")
        except OSError:
            pass


class ToolImportDialog(QMainWindow):
    """Dialog for browsing and importing tools from a GitHub repository."""

    tools_imported = pyqtSignal()  # emitted after successful install so caller can refresh

    def __init__(self, local_tools_dir: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import Tools")
        self.setMinimumSize(650, 480)
        self.resize(700, 520)
        self._local_tools_dir = local_tools_dir
        self._fetched_tools: List[dict] = []
        self._worker: Optional[ToolFetchWorker] = None

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # --- Repository URL row ---
        url_layout = QHBoxLayout()
        url_layout.addWidget(QLabel("Repository URL:"))

        default_api_url = (
            f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"
            f"/contents/tools?ref=main"
        )
        self.url_field = QLineEdit(default_api_url)
        self.url_field.setPlaceholderText("GitHub Contents API URL for a tools/ directory")
        url_layout.addWidget(self.url_field, stretch=1)

        self.fetch_btn = QPushButton("Fetch")
        self.fetch_btn.setProperty("class", "primary")
        self.fetch_btn.clicked.connect(self._on_fetch)
        url_layout.addWidget(self.fetch_btn)

        layout.addLayout(url_layout)

        # --- Info label ---
        info = QLabel(
            "Enter a GitHub Contents API URL pointing to a tools/ directory, then click Fetch.\n"
            "Select the tools you want to install and click Install Selected."
        )
        info.setObjectName("secondary_label")
        info.setWordWrap(True)
        layout.addWidget(info)

        # --- Tool list table ---
        self.tool_table = QTableWidget(0, 3)
        self.tool_table.setHorizontalHeaderLabels(["Install", "Tool Name", "Status"])
        self.tool_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tool_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tool_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tool_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tool_table.verticalHeader().setVisible(False)
        layout.addWidget(self.tool_table, stretch=1)

        # --- Status label ---
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        # --- Button row ---
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(self._select_all)
        btn_layout.addWidget(self.select_all_btn)

        self.deselect_all_btn = QPushButton("Deselect All")
        self.deselect_all_btn.clicked.connect(self._deselect_all)
        btn_layout.addWidget(self.deselect_all_btn)

        btn_layout.addStretch()

        self.install_btn = QPushButton("Install Selected")
        self.install_btn.setProperty("class", "success")
        self.install_btn.setEnabled(False)
        self.install_btn.clicked.connect(self._on_install)
        btn_layout.addWidget(self.install_btn)

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        btn_layout.addWidget(self.close_btn)

        layout.addLayout(btn_layout)

    # -- Fetch available tools --
    def _on_fetch(self):
        url = self.url_field.text().strip()
        if not url:
            self.status_label.setText("Please enter a URL.")
            self.status_label.setStyleSheet("color: #FF9500; font-size: 12px;")
            return

        self.fetch_btn.setEnabled(False)
        self.install_btn.setEnabled(False)
        self.status_label.setText("Fetching tool list...")
        self.status_label.setStyleSheet("color: #007AFF; font-size: 12px;")
        QApplication.processEvents()

        self._worker = ToolFetchWorker(url)
        self._worker.listing_ready.connect(self._on_listing_ready)
        self._worker.error.connect(self._on_fetch_error)
        self._worker._mode = "list"
        self._worker.start()

    def _on_listing_ready(self, tools: list):
        self._fetched_tools = tools
        self.tool_table.setRowCount(0)

        installed_tools = set()
        if self._local_tools_dir.exists():
            installed_tools = {
                p.name for p in self._local_tools_dir.iterdir() if p.is_dir()
            }

        for row_idx, tool in enumerate(tools):
            self.tool_table.insertRow(row_idx)

            # Checkbox
            cb = QCheckBox()
            cb_widget = QWidget()
            cb_layout = QHBoxLayout(cb_widget)
            cb_layout.addWidget(cb)
            cb_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb_layout.setContentsMargins(0, 0, 0, 0)
            self.tool_table.setCellWidget(row_idx, 0, cb_widget)

            # Tool name
            name_item = QTableWidgetItem(tool["name"])
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.tool_table.setItem(row_idx, 1, name_item)

            # Status
            status = "Installed" if tool["name"] in installed_tools else "Not installed"
            status_item = QTableWidgetItem(status)
            status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.tool_table.setItem(row_idx, 2, status_item)

        count = len(tools)
        self.status_label.setText(f"Found {count} tool(s)." if count else "No tools found in this repository.")
        self.status_label.setStyleSheet("color: #34C759; font-size: 12px;" if count else "color: #FF9500; font-size: 12px;")
        self.fetch_btn.setEnabled(True)
        self.install_btn.setEnabled(count > 0)

    def _on_fetch_error(self, message: str):
        self.status_label.setText(f"Fetch failed: {message}")
        self.status_label.setStyleSheet("color: #FF3B30; font-size: 12px;")
        self.fetch_btn.setEnabled(True)
        logger.error(f"Tool import: fetch error: {message}")

    # -- Selection helpers --
    def _select_all(self):
        for row in range(self.tool_table.rowCount()):
            widget = self.tool_table.cellWidget(row, 0)
            if widget:
                cb = widget.findChild(QCheckBox)
                if cb:
                    cb.setChecked(True)

    def _deselect_all(self):
        for row in range(self.tool_table.rowCount()):
            widget = self.tool_table.cellWidget(row, 0)
            if widget:
                cb = widget.findChild(QCheckBox)
                if cb:
                    cb.setChecked(False)

    def _get_selected_tools(self) -> List[dict]:
        selected = []
        for row in range(self.tool_table.rowCount()):
            widget = self.tool_table.cellWidget(row, 0)
            if widget:
                cb = widget.findChild(QCheckBox)
                if cb and cb.isChecked():
                    selected.append(self._fetched_tools[row])
        return selected

    # -- Install selected tools --
    def _on_install(self):
        selected = self._get_selected_tools()
        if not selected:
            self.status_label.setText("No tools selected.")
            self.status_label.setStyleSheet("color: #FF9500; font-size: 12px;")
            return

        self.install_btn.setEnabled(False)
        self.fetch_btn.setEnabled(False)
        self.status_label.setText("Installing...")
        self.status_label.setStyleSheet("color: #007AFF; font-size: 12px;")
        QApplication.processEvents()

        self._worker = ToolFetchWorker(self.url_field.text().strip())
        self._worker.download_progress.connect(self._on_download_progress)
        self._worker.download_finished.connect(self._on_download_finished)
        self._worker.start_download(selected, self._local_tools_dir)

    def _on_download_progress(self, message: str):
        self.status_label.setText(message)
        self.status_label.setStyleSheet("color: #007AFF; font-size: 12px;")
        QApplication.processEvents()

    def _on_download_finished(self, installed: list, errors: list):
        self.fetch_btn.setEnabled(True)
        self.install_btn.setEnabled(True)

        if errors:
            error_text = "\n".join(errors)
            QMessageBox.warning(
                self, "Import Errors",
                f"Some tools failed to install:\n\n{error_text}"
            )

        if installed:
            # Refresh status column
            self._refresh_status_column()

            names = ", ".join(installed)

            # Find actual backup files that were created
            backup_files: List[str] = []
            for n in installed:
                tool_dir = self._local_tools_dir / n
                backups = sorted(tool_dir.glob("tool.json.bak.*"))
                if backups:
                    # Show the most recent backup
                    backup_files.append(f"  {n}/{backups[-1].name}")

            if backup_files:
                backup_list = "\n".join(backup_files)
                backup_note = (
                    f"\n\nYour previous tool.json file(s) have been backed up:\n"
                    f"{backup_list}\n\n"
                    f"You can compare the backup against the new tool.json to "
                    f"restore your custom settings. Use Tools > Edit Tool "
                    f"Configuration to edit tool.json, or Tools > Open Tools "
                    f"Folder to view the backup files."
                )
            else:
                backup_note = ""

            msg = (
                f"Successfully installed: {names}\n\n"
                f"Please review and configure the defaults in each tool's "
                f"tool.json file before running.{backup_note}"
            )

            QMessageBox.information(self, "Tools Installed", msg)
            self.tools_imported.emit()

            self.status_label.setText(f"Installed {len(installed)} tool(s)")
            self.status_label.setStyleSheet("color: #34C759; font-size: 12px;")
            logger.info(f"Tool import: installed {installed}")
        else:
            self.status_label.setText("No tools were installed.")
            self.status_label.setStyleSheet("color: #FF9500; font-size: 12px;")

    def _refresh_status_column(self):
        """Update the Status column after an install."""
        installed_tools = set()
        if self._local_tools_dir.exists():
            installed_tools = {
                p.name for p in self._local_tools_dir.iterdir() if p.is_dir()
            }
        for row in range(self.tool_table.rowCount()):
            name_item = self.tool_table.item(row, 1)
            if name_item:
                status = "Installed" if name_item.text() in installed_tools else "Not installed"
                status_item = self.tool_table.item(row, 2)
                if status_item:
                    status_item.setText(status)


class ToolJsonEditorDialog(QMainWindow):
    """A window for viewing and editing a tool's tool.json file.

    Modelled after ``ConfigEditorDialog`` — provides a raw JSON text editor
    with Reload / Save / Validate controls.
    """

    config_saved = pyqtSignal()  # Emitted after a successful save

    def __init__(self, tool_json_path: Path, parent=None):
        super().__init__(parent)
        self._tool_json_path = tool_json_path
        self.setWindowTitle(f"Tool Configuration — {tool_json_path.parent.name}")
        self.setMinimumSize(600, 450)
        self.resize(680, 550)
        self._is_modified = False

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)

        # Info label
        info_label = QLabel(f"Editing: {tool_json_path}")
        info_label.setObjectName("secondary_label")
        layout.addWidget(info_label)

        # Text editor
        self.text_edit = QTextEdit()
        self.text_edit.setFont(QFont("Menlo", 11))
        self.text_edit.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.text_edit)

        # Status label
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        reload_btn = QPushButton("Reload")
        reload_btn.clicked.connect(self._load)
        btn_layout.addWidget(reload_btn)

        btn_layout.addStretch()

        save_btn = QPushButton("Save")
        save_btn.setProperty("class", "success")
        save_btn.clicked.connect(self._save)
        btn_layout.addWidget(save_btn)

        validate_btn = QPushButton("Validate JSON")
        validate_btn.setProperty("class", "primary")
        validate_btn.clicked.connect(self._validate)
        btn_layout.addWidget(validate_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

        # Load initial content
        self._load()

    def _on_text_changed(self):
        self._is_modified = True
        self.status_label.setText("")

    def _load(self):
        try:
            if self._tool_json_path.exists():
                with open(self._tool_json_path, "r", encoding="utf-8") as f:
                    content = f.read()
                self.text_edit.setPlainText(content)
                self._is_modified = False
                self.status_label.setText("")
            else:
                self.text_edit.setPlainText("{}")
                self.status_label.setText("File not found — starting with empty JSON.")
                self.status_label.setStyleSheet("color: #FF9500; font-size: 12px;")
        except Exception as e:
            self.text_edit.setPlainText("")
            self.status_label.setText(f"Error loading: {e}")
            self.status_label.setStyleSheet("color: #FF3B30; font-size: 12px;")

    def _validate(self) -> bool:
        try:
            json.loads(self.text_edit.toPlainText())
            self.status_label.setText("✓ Valid JSON")
            self.status_label.setStyleSheet("color: #34C759; font-size: 12px;")
            return True
        except json.JSONDecodeError as e:
            self.status_label.setText(f"✗ Invalid JSON: {e}")
            self.status_label.setStyleSheet("color: #FF3B30; font-size: 12px;")
            return False

    def _save(self):
        if not self._validate():
            QMessageBox.warning(
                self, "Invalid JSON",
                "The file contains invalid JSON and cannot be saved.\n\n"
                "Please fix the errors and try again."
            )
            return

        try:
            data = json.loads(self.text_edit.toPlainText())
            formatted = json.dumps(data, indent=2)

            with open(self._tool_json_path, "w", encoding="utf-8") as f:
                f.write(formatted)

            self.text_edit.setPlainText(formatted)
            self._is_modified = False
            self.status_label.setText("✓ Saved")
            self.status_label.setStyleSheet("color: #34C759; font-size: 12px;")
            logger.info(f"Tool config editor: saved {self._tool_json_path}")
            self.config_saved.emit()
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save:\n{e}")

    def closeEvent(self, event):
        if self._is_modified:
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "You have unsaved changes. Close without saving?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
        event.accept()


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
        self._is_capturing = False  # True while a capture+merge is in progress
        self.capture_interval = 30  # Default capture interval in seconds
        self.theme_mode = "system"  # "light", "dark", or "system"
        self.meeting_details_dirty = False  # Track if meeting details need saving
        self._discovered_tools: Dict[str, dict] = {}  # tool_key → parsed JSON definition
        self._tool_scripts_dir: Optional[Path] = None
        self._tool_runner: Optional[ToolRunnerWorker] = None
        self._tool_start_time: float = 0.0  # time.time() when tool started
        self._tool_elapsed_timer: Optional[QTimer] = None  # ticks every second while tool runs
        self._compact_mode = False  # Track compact/expanded view state
        self._expanded_size = None  # Remember window size before compacting
        
        # Setup UI
        self._setup_window()
        self._setup_ui()
        self._setup_menubar()
        self._setup_tray()
        self._load_config()
        self._update_button_states()  # Set initial disabled state before permission check
        self._check_permissions()
        
        # Default window size (4:3 aspect ratio)
        self.resize(600, 450)
        
        # Start non-blocking update check in the background
        self._startup_update_worker = UpdateCheckWorker()
        self._startup_update_worker.update_available.connect(self._on_startup_update_available)
        self._startup_update_worker.start()
        
        # Default to "hidden from screen sharing" — deferred because the
        # native NSWindow doesn't exist until after show() is called.
        if _HAS_APPKIT:
            QTimer.singleShot(100, lambda: self._toggle_privacy_mode(True))
        
    def _setup_window(self):
        """Configure main window properties."""
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(450, 300)
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
        self.new_btn.setProperty("class", "primary")
        self.new_btn.setToolTip("Start a new recording session")
        self.new_btn.clicked.connect(self._on_new_recording)
        app_layout.addWidget(self.new_btn)
        
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setProperty("class", "pink")
        self.reset_btn.setEnabled(False)
        self.reset_btn.setToolTip("Reset the current recording session")
        self.reset_btn.clicked.connect(self._on_reset_recording)
        app_layout.addWidget(self.reset_btn)
        
        self.load_previous_btn = QPushButton("Load Previous Meeting")
        self.load_previous_btn.setToolTip("Load meeting details and transcript from a previous recording folder")
        self.load_previous_btn.clicked.connect(self._on_load_previous_meeting)
        app_layout.addWidget(self.load_previous_btn)
        
        app_layout.addStretch()
        
        main_layout.addWidget(app_group)
        
        # === Recording Controls Section ===
        controls_group = QWidget()
        controls_layout = QHBoxLayout(controls_group)
        controls_layout.setContentsMargins(0, 4, 0, 4)
        controls_layout.setSpacing(8)
        
        self.capture_btn = QPushButton("Capture Now")
        self.capture_btn.setProperty("class", "primary")
        self.capture_btn.setEnabled(False)
        self.capture_btn.setToolTip("Take a single transcript snapshot")
        self.capture_btn.clicked.connect(self._on_capture_now)
        controls_layout.addWidget(self.capture_btn)
        
        self.auto_capture_btn = QPushButton("Start Auto Capture")
        self.auto_capture_btn.setProperty("class", "success")
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
        
        # Meeting Date/Time
        datetime_layout = QHBoxLayout()
        datetime_layout.setSpacing(4)
        datetime_label = QLabel("Date/Time:")
        datetime_label.setFixedWidth(110)
        datetime_layout.addWidget(datetime_label)
        
        self.meeting_datetime_input = QLineEdit()
        self.meeting_datetime_input.textChanged.connect(self._on_meeting_details_changed)
        datetime_layout.addWidget(self.meeting_datetime_input, stretch=1)
        
        # Grab the native system icons once
        style = self.style()
        icon_up = style.standardIcon(QStyle.StandardPixmap.SP_ArrowUp)
        icon_down = style.standardIcon(QStyle.StandardPixmap.SP_ArrowDown)

        # Round time buttons — stacked vertically beside the text field
        time_btn_stack = QVBoxLayout()
        time_btn_stack.setSpacing(1)
        time_btn_stack.setContentsMargins(0, 0, 0, 0)
        
        self.time_up_btn = QPushButton()
        self.time_up_btn.setObjectName("time_btn")
        self.time_up_btn.setIcon(icon_up)
        self.time_up_btn.setFixedSize(28, 14)
        self.time_up_btn.setToolTip("Round time up by 5 minutes")
        self.time_up_btn.clicked.connect(self._on_round_time_up)
        time_btn_stack.addWidget(self.time_up_btn)
        
        self.time_down_btn = QPushButton()
        self.time_down_btn.setObjectName("time_btn")
        self.time_down_btn.setIcon(icon_down)
        self.time_down_btn.setFixedSize(28, 14)
        self.time_down_btn.setToolTip("Round time down by 5 minutes")
        self.time_down_btn.clicked.connect(self._on_round_time_down)
        time_btn_stack.addWidget(self.time_down_btn)
        
        datetime_layout.addLayout(time_btn_stack)
        
        details_layout.addLayout(datetime_layout)
        
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
        self.save_details_btn.setProperty("class", "primary")
        self.save_details_btn.setEnabled(False)
        self.save_details_btn.clicked.connect(self._on_save_details_clicked)
        details_actions_layout.addWidget(self.save_details_btn)
        
        self.open_folder_btn2 = QPushButton("Open Recording Folder")
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
        
        self.open_folder_btn = QPushButton("Open Recording Folder")
        self.open_folder_btn.setEnabled(False)
        self.open_folder_btn.clicked.connect(self._on_open_folder)
        actions_layout.addWidget(self.open_folder_btn)
        
        actions_layout.addStretch()
        
        self.line_count_label = QLabel("Lines: 0")
        actions_layout.addWidget(self.line_count_label)
        
        transcript_layout.addLayout(actions_layout)
        
        self.tab_widget.addTab(transcript_tab, "Meeting Transcript")
        
        # --- Meeting Tools Tab ---
        tools_tab = QWidget()
        tools_tab.setAutoFillBackground(False)
        tools_layout = QVBoxLayout(tools_tab)
        tools_layout.setContentsMargins(0, 8, 0, 0)
        tools_layout.setSpacing(6)
        
        # Tool selection row
        tool_select_layout = QHBoxLayout()
        tool_label = QLabel("Tool:")
        tool_label.setFixedWidth(50)
        tool_select_layout.addWidget(tool_label)
        
        self.tool_combo = QComboBox()
        self.tool_combo.setMinimumWidth(200)
        self.tool_combo.addItem("Select a tool...", None)
        self.tool_combo.currentIndexChanged.connect(self._on_tool_changed)
        tool_select_layout.addWidget(self.tool_combo)
        
        self.run_tool_btn = QPushButton("Run")
        self.run_tool_btn.setProperty("class", "primary")
        self.run_tool_btn.setEnabled(False)
        self.run_tool_btn.clicked.connect(self._on_run_tool)
        tool_select_layout.addWidget(self.run_tool_btn)
        
        self.cancel_tool_btn = QPushButton("Cancel")
        self.cancel_tool_btn.setEnabled(False)
        self.cancel_tool_btn.setVisible(False)
        self.cancel_tool_btn.clicked.connect(self._on_cancel_tool)
        tool_select_layout.addWidget(self.cancel_tool_btn)
        
        self.tool_elapsed_label = QLabel("")
        self.tool_elapsed_label.setVisible(False)
        tool_select_layout.addWidget(self.tool_elapsed_label)
        
        tool_select_layout.addStretch()
        tools_layout.addLayout(tool_select_layout)
        
        # --- Tool description (no border) ---
        self.tool_description_label = QLabel("")
        self.tool_description_label.setWordWrap(True)
        self.tool_description_label.setStyleSheet(
            "color: palette(windowText); font-size: 13px; padding: 2px 0;"
        )
        self.tool_description_label.setVisible(False)
        tools_layout.addWidget(self.tool_description_label)
        
        # --- Parameters section (unframed, with spacing above/below) ---
        tools_layout.addSpacing(6)
        
        self.tool_params_toggle = QPushButton("▶ Parameters")
        self.tool_params_toggle.setFlat(True)
        self.tool_params_toggle.setStyleSheet(
            "text-align: left; font-weight: 600; padding: 2px 0;"
        )
        self.tool_params_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tool_params_toggle.setVisible(False)
        self.tool_params_toggle.clicked.connect(self._toggle_tool_params)
        tools_layout.addWidget(self.tool_params_toggle)
        
        self.tool_params_table = QTableWidget(0, 3)
        self.tool_params_table.setHorizontalHeaderLabels(["Flag", "Parameter", "Value"])
        self.tool_params_table.horizontalHeader().setStretchLastSection(True)
        self.tool_params_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.tool_params_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.tool_params_table.verticalHeader().setVisible(False)
        self.tool_params_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tool_params_table.setMaximumHeight(160)
        self.tool_params_table.setVisible(False)
        self.tool_params_table.cellChanged.connect(self._on_tool_param_edited)
        tools_layout.addWidget(self.tool_params_table)
        
        # --- Command preview (inside collapsible section) ---
        self.tool_command_frame = QFrame()
        self.tool_command_frame.setFrameShape(QFrame.Shape.StyledPanel)
        self.tool_command_frame.setFrameShadow(QFrame.Shadow.Plain)
        self.tool_command_frame.setStyleSheet(
            "QFrame { border: 1px solid palette(mid); border-radius: 4px; }"
        )
        self.tool_command_frame.setVisible(False)
        cmd_inner = QVBoxLayout(self.tool_command_frame)
        cmd_inner.setContentsMargins(8, 6, 8, 6)
        
        self.tool_command_label = QLabel("")
        self.tool_command_label.setObjectName("secondary_label")
        self.tool_command_label.setWordWrap(True)
        self.tool_command_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.tool_command_label.setStyleSheet("border: none;")
        cmd_inner.addWidget(self.tool_command_label)
        
        tools_layout.addWidget(self.tool_command_frame)
        
        # Output area (always visible)
        self.tool_output_area = QTextEdit()
        self.tool_output_area.setReadOnly(True)
        self.tool_output_area.setPlaceholderText(
            "Select a tool from the dropdown above and click Run.\n\n"
            "Tool output will appear here."
        )
        self.tool_output_area.setFont(QFont("Menlo", 11))
        tools_layout.addWidget(self.tool_output_area, stretch=1)
        
        self.tab_widget.addTab(tools_tab, "Meeting Tools")
        
        main_layout.addWidget(self.tab_widget, stretch=1)
        
        # === Separator before status bar ===
        self.separator_bottom = QFrame()
        self.separator_bottom.setFrameShape(QFrame.Shape.HLine)
        self.separator_bottom.setFrameShadow(QFrame.Shadow.Plain)
        self.separator_bottom.setFixedHeight(1)
        main_layout.addWidget(self.separator_bottom)
        
        # === Apply Modern Styling ===
        self._apply_styles()
        
        # === Status Bar ===
        # Build a custom status bar layout: [compact_btn] [status_label] ... [version]
        # We avoid QStatusBar.showMessage() because it hides addWidget items.
        # Instead, use a permanent widget container on the left with a label we
        # control ourselves, so the compact button is always visible.
        status_container = QWidget()
        status_hlayout = QHBoxLayout(status_container)
        status_hlayout.setContentsMargins(0, 0, 0, 0)
        status_hlayout.setSpacing(4)
        
        # Compact/Expand toggle button
        self.compact_btn = QPushButton()
        self.compact_btn.setFixedSize(20, 20)
        self.compact_btn.setToolTip("Compact view")
        self.compact_btn.setIcon(self.style().standardIcon(
            QStyle.StandardPixmap.SP_ArrowUp))
        self.compact_btn.setFlat(True)
        self.compact_btn.clicked.connect(self._toggle_compact_mode)
        status_hlayout.addWidget(self.compact_btn)
        
        # Status message label (replaces showMessage)
        self._status_msg_label = QLabel("Ready")
        status_hlayout.addWidget(self._status_msg_label, stretch=1)
        
        self.statusBar().addWidget(status_container, stretch=1)
        
        # Add version label to the right side of the status bar
        self.version_label = QLabel(f"v{APP_VERSION}")
        self.version_label.setStyleSheet("color: gray; padding-right: 8px;")
        self.statusBar().addPermanentWidget(self.version_label)
        
        # Redirect statusBar().showMessage() to our custom label so the
        # compact button is never hidden by temporary messages.
        self.statusBar().showMessage = self._show_status_message
    
    def _show_status_message(self, text: str, timeout: int = 0):
        """Set status bar text via the custom label (keeps compact button visible)."""
        self._status_msg_label.setText(text)
    
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
        """Apply the global application stylesheet.
        
        Sets a single comprehensive QSS on QApplication so that every
        window, dialog, and popup inherits the theme automatically.
        After swapping the stylesheet, unpolish/polish the entire widget
        tree so the change takes effect immediately (required for live
        Light ↔ Dark toggling).
        """
        is_dark = self._is_dark_mode()
        app = QApplication.instance()
        app.setStyleSheet(get_application_stylesheet(is_dark))
        
        # Force every widget in the app to re-read the new stylesheet
        for widget in app.allWidgets():
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self.update()
        
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
        
        self.privacy_action = QAction("Hide from Screen Sharing", self)
        self.privacy_action.setCheckable(True)
        self.privacy_action.setChecked(True)  # Private by default
        self.privacy_action.setEnabled(_HAS_APPKIT)
        self.privacy_action.triggered.connect(self._toggle_privacy_mode)
        view_menu.addAction(self.privacy_action)
        
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
        
        # Tools menu
        tools_menu = menubar.addMenu("Tools")
        
        import_tools_action = QAction("Import Tools...", self)
        import_tools_action.triggered.connect(self._show_tool_import)
        tools_menu.addAction(import_tools_action)
        
        edit_tool_config_action = QAction("Edit Tool Configuration...", self)
        edit_tool_config_action.triggered.connect(self._show_tool_json_editor)
        tools_menu.addAction(edit_tool_config_action)
        
        tools_menu.addSeparator()
        
        open_tools_folder_action = QAction("Open Tools Folder", self)
        open_tools_folder_action.triggered.connect(self._open_tools_folder)
        tools_menu.addAction(open_tools_folder_action)
        
        refresh_tools_action = QAction("Refresh Tools", self)
        refresh_tools_action.triggered.connect(self._scan_tools)
        tools_menu.addAction(refresh_tools_action)
        
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
            
            # Ensure tools directory exists alongside recordings
            (self.export_base_dir / "tools").mkdir(parents=True, exist_ok=True)
            
            # Configure logging from config
            setup_logging(self.config)
            
            # Populate app selection and discover tools
            self._populate_app_combo()
            self._scan_tools()
            
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
        
        # NOTE: The recording folder is NOT created here — it is deferred
        # until the first capture or the user saves meeting details.  This
        # avoids creating empty folders for sessions that are never used.
        
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
        logger.info(f"New session: prepared for {self.selected_app_key} (folder deferred: {self.current_recording_path})")
        
        # Set focus to Meeting Name field for quick entry
        self.meeting_name_input.setFocus()
    
    def _on_reset_recording(self):
        """Reset the current recording session."""
        if self.is_recording:
            reply = QMessageBox.question(
                self, "Auto Capture Running",
                "Auto capture is currently running. Resetting will stop "
                "the capture and clear the current session.\n\n"
                "Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
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
        
        # Reset Meeting Tools panel to default state
        self.tool_combo.setCurrentIndex(0)
        self.tool_output_area.clear()
        self.tool_output_area.setPlaceholderText(
            "Select a tool from the dropdown above and click Run.\n\n"
            "Tool output will appear here."
        )
        
        self._update_button_states()
        self._set_status("Ready", "gray")
        self.statusBar().showMessage("Session reset")
        logger.info("Session reset")
        
    def _ensure_recorder(self) -> bool:
        """Create a recorder instance on-demand for a loaded session.
        
        When a previous meeting is loaded there is no recorder yet.  This
        helper creates one using the currently selected application so that
        capture operations can proceed.
        
        Returns True when a recorder is available, False otherwise.
        """
        if self.recorder_instance:
            return True
        
        if not self.current_recording_path:
            return False
        
        if not self.selected_app_key or not self.config:
            QMessageBox.warning(
                self, "No Application Selected",
                "Please select a meeting application before capturing."
            )
            return False
        
        app_config = self.config.get("application_settings", {}).get(self.selected_app_key, {})
        if not app_config:
            QMessageBox.warning(
                self, "Configuration Error",
                f"No configuration found for {self.selected_app_key}"
            )
            return False
        
        # Set up snapshots path for the loaded recording folder
        self.snapshots_path = self.current_recording_path / ".snapshots"
        self.merged_transcript_path = self.current_recording_path / "meeting_transcript.txt"
        
        tr_config = app_config.copy()
        tr_config["base_transcript_directory"] = str(self.snapshots_path)
        tr_config["name"] = self.selected_app_key
        
        try:
            self.recorder_instance = TranscriptRecorder(app_config=tr_config, logger=logger)
        except Exception as e:
            logger.error(f"Failed to create recorder for loaded session: {e}", exc_info=True)
            QMessageBox.critical(self, "Error", f"Failed to initialize recorder:\n{e}")
            return False
        
        logger.info(f"Recorder created on-demand for loaded session: {self.selected_app_key}")
        self._update_button_states()
        return True
    
    def _on_start_recording(self):
        """Start continuous recording."""
        if not self._ensure_recorder():
            logger.warning("Start recording: no active session")
            return
        
        # Switch to transcript tab
        self.tab_widget.setCurrentIndex(1)  # Meeting Transcript tab
            
        self.recording_worker = RecordingWorker(self.capture_interval)
        self.recording_worker.capture_requested.connect(self._on_auto_capture_requested)
        self.recording_worker.countdown_tick.connect(self._on_countdown_tick)
        
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
        """Take a manual snapshot and merge into meeting transcript."""
        self._do_capture_and_merge(auto=False)
    
    def _ensure_recording_folder(self) -> bool:
        """Create the recording folder on disk if it doesn't already exist.
        
        The folder creation is deferred from ``_on_new_recording`` so that
        empty folders are never left behind for sessions that are abandoned
        before any capture or details-save occurs.
        
        Returns True on success, False on failure.
        """
        if not self.current_recording_path:
            return False
        if self.current_recording_path.exists():
            return True
        try:
            self.current_recording_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Recording folder created: {self.current_recording_path}")
            return True
        except OSError as e:
            logger.error(f"Failed to create recording folder: {e}")
            QMessageBox.critical(self, "Error", f"Failed to create recording folder:\n{e}")
            return False
    
    def _do_capture_and_merge(self, auto: bool = False):
        """Unified capture and merge — single code path for manual and auto capture.
        
        Uses the existence of the merged transcript file (rather than a counter)
        to decide between an initial copy and a smart merge.  This ensures no
        content is lost when manual and auto captures are intermixed.
        
        A ``_is_capturing`` flag prevents re-entrant calls so that a manual
        capture cannot overlap with an auto capture (and vice-versa).
        
        Args:
            auto: True when triggered by the auto-capture timer, False for manual.
        """
        if not self.recorder_instance:
            if not auto:
                if not self._ensure_recorder():
                    logger.warning("Manual capture: no active session")
                    return
            else:
                return
        
        if self._is_capturing:
            logger.debug("Capture already in progress, skipping")
            return
        
        # Ensure the recording folder exists on disk (deferred from New Recording)
        if not self._ensure_recording_folder():
            return
        
        self._is_capturing = True
        self._update_button_states()
        
        # Switch to transcript tab only on manual capture
        if not auto:
            self.tab_widget.setCurrentIndex(1)
        
        source = "Auto" if auto else "Manual"
        self.statusBar().showMessage("Capturing transcript...")
        QApplication.processEvents()  # Ensure UI updates before blocking call
        
        logger.debug(f"{source} capture: starting")
        
        loop = asyncio.new_event_loop()
        try:
            success, file_path, line_count = loop.run_until_complete(
                self.recorder_instance.export_transcript_text()
            )
            
            if success and file_path:
                self.snapshot_count += 1
                overlap_count = 0
                
                # Use file existence (not a counter) to decide copy vs merge.
                # This correctly handles intermixed manual + auto captures.
                if self.merged_transcript_path and self.merged_transcript_path.exists():
                    merge_ok, _, overlap_count = smart_merge(
                        str(self.merged_transcript_path),
                        file_path,
                        str(self.merged_transcript_path)
                    )
                    logger.info(
                        f"{source} capture: snapshot #{self.snapshot_count} merged "
                        f"({line_count} lines, {overlap_count} overlap)"
                    )
                else:
                    shutil.copy(file_path, str(self.merged_transcript_path))
                    logger.info(f"{source} capture: first snapshot saved ({line_count} lines)")
                
                # Save meeting details if modified
                self._save_meeting_details()
                
                # Display the merged transcript
                self._update_transcript_display(str(self.merged_transcript_path), line_count or 0)
                self.statusBar().showMessage(
                    f"{source} capture: {line_count} lines (snapshot #{self.snapshot_count})"
                )
                self._set_status("Captured", "green")
            else:
                logger.warning(f"{source} capture: no transcript data returned")
                if not auto:
                    QMessageBox.warning(
                        self, "Capture Failed",
                        "Could not capture transcript. Make sure:\n"
                        "• The meeting application is running\n"
                        "• Captions/transcript is enabled\n"
                        "• The transcript window is visible"
                    )
                self._set_status("Capture failed", "red")
        except Exception as e:
            logger.error(f"{source} capture failed: {e}", exc_info=True)
            if not auto:
                QMessageBox.critical(self, "Error", f"Capture failed:\n{e}")
            self._set_status("Error", "red")
        finally:
            loop.close()
            self._is_capturing = False
            self._update_button_states()
            
    def _on_auto_capture_requested(self):
        """Handle auto-capture timer requesting a snapshot."""
        if not self.is_recording:
            return  # Ignore stale signals after auto capture was stopped
        self._do_capture_and_merge(auto=True)
            
    def _on_countdown_tick(self, seconds: int):
        """Update countdown display in status bar."""
        if seconds == 0:
            self.statusBar().showMessage("Capturing...")
        else:
            self.statusBar().showMessage(f"Next capture in {seconds}s")
        
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
    
    def _on_load_previous_meeting(self):
        """Load meeting details and transcript from a previous recording folder."""
        # Default to the recordings directory
        start_dir = str(self.export_base_dir / "recordings")
        if not Path(start_dir).exists():
            start_dir = str(self.export_base_dir)
        
        selected_dir = QFileDialog.getExistingDirectory(
            self,
            "Select a Previous Recording Folder",
            start_dir,
            QFileDialog.Option.ShowDirsOnly
        )
        
        if not selected_dir:
            return  # User cancelled
        
        selected_path = Path(selected_dir)
        
        # Validate: must contain at least a meeting_transcript.txt or meeting_details.txt
        has_transcript = (selected_path / "meeting_transcript.txt").exists()
        has_details = (selected_path / "meeting_details.txt").exists()
        
        if not has_transcript and not has_details:
            QMessageBox.warning(
                self, "Invalid Recording Folder",
                "The selected folder does not contain a meeting_transcript.txt "
                "or meeting_details.txt file.\n\n"
                "Please select a valid recording folder."
            )
            return
        
        # If there's an active auto capture, prompt to confirm
        if self.is_recording:
            reply = QMessageBox.question(
                self, "Auto Capture Running",
                "Auto capture is currently running. Loading a previous meeting "
                "will stop the capture and reset the current session.\n\n"
                "Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            self._on_stop_recording()
        
        # Reset current session state
        self.recorder_instance = None
        self.snapshot_count = 0
        self._is_capturing = False
        
        # Set paths for the loaded recording
        self.current_recording_path = selected_path
        self.snapshots_path = selected_path / ".snapshots"
        self.merged_transcript_path = selected_path / "meeting_transcript.txt"
        
        # Parse meeting_details.txt if it exists
        self.meeting_datetime_input.clear()
        self.meeting_name_input.clear()
        self.meeting_notes_input.clear()
        
        if has_details:
            self._load_meeting_details_from_file(selected_path / "meeting_details.txt")
        
        # Load transcript if it exists
        self.transcript_text.clear()
        if has_transcript:
            try:
                transcript_content = (selected_path / "meeting_transcript.txt").read_text(encoding='utf-8')
                self.transcript_text.setPlainText(transcript_content)
                line_count = len(transcript_content.splitlines())
                self.line_count_label.setText(f"Lines: {line_count}")
            except Exception as e:
                logger.error(f"Failed to load transcript: {e}")
                self.line_count_label.setText("Lines: 0")
        else:
            self.line_count_label.setText("Lines: 0")
        
        self.meeting_details_dirty = False
        
        # Reset Meeting Tools panel
        self.tool_combo.setCurrentIndex(0)
        self.tool_output_area.clear()
        
        self._update_button_states()
        
        folder_name = selected_path.name
        self._set_status("Loaded previous meeting", "blue")
        self.statusBar().showMessage(f"Loaded — {folder_name}")
        logger.info(f"Loaded previous meeting from: {selected_path}")
        
        # Switch to Meeting Details tab
        self.tab_widget.setCurrentIndex(0)
    
    def _load_meeting_details_from_file(self, details_path: Path):
        """Parse a meeting_details.txt file and populate the UI fields.
        
        Expected format (written by _save_meeting_details):
            Meeting Name: <name>
            ====================
            
            Date/Time: <datetime>
            
            Notes:
            ----------------------------------------
            <notes content>
        """
        try:
            content = details_path.read_text(encoding='utf-8')
        except Exception as e:
            logger.error(f"Failed to read meeting details: {e}")
            return
        
        lines = content.splitlines()
        meeting_name = ""
        meeting_datetime = ""
        notes_lines = []
        in_notes = False
        
        for i, line in enumerate(lines):
            if in_notes:
                # Skip the dashes separator line immediately after "Notes:"
                if i > 0 and lines[i - 1].strip() == "Notes:" and line.strip().startswith("---"):
                    continue
                notes_lines.append(line)
            elif line.startswith("Meeting Name:"):
                meeting_name = line[len("Meeting Name:"):].strip()
            elif line.startswith("Date/Time:"):
                meeting_datetime = line[len("Date/Time:"):].strip()
            elif line.strip() == "Notes:":
                in_notes = True
            # Skip separator lines (====)
        
        if meeting_name:
            self.meeting_name_input.setText(meeting_name)
        if meeting_datetime:
            self.meeting_datetime_input.setText(meeting_datetime)
        if notes_lines:
            # Strip trailing empty lines
            while notes_lines and not notes_lines[-1].strip():
                notes_lines.pop()
            self.meeting_notes_input.setPlainText("\n".join(notes_lines))
            
    def _update_button_states(self):
        """Update button enabled states based on current state."""
        has_recorder = self.recorder_instance is not None
        has_session = has_recorder or self.current_recording_path is not None
        has_content = self.snapshot_count > 0
        # For loaded sessions, check if transcript text has content
        has_transcript_text = has_content or bool(self.transcript_text.toPlainText().strip())
        
        # Top-level controls
        self.app_combo.setEnabled(not has_session)
        self.new_btn.setEnabled(not has_session)
        self.reset_btn.setEnabled(has_session)
        
        # Recording controls — enabled when there is any session (active or loaded)
        # Capture Now is disabled while any capture+merge is in progress
        self.capture_btn.setEnabled(has_session and not self._is_capturing)
        self.auto_capture_btn.setEnabled(has_session and not self._is_capturing)
        
        # Tab widget — disabled entirely when no session exists
        self.tab_widget.setEnabled(has_session)
        
        # Transcript tab controls (explicit state within enabled tab)
        self.copy_btn.setEnabled(has_transcript_text)
        self.open_folder_btn.setEnabled(has_transcript_text)
        
        # Meeting Details tab controls
        self.save_details_btn.setEnabled(has_session)
        self.open_folder_btn2.setEnabled(has_session)
        
        # Meeting Tools tab controls
        has_tool = self.tool_combo.currentData() is not None
        self.run_tool_btn.setEnabled(has_session and has_tool)
        
        # Update auto capture button text and style
        self._update_auto_capture_btn_style()
    
    def _update_auto_capture_btn_style(self):
        """Update the auto capture button text and color based on recording state."""
        if self.is_recording:
            self.auto_capture_btn.setText("Stop Auto Capture")
            self.auto_capture_btn.setProperty("class", "danger")
        else:
            self.auto_capture_btn.setText("Start Auto Capture")
            self.auto_capture_btn.setProperty("class", "success")
        
        # Force Qt to re-read the stylesheet for this widget
        self.auto_capture_btn.style().unpolish(self.auto_capture_btn)
        self.auto_capture_btn.style().polish(self.auto_capture_btn)
    
    def _toggle_compact_mode(self):
        """Toggle between compact and expanded window views."""
        self._compact_mode = not self._compact_mode
        style = self.style()
        
        if self._compact_mode:
            # Remember current window size before compacting
            self._expanded_size = self.size()
            
            # Hide tab widget and bottom separator
            self.tab_widget.hide()
            self.separator_bottom.hide()
            
            # Update button to show "expand" (down arrow) icon
            self.compact_btn.setIcon(style.standardIcon(
                QStyle.StandardPixmap.SP_ArrowDown))
            self.compact_btn.setToolTip("Expand view")
            
            # Let Qt recalculate layouts after hiding widgets, then shrink.
            QApplication.processEvents()
            self.setMinimumHeight(0)
            self.resize(self.width(), self.minimumSizeHint().height())
        else:
            # Show tab widget and bottom separator
            self.tab_widget.show()
            self.separator_bottom.show()
            
            # Update button to show "compact" (up arrow) icon
            self.compact_btn.setIcon(style.standardIcon(
                QStyle.StandardPixmap.SP_ArrowUp))
            self.compact_btn.setToolTip("Compact view")
            
            # Restore minimum height and previous window size
            self.setMinimumHeight(300)
            self.resize(self._expanded_size)
    
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
        """Save meeting details to file if modified.
        
        The file is also written when it does not yet exist on disk,
        ensuring that the default timestamp populated by New Recording
        is always persisted once the first capture occurs.
        """
        if not self.current_recording_path:
            return
        
        meeting_name = self.meeting_name_input.text().strip()
        meeting_datetime = self.meeting_datetime_input.text().strip()
        meeting_notes = self.meeting_notes_input.toPlainText().strip()
        
        # Only save if there's content
        if not meeting_name and not meeting_datetime and not meeting_notes:
            return
        
        # Ensure the recording folder exists on disk (deferred from New Recording)
        if not self._ensure_recording_folder():
            return
        
        details_path = self.current_recording_path / "meeting_details.txt"
        file_missing = not details_path.exists()
        
        if not force and not self.meeting_details_dirty and not file_missing:
            return
        
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
    
    # ------------------------------------------------------------------
    #  Meeting Tools — discovery, display, and execution
    # ------------------------------------------------------------------

    def _toggle_tool_params(self):
        """Toggle visibility of the parameters table."""
        visible = not self.tool_params_table.isVisible()
        self.tool_params_table.setVisible(visible)
        self.tool_params_toggle.setText(
            "▼ Parameters" if visible else "▶ Parameters"
        )

    def _scan_tools(self):
        """Scan ``<export_dir>/tools/`` for tool definitions.
        
        Each tool lives in its own sub-folder::
        
            tools/
            └── summarize_meeting/
                ├── tool.json               (or any .json — first found is used)
                ├── summarize_meeting.sh
                └── README.md               (optional)
        
        The JSON file must contain ``display_name`` and ``script`` keys.
        Built-in parameter values are resolved at run-time.
        """
        self._discovered_tools = {}
        self.tool_combo.clear()
        self.tool_combo.addItem("Select a tool...", None)
        
        if not self.export_base_dir:
            return
        
        self._tool_scripts_dir = self.export_base_dir / "tools"
        
        # Create the directory if it doesn't exist
        try:
            self._tool_scripts_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"Tools: failed to create tools directory: {e}")
            return
        
        # Each immediate sub-directory is a potential tool
        try:
            subdirs = sorted(
                p for p in self._tool_scripts_dir.iterdir() if p.is_dir()
            )
        except OSError as e:
            logger.error(f"Tools: could not list tools directory: {e}")
            return
        
        for tool_dir in subdirs:
            # Find the first .json file in the sub-directory
            json_files = sorted(tool_dir.glob("*.json"))
            if not json_files:
                logger.debug(f"Tools: no .json definition in {tool_dir.name}/ — skipped")
                continue
            
            json_path = json_files[0]  # use the first one found
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    tool_def = json.load(f)
                
                # Validate required fields
                if not tool_def.get("display_name") or not tool_def.get("script"):
                    logger.warning(f"Tools: {tool_dir.name}/{json_path.name} missing 'display_name' or 'script'")
                    continue
                
                # Verify the referenced script exists inside the same sub-folder
                script_path = tool_dir / tool_def["script"]
                if not script_path.exists():
                    logger.warning(f"Tools: script not found: {script_path}")
                    continue
                
                # Stash resolved paths
                tool_def["_script_path"] = str(script_path)
                tool_def["_json_path"] = str(json_path)
                tool_def["_tool_dir"] = str(tool_dir)
                
                tool_key = tool_dir.name
                self._discovered_tools[tool_key] = tool_def
                self.tool_combo.addItem(tool_def["display_name"], tool_key)
                
                logger.debug(f"Tools: discovered '{tool_def['display_name']}' in {tool_dir.name}/")
                
            except json.JSONDecodeError as e:
                logger.warning(f"Tools: invalid JSON in {tool_dir.name}/{json_path.name}: {e}")
            except Exception as e:
                logger.error(f"Tools: error loading {tool_dir.name}/{json_path.name}: {e}")
        
        count = len(self._discovered_tools)
        if count:
            logger.info(f"Tools: discovered {count} tool(s) in {self._tool_scripts_dir}")
        else:
            logger.debug(f"Tools: no tools found in {self._tool_scripts_dir}")

    def _get_builtin_values(self) -> Dict[str, str]:
        """Return a mapping of built-in parameter names to current app values.
        
        These names can be referenced in a tool JSON via the ``"builtin"``
        field on a parameter entry.
        """
        values: Dict[str, str] = {}
        if self.current_recording_path:
            values["meeting_directory"] = str(self.current_recording_path)
        if self.merged_transcript_path:
            values["meeting_transcript"] = str(self.merged_transcript_path)
        if self.current_recording_path:
            values["meeting_details"] = str(self.current_recording_path / "meeting_details.txt")
        if self.export_base_dir:
            values["export_directory"] = str(self.export_base_dir)
        if self.selected_app_key:
            values["app_name"] = self.selected_app_key
        return values

    def _on_tool_changed(self, index: int):
        """Handle tool selection change — populate the parameters table."""
        tool_key = self.tool_combo.currentData()
        has_tool = tool_key is not None
        has_session = self.recorder_instance is not None or self.current_recording_path is not None
        is_running = self._tool_runner is not None
        self.run_tool_btn.setEnabled(has_tool and has_session and not is_running)
        
        # Hide everything when no tool is selected
        if not has_tool:
            self.tool_description_label.setVisible(False)
            self.tool_params_toggle.setVisible(False)
            self.tool_params_table.setVisible(False)
            self.tool_params_table.setRowCount(0)
            self.tool_command_frame.setVisible(False)
            self.tool_output_area.clear()
            return
        
        tool_def = self._discovered_tools.get(tool_key, {})
        description = tool_def.get("description", "")
        parameters = tool_def.get("parameters", [])
        
        # Description
        self.tool_description_label.setText(description)
        self.tool_description_label.setVisible(bool(description))
        
        # Populate the parameters table
        builtins = self._get_builtin_values()
        self.tool_params_table.setRowCount(len(parameters))
        
        for row, param in enumerate(parameters):
            flag = param.get("flag", "")
            label = param.get("label", flag)
            builtin_key = param.get("builtin")
            default = param.get("default", "")
            
            # Column 0 — Flag (read-only)
            flag_item = QTableWidgetItem(flag)
            flag_item.setFlags(flag_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.tool_params_table.setItem(row, 0, flag_item)
            
            # Column 1 — Label (read-only)
            label_text = f"{label}  (auto)" if builtin_key else label
            label_item = QTableWidgetItem(label_text)
            label_item.setFlags(label_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.tool_params_table.setItem(row, 1, label_item)
            
            # Column 2 — Value (editable)
            if builtin_key:
                value = builtins.get(builtin_key, f"<{builtin_key}>")
            else:
                value = str(default)
            value_item = QTableWidgetItem(value)
            self.tool_params_table.setItem(row, 2, value_item)
        
        # Show the toggle but keep the table collapsed by default
        has_params = len(parameters) > 0
        self.tool_params_toggle.setVisible(has_params)
        if has_params:
            self.tool_params_table.setVisible(False)
            self.tool_params_toggle.setText("▶ Parameters")
        
        # Command preview starts hidden (collapsed with params section)
        self.tool_command_frame.setVisible(False)
        
        # Show tool info and command preview in the output area
        self._update_tool_output_preview()
    
    def _on_tool_param_edited(self, row: int, column: int):
        """Refresh the command preview when the user edits a parameter value."""
        if column == 2:  # only the Value column matters
            self._update_tool_output_preview()
    
    def _update_tool_command_preview(self):
        """Build the command from current table values and show it in the label.
        
        This is a *preview* — it silently hides the label when a required
        parameter is missing instead of writing an error to the output area.
        The command frame is only shown when the parameters section is expanded.
        """
        command = self._build_tool_command(preview=True)
        if command:
            self.tool_command_label.setText(f"Command: {' '.join(command)}")
            # Only show if the params section is expanded
            self.tool_command_frame.setVisible(self.tool_params_table.isVisible())
        else:
            self.tool_command_frame.setVisible(False)
    
    def _update_tool_output_preview(self):
        """Show the tool name, run instruction, and command in the output area.
        
        This gives the user a clear preview of what will happen when they
        click Run, replacing the old command-in-the-collapsible-section approach.
        """
        tool_key = self.tool_combo.currentData()
        if not tool_key:
            self.tool_output_area.clear()
            return
        
        tool_def = self._discovered_tools.get(tool_key, {})
        display_name = tool_def.get("display_name", tool_key)
        
        command = self._build_tool_command(preview=True)
        cmd_text = " ".join(command) if command else "<unable to build command>"
        
        separator = "—" * 40
        preview_text = (
            f"{separator}\n"
            f"{display_name}\n"
            f"{separator}\n"
            f"\n"
            f"Clicking Run will execute the following command.  "
            f"The output from {display_name} will be shown here when completed.\n"
            f"\n"
            f"command: {cmd_text}\n"
        )
        self.tool_output_area.setPlainText(preview_text)
    
    def _build_tool_command(self, preview: bool = False) -> Optional[List[str]]:
        """Read the parameters table and build the command list.
        
        Returns the command list, or None if a required parameter is missing.
        """
        tool_key = self.tool_combo.currentData()
        if not tool_key:
            return None
        
        tool_def = self._discovered_tools.get(tool_key)
        if not tool_def:
            return None
        
        script_path = Path(tool_def["_script_path"])
        if not script_path.exists():
            if not preview:
                self.tool_output_area.setPlainText(f"Error: script not found: {script_path}")
            return None
        
        # Determine the interpreter from the file extension
        interpreters = {
            ".sh": "/bin/bash", ".bash": "/bin/bash",
            ".zsh": "/bin/zsh",
            ".py": sys.executable,
        }
        interpreter = interpreters.get(script_path.suffix.lower())
        command: List[str] = [interpreter, str(script_path)] if interpreter else [str(script_path)]
        
        # If running directly (no interpreter), ensure the execute bit is set
        if not interpreter:
            try:
                mode = script_path.stat().st_mode
                if not (mode & 0o100):
                    script_path.chmod(mode | 0o755)
            except OSError as e:
                logger.warning(f"Tools: could not set execute permission: {e}")
        
        # Read flag/value pairs from the table
        parameters = tool_def.get("parameters", [])
        for row in range(self.tool_params_table.rowCount()):
            if row >= len(parameters):
                break
            param = parameters[row]
            flag_item = self.tool_params_table.item(row, 0)
            value_item = self.tool_params_table.item(row, 2)
            flag = flag_item.text().strip() if flag_item else ""
            value = value_item.text().strip() if value_item else ""
            
            if not flag:
                continue
            
            if value and not value.startswith("<"):
                command.extend([flag, value])
            elif param.get("required", False):
                if not preview:
                    self.tool_output_area.setPlainText(
                        f"Error: required parameter '{param.get('label', flag)}' has no value.\n"
                        "Enter a value in the Parameters table above."
                    )
                return None
        
        return command
    
    @staticmethod
    def _format_elapsed(seconds: int) -> str:
        """Return a human-friendly elapsed time string (e.g. '12s', '1m 23s')."""
        if seconds < 60:
            return f"{seconds}s"
        minutes, secs = divmod(seconds, 60)
        if minutes < 60:
            return f"{minutes}m {secs}s"
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h {minutes}m {secs}s"
    
    def _on_tool_timer_tick(self):
        """Update the elapsed-time label while a tool is running."""
        elapsed = int(time.time() - self._tool_start_time)
        self.tool_elapsed_label.setText(self._format_elapsed(elapsed))
        self.statusBar().showMessage(
            f"Running tool… {self._format_elapsed(elapsed)}"
        )
    
    def _on_cancel_tool(self):
        """Cancel the currently running tool."""
        if self._tool_runner:
            logger.info("Tools: cancel requested by user")
            self._tool_runner.cancel()
            self.cancel_tool_btn.setEnabled(False)
            self.cancel_tool_btn.setText("Cancelling…")
    
    def _on_run_tool(self):
        """Build the command line from the parameters table and run the script."""
        command = self._build_tool_command()
        if not command:
            return
        
        tool_key = self.tool_combo.currentData()
        tool_def = self._discovered_tools.get(tool_key, {})
        display_name = tool_def.get("display_name", tool_key)
        tool_dir = tool_def.get("_tool_dir", str(self._tool_scripts_dir))
        
        # Show running state in output area
        cmd_text = " ".join(command)
        self.tool_output_area.setPlainText(
            f"Running: {display_name}\n{'—' * 60}\n\n"
            f"command: {cmd_text}\n"
        )
        
        # Button states: disable Run, show & enable Cancel
        self.run_tool_btn.setEnabled(False)
        self.run_tool_btn.setText("Running…")
        self.cancel_tool_btn.setText("Cancel")
        self.cancel_tool_btn.setEnabled(True)
        self.cancel_tool_btn.setVisible(True)
        
        # Start elapsed-time counter
        self._tool_start_time = time.time()
        self.tool_elapsed_label.setText("0s")
        self.tool_elapsed_label.setVisible(True)
        if self._tool_elapsed_timer is None:
            self._tool_elapsed_timer = QTimer(self)
            self._tool_elapsed_timer.timeout.connect(self._on_tool_timer_tick)
        self._tool_elapsed_timer.start(1000)
        
        self.statusBar().showMessage(f"Running tool: {display_name}")
        QApplication.processEvents()
        
        logger.info(f"Tools: started '{display_name}' → {cmd_text}")
        
        # Start background worker (cwd = the tool's own directory)
        self._tool_runner = ToolRunnerWorker(command, cwd=tool_dir)
        self._tool_runner.output_ready.connect(self._on_tool_finished)
        self._tool_runner.start()
    
    def _on_tool_finished(self, stdout: str, stderr: str, exit_code: int):
        """Handle tool script completion."""
        # Stop elapsed timer
        if self._tool_elapsed_timer:
            self._tool_elapsed_timer.stop()
        
        elapsed = int(time.time() - self._tool_start_time)
        elapsed_str = self._format_elapsed(elapsed)
        
        tool_key = self.tool_combo.currentData()
        display_name = self._discovered_tools.get(tool_key, {}).get("display_name", "Tool")
        
        cancelled = exit_code == -2
        
        # Append output to the existing header
        current = self.tool_output_area.toPlainText()
        parts = [current]
        if stdout:
            parts.append(stdout)
        if stderr:
            parts.append(f"\n--- stderr ---\n{stderr}")
        
        if cancelled:
            parts.append(f"\n{'—' * 60}\nCancelled after {elapsed_str}")
        else:
            parts.append(f"\n{'—' * 60}\nFinished in {elapsed_str} (exit code {exit_code})")
        
        self.tool_output_area.setPlainText("\n".join(parts))
        
        # Scroll to bottom
        scrollbar = self.tool_output_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        
        # Restore button / label state
        self.run_tool_btn.setText("Run")
        self.run_tool_btn.setEnabled(True)
        self.cancel_tool_btn.setEnabled(False)
        self.cancel_tool_btn.setVisible(False)
        self.tool_elapsed_label.setVisible(False)
        self._tool_runner = None
        
        if cancelled:
            self.statusBar().showMessage(f"Tool cancelled: {display_name} ({elapsed_str})")
            logger.info(f"Tools: '{display_name}' cancelled after {elapsed_str}")
        elif exit_code == 0:
            self.statusBar().showMessage(f"Tool completed: {display_name} ({elapsed_str})")
            logger.info(f"Tools: '{display_name}' completed in {elapsed_str} (exit code 0)")
        else:
            self.statusBar().showMessage(f"Tool failed: {display_name} (exit code {exit_code}, {elapsed_str})")
            logger.warning(f"Tools: '{display_name}' failed (exit code {exit_code}) after {elapsed_str}")
    
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
    
    def _toggle_privacy_mode(self, checked: bool):
        """Toggle macOS window sharing type to hide/show in screen recordings.
        
        Uses NSWindow.setSharingType_:
            0 = NSWindowSharingNone   — invisible to screen capture / sharing
            1 = NSWindowSharingReadOnly — normal (visible)
        """
        if not _HAS_APPKIT:
            return
        
        try:
            title = self.windowTitle()
            for ns_window in NSApp().windows():
                if ns_window.title() == title:
                    ns_window.setSharingType_(0 if checked else 1)
                    break
            
            if checked:
                self.statusBar().showMessage("Window hidden from screen sharing")
                logger.info("Privacy: window hidden from screen sharing")
            else:
                self.statusBar().showMessage("Window visible to screen sharing")
                logger.info("Privacy: window visible to screen sharing")
        except Exception as e:
            logger.error(f"Privacy: failed to toggle sharing type: {e}")
    
    def _show_log_viewer(self):
        """Open the log viewer window."""
        self.log_viewer = LogViewerDialog(self)
        self.log_viewer.show()
    
    def _show_config_editor(self):
        """Open the configuration editor window."""
        self.config_editor = ConfigEditorDialog(self)
        self.config_editor.config_saved.connect(self._reload_configuration)
        self.config_editor.show()
    
    def _show_tool_import(self):
        """Open the Tool Import dialog."""
        tools_dir = self.export_base_dir / "tools"
        tools_dir.mkdir(parents=True, exist_ok=True)
        self._tool_import_dialog = ToolImportDialog(tools_dir, self)
        self._tool_import_dialog.tools_imported.connect(self._scan_tools)
        self._tool_import_dialog.show()
    
    def _show_tool_json_editor(self):
        """Open the tool.json editor for a selected tool.

        If multiple tools are installed, presents a selection dialog.
        """
        tools_dir = self.export_base_dir / "tools"
        if not tools_dir.exists():
            QMessageBox.information(self, "No Tools", "No tools directory found.")
            return

        tool_dirs = sorted(
            p for p in tools_dir.iterdir()
            if p.is_dir() and (p / "tool.json").exists()
        )

        if not tool_dirs:
            QMessageBox.information(
                self, "No Tools",
                "No tools with a tool.json file were found.\n\n"
                "Use Tools > Import Tools to install tools first."
            )
            return

        if len(tool_dirs) == 1:
            chosen = tool_dirs[0]
        else:
            names = [d.name for d in tool_dirs]
            name, ok = QInputDialog.getItem(
                self,
                "Select Tool",
                "Choose a tool to edit:",
                names,
                0,
                False,
            )
            if not ok:
                return
            chosen = tools_dir / name

        tool_json_path = chosen / "tool.json"
        self._tool_json_editor = ToolJsonEditorDialog(tool_json_path, self)
        self._tool_json_editor.config_saved.connect(self._scan_tools)
        self._tool_json_editor.show()
    
    def _open_tools_folder(self):
        """Open the tools directory in Finder."""
        tools_dir = self.export_base_dir / "tools"
        tools_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(tools_dir)])
    
    def _reload_configuration(self):
        """Reload the configuration file."""
        try:
            with open(DEFAULT_CONFIG_PATH, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
            
            # Reconfigure logging
            setup_logging(self.config)
            
            # Repopulate app selection and re-scan tools
            self._populate_app_combo()
            self._scan_tools()
            
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
