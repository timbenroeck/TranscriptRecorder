"""
Accessibility Inspector — interactive tool for exploring the macOS
accessibility tree of running applications.

Helps build ``transcript_search_paths`` by letting the user:
  1. Browse running GUI apps with searchable window titles.
  2. Serialize and filter the accessibility tree for a chosen process.
  3. Select a node and auto-generate a minimal search rule.
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

import psutil

# Quartz/CoreGraphics — one fast system call to list all windows + owner PIDs
try:
    from Quartz import (
        CGWindowListCopyWindowInfo,
        kCGWindowListOptionOnScreenOnly,
        kCGWindowListExcludeDesktopElements,
        kCGNullWindowID,
    )
    _HAS_QUARTZ = True
except ImportError:
    _HAS_QUARTZ = False
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QTextEdit, QSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QStackedWidget, QTreeWidget, QTreeWidgetItem, QSplitter,
)

from gui.constants import logger

# macOS accessibility bindings — same imports as transcript_recorder.py
try:
    from ApplicationServices import (
        AXUIElementCreateApplication,
        AXUIElementCopyAttributeValue,
        kAXChildrenAttribute,
        kAXTitleAttribute,
        kAXValueAttribute,
        kAXRoleAttribute,
        kAXSubroleAttribute,
        kAXDescriptionAttribute,
        AXIsProcessTrusted,
    )
    kAXErrorSuccess = 0
    _HAS_AX = True
except ImportError:
    _HAS_AX = False
    AXUIElementCreateApplication = None  # type: ignore
    AXUIElementCopyAttributeValue = None  # type: ignore
    kAXChildrenAttribute = ""  # type: ignore
    kAXTitleAttribute = ""  # type: ignore
    kAXValueAttribute = ""  # type: ignore
    kAXRoleAttribute = ""  # type: ignore
    kAXSubroleAttribute = ""  # type: ignore
    kAXDescriptionAttribute = ""  # type: ignore
    AXIsProcessTrusted = lambda: False  # type: ignore
    kAXErrorSuccess = 1  # type: ignore

# AXIdentifier is not exported as a constant by pyobjc — use the raw string
_kAXIdentifierAttribute = "AXIdentifier"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ax_get(element: Any, attr: str) -> Any:
    """Synchronously read a single AX attribute. Returns None on failure."""
    if element is None or AXUIElementCopyAttributeValue is None:
        return None
    try:
        err, value = AXUIElementCopyAttributeValue(element, attr, None)
        return value if err == kAXErrorSuccess else None
    except Exception:
        return None


def _get_window_map() -> Dict[int, List[str]]:
    """Return a dict of {pid: [window_title, ...]} using CoreGraphics."""
    result: Dict[int, List[str]] = defaultdict(list)
    if not _HAS_QUARTZ:
        return result
    try:
        options = kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements
        window_list = CGWindowListCopyWindowInfo(options, kCGNullWindowID)
        if not window_list:
            return result
        for win in window_list:
            pid = win.get("kCGWindowOwnerPID", 0)
            name = win.get("kCGWindowName", "") or ""
            if pid and name.strip():
                result[pid].append(name.strip())
            elif pid:
                result[pid]  # ensure key exists via defaultdict
    except Exception:
        pass
    return dict(result)


def _exe_for_pid(pid: int) -> str:
    """Return the executable path for *pid* via psutil, or empty string."""
    try:
        proc = psutil.Process(pid)
        return proc.exe() or ""
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Rule generation
# ---------------------------------------------------------------------------

def _node_label(node: dict) -> str:
    """Build a short human-readable label for a tree node."""
    role = node.get("role", "")
    identifier = node.get("identifier", "")
    title = node.get("title", "")
    desc = node.get("description", "")
    value = node.get("value", "")

    # Show identifier (class name) in brackets like Apple's inspector
    bracket = f"  [{identifier}]" if identifier else ""

    ident = title or desc or ""
    if ident:
        if len(ident) > 40:
            ident = ident[:37] + "\u2026"
        return f'{role}  "{ident}"{bracket}'
    if value:
        short = value if len(value) <= 30 else value[:27] + "\u2026"
        return f'{role}  val="{short}"{bracket}'
    return f"{role}{bracket}" if (role or identifier) else "(unknown)"


def _has_identifier(node: dict) -> bool:
    """True if the node has a title or description we can match on."""
    return bool(node.get("title") or node.get("description"))


def _ancestor_path(tree: dict, target_idx: int) -> Optional[List[dict]]:
    """Walk the tree to find the node with ``_idx_`` == *target_idx* and
    return the list of ancestors from root to that node inclusive.

    Uses an iterative DFS with an explicit stack to avoid deep recursion.
    """
    # Stack entries: (node, path_so_far)
    stack: List[Tuple[dict, List[dict]]] = [(tree, [])]
    while stack:
        node, path = stack.pop()
        current_path = path + [node]
        if node.get("_idx_") == target_idx:
            return current_path
        for child in reversed(node.get("children", [])):
            stack.append((child, current_path))
    return None


def _generate_rule_steps(ancestor_chain: List[dict]) -> List[dict]:
    """Given a root-to-target ancestor chain, produce the simplest rule steps.

    Strategy:
      - Walk from the root toward the target.
      - Whenever we find a node with an identifying attribute (title or
        description), emit a rule step for it.
      - The ``levels_deep`` for each step is the depth gap since the
        previous emitted step (so the engine knows how far to search).
      - Always emit the final target node.
    """
    if not ancestor_chain:
        return []

    steps: List[dict] = []
    last_emitted_depth = -1

    for i, node in enumerate(ancestor_chain):
        depth = node.get("_depth_", i)
        role = node.get("role", "")
        title = node.get("title", "")
        desc = node.get("description", "")
        is_target = (i == len(ancestor_chain) - 1)

        if not (is_target or _has_identifier(node)):
            continue

        gap = depth - last_emitted_depth
        step: Dict[str, Any] = {"role": role}

        if desc:
            step["description_contains"] = desc
        elif title:
            step["title_contains"] = title

        step["search_scope"] = {"levels_deep": max(gap, 1)}
        steps.append(step)
        last_emitted_depth = depth

    return steps


# ---------------------------------------------------------------------------
# Background workers
# ---------------------------------------------------------------------------

class _ProcessListWorker(QThread):
    """Enumerate running GUI applications using CoreGraphics window list."""

    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def run(self):
        try:
            window_map = _get_window_map()

            owner_names: Dict[int, str] = {}
            if _HAS_QUARTZ:
                try:
                    options = (kCGWindowListOptionOnScreenOnly
                               | kCGWindowListExcludeDesktopElements)
                    window_list = CGWindowListCopyWindowInfo(
                        options, kCGNullWindowID
                    )
                    if window_list:
                        for win in window_list:
                            pid = win.get("kCGWindowOwnerPID", 0)
                            owner = win.get("kCGWindowOwnerName", "") or ""
                            if pid and owner.strip() and pid not in owner_names:
                                owner_names[pid] = owner.strip()
                except Exception:
                    pass

            results: List[Tuple[int, str, str, str]] = []

            for pid, titles in window_map.items():
                if pid <= 1:
                    continue
                owner = owner_names.get(pid, "")
                titles_str = " | ".join(dict.fromkeys(titles))
                exe = _exe_for_pid(pid)
                display_name = owner or os.path.basename(exe) or str(pid)
                results.append((pid, display_name, titles_str, exe))

            results.sort(key=lambda r: r[1].lower())
            self.finished.emit(results)
        except Exception as exc:
            self.error.emit(str(exc))


class _AXTreeWorker(QThread):
    """Serialize the accessibility tree for a given PID."""

    finished = pyqtSignal(dict, int)  # (tree_dict, node_count)
    error = pyqtSignal(str)

    def __init__(
        self,
        pid: int,
        max_depth: int = 25,
        roles_to_skip: Optional[List[str]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.pid = pid
        self.max_depth = max_depth
        self.roles_to_skip = roles_to_skip or []
        self._node_count = 0

    def run(self):
        try:
            if not _HAS_AX:
                self.error.emit("ApplicationServices not available.")
                return

            app_ref = AXUIElementCreateApplication(self.pid)
            if app_ref is None:
                self.error.emit(f"Cannot create AX element for PID {self.pid}.")
                return

            # Bump recursion limit for very deep trees
            old_limit = sys.getrecursionlimit()
            sys.setrecursionlimit(max(old_limit, 2000))

            self._node_count = 0
            tree = self._serialize(app_ref, 0)
            self.finished.emit(tree or {}, self._node_count)

            sys.setrecursionlimit(old_limit)
        except Exception as exc:
            self.error.emit(str(exc))

    def _serialize(self, element: Any, depth: int) -> Optional[Dict[str, Any]]:
        if element is None:
            return None
        if depth > self.max_depth:
            return {"_depth_": depth, "_idx_": -1,
                    "_info_": f"<Max depth {self.max_depth} reached>"}

        data: Dict[str, Any] = {"_depth_": depth}
        attrs = {
            "role": kAXRoleAttribute,
            "subrole": kAXSubroleAttribute,
            "title": kAXTitleAttribute,
            "value": kAXValueAttribute,
            "description": kAXDescriptionAttribute,
            "identifier": _kAXIdentifierAttribute,
        }

        current_role: Optional[str] = None
        for key, attr_const in attrs.items():
            val = _ax_get(element, attr_const)
            if val is not None:
                if key == "role":
                    current_role = str(val)
                if isinstance(val, str) and val.strip():
                    data[key] = val
                elif isinstance(val, (int, float, bool)):
                    data[key] = val

        # Assign a visit-order index so we can locate this node later
        data["_idx_"] = self._node_count
        self._node_count += 1

        # For skipped roles: keep the node itself but don't recurse children.
        skip_children = (
            current_role is not None
            and current_role in self.roles_to_skip
            and depth > 0
        )

        if not skip_children and depth < self.max_depth:
            children = _ax_get(element, kAXChildrenAttribute)
            if children:
                child_list: List[Dict[str, Any]] = []
                for child in children:
                    child_data = self._serialize(child, depth + 1)
                    if child_data:
                        child_list.append(child_data)
                if child_list:
                    data["children"] = child_list

        # >2 because _depth_ + _idx_ are always present
        return data if len(data) > 2 else None


# ---------------------------------------------------------------------------
# Main inspector window
# ---------------------------------------------------------------------------

class AccessibilityInspectorDialog(QMainWindow):
    """Two-panel accessibility inspector for building transcript search paths."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Accessibility Inspector")
        self.setMinimumSize(880, 600)
        self.resize(1020, 720)

        self._process_worker: Optional[_ProcessListWorker] = None
        self._tree_worker: Optional[_AXTreeWorker] = None
        self._current_pid: Optional[int] = None
        self._current_app_name: str = ""
        self._current_exe: str = ""
        self._current_tree: Optional[dict] = None
        self._current_node_count: int = 0
        self._all_processes: List[Tuple[int, str, str, str]] = []
        self._generated_rule: Optional[dict] = None
        self._populating_tree: bool = False  # guard against signals during build

        # Central widget with stacked panels
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._stack = QStackedWidget()
        outer.addWidget(self._stack)

        # Panel 0 — process list
        self._stack.addWidget(self._build_process_panel())
        # Panel 1 — AX tree viewer
        self._stack.addWidget(self._build_tree_panel())

        self._stack.setCurrentIndex(0)

        # Auto-fetch on open
        QTimer.singleShot(200, self._fetch_processes)

    # ------------------------------------------------------------------
    # Panel builders
    # ------------------------------------------------------------------

    def _build_process_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        heading = QLabel("Select an Application")
        heading.setStyleSheet("font-size: 16px; font-weight: 700; background: transparent;")
        layout.addWidget(heading)

        desc = QLabel(
            "Browse running applications by name, window title, or command path. "
            "Select one and click Inspect to explore its accessibility tree."
        )
        desc.setObjectName("secondary_label")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        search_row = QHBoxLayout()
        search_row.setSpacing(6)

        self._proc_filter = QLineEdit()
        self._proc_filter.setPlaceholderText("Filter by app name, window title, or path\u2026")
        self._proc_filter.setClearButtonEnabled(True)
        self._proc_filter.textChanged.connect(self._apply_process_filter)
        search_row.addWidget(self._proc_filter, stretch=1)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setProperty("class", "secondary-action")
        self._refresh_btn.clicked.connect(self._fetch_processes)
        search_row.addWidget(self._refresh_btn)

        layout.addLayout(search_row)

        self._proc_table = QTableWidget(0, 4)
        self._proc_table.setHorizontalHeaderLabels(
            ["App Name", "Window Titles", "PID", "Command Path"]
        )
        hdr = self._proc_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        hdr.resizeSection(0, 160)
        hdr.resizeSection(3, 240)
        self._proc_table.verticalHeader().setVisible(False)
        self._proc_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._proc_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._proc_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._proc_table.doubleClicked.connect(self._on_inspect)
        layout.addWidget(self._proc_table, stretch=1)

        self._proc_status = QLabel("")
        self._proc_status.setObjectName("dialog_status")
        layout.addWidget(self._proc_status)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()

        self._inspect_btn = QPushButton("Inspect")
        self._inspect_btn.setProperty("class", "action")
        self._inspect_btn.setEnabled(False)
        self._inspect_btn.clicked.connect(self._on_inspect)
        btn_row.addWidget(self._inspect_btn)

        self._proc_table.itemSelectionChanged.connect(
            lambda: self._inspect_btn.setEnabled(
                len(self._proc_table.selectedItems()) > 0
            )
        )

        layout.addLayout(btn_row)
        return panel

    def _build_tree_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Header
        header_row = QHBoxLayout()
        header_row.setSpacing(8)

        self._back_btn = QPushButton("Back")
        self._back_btn.setProperty("class", "secondary-action")
        self._back_btn.clicked.connect(self._on_back)
        header_row.addWidget(self._back_btn)

        self._tree_heading = QLabel("Accessibility Tree")
        self._tree_heading.setStyleSheet(
            "font-size: 16px; font-weight: 700; background: transparent;"
        )
        header_row.addWidget(self._tree_heading, stretch=1)
        layout.addLayout(header_row)

        # Controls row 1: depth + roles to skip + fetch
        ctrl1 = QHBoxLayout()
        ctrl1.setSpacing(8)
        ctrl1.addWidget(QLabel("Depth:"))
        self._depth_spin = QSpinBox()
        self._depth_spin.setRange(1, 100)
        self._depth_spin.setValue(3)
        self._depth_spin.setFixedWidth(70)
        ctrl1.addWidget(self._depth_spin)
        ctrl1.addWidget(QLabel("Roles to skip:"))
        self._skip_roles_edit = QLineEdit("AXButton")
        self._skip_roles_edit.setPlaceholderText("Comma-separated, e.g. AXButton, AXImage")
        ctrl1.addWidget(self._skip_roles_edit, stretch=1)
        self._fetch_tree_btn = QPushButton("Fetch Tree")
        self._fetch_tree_btn.setProperty("class", "action")
        self._fetch_tree_btn.clicked.connect(self._fetch_tree)
        ctrl1.addWidget(self._fetch_tree_btn)
        layout.addLayout(ctrl1)

        # Controls row 2: text filter
        ctrl2 = QHBoxLayout()
        ctrl2.setSpacing(8)
        ctrl2.addWidget(QLabel("Text filter:"))
        self._text_filter = QLineEdit()
        self._text_filter.setPlaceholderText(
            "Search titles, values, descriptions, identifiers in the tree\u2026"
        )
        self._text_filter.setClearButtonEnabled(True)
        self._text_filter.textChanged.connect(self._apply_text_filter)
        ctrl2.addWidget(self._text_filter, stretch=1)
        self._match_count_label = QLabel("")
        self._match_count_label.setObjectName("secondary_label")
        self._match_count_label.setFixedWidth(120)
        ctrl2.addWidget(self._match_count_label)
        layout.addLayout(ctrl2)

        # Splitter: tree widget (top) + rule preview (bottom)
        self._splitter = QSplitter(Qt.Orientation.Vertical)

        # Tree widget
        self._tree_widget = QTreeWidget()
        self._tree_widget.setHeaderLabels(
            ["Node", "Role", "Identifier", "Title / Description"]
        )
        tw_hdr = self._tree_widget.header()
        tw_hdr.setStretchLastSection(True)
        tw_hdr.resizeSection(0, 340)
        tw_hdr.resizeSection(1, 110)
        tw_hdr.resizeSection(2, 160)
        self._tree_widget.setFont(QFont("Menlo", 12))
        self._tree_widget.setAlternatingRowColors(True)
        self._tree_widget.currentItemChanged.connect(self._on_tree_node_selected)
        self._splitter.addWidget(self._tree_widget)

        # Rule preview area
        rule_container = QWidget()
        rule_layout = QVBoxLayout(rule_container)
        rule_layout.setContentsMargins(0, 4, 0, 0)
        rule_layout.setSpacing(4)

        rule_header = QLabel("Generated Rule")
        rule_header.setStyleSheet("font-size: 13px; font-weight: 600; background: transparent;")
        rule_layout.addWidget(rule_header)

        self._rule_preview = QTextEdit()
        self._rule_preview.setReadOnly(True)
        self._rule_preview.setFont(QFont("Menlo", 11))
        self._rule_preview.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._rule_preview.setPlaceholderText(
            "Select a node in the tree above to generate a search rule\u2026"
        )
        self._rule_preview.setMaximumHeight(220)
        rule_layout.addWidget(self._rule_preview)

        self._splitter.addWidget(rule_container)
        self._splitter.setStretchFactor(0, 3)
        self._splitter.setStretchFactor(1, 1)

        layout.addWidget(self._splitter, stretch=1)

        # Status + buttons
        self._tree_status = QLabel("")
        self._tree_status.setObjectName("dialog_status")
        layout.addWidget(self._tree_status)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._copy_json_btn = QPushButton("Copy Full Tree")
        self._copy_json_btn.setEnabled(False)
        self._copy_json_btn.clicked.connect(self._on_copy_json)
        btn_row.addWidget(self._copy_json_btn)

        self._copy_rule_btn = QPushButton("Copy Rule")
        self._copy_rule_btn.setProperty("class", "primary")
        self._copy_rule_btn.setEnabled(False)
        self._copy_rule_btn.clicked.connect(self._on_copy_rule)
        btn_row.addWidget(self._copy_rule_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        return panel

    # ------------------------------------------------------------------
    # Process list logic
    # ------------------------------------------------------------------

    def _set_proc_status(self, text: str, state: str = ""):
        self._proc_status.setText(text)
        self._proc_status.setProperty("status_state", state)
        self._proc_status.style().unpolish(self._proc_status)
        self._proc_status.style().polish(self._proc_status)

    def _set_tree_status(self, text: str, state: str = ""):
        self._tree_status.setText(text)
        self._tree_status.setProperty("status_state", state)
        self._tree_status.style().unpolish(self._tree_status)
        self._tree_status.style().polish(self._tree_status)

    def _fetch_processes(self):
        if not _HAS_AX:
            self._set_proc_status("ApplicationServices not available.", "error")
            return
        if not AXIsProcessTrusted():
            self._set_proc_status(
                "Accessibility permission not granted. "
                "Enable it in System Settings > Privacy & Security > Accessibility.",
                "error",
            )
            return

        self._refresh_btn.setEnabled(False)
        self._inspect_btn.setEnabled(False)
        self._set_proc_status("Scanning running applications\u2026", "info")
        QApplication.processEvents()

        self._process_worker = _ProcessListWorker()
        self._process_worker.finished.connect(self._on_processes_loaded)
        self._process_worker.error.connect(self._on_process_error)
        self._process_worker.start()

    def _on_processes_loaded(self, results: list):
        self._all_processes = results
        self._populate_process_table(results)
        count = len(results)
        self._set_proc_status(
            f"Found {count} application{'s' if count != 1 else ''} with windows.",
            "success" if count else "warn",
        )
        self._refresh_btn.setEnabled(True)

    def _on_process_error(self, message: str):
        self._set_proc_status(f"Error: {message}", "error")
        self._refresh_btn.setEnabled(True)
        logger.error(f"AX Inspector: process scan error: {message}")

    def _populate_process_table(self, results: list):
        self._proc_table.setRowCount(0)
        for row_idx, (pid, display_name, titles_str, exe) in enumerate(results):
            self._proc_table.insertRow(row_idx)
            name_item = QTableWidgetItem(display_name)
            name_item.setData(Qt.ItemDataRole.UserRole, pid)
            name_item.setData(Qt.ItemDataRole.UserRole + 1, exe)
            self._proc_table.setItem(row_idx, 0, name_item)
            self._proc_table.setItem(row_idx, 1, QTableWidgetItem(titles_str))
            self._proc_table.setItem(row_idx, 2, QTableWidgetItem(str(pid)))
            self._proc_table.setItem(row_idx, 3, QTableWidgetItem(exe))

    def _apply_process_filter(self, text: str):
        needle = text.strip().lower()
        if not needle:
            self._populate_process_table(self._all_processes)
            return
        filtered = [
            entry for entry in self._all_processes
            if (needle in entry[1].lower()
                or needle in entry[2].lower()
                or needle in entry[3].lower())
        ]
        self._populate_process_table(filtered)

    # ------------------------------------------------------------------
    # Inspect transition
    # ------------------------------------------------------------------

    def _on_inspect(self):
        row = self._proc_table.currentRow()
        if row < 0:
            return
        name_item = self._proc_table.item(row, 0)
        if name_item is None:
            return

        pid = name_item.data(Qt.ItemDataRole.UserRole)
        app_name = name_item.text()
        exe = name_item.data(Qt.ItemDataRole.UserRole + 1) or ""

        self._current_pid = pid
        self._current_app_name = app_name
        self._current_exe = exe
        self._tree_heading.setText(f"Accessibility Tree \u2014 {app_name} (PID {pid})")
        self._stack.setCurrentIndex(1)
        self._fetch_tree()

    def _on_back(self):
        self._stack.setCurrentIndex(0)
        self._tree_widget.clear()
        self._rule_preview.clear()
        self._current_tree = None
        self._generated_rule = None
        self._copy_json_btn.setEnabled(False)
        self._copy_rule_btn.setEnabled(False)
        self._text_filter.clear()
        self._match_count_label.clear()

    # ------------------------------------------------------------------
    # AX tree logic
    # ------------------------------------------------------------------

    def _parse_skip_roles(self) -> List[str]:
        raw = self._skip_roles_edit.text()
        return [r.strip() for r in raw.split(",") if r.strip()]

    def _fetch_tree(self):
        if self._current_pid is None:
            return
        self._fetch_tree_btn.setEnabled(False)
        self._copy_json_btn.setEnabled(False)
        self._copy_rule_btn.setEnabled(False)
        self._tree_widget.clear()
        self._rule_preview.clear()
        self._text_filter.clear()
        self._match_count_label.clear()
        self._set_tree_status("Serializing accessibility tree\u2026", "info")
        QApplication.processEvents()

        depth = self._depth_spin.value()
        skip = self._parse_skip_roles()
        self._tree_worker = _AXTreeWorker(
            self._current_pid, max_depth=depth, roles_to_skip=skip
        )
        self._tree_worker.finished.connect(self._on_tree_loaded)
        self._tree_worker.error.connect(self._on_tree_error)
        self._tree_worker.start()

    def _on_tree_loaded(self, tree: dict, node_count: int):
        self._current_tree = tree
        self._current_node_count = node_count
        self._fetch_tree_btn.setEnabled(True)
        self._copy_json_btn.setEnabled(True)

        if not tree:
            self._set_tree_status(
                "Tree is empty \u2014 the application may not expose accessibility data.",
                "warn",
            )
            return

        # --- Critical: block signals & updates during bulk population ---
        self._populating_tree = True
        self._tree_widget.blockSignals(True)
        self._tree_widget.setUpdatesEnabled(False)
        try:
            self._populate_tree_widget(tree, None)
            self._tree_widget.expandToDepth(1)
        except Exception as exc:
            logger.error(f"AX Inspector: tree population error: {exc}")
        finally:
            self._tree_widget.setUpdatesEnabled(True)
            self._tree_widget.blockSignals(False)
            self._populating_tree = False

        self._set_tree_status(
            f"Loaded {node_count} node{'s' if node_count != 1 else ''} "
            f"(depth {self._depth_spin.value()}).  "
            f"Select a node to generate a rule.",
            "success",
        )

    def _on_tree_error(self, message: str):
        self._set_tree_status(f"Error: {message}", "error")
        self._fetch_tree_btn.setEnabled(True)
        logger.error(f"AX Inspector: tree error: {message}")

    def _populate_tree_widget(self, node: dict, parent_item: Optional[QTreeWidgetItem]):
        """Iteratively populate the QTreeWidget from the serialized dict.

        Uses an explicit stack instead of recursion to handle arbitrarily
        large trees without hitting Python's recursion limit.
        """
        # Stack entries: (node_dict, parent_QTreeWidgetItem_or_None)
        stack: List[Tuple[dict, Optional[QTreeWidgetItem]]] = [(node, parent_item)]

        while stack:
            current_node, current_parent = stack.pop()

            label = _node_label(current_node)
            role = current_node.get("role", "")
            identifier = current_node.get("identifier", "")
            title = current_node.get("title", "")
            desc = current_node.get("description", "")
            ident_col = title or desc or current_node.get("value", "")

            if current_parent is None:
                item = QTreeWidgetItem(
                    self._tree_widget, [label, role, identifier, ident_col]
                )
            else:
                item = QTreeWidgetItem(
                    current_parent, [label, role, identifier, ident_col]
                )

            # Store the node dict for rule generation
            item.setData(0, Qt.ItemDataRole.UserRole, current_node)

            # Dim nodes without title/description (less useful as rule anchors)
            if not _has_identifier(current_node):
                dim_color = QColor("#636366")
                for col in range(4):
                    item.setForeground(col, dim_color)

            # Push children in reverse so they appear in original order
            children = current_node.get("children", [])
            for child in reversed(children):
                stack.append((child, item))

    # ------------------------------------------------------------------
    # Node selection -> rule generation
    # ------------------------------------------------------------------

    def _on_tree_node_selected(self, current: QTreeWidgetItem,
                               _previous: QTreeWidgetItem):
        # Guard: skip if called during bulk population
        if self._populating_tree:
            return
        if current is None:
            self._rule_preview.clear()
            self._copy_rule_btn.setEnabled(False)
            return

        node = current.data(0, Qt.ItemDataRole.UserRole)
        if not node or not self._current_tree:
            return

        target_idx = node.get("_idx_")
        if target_idx is None:
            return

        chain = _ancestor_path(self._current_tree, target_idx)
        if not chain:
            self._rule_preview.setPlainText("# Could not trace path to this node.")
            return

        steps = _generate_rule_steps(chain)
        skip_roles = self._parse_skip_roles()

        rule: Dict[str, Any] = {
            "display_name": self._current_app_name,
            "command_paths": [self._current_exe] if self._current_exe else [],
            "rules_to_find_transcript_table": [
                {
                    "path_name": "Inspector Generated Path",
                    "steps": steps,
                }
            ],
            "traversal_roles_to_skip": skip_roles,
            "traversal_mode": "bfs",
            "serialization_text_element_roles": {
                "AXTextArea": "AXValue",
                "AXStaticText": "AXValue",
            },
            "serialization_export_depth": 10,
            "serialization_save_json": False,
            "monitor_interval_seconds": 30,
        }

        self._generated_rule = rule
        self._rule_preview.setPlainText(json.dumps(rule, indent=2, ensure_ascii=False))
        self._copy_rule_btn.setEnabled(True)

    # ------------------------------------------------------------------
    # Text filter (operates on tree widget labels)
    # ------------------------------------------------------------------

    def _apply_text_filter(self, text: str):
        """Show/hide tree items based on text filter."""
        needle = text.strip().lower()

        if not needle:
            self._set_all_visible(self._tree_widget.invisibleRootItem(), True)
            self._match_count_label.clear()
            return

        match_count = self._filter_tree_item(
            self._tree_widget.invisibleRootItem(), needle
        )
        self._match_count_label.setText(
            f"{match_count} match{'es' if match_count != 1 else ''}"
            if match_count else "No matches"
        )

    def _set_all_visible(self, item: QTreeWidgetItem, visible: bool):
        for i in range(item.childCount()):
            child = item.child(i)
            child.setHidden(not visible)
            self._set_all_visible(child, visible)

    def _filter_tree_item(self, item: QTreeWidgetItem, needle: str) -> int:
        """Recursively filter: show items that match or have matching
        descendants.  Returns the number of direct matches.
        """
        total = 0
        for i in range(item.childCount()):
            child = item.child(i)
            text_cols = " ".join(
                (child.text(c) or "") for c in range(child.columnCount())
            ).lower()
            is_match = needle in text_cols
            child_matches = self._filter_tree_item(child, needle)

            if is_match or child_matches > 0:
                child.setHidden(False)
                if is_match:
                    child.setExpanded(True)
                    total += 1
                total += child_matches
            else:
                child.setHidden(True)
        return total

    # ------------------------------------------------------------------
    # Copy actions
    # ------------------------------------------------------------------

    def _on_copy_json(self):
        if self._current_tree:
            text = json.dumps(self._current_tree, indent=2, ensure_ascii=False)
            clipboard = QApplication.clipboard()
            if clipboard:
                clipboard.setText(text)
                self._set_tree_status("Full tree copied to clipboard.", "info")

    def _on_copy_rule(self):
        text = self._rule_preview.toPlainText()
        if text:
            clipboard = QApplication.clipboard()
            if clipboard:
                clipboard.setText(text)
                self._set_tree_status("Generated rule copied to clipboard.", "info")
