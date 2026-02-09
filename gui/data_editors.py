"""
Reusable editor widgets for structured JSON data files that tools declare
in their tool.json via the "data_files" array.
"""
import json
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QStackedWidget, QTextEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)

from gui.constants import logger
from gui.dialogs import ThemedMessageDialog


class BaseDataEditor(QWidget):
    """Abstract base for structured data editors."""
    modified = pyqtSignal()

    def __init__(self, file_path: Path, parent=None):
        super().__init__(parent)
        self._file_path = file_path
        self._is_modified = False

    def load(self):
        raise NotImplementedError

    def save(self) -> bool:
        raise NotImplementedError

    def get_data(self):
        """Return the current editor state as a Python object (dict or list)."""
        raise NotImplementedError

    def load_from_data(self, data):
        """Populate the editor from a Python object without reading from disk."""
        raise NotImplementedError

    def is_modified(self) -> bool:
        return self._is_modified


class KeyArrayGridEditor(BaseDataEditor):
    """Editor for ``{ "Key": ["val1", "val2", ...] }`` JSON files.

    Renders a two-column datagrid where the first column is the key (correct
    term) and the second column shows the array values as a comma-separated
    string.  Both columns are editable inline.
    """

    def __init__(self, file_path: Path, key_label: str = "Key",
                 values_label: str = "Values (comma-separated)", parent=None):
        super().__init__(file_path, parent)
        self._key_label = key_label
        self._values_label = values_label
        self._loading = False  # guard against cellChanged during load

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Table
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([self._key_label, self._values_label])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Interactive)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.cellChanged.connect(self._on_cell_changed)
        layout.addWidget(self.table)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)

        add_btn = QPushButton("+ Add Row")
        add_btn.setProperty("class", "secondary-action")
        add_btn.clicked.connect(self._add_row)
        btn_layout.addWidget(add_btn)

        delete_btn = QPushButton("- Delete Row")
        delete_btn.setProperty("class", "danger-outline")
        delete_btn.clicked.connect(self._delete_row)
        btn_layout.addWidget(delete_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self.load()

    def get_data(self):
        data = {}
        for row in range(self.table.rowCount()):
            key_item = self.table.item(row, 0)
            vals_item = self.table.item(row, 1)
            key = key_item.text().strip() if key_item else ""
            vals_str = vals_item.text().strip() if vals_item else ""
            if not key:
                continue
            values = [v.strip() for v in vals_str.split(",") if v.strip()]
            data[key] = values
        return data

    def load_from_data(self, data):
        self._loading = True
        self.table.setRowCount(0)
        if isinstance(data, dict):
            for key in sorted(data.keys()):
                values = data[key]
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(str(key)))
                vals_str = ", ".join(str(v) for v in values) if isinstance(values, list) else str(values)
                self.table.setItem(row, 1, QTableWidgetItem(vals_str))
        self._loading = False

    def load(self):
        try:
            if self._file_path.exists():
                with open(self._file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.load_from_data(data)
            else:
                self.load_from_data({})
        except Exception as e:
            logger.error(f"DataFileEditor: failed to load {self._file_path}: {e}")
            self.load_from_data({})
        self._is_modified = False

    def save(self) -> bool:
        data = self.get_data()
        try:
            with open(self._file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
                f.write('\n')
            self._is_modified = False
            return True
        except Exception as e:
            logger.error(f"DataFileEditor: failed to save {self._file_path}: {e}")
            return False

    def _on_cell_changed(self, row: int, col: int):
        if not self._loading:
            self._is_modified = True
            self.modified.emit()

    def _add_row(self):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(""))
        self.table.setItem(row, 1, QTableWidgetItem(""))
        self.table.editItem(self.table.item(row, 0))
        self._is_modified = True
        self.modified.emit()

    def _delete_row(self):
        row = self.table.currentRow()
        if row < 0:
            return
        key_item = self.table.item(row, 0)
        key_text = key_item.text() if key_item else "(empty)"
        if ThemedMessageDialog.question(
            self, "Delete Row",
            f'Delete row "{key_text}"?'
        ):
            self.table.removeRow(row)
            self._is_modified = True
            self.modified.emit()


class KeyValueGridEditor(BaseDataEditor):
    """Editor for ``{ "key": "value" }`` JSON files.

    Renders a two-column datagrid with Key and Value, both editable inline.
    """

    def __init__(self, file_path: Path, key_label: str = "Key",
                 value_label: str = "Value", parent=None):
        super().__init__(file_path, parent)
        self._key_label = key_label
        self._value_label = value_label
        self._loading = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([self._key_label, self._value_label])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Interactive)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.cellChanged.connect(self._on_cell_changed)
        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)

        add_btn = QPushButton("+ Add Row")
        add_btn.setProperty("class", "secondary-action")
        add_btn.clicked.connect(self._add_row)
        btn_layout.addWidget(add_btn)

        delete_btn = QPushButton("- Delete Row")
        delete_btn.setProperty("class", "danger-outline")
        delete_btn.clicked.connect(self._delete_row)
        btn_layout.addWidget(delete_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self.load()

    def get_data(self):
        data = {}
        for row in range(self.table.rowCount()):
            key_item = self.table.item(row, 0)
            val_item = self.table.item(row, 1)
            key = key_item.text().strip() if key_item else ""
            val = val_item.text().strip() if val_item else ""
            if not key:
                continue
            data[key] = val
        return data

    def load_from_data(self, data):
        self._loading = True
        self.table.setRowCount(0)
        if isinstance(data, dict):
            for key in sorted(data.keys()):
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(str(key)))
                self.table.setItem(row, 1, QTableWidgetItem(str(data[key])))
        self._loading = False

    def load(self):
        try:
            if self._file_path.exists():
                with open(self._file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.load_from_data(data)
            else:
                self.load_from_data({})
        except Exception as e:
            logger.error(f"DataFileEditor: failed to load {self._file_path}: {e}")
            self.load_from_data({})
        self._is_modified = False

    def save(self) -> bool:
        data = self.get_data()
        try:
            with open(self._file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
                f.write('\n')
            self._is_modified = False
            return True
        except Exception as e:
            logger.error(f"DataFileEditor: failed to save {self._file_path}: {e}")
            return False

    def _on_cell_changed(self, row: int, col: int):
        if not self._loading:
            self._is_modified = True
            self.modified.emit()

    def _add_row(self):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(""))
        self.table.setItem(row, 1, QTableWidgetItem(""))
        self.table.editItem(self.table.item(row, 0))
        self._is_modified = True
        self.modified.emit()

    def _delete_row(self):
        row = self.table.currentRow()
        if row < 0:
            return
        key_item = self.table.item(row, 0)
        key_text = key_item.text() if key_item else "(empty)"
        if ThemedMessageDialog.question(
            self, "Delete Row",
            f'Delete row "{key_text}"?'
        ):
            self.table.removeRow(row)
            self._is_modified = True
            self.modified.emit()


class StringListEditor(BaseDataEditor):
    """Editor for ``["item1", "item2", ...]`` JSON arrays.

    Renders a single-column list with Add / Delete / Move-up / Move-down
    controls.
    """

    def __init__(self, file_path: Path, item_label: str = "Value", parent=None):
        super().__init__(file_path, parent)
        self._item_label = item_label
        self._loading = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget(0, 1)
        self.table.setHorizontalHeaderLabels([self._item_label])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.cellChanged.connect(self._on_cell_changed)
        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)

        add_btn = QPushButton("+ Add")
        add_btn.setProperty("class", "secondary-action")
        add_btn.clicked.connect(self._add_row)
        btn_layout.addWidget(add_btn)

        delete_btn = QPushButton("- Delete")
        delete_btn.setProperty("class", "danger-outline")
        delete_btn.clicked.connect(self._delete_row)
        btn_layout.addWidget(delete_btn)

        up_btn = QPushButton("Move Up")
        up_btn.clicked.connect(self._move_up)
        btn_layout.addWidget(up_btn)

        down_btn = QPushButton("Move Down")
        down_btn.clicked.connect(self._move_down)
        btn_layout.addWidget(down_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self.load()

    def get_data(self):
        data = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            val = item.text().strip() if item else ""
            if val:
                data.append(val)
        return data

    def load_from_data(self, data):
        self._loading = True
        self.table.setRowCount(0)
        if isinstance(data, list):
            for item in data:
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(str(item)))
        self._loading = False

    def load(self):
        try:
            if self._file_path.exists():
                with open(self._file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.load_from_data(data)
            else:
                self.load_from_data([])
        except Exception as e:
            logger.error(f"DataFileEditor: failed to load {self._file_path}: {e}")
            self.load_from_data([])
        self._is_modified = False

    def save(self) -> bool:
        data = self.get_data()
        try:
            with open(self._file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
                f.write('\n')
            self._is_modified = False
            return True
        except Exception as e:
            logger.error(f"DataFileEditor: failed to save {self._file_path}: {e}")
            return False

    def _on_cell_changed(self, row: int, col: int):
        if not self._loading:
            self._is_modified = True
            self.modified.emit()

    def _add_row(self):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(""))
        self.table.editItem(self.table.item(row, 0))
        self._is_modified = True
        self.modified.emit()

    def _delete_row(self):
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, 0)
        text = item.text() if item else "(empty)"
        if ThemedMessageDialog.question(
            self, "Delete Item",
            f'Delete "{text}"?'
        ):
            self.table.removeRow(row)
            self._is_modified = True
            self.modified.emit()

    def _move_up(self):
        row = self.table.currentRow()
        if row <= 0:
            return
        self._swap_rows(row, row - 1)
        self.table.setCurrentCell(row - 1, 0)

    def _move_down(self):
        row = self.table.currentRow()
        if row < 0 or row >= self.table.rowCount() - 1:
            return
        self._swap_rows(row, row + 1)
        self.table.setCurrentCell(row + 1, 0)

    def _swap_rows(self, a: int, b: int):
        self._loading = True
        item_a = self.table.item(a, 0)
        item_b = self.table.item(b, 0)
        text_a = item_a.text() if item_a else ""
        text_b = item_b.text() if item_b else ""
        self.table.item(a, 0).setText(text_b)
        self.table.item(b, 0).setText(text_a)
        self._loading = False
        self._is_modified = True
        self.modified.emit()


