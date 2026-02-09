"""
Dialog windows for log viewing.
"""
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QMessageBox,
)

import gui.constants as _constants
from gui.constants import logger


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
        log_path = _constants.current_log_file_path
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
        log_path = _constants.current_log_file_path
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

