"""
Form-based rule editor for rule.json files.

Provides a user-friendly GUI so users never need to edit raw JSON.
Each section of the rule definition has dedicated widgets.
"""
import json
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QLineEdit, QSpinBox, QComboBox, QCheckBox,
    QTextEdit, QTabWidget, QGroupBox, QScrollArea,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QFileDialog, QSizePolicy, QFrame,
)

from gui.constants import logger
from gui.dialogs import ThemedMessageDialog


# Common AX roles offered in drop-downs for convenience
_COMMON_AX_ROLES = [
    "AXWindow", "AXGroup", "AXTable", "AXList", "AXCell",
    "AXRow", "AXColumn", "AXScrollArea", "AXStaticText",
    "AXTextArea", "AXButton", "AXImage", "AXWebArea",
    "AXOutline", "AXSheet",
]

# Common AX attribute names used in serialization_text_element_roles
_COMMON_AX_ATTRS = [
    "AXValue", "AXDescription", "AXTitle",
]


class _CommandPathsEditor(QWidget):
    """Editable list of command paths with Add / Remove / Browse buttons."""

    modified = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget(0, 1)
        self.table.setHorizontalHeaderLabels(["Executable Path"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.cellChanged.connect(lambda: self.modified.emit())
        layout.addWidget(self.table)

        btn = QHBoxLayout()
        btn.setSpacing(6)

        add_btn = QPushButton("+ Add")
        add_btn.setProperty("class", "secondary-action")
        add_btn.clicked.connect(self._add_row)
        btn.addWidget(add_btn)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse)
        btn.addWidget(browse_btn)

        remove_btn = QPushButton("- Remove")
        remove_btn.setProperty("class", "danger-outline")
        remove_btn.clicked.connect(self._remove_row)
        btn.addWidget(remove_btn)

        btn.addStretch()
        layout.addLayout(btn)

    def set_paths(self, paths: list):
        self.table.setRowCount(0)
        for p in paths:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(p)))

    def get_paths(self) -> list:
        paths = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            val = item.text().strip() if item else ""
            if val:
                paths.append(val)
        return paths

    def _add_row(self):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(""))
        self.table.editItem(self.table.item(row, 0))
        self.modified.emit()

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Executable", "/Applications",
            "All Files (*)"
        )
        if path:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(path))
            self.modified.emit()

    def _remove_row(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)
            self.modified.emit()


class _RolesToSkipEditor(QWidget):
    """Editable list of AX roles to skip during traversal."""

    modified = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget(0, 1)
        self.table.setHorizontalHeaderLabels(["AX Role"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.cellChanged.connect(lambda: self.modified.emit())
        layout.addWidget(self.table)

        btn = QHBoxLayout()
        btn.setSpacing(6)

        add_btn = QPushButton("+ Add")
        add_btn.setProperty("class", "secondary-action")
        add_btn.clicked.connect(self._add_row)
        btn.addWidget(add_btn)

        remove_btn = QPushButton("- Remove")
        remove_btn.setProperty("class", "danger-outline")
        remove_btn.clicked.connect(self._remove_row)
        btn.addWidget(remove_btn)

        btn.addStretch()
        layout.addLayout(btn)

    def set_roles(self, roles: list):
        self.table.setRowCount(0)
        for r in roles:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(r)))

    def get_roles(self) -> list:
        roles = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            val = item.text().strip() if item else ""
            if val:
                roles.append(val)
        return roles

    def _add_row(self):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(""))
        self.table.editItem(self.table.item(row, 0))
        self.modified.emit()

    def _remove_row(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)
            self.modified.emit()


class _TextElementRolesEditor(QWidget):
    """Key-value grid: AX Role -> AX Attribute for serialization."""

    modified = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["AX Role", "Attribute"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Interactive
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.cellChanged.connect(lambda: self.modified.emit())
        layout.addWidget(self.table)

        btn = QHBoxLayout()
        btn.setSpacing(6)

        add_btn = QPushButton("+ Add")
        add_btn.setProperty("class", "secondary-action")
        add_btn.clicked.connect(self._add_row)
        btn.addWidget(add_btn)

        remove_btn = QPushButton("- Remove")
        remove_btn.setProperty("class", "danger-outline")
        remove_btn.clicked.connect(self._remove_row)
        btn.addWidget(remove_btn)

        btn.addStretch()
        layout.addLayout(btn)

    def set_roles(self, mapping: dict):
        self.table.setRowCount(0)
        for role, attr in mapping.items():
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(role)))
            self.table.setItem(row, 1, QTableWidgetItem(str(attr)))

    def get_roles(self) -> dict:
        result = {}
        for row in range(self.table.rowCount()):
            role_item = self.table.item(row, 0)
            attr_item = self.table.item(row, 1)
            role = role_item.text().strip() if role_item else ""
            attr = attr_item.text().strip() if attr_item else ""
            if role:
                result[role] = attr
        return result

    def _add_row(self):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(""))
        self.table.setItem(row, 1, QTableWidgetItem("AXValue"))
        self.table.editItem(self.table.item(row, 0))
        self.modified.emit()

    def _remove_row(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)
            self.modified.emit()