# Map of editor type name -> editor class
DATA_FILE_EDITORS = {
    "key_array_grid": KeyArrayGridEditor,
    "key_value_grid": KeyValueGridEditor,
    "string_list": StringListEditor,
}


class DataFileEditorDialog(QMainWindow):
    """A window for editing a tool's data file using a structured editor
    with an optional raw JSON code view for bulk editing.

    Picks the appropriate editor widget based on the ``editor`` type declared
    in the tool's ``data_files`` entry.  A toggle lets the user switch between
    the structured editor and a raw JSON text editor at any time.
    """

    data_saved = pyqtSignal()  # Emitted after a successful save

    _VIEW_EDITOR = 0
    _VIEW_CODE = 1

    def __init__(self, file_path: Path, editor_type: str, label: str,
                 tool_name: str = "", parent=None):
        super().__init__(parent)
        self._file_path = file_path
        self._current_view = self._VIEW_EDITOR
        self.setWindowTitle(f"{label} — {tool_name}" if tool_name else label)
        self.setMinimumSize(600, 400)
        self.resize(700, 500)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)

        # --- Header row: info label + view toggle ---
        header_layout = QHBoxLayout()

        info = QLabel(f"Editing: {file_path}")
        info.setObjectName("secondary_label")
        info.setWordWrap(True)
        header_layout.addWidget(info, stretch=1)

        # View toggle buttons
        self.editor_btn = QPushButton("Editor")
        self.editor_btn.setProperty("class", "primary")
        self.editor_btn.setFixedWidth(70)
        self.editor_btn.clicked.connect(lambda: self._switch_view(self._VIEW_EDITOR))
        header_layout.addWidget(self.editor_btn)

        self.code_btn = QPushButton("Code")
        self.code_btn.setFixedWidth(70)
        self.code_btn.clicked.connect(lambda: self._switch_view(self._VIEW_CODE))
        header_layout.addWidget(self.code_btn)

        layout.addLayout(header_layout)

        # --- Stacked widget for views ---
        self.view_stack = QStackedWidget()

        # Page 0: Structured editor
        editor_cls = DATA_FILE_EDITORS.get(editor_type)
        if editor_cls:
            self.editor = editor_cls(file_path)
        else:
            logger.warning(f"DataFileEditor: unknown editor type '{editor_type}', "
                           f"falling back to key_value_grid")
            self.editor = KeyValueGridEditor(file_path)
        self.editor.modified.connect(self._on_modified)
        self.view_stack.addWidget(self.editor)

        # Page 1: Raw JSON code editor
        self.code_edit = QTextEdit()
        self.code_edit.setFont(QFont("Menlo", 11))
        self.code_edit.setAcceptRichText(False)
        self.code_edit.textChanged.connect(self._on_code_changed)
        self.view_stack.addWidget(self.code_edit)

        layout.addWidget(self.view_stack, stretch=1)

        # Status
        self.status_label = QLabel("")
        self.status_label.setObjectName("dialog_status")
        layout.addWidget(self.status_label)

        # Buttons
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

        layout.addLayout(btn_layout)

        # Track modification state for code view
        self._code_modified = False
        self._code_loading = False  # guard against textChanged during programmatic set

    # -- View switching --

    def _switch_view(self, target: int):
        if target == self._current_view:
            return

        if target == self._VIEW_CODE:
            # Editor -> Code: serialize structured data to JSON text
            try:
                data = self.editor.get_data()
                text = json.dumps(data, indent=4, ensure_ascii=False)
                self._code_loading = True
                self.code_edit.setPlainText(text)
                self._code_loading = False
                self._code_modified = self.editor.is_modified()
            except Exception as e:
                ThemedMessageDialog.warning(self, "Error", f"Failed to serialize data: {e}")
                return
        else:
            # Code -> Editor: parse JSON and load into structured editor
            text = self.code_edit.toPlainText()
            try:
                data = json.loads(text)
            except json.JSONDecodeError as e:
                ThemedMessageDialog.warning(
                    self, "Invalid JSON",
                    f"Cannot switch to Editor view — the JSON is invalid: {e}. "
                    "Fix the JSON errors or use Reload to discard changes."
                )
                return

            was_modified = self._code_modified or self.editor.is_modified()
            self.editor.load_from_data(data)
            self.editor._is_modified = was_modified

        self._current_view = target
        self.view_stack.setCurrentIndex(target)
        self._update_toggle_style()

    def _update_toggle_style(self):
        """Update button styling to reflect the active view."""
        if self._current_view == self._VIEW_EDITOR:
            self.editor_btn.setProperty("class", "primary")
            self.code_btn.setProperty("class", "")
        else:
            self.editor_btn.setProperty("class", "")
            self.code_btn.setProperty("class", "primary")
        # Force style refresh
        self.editor_btn.style().unpolish(self.editor_btn)
        self.editor_btn.style().polish(self.editor_btn)
        self.code_btn.style().unpolish(self.code_btn)
        self.code_btn.style().polish(self.code_btn)

    # -- Status helper --
    def _set_status(self, text: str, state: str = ""):
        """Set status label text with themed state (info, success, warn, error, or empty)."""
        self.status_label.setText(text)
        self.status_label.setProperty("status_state", state)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    # -- Modification tracking --

    def _on_modified(self):
        self.status_label.setText("")

    def _on_code_changed(self):
        if not self._code_loading:
            self._code_modified = True
            self.status_label.setText("")

    def _is_any_modified(self) -> bool:
        if self._current_view == self._VIEW_EDITOR:
            return self.editor.is_modified()
        return self._code_modified

    # -- Reload --

    def _reload(self):
        if self._is_any_modified():
            if not ThemedMessageDialog.question(
                self, "Unsaved Changes",
                "You have unsaved changes. Reload and discard them?"
            ):
                return

        if self._current_view == self._VIEW_EDITOR:
            self.editor.load()
        else:
            # Reload from disk into code view
            try:
                if self._file_path.exists():
                    with open(self._file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    # Pretty-print if it's valid JSON
                    try:
                        data = json.loads(content)
                        content = json.dumps(data, indent=4, ensure_ascii=False)
                    except (json.JSONDecodeError, ValueError):
                        pass
                    self._code_loading = True
                    self.code_edit.setPlainText(content)
                    self._code_loading = False
                else:
                    self._code_loading = True
                    self.code_edit.setPlainText("{}")
                    self._code_loading = False
            except Exception as e:
                self._set_status(f"Error loading: {e}", "error")
                return
            self._code_modified = False

        self._set_status("Reloaded from disk.", "info")

    # -- Save --

    def _save(self):
        if self._current_view == self._VIEW_EDITOR:
            if self.editor.save():
                self._set_status("✓ Saved", "success")
                logger.info(f"DataFileEditor: saved {self._file_path}")
                self.data_saved.emit()
            else:
                self._set_status("✗ Save failed — check the log for details", "error")
        else:
            # Save from code view — validate, format, and write
            text = self.code_edit.toPlainText()
            try:
                data = json.loads(text)
            except json.JSONDecodeError as e:
                self._set_status(f"✗ Invalid JSON: {e}", "error")
                ThemedMessageDialog.warning(
                    self, "Invalid JSON",
                    f"Cannot save — the JSON is invalid: {e}"
                )
                return

            try:
                formatted = json.dumps(data, indent=4, ensure_ascii=False)
                with open(self._file_path, 'w', encoding='utf-8') as f:
                    f.write(formatted)
                    f.write('\n')
                # Update the code edit with formatted version
                self._code_loading = True
                self.code_edit.setPlainText(formatted)
                self._code_loading = False
                self._code_modified = False
                # Also reload the structured editor so it stays in sync
                self.editor.load()
                self._set_status("✓ Saved", "success")
                logger.info(f"DataFileEditor: saved {self._file_path} (from code view)")
                self.data_saved.emit()
            except Exception as e:
                self._set_status(f"✗ Save failed: {e}", "error")

    def closeEvent(self, event):
        if self._is_any_modified():
            if not ThemedMessageDialog.question(
                self, "Unsaved Changes",
                "You have unsaved changes. Close without saving?"
            ):
                event.ignore()
                return
        event.accept()
