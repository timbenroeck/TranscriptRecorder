"""
Tool management dialogs: importing tools from GitHub, editing tool.json files,
and editing the chat configuration section of config.json.
"""
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QCheckBox,
)

from gui.constants import APP_NAME, APP_VERSION, logger
from gui.dialogs import ThemedMessageDialog
from gui.versioning import read_stored_hash
from gui.workers import ToolFetchWorker
from version import GITHUB_OWNER, GITHUB_REPO


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
        self.fetch_btn.setProperty("class", "action")
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
        self.status_label.setObjectName("dialog_status")
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
        self.install_btn.setProperty("class", "primary")
        self.install_btn.setEnabled(False)
        self.install_btn.clicked.connect(self._on_install)
        btn_layout.addWidget(self.install_btn)

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        btn_layout.addWidget(self.close_btn)

        layout.addLayout(btn_layout)

    # -- Status helper --
    def _set_status(self, text: str, state: str = ""):
        """Set status label text with themed state (info, success, warn, error, or empty)."""
        self.status_label.setText(text)
        self.status_label.setProperty("status_state", state)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    # -- Fetch available tools --
    def _on_fetch(self):
        url = self.url_field.text().strip()
        if not url:
            self._set_status("Please enter a URL.", "warn")
            return

        self.fetch_btn.setEnabled(False)
        self.install_btn.setEnabled(False)
        self._set_status("Fetching tool list...", "info")
        QApplication.processEvents()

        self._worker = ToolFetchWorker(url)
        self._worker.listing_ready.connect(self._on_listing_ready)
        self._worker.error.connect(self._on_fetch_error)
        self._worker._mode = "list"
        self._worker.start()

    def _on_listing_ready(self, tools: list):
        self._fetched_tools = tools
        self.tool_table.setRowCount(0)

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

            # Status — hash-aware
            status = self._compute_tool_status(tool["name"])
            status_item = QTableWidgetItem(status)
            status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.tool_table.setItem(row_idx, 2, status_item)

        count = len(tools)
        if count:
            self._set_status(f"Found {count} tool(s).", "success")
        else:
            self._set_status("No tools found in this repository.", "warn")
        self.fetch_btn.setEnabled(True)
        self.install_btn.setEnabled(count > 0)

    def _on_fetch_error(self, message: str):
        self._set_status(f"Fetch failed: {message}", "error")
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
            self._set_status("No tools selected.", "warn")
            return

        self.install_btn.setEnabled(False)
        self.fetch_btn.setEnabled(False)
        self._set_status("Installing...", "info")
        QApplication.processEvents()

        self._worker = ToolFetchWorker(self.url_field.text().strip())
        self._worker.download_progress.connect(self._on_download_progress)
        self._worker.download_finished.connect(self._on_download_finished)
        self._worker.start_download(selected, self._local_tools_dir)

    def _on_download_progress(self, message: str):
        self._set_status(message, "info")
        QApplication.processEvents()

    def _on_download_finished(self, installed: list, errors: list):
        self.fetch_btn.setEnabled(True)
        self.install_btn.setEnabled(True)

        if errors:
            error_text = "\n".join(errors)
            ThemedMessageDialog.warning(
                self, "Import Errors",
                f"Some tools failed to install: {error_text}"
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
                backup_list = ", ".join(backup_files)
                backup_note = (
                    f" Your previous tool.json file(s) have been backed up: "
                    f"{backup_list}. "
                    f"You can compare the backup against the new tool.json to "
                    f"restore your custom settings. Use Tools > Edit Tool "
                    f"Configuration to edit tool.json, or Tools > Open Tools "
                    f"Folder to view the backup files."
                )
            else:
                backup_note = ""

            msg = (
                f"Successfully installed: {names}. "
                f"Please review and configure the defaults in each tool's "
                f"tool.json file before running.{backup_note}"
            )

            ThemedMessageDialog.info(self, "Tools Installed", msg)
            self.tools_imported.emit()

            self._set_status(f"Installed {len(installed)} tool(s)", "success")
            logger.info(f"Tool import: installed {installed}")
        else:
            self._set_status("No tools were installed.", "warn")

    def _compute_tool_status(self, tool_name: str) -> str:
        """Compute install status for a tool using .sha256 hash files."""
        local_tool_json = self._local_tools_dir / tool_name / "tool.json"
        if not local_tool_json.exists():
            return "Not installed"

        local_hash = read_stored_hash(local_tool_json)
        if local_hash is None:
            return "Installed (modified)"

        return "Installed"

    def _refresh_status_column(self):
        """Update the Status column after an install."""
        for row in range(self.tool_table.rowCount()):
            name_item = self.tool_table.item(row, 1)
            if name_item:
                status = self._compute_tool_status(name_item.text())
                status_item = self.tool_table.item(row, 2)
                if status_item:
                    status_item.setText(status)


class ToolJsonEditorDialog(QMainWindow):
    """A window for viewing and editing a tool's tool.json file.

    Provides a raw JSON text editor for a tool's tool.json file
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
        self.status_label.setObjectName("dialog_status")
        layout.addWidget(self.status_label)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        reload_btn = QPushButton("Reload")
        reload_btn.clicked.connect(self._load)
        btn_layout.addWidget(reload_btn)

        btn_layout.addStretch()

        save_btn = QPushButton("Save")
        save_btn.setProperty("class", "action")
        save_btn.clicked.connect(self._save)
        btn_layout.addWidget(save_btn)

        validate_btn = QPushButton("Validate JSON")
        validate_btn.setProperty("class", "secondary-action")
        validate_btn.clicked.connect(self._validate)
        btn_layout.addWidget(validate_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

        # Load initial content
        self._load()

    def _set_status(self, text: str, state: str = ""):
        """Set status label text with themed state (info, success, warn, error, or empty)."""
        self.status_label.setText(text)
        self.status_label.setProperty("status_state", state)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

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
                self._set_status("File not found — starting with empty JSON.", "warn")
        except Exception as e:
            self.text_edit.setPlainText("")
            self._set_status(f"Error loading: {e}", "error")

    def _validate(self) -> bool:
        try:
            json.loads(self.text_edit.toPlainText())
            self._set_status("✓ Valid JSON", "success")
            return True
        except json.JSONDecodeError as e:
            self._set_status(f"✗ Invalid JSON: {e}", "error")
            return False

    def _save(self):
        if not self._validate():
            ThemedMessageDialog.warning(
                self, "Invalid JSON",
                "The file contains invalid JSON and cannot be saved. "
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
            self._set_status("✓ Saved", "success")
            logger.info(f"Tool config editor: saved {self._tool_json_path}")
            self.config_saved.emit()
        except Exception as e:
            ThemedMessageDialog.critical(self, "Save Error", f"Failed to save: {e}")

    def closeEvent(self, event):
        if self._is_modified:
            if not ThemedMessageDialog.question(
                self,
                "Unsaved Changes",
                "You have unsaved changes. Close without saving?"
            ):
                event.ignore()
                return
        event.accept()


class ChatConfigEditorDialog(QMainWindow):
    """A window for editing the ``chat`` section of config.json.

    Modeled on :class:`ToolJsonEditorDialog` but operates on a single
    subsection of the global config file rather than a standalone file.
    On save the full config is re-written with the updated ``chat`` block,
    and ``config_saved`` is emitted so the caller can reload settings.
    """

    config_saved = pyqtSignal()

    def __init__(self, config_path: Path, parent=None):
        super().__init__(parent)
        self._config_path = config_path
        self.setWindowTitle("Chat Configuration")
        self.setMinimumSize(600, 450)
        self.resize(680, 550)
        self._is_modified = False

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)

        info_label = QLabel(f"Editing: {config_path}  [chat section]")
        info_label.setObjectName("secondary_label")
        layout.addWidget(info_label)

        self.text_edit = QTextEdit()
        self.text_edit.setFont(QFont("Menlo", 11))
        self.text_edit.setAcceptRichText(False)
        self.text_edit.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.text_edit)

        self.status_label = QLabel("")
        self.status_label.setObjectName("dialog_status")
        layout.addWidget(self.status_label)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        reload_btn = QPushButton("Reload")
        reload_btn.clicked.connect(self._load)
        btn_layout.addWidget(reload_btn)

        btn_layout.addStretch()

        save_btn = QPushButton("Save")
        save_btn.setProperty("class", "action")
        save_btn.clicked.connect(self._save)
        btn_layout.addWidget(save_btn)

        validate_btn = QPushButton("Validate JSON")
        validate_btn.setProperty("class", "secondary-action")
        validate_btn.clicked.connect(self._validate)
        btn_layout.addWidget(validate_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

        self._load()

    def _set_status(self, text: str, state: str = ""):
        self.status_label.setText(text)
        self.status_label.setProperty("status_state", state)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _on_text_changed(self):
        self._is_modified = True
        self.status_label.setText("")

    def _load(self):
        try:
            if self._config_path.exists():
                with open(self._config_path, "r", encoding="utf-8") as f:
                    full_config = json.load(f)
                chat_section = full_config.get("chat", {})
                self.text_edit.setPlainText(
                    json.dumps(chat_section, indent=2, ensure_ascii=False))
                self._is_modified = False
                self.status_label.setText("")
            else:
                self.text_edit.setPlainText("{}")
                self._set_status("Config file not found — starting with empty chat section.", "warn")
        except Exception as e:
            self.text_edit.setPlainText("{}")
            self._set_status(f"Error loading: {e}", "error")

    def _validate(self) -> bool:
        try:
            json.loads(self.text_edit.toPlainText())
            self._set_status("\u2713 Valid JSON", "success")
            return True
        except json.JSONDecodeError as e:
            self._set_status(f"\u2717 Invalid JSON: {e}", "error")
            return False

    def _save(self):
        if not self._validate():
            ThemedMessageDialog.warning(
                self, "Invalid JSON",
                "The chat configuration contains invalid JSON and cannot be saved. "
                "Please fix the errors and try again."
            )
            return

        try:
            chat_data = json.loads(self.text_edit.toPlainText())

            with open(self._config_path, "r", encoding="utf-8") as f:
                full_config = json.load(f)

            full_config["chat"] = chat_data
            formatted_chat = json.dumps(chat_data, indent=2, ensure_ascii=False)

            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(full_config, f, indent=2, ensure_ascii=False)

            self.text_edit.setPlainText(formatted_chat)
            self._is_modified = False
            self._set_status("\u2713 Saved", "success")
            logger.info("Chat config editor: saved chat section")
            self.config_saved.emit()
        except Exception as e:
            ThemedMessageDialog.critical(self, "Save Error", f"Failed to save: {e}")

    def closeEvent(self, event):
        if self._is_modified:
            if not ThemedMessageDialog.question(
                self,
                "Unsaved Changes",
                "You have unsaved changes. Close without saving?"
            ):
                event.ignore()
                return
        event.accept()