class _StepEditor(QGroupBox):
    """Editor widget for a single search step within a path."""

    modified = pyqtSignal()

    def __init__(self, step_data: dict = None, step_index: int = 0, parent=None):
        super().__init__(f"Step {step_index + 1}", parent)
        self._step_index = step_index
        form = QFormLayout(self)
        form.setContentsMargins(8, 12, 8, 8)

        # Role
        self.role_combo = QComboBox()
        self.role_combo.setEditable(True)
        self.role_combo.addItems(_COMMON_AX_ROLES)
        self.role_combo.currentTextChanged.connect(lambda: self.modified.emit())
        form.addRow("Role:", self.role_combo)

        # Match type
        self.match_type_combo = QComboBox()
        self.match_type_combo.addItems([
            "title_contains",
            "title_matches_one_of",
            "description_contains",
            "title (exact)",
            "description (exact)",
        ])
        self.match_type_combo.currentTextChanged.connect(lambda: self.modified.emit())
        form.addRow("Match Type:", self.match_type_combo)

        # Match value
        self.match_value = QLineEdit()
        self.match_value.setPlaceholderText("Match value (comma-separated for 'matches one of')")
        self.match_value.textChanged.connect(lambda: self.modified.emit())
        form.addRow("Match Value:", self.match_value)

        # Search depth
        self.levels_deep = QSpinBox()
        self.levels_deep.setRange(1, 200)
        self.levels_deep.setValue(1)
        self.levels_deep.valueChanged.connect(lambda: self.modified.emit())
        form.addRow("Search Depth:", self.levels_deep)

        # Index (optional)
        self.index_spin = QSpinBox()
        self.index_spin.setRange(-1, 100)
        self.index_spin.setValue(-1)
        self.index_spin.setSpecialValueText("(none)")
        self.index_spin.valueChanged.connect(lambda: self.modified.emit())
        form.addRow("Index (optional):", self.index_spin)

        if step_data:
            self._load(step_data)

    def _load(self, data: dict):
        role = data.get("role", "")
        idx = self.role_combo.findText(role)
        if idx >= 0:
            self.role_combo.setCurrentIndex(idx)
        else:
            self.role_combo.setCurrentText(role)

        # Determine match type/value
        if "title_contains" in data:
            self.match_type_combo.setCurrentText("title_contains")
            self.match_value.setText(str(data["title_contains"]))
        elif "title_matches_one_of" in data:
            self.match_type_combo.setCurrentText("title_matches_one_of")
            vals = data["title_matches_one_of"]
            self.match_value.setText(", ".join(vals) if isinstance(vals, list) else str(vals))
        elif "description_contains" in data:
            self.match_type_combo.setCurrentText("description_contains")
            self.match_value.setText(str(data["description_contains"]))
        elif "title" in data:
            self.match_type_combo.setCurrentText("title (exact)")
            self.match_value.setText(str(data["title"]))
        elif "description" in data:
            self.match_type_combo.setCurrentText("description (exact)")
            self.match_value.setText(str(data["description"]))

        scope = data.get("search_scope", {})
        self.levels_deep.setValue(scope.get("levels_deep", 1))

        idx_val = data.get("index")
        self.index_spin.setValue(idx_val if idx_val is not None else -1)

    def to_dict(self) -> dict:
        d = {"role": self.role_combo.currentText()}
        match_type = self.match_type_combo.currentText()
        val = self.match_value.text().strip()

        if match_type == "title_contains" and val:
            d["title_contains"] = val
        elif match_type == "title_matches_one_of" and val:
            d["title_matches_one_of"] = [v.strip() for v in val.split(",") if v.strip()]
        elif match_type == "description_contains" and val:
            d["description_contains"] = val
        elif match_type == "title (exact)" and val:
            d["title"] = val
        elif match_type == "description (exact)" and val:
            d["description"] = val

        d["search_scope"] = {"levels_deep": self.levels_deep.value()}

        if self.index_spin.value() >= 0:
            d["index"] = self.index_spin.value()

        return d


