"""
Dialog windows for log viewing, first-run setup, and configuration editing.
"""
import json
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QMessageBox, QFileDialog,
    QGroupBox, QLineEdit, QInputDialog, QDialog,
)

from gui.constants import (
    APP_NAME, APP_VERSION, APP_SUPPORT_DIR, CONFIG_PATH,
    DEFAULT_EXPORT_DIR, current_log_file_path, logger, resource_path,
)
from version import GITHUB_OWNER, GITHUB_REPO


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


class SetupDialog(QDialog):
    """First-run setup dialog shown when no configuration file exists."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} — First-Run Setup")
        self.setMinimumWidth(500)
        self.setModal(True)
        
        self._chosen_config_path: Optional[Path] = None  # set on success
        
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)
        
        # Header
        header = QLabel(f"Welcome to {APP_NAME}")
        header.setFont(QFont(".AppleSystemUIFont", 18, QFont.Weight.Bold))
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)
        
        desc = QLabel(
            "Choose how to get started. You can always change the export\n"
            "directory later from the Settings menu."
        )
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        layout.addWidget(desc)
        
        layout.addSpacing(8)
        
        # Option 1 — new setup
        new_group = QGroupBox("Option A: Set up a new export directory")
        new_layout = QVBoxLayout(new_group)
        new_desc = QLabel(
            "Pick a folder where recordings, tools, and transcripts will be saved.\n"
            "A default configuration will be created for you."
        )
        new_desc.setWordWrap(True)
        new_layout.addWidget(new_desc)
        new_btn = QPushButton("Choose Export Directory…")
        new_btn.clicked.connect(self._setup_new)
        new_layout.addWidget(new_btn)
        layout.addWidget(new_group)
        
        # Option 2 — import existing config
        import_group = QGroupBox("Option B: Import an existing configuration")
        import_layout = QVBoxLayout(import_group)
        import_desc = QLabel(
            "Select an existing config.json file (e.g. from a shared drive or backup).\n"
            "It will be copied to the application's settings folder."
        )
        import_desc.setWordWrap(True)
        import_layout.addWidget(import_desc)
        import_btn = QPushButton("Select config.json…")
        import_btn.clicked.connect(self._import_existing)
        import_layout.addWidget(import_btn)
        layout.addWidget(import_group)
        
        layout.addStretch()
        
        # Cancel
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
    
    def _setup_new(self):
        """Let the user pick an export directory and create a fresh config."""
        chosen_dir = QFileDialog.getExistingDirectory(
            self,
            "Choose Export Directory",
            str(DEFAULT_EXPORT_DIR),
            QFileDialog.Option.ShowDirsOnly
        )
        if not chosen_dir:
            return
        
        export_path = Path(chosen_dir)
        
        # Copy bundled config to App Support, updating export_directory
        bundled_config = resource_path("config.json")
        if not bundled_config.exists():
            QMessageBox.critical(
                self, "Error",
                "Could not find the bundled configuration file.\n"
                "Please reinstall the application."
            )
            return
        
        try:
            APP_SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
            
            with open(bundled_config, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            
            # Set the export directory to user's choice
            if "client_settings" not in config_data:
                config_data["client_settings"] = {}
            config_data["client_settings"]["export_directory"] = str(export_path)
            
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2)
            
            # Create the export directory and tools sub-directory
            export_path.mkdir(parents=True, exist_ok=True)
            (export_path / "tools").mkdir(parents=True, exist_ok=True)
            
            logger.info(f"Setup: created config at {CONFIG_PATH}, export dir={export_path}")
            self.accept()
            
        except Exception as e:
            QMessageBox.critical(self, "Setup Error", f"Failed to create configuration:\n{e}")
    
    def _import_existing(self):
        """Let the user pick an existing config.json and copy it to App Support."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Configuration File",
            str(Path.home()),
            "JSON Files (*.json);;All Files (*)"
        )
        if not file_path:
            return
        
        src = Path(file_path)
        
        try:
            # Validate it's valid JSON
            with open(src, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            
            APP_SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
            
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2)
            
            logger.info(f"Setup: imported config from {src} to {CONFIG_PATH}")
            self.accept()
            
        except json.JSONDecodeError as e:
            QMessageBox.critical(
                self, "Invalid File",
                f"The selected file is not valid JSON:\n{e}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Import Error", f"Failed to import configuration:\n{e}")


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
        info_label = QLabel(f"Editing: {CONFIG_PATH}")
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
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
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
            
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                f.write(formatted)
            
            self.config_text.setPlainText(formatted)
            self._is_modified = False
            self.status_label.setText("✓ Configuration saved")
            self.status_label.setStyleSheet("color: #34C759; font-size: 12px;")
            logger.info(f"Config editor: saved to {CONFIG_PATH}")
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