class _PathEditor(QGroupBox):
    """Editor for a single search path (a named sequence of steps)."""

    modified = pyqtSignal()

    def __init__(self, path_data: dict = None, path_index: int = 0, parent=None):
        super().__init__(parent)
        self._path_index = path_index
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 12, 8, 8)

        # Path name
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Path Name:"))
        self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(self._update_title)
        self.name_edit.textChanged.connect(lambda: self.modified.emit())
        name_layout.addWidget(self.name_edit)
        layout.addLayout(name_layout)

        # Steps container
        self._steps_layout = QVBoxLayout()
        layout.addLayout(self._steps_layout)
        self._step_editors: List[_StepEditor] = []

        # Step buttons
        step_btn = QHBoxLayout()
        step_btn.setSpacing(6)

        add_step_btn = QPushButton("+ Add Step")
        add_step_btn.setProperty("class", "secondary-action")
        add_step_btn.clicked.connect(self._add_step)
        step_btn.addWidget(add_step_btn)

        remove_step_btn = QPushButton("- Remove Last Step")
        remove_step_btn.setProperty("class", "danger-outline")
        remove_step_btn.clicked.connect(self._remove_last_step)
        step_btn.addWidget(remove_step_btn)

        step_btn.addStretch()
        layout.addLayout(step_btn)

        if path_data:
            self._load(path_data)
        else:
            self.name_edit.setText(f"Path {path_index + 1}")

        self._update_title()

    def _update_title(self):
        name = self.name_edit.text().strip() or f"Path {self._path_index + 1}"
        self.setTitle(f"Search Path: {name}")

    def _load(self, data: dict):
        self.name_edit.setText(data.get("path_name", ""))
        for i, step in enumerate(data.get("steps", [])):
            self._add_step_widget(step, i)

    def _add_step(self):
        self._add_step_widget(None, len(self._step_editors))
        self.modified.emit()

    def _add_step_widget(self, step_data: Optional[dict], index: int):
        editor = _StepEditor(step_data, index, self)
        editor.modified.connect(self.modified.emit)
        self._step_editors.append(editor)
        self._steps_layout.addWidget(editor)

    def _remove_last_step(self):
        if self._step_editors:
            editor = self._step_editors.pop()
            self._steps_layout.removeWidget(editor)
            editor.deleteLater()
            self.modified.emit()

    def to_dict(self) -> dict:
        return {
            "path_name": self.name_edit.text().strip(),
            "steps": [s.to_dict() for s in self._step_editors],
        }


class RuleEditorDialog(QMainWindow):
    """Form-based editor for rule.json files.

    Provides tabs for General Settings, Serialization Settings, and
    Search Rules (the transcript-finding path/step builder).
    """

    rule_saved = pyqtSignal()

    def __init__(self, rule_json_path: Path, parent=None):
        super().__init__(parent)
        self._rule_json_path = rule_json_path
        self._is_modified = False
        self.setWindowTitle(f"Rule Editor — {rule_json_path.parent.name}")
        self.setMinimumSize(700, 600)
        self.resize(780, 680)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 12, 12, 12)

        # Info label
        info = QLabel(f"Editing: {rule_json_path}")
        info.setObjectName("secondary_label")
        info.setWordWrap(True)
        main_layout.addWidget(info)

        # Tab widget
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs, stretch=1)

        # --- Tab 1: General Settings ---
        general_scroll = QScrollArea()
        general_scroll.setWidgetResizable(True)
        general_widget = QWidget()
        general_layout = QFormLayout(general_widget)
        general_layout.setContentsMargins(12, 12, 12, 12)
        general_layout.setSpacing(10)

        self.display_name_edit = QLineEdit()
        self.display_name_edit.textChanged.connect(self._mark_modified)
        general_layout.addRow("Display Name:", self.display_name_edit)

        self.command_paths_editor = _CommandPathsEditor()
        self.command_paths_editor.modified.connect(self._mark_modified)
        general_layout.addRow("Command Paths:", self.command_paths_editor)

        self.monitor_interval_spin = QSpinBox()
        self.monitor_interval_spin.setRange(5, 300)
        self.monitor_interval_spin.setSuffix(" seconds")
        self.monitor_interval_spin.valueChanged.connect(self._mark_modified)
        general_layout.addRow("Monitor Interval:", self.monitor_interval_spin)

        self.traversal_mode_combo = QComboBox()
        self.traversal_mode_combo.addItems(["bfs", "dfs"])
        self.traversal_mode_combo.currentTextChanged.connect(self._mark_modified)
        general_layout.addRow("Traversal Mode:", self.traversal_mode_combo)

        self.incremental_export_cb = QCheckBox("Enable incremental export")
        self.incremental_export_cb.stateChanged.connect(self._mark_modified)
        general_layout.addRow("Incremental Export:", self.incremental_export_cb)

        self.exclude_pattern_edit = QLineEdit()
        self.exclude_pattern_edit.setPlaceholderText("Optional regex pattern to exclude from transcript")
        self.exclude_pattern_edit.textChanged.connect(self._mark_modified)
        general_layout.addRow("Exclude Pattern:", self.exclude_pattern_edit)

        self.roles_to_skip_editor = _RolesToSkipEditor()
        self.roles_to_skip_editor.modified.connect(self._mark_modified)
        general_layout.addRow("Roles to Skip:", self.roles_to_skip_editor)

        general_scroll.setWidget(general_widget)
        self.tabs.addTab(general_scroll, "General")

        # --- Tab 2: Serialization ---
        serial_scroll = QScrollArea()
        serial_scroll.setWidgetResizable(True)
        serial_widget = QWidget()
        serial_layout = QFormLayout(serial_widget)
        serial_layout.setContentsMargins(12, 12, 12, 12)
        serial_layout.setSpacing(10)

        self.export_depth_spin = QSpinBox()
        self.export_depth_spin.setRange(1, 100)
        self.export_depth_spin.valueChanged.connect(self._mark_modified)
        serial_layout.addRow("Export Depth:", self.export_depth_spin)

        self.save_json_cb = QCheckBox("Save accessibility tree as JSON (debug)")
        self.save_json_cb.stateChanged.connect(self._mark_modified)
        serial_layout.addRow("Save JSON:", self.save_json_cb)

        self.text_roles_editor = _TextElementRolesEditor()
        self.text_roles_editor.modified.connect(self._mark_modified)
        serial_layout.addRow("Text Element Roles:", self.text_roles_editor)

        serial_scroll.setWidget(serial_widget)
        self.tabs.addTab(serial_scroll, "Serialization")

        # --- Tab 3: Search Rules ---
        search_scroll = QScrollArea()
        search_scroll.setWidgetResizable(True)
        search_widget = QWidget()
        self._search_layout = QVBoxLayout(search_widget)
        self._search_layout.setContentsMargins(12, 12, 12, 12)
        self._search_layout.setSpacing(10)

        search_info = QLabel(
            "Define one or more search paths. Each path is tried in order "
            "until the transcript element is found. Within a path, steps "
            "are evaluated sequentially — each step narrows the search "
            "from the results of the previous step."
        )
        search_info.setWordWrap(True)
        search_info.setObjectName("secondary_label")
        self._search_layout.addWidget(search_info)

        self._path_editors: List[_PathEditor] = []
        self._paths_container = QVBoxLayout()
        self._search_layout.addLayout(self._paths_container)

        path_btns = QHBoxLayout()
        path_btns.setSpacing(6)

        add_path_btn = QPushButton("+ Add Search Path")
        add_path_btn.setProperty("class", "secondary-action")
        add_path_btn.clicked.connect(self._add_path)
        path_btns.addWidget(add_path_btn)

        remove_path_btn = QPushButton("- Remove Last Path")
        remove_path_btn.setProperty("class", "danger-outline")
        remove_path_btn.clicked.connect(self._remove_last_path)
        path_btns.addWidget(remove_path_btn)

        path_btns.addStretch()
        self._search_layout.addLayout(path_btns)

        self._search_layout.addStretch()

        search_scroll.setWidget(search_widget)
        self.tabs.addTab(search_scroll, "Search Rules")

        # --- Status + Buttons ---
        self.status_label = QLabel("")
        self.status_label.setObjectName("dialog_status")
        main_layout.addWidget(self.status_label)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        reload_btn = QPushButton("Reload")
        reload_btn.clicked.connect(self._reload)
        btn_layout.addWidget(reload_btn)

        btn_layout.addStretch()

        save_btn = QPushButton("Save")
        save_btn.setProperty("class", "action")
        save_btn.clicked.connect(self._save)
        btn_layout.addWidget(save_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)

        main_layout.addLayout(btn_layout)

        # Load initial data
        self._load()

    def _set_status(self, text: str, state: str = ""):
        """Set status label text with themed state (info, success, warn, error, or empty)."""
        self.status_label.setText(text)
        self.status_label.setProperty("status_state", state)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _mark_modified(self):
        self._is_modified = True
        self.status_label.setText("")

    def _load(self):
        """Load rule.json into the form."""
        try:
            if not self._rule_json_path.exists():
                self._set_status("Rule file not found.", "warn")
                return

            with open(self._rule_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # General tab
            self.display_name_edit.setText(data.get("display_name", ""))
            self.command_paths_editor.set_paths(data.get("command_paths", []))
            self.monitor_interval_spin.setValue(data.get("monitor_interval_seconds", 30))

            mode = data.get("traversal_mode", "bfs")
            idx = self.traversal_mode_combo.findText(mode)
            if idx >= 0:
                self.traversal_mode_combo.setCurrentIndex(idx)

            self.incremental_export_cb.setChecked(data.get("incremental_export", False))
            self.exclude_pattern_edit.setText(data.get("exclude_pattern", ""))
            self.roles_to_skip_editor.set_roles(data.get("traversal_roles_to_skip", []))

            # Serialization tab
            self.export_depth_spin.setValue(data.get("serialization_export_depth", 10))
            self.save_json_cb.setChecked(data.get("serialization_save_json", False))
            self.text_roles_editor.set_roles(data.get("serialization_text_element_roles", {}))

            # Search rules tab — clear existing and rebuild
            for editor in self._path_editors:
                self._paths_container.removeWidget(editor)
                editor.deleteLater()
            self._path_editors.clear()

            for i, path_data in enumerate(data.get("rules_to_find_transcript_table", [])):
                self._add_path_widget(path_data, i)

            self._is_modified = False
            self.status_label.setText("")

        except json.JSONDecodeError as e:
            self._set_status(f"Invalid JSON: {e}", "error")
        except Exception as e:
            self._set_status(f"Error loading rule: {e}", "error")
            logger.error(f"RuleEditor: failed to load {self._rule_json_path}: {e}")

    def _reload(self):
        if self._is_modified:
            if not ThemedMessageDialog.question(
                self, "Unsaved Changes",
                "You have unsaved changes. Reload and discard them?"
            ):
                return
        self._load()
        self._set_status("Reloaded from disk.", "info")

    def _save(self):
        """Build the rule dict from form widgets and write to rule.json."""
        data = {}

        # General
        data["display_name"] = self.display_name_edit.text().strip()
        if not data["display_name"]:
            ThemedMessageDialog.warning(self, "Validation Error", "Display Name is required.")
            return

        data["command_paths"] = self.command_paths_editor.get_paths()
        data["monitor_interval_seconds"] = self.monitor_interval_spin.value()
        data["traversal_mode"] = self.traversal_mode_combo.currentText()
        data["incremental_export"] = self.incremental_export_cb.isChecked()

        exclude = self.exclude_pattern_edit.text().strip()
        if exclude:
            data["exclude_pattern"] = exclude

        data["traversal_roles_to_skip"] = self.roles_to_skip_editor.get_roles()

        # Serialization
        data["serialization_export_depth"] = self.export_depth_spin.value()
        data["serialization_save_json"] = self.save_json_cb.isChecked()
        data["serialization_text_element_roles"] = self.text_roles_editor.get_roles()

        # Search rules
        paths = [editor.to_dict() for editor in self._path_editors]
        data["rules_to_find_transcript_table"] = paths

        try:
            formatted = json.dumps(data, indent=2)
            with open(self._rule_json_path, 'w', encoding='utf-8') as f:
                f.write(formatted)

            self._is_modified = False
            self._set_status("✓ Saved", "success")
            logger.info(f"RuleEditor: saved {self._rule_json_path}")
            self.rule_saved.emit()

        except Exception as e:
            ThemedMessageDialog.critical(self, "Save Error", f"Failed to save rule: {e}")

    # -- Path management --
    def _add_path(self):
        self._add_path_widget(None, len(self._path_editors))
        self._mark_modified()

    def _add_path_widget(self, path_data: Optional[dict], index: int):
        editor = _PathEditor(path_data, index, self)
        editor.modified.connect(self._mark_modified)
        self._path_editors.append(editor)
        self._paths_container.addWidget(editor)

    def _remove_last_path(self):
        if self._path_editors:
            editor = self._path_editors.pop()
            self._paths_container.removeWidget(editor)
            editor.deleteLater()
            self._mark_modified()

    def closeEvent(self, event):
        if self._is_modified:
            if not ThemedMessageDialog.question(
                self, "Unsaved Changes",
                "You have unsaved changes. Close without saving?"
            ):
                event.ignore()
                return
        event.accept()
