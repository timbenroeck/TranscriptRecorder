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
from collections import defaultdict, deque
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
    QFormLayout, QLabel, QPushButton, QLineEdit, QTextEdit, QSpinBox,
    QComboBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QStackedWidget, QTreeWidget, QTreeWidgetItem,
    QSplitter, QTabWidget, QGroupBox, QListWidget, QScrollArea,
)

from gui.constants import logger

# macOS accessibility bindings — same imports as transcript_recorder.py
try:
    from ApplicationServices import (
        AXUIElementCreateApplication,
        AXUIElementCopyAttributeValue,
        AXUIElementSetAttributeValue,
        kAXChildrenAttribute,
        kAXTitleAttribute,
        kAXValueAttribute,
        kAXRoleAttribute,
        kAXSubroleAttribute,
        kAXDescriptionAttribute,
        kAXWindowsAttribute,
        AXIsProcessTrusted,
    )
    kAXErrorSuccess = 0
    _HAS_AX = True
except ImportError:
    _HAS_AX = False
    AXUIElementCreateApplication = None  # type: ignore
    AXUIElementCopyAttributeValue = None  # type: ignore
    AXUIElementSetAttributeValue = None  # type: ignore
    kAXChildrenAttribute = ""  # type: ignore
    kAXTitleAttribute = ""  # type: ignore
    kAXValueAttribute = ""  # type: ignore
    kAXRoleAttribute = ""  # type: ignore
    kAXSubroleAttribute = ""  # type: ignore
    kAXDescriptionAttribute = ""  # type: ignore
    kAXWindowsAttribute = ""  # type: ignore
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


def _force_accessibility_refresh(app_ref: Any, pid: int) -> None:
    """Poke an app's AX tree so lazy Electron apps expose their elements.

    Sets ``AXManualAccessibility = True`` on the app element, then reads
    windows and their children to force the tree to materialise.  Safe to
    call on any process — unsupported attributes are silently ignored.
    """
    if app_ref is None or AXUIElementSetAttributeValue is None:
        return
    try:
        err = AXUIElementSetAttributeValue(
            app_ref, "AXManualAccessibility", True,
        )
        if err == kAXErrorSuccess:
            logger.debug("AX poke (inspector): set AXManualAccessibility=True on PID %d", pid)
        else:
            logger.debug(
                "AX poke (inspector): AXManualAccessibility not supported by PID %d "
                "(error=%s), continuing anyway", pid, err,
            )

        windows = _ax_get(app_ref, kAXWindowsAttribute)
        if windows:
            for win in windows:
                _ax_get(win, kAXChildrenAttribute)
        else:
            _ax_get(app_ref, kAXChildrenAttribute)

        logger.debug(
            "AX poke (inspector): tickled AX tree for PID %d (%d windows)",
            pid, len(windows) if windows else 0,
        )
    except Exception as exc:
        logger.warning("AX poke (inspector): unexpected error for PID %d: %s", pid, exc)


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


def _proc_name_for_pid(pid: int) -> str:
    """Return the process name for *pid* via psutil, or empty string.

    This is the value that ``app_names`` in source.json matches against.
    """
    try:
        proc = psutil.Process(pid)
        return proc.name() or ""
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
    raw_value = node.get("value", "")
    # Ensure value is always a string (AX values can be numeric, e.g. floats
    # from AXSplitter or booleans from checkboxes).
    value = str(raw_value) if raw_value is not None and not isinstance(raw_value, str) else (raw_value or "")

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
# Synchronous AX helpers for test export (run inside QThread)
# ---------------------------------------------------------------------------

_CONFIG_KEY_TO_AX = {
    "role": kAXRoleAttribute,
    "subrole": kAXSubroleAttribute,
    "title": kAXTitleAttribute,
    "title_contains": kAXTitleAttribute,
    "title_matches_one_of": kAXTitleAttribute,
    "description": kAXDescriptionAttribute,
    "description_contains": kAXDescriptionAttribute,
}


def _sync_check_match(element: Any, criteria: Dict[str, Any]) -> bool:
    """Check if an AX element matches all specified criteria (synchronous)."""
    if element is None:
        return False
    for key, expected in criteria.items():
        if key in ("search_scope", "index", "_source_depth_"):
            continue
        attr = _CONFIG_KEY_TO_AX.get(key)
        if attr is None:
            logger.debug(
                "AX test-export match: unknown criteria key %r (skipped)", key
            )
            continue
        actual = _ax_get(element, attr)
        # Coerce pyobjc types to native Python for reliable comparisons
        if actual is not None and not isinstance(actual, (str, int, float, bool)):
            try:
                actual = str(actual)
            except Exception:
                pass
        if key in ("role", "subrole", "title", "description"):
            if actual != expected:
                return False
        elif key == "title_contains":
            actual_str = str(actual) if actual is not None else ""
            if not (actual_str and expected.lower() in actual_str.lower()):
                return False
        elif key == "title_matches_one_of":
            actual_str = str(actual) if actual is not None else ""
            if not (actual_str
                    and isinstance(expected, list)
                    and any(o.lower() in actual_str.lower() for o in expected)):
                return False
        elif key == "description_contains":
            actual_str = str(actual) if actual is not None else ""
            if not (actual_str and expected.lower() in actual_str.lower()):
                return False
    return True


def _sync_search_descendants(
    start_node: Any,
    criteria: Dict[str, Any],
    levels: int,
    roles_to_skip: Optional[List[str]] = None,
) -> List[Any]:
    """BFS descendant search that returns matching AX elements (synchronous)."""
    matches: List[Any] = []
    if start_node is None:
        return matches
    effective = levels if levels > 0 else 50
    queue: deque = deque([(start_node, 0)])
    visited: set = {start_node}
    while queue:
        elem, depth = queue.popleft()
        if depth > effective:
            continue
        if _sync_check_match(elem, criteria):
            matches.append(elem)
        if depth < effective:
            role = _ax_get(elem, kAXRoleAttribute)
            if role and roles_to_skip and role in roles_to_skip and depth > 0:
                continue
            children = _ax_get(elem, kAXChildrenAttribute) or []
            for child in children:
                if child not in visited:
                    visited.add(child)
                    queue.append((child, depth + 1))
    return matches


def _sync_find_element_by_steps(
    app_ref: Any,
    steps: List[dict],
    roles_to_skip: Optional[List[str]] = None,
) -> Optional[Any]:
    """Walk search-path steps from the app root to find the target element."""
    current = [app_ref]
    for step_num, step in enumerate(steps, 1):
        criteria = {
            k: v for k, v in step.items()
            if k not in ("search_scope", "index", "_source_depth_")
        }
        levels_deep = step.get("search_scope", {}).get("levels_deep", 1)
        idx = step.get("index")

        logger.debug(
            "AX test-export step %d/%d: criteria=%r, levels_deep=%d, "
            "searching from %d parent(s), roles_to_skip=%r",
            step_num, len(steps), criteria, levels_deep,
            len(current), roles_to_skip,
        )

        found: List[Any] = []
        for parent in current:
            parent_role = _ax_get(parent, kAXRoleAttribute)
            parent_title = _ax_get(parent, kAXTitleAttribute) or ""
            parent_desc = _ax_get(parent, kAXDescriptionAttribute) or ""
            parent_children = _ax_get(parent, kAXChildrenAttribute)
            child_count = len(parent_children) if parent_children else 0
            logger.debug(
                "AX test-export step %d: searching from %s '%s' "
                "(children=%d)",
                step_num, parent_role, parent_title or parent_desc,
                child_count,
            )
            found.extend(
                _sync_search_descendants(parent, criteria, levels_deep, roles_to_skip)
            )

        logger.debug(
            "AX test-export step %d: found %d match(es)", step_num, len(found)
        )
        if found:
            first_role = _ax_get(found[0], kAXRoleAttribute)
            first_title = _ax_get(found[0], kAXTitleAttribute) or ""
            first_desc = _ax_get(found[0], kAXDescriptionAttribute) or ""
            logger.debug(
                "AX test-export step %d: first match = %s '%s'",
                step_num, first_role, first_title or first_desc,
            )

        if not found:
            logger.warning(
                "AX test-export step %d FAILED: no match for criteria=%r "
                "within %d level(s)",
                step_num, criteria, levels_deep,
            )
            return None
        if idx is not None and 0 <= idx < len(found):
            current = [found[idx]]
        else:
            current = found
    return current[0] if current else None


def _sync_collect_text_values(
    start_node: Any,
    levels_to_search: int,
    roles_to_include: Dict[str, str],
    roles_to_skip: Optional[List[str]] = None,
    traversal_mode: str = "bfs",
) -> List[str]:
    """Collect text values from the AX tree (synchronous)."""
    values: List[str] = []
    if start_node is None:
        return values
    effective = levels_to_search if levels_to_search > 0 else 50

    def process_node(node: Any):
        role = _ax_get(node, kAXRoleAttribute)
        if role in roles_to_include:
            text_attr = roles_to_include[role]
            raw = _ax_get(node, text_attr)
            if isinstance(raw, str) and raw.strip():
                values.append(raw.strip())

    if traversal_mode.lower() == "dfs":
        def dfs(node: Any, depth: int):
            if depth > effective:
                return
            process_node(node)
            role = _ax_get(node, kAXRoleAttribute)
            if role and roles_to_skip and role in roles_to_skip and depth > 0:
                return
            children = _ax_get(node, kAXChildrenAttribute) or []
            for child in children:
                dfs(child, depth + 1)
        dfs(start_node, 0)
    else:  # bfs
        queue: deque = deque([(start_node, 0)])
        while queue:
            node, depth = queue.popleft()
            if depth > effective:
                continue
            process_node(node)
            if depth < effective:
                role = _ax_get(node, kAXRoleAttribute)
                if role and roles_to_skip and role in roles_to_skip and depth > 0:
                    continue
                children = _ax_get(node, kAXChildrenAttribute) or []
                for child in children:
                    queue.append((child, depth + 1))
    return values


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

            results: List[Tuple[int, str, str, str, str]] = []

            for pid, titles in window_map.items():
                if pid <= 1:
                    continue
                owner = owner_names.get(pid, "")
                titles_str = " | ".join(dict.fromkeys(titles))
                exe = _exe_for_pid(pid)
                proc_name = _proc_name_for_pid(pid)
                display_name = owner or os.path.basename(exe) or str(pid)
                results.append((pid, display_name, titles_str, exe, proc_name))

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

            _force_accessibility_refresh(app_ref, self.pid)

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


class _TestExportWorker(QThread):
    """Run a test export: find transcript element via steps, then collect text."""

    finished = pyqtSignal(list, str)   # (text_lines, element_descriptor)
    error = pyqtSignal(str)

    def __init__(
        self,
        pid: int,
        steps: List[dict],
        export_depth: int,
        traversal_mode: str,
        text_element_roles: Dict[str, str],
        roles_to_skip: Optional[List[str]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.pid = pid
        self.steps = steps
        self.export_depth = export_depth
        self.traversal_mode = traversal_mode
        self.text_element_roles = text_element_roles
        self.roles_to_skip = roles_to_skip or []

    def run(self):
        try:
            if not _HAS_AX:
                self.error.emit("ApplicationServices not available.")
                return

            app_ref = AXUIElementCreateApplication(self.pid)
            if app_ref is None:
                self.error.emit(f"Cannot create AX element for PID {self.pid}.")
                return

            _force_accessibility_refresh(app_ref, self.pid)

            # Step 1: Find the transcript element using the configured steps
            if not self.steps:
                self.error.emit("No search steps defined. Add steps by selecting nodes in the tree.")
                return

            logger.debug(
                "AX test-export: pid=%d, steps=%r, depth=%d, mode=%s, "
                "text_roles=%r, skip=%r",
                self.pid, self.steps, self.export_depth,
                self.traversal_mode, self.text_element_roles, self.roles_to_skip,
            )

            # Verify app is reachable
            app_role = _ax_get(app_ref, kAXRoleAttribute)
            app_title = _ax_get(app_ref, kAXTitleAttribute)
            app_children = _ax_get(app_ref, kAXChildrenAttribute)
            logger.debug(
                "AX test-export: app_ref role=%r title=%r children=%d",
                app_role, app_title,
                len(app_children) if app_children else 0,
            )
            if not app_children:
                self.error.emit(
                    f"Cannot read AX children for PID {self.pid}. "
                    "The app may have exited or accessibility access is denied."
                )
                return

            element = _sync_find_element_by_steps(
                app_ref, self.steps, self.roles_to_skip
            )
            if element is None:
                self.error.emit(
                    "Search steps did not find a matching element. "
                    "Check your steps and try increasing levels_deep. "
                    "See log for step-by-step diagnostics."
                )
                return

            # Describe what we found
            role = _ax_get(element, kAXRoleAttribute) or "Unknown"
            title = _ax_get(element, kAXTitleAttribute) or ""
            desc = _ax_get(element, kAXDescriptionAttribute) or ""
            descriptor = f'{role} "{title or desc}"' if (title or desc) else role

            # Step 2: Collect text values from the found element
            lines = _sync_collect_text_values(
                element,
                self.export_depth,
                self.text_element_roles,
                self.roles_to_skip,
                self.traversal_mode,
            )
            self.finished.emit(lines, descriptor)

        except Exception as exc:
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# Main inspector window
# ---------------------------------------------------------------------------

class AccessibilityInspectorDialog(QMainWindow):
    """Two-panel accessibility inspector for building transcript search paths."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Accessibility Inspector")
        self.setMinimumSize(920, 680)
        self.resize(1080, 820)

        self._process_worker: Optional[_ProcessListWorker] = None
        self._tree_worker: Optional[_AXTreeWorker] = None
        self._test_export_worker: Optional[_TestExportWorker] = None
        self._current_pid: Optional[int] = None
        self._current_app_name: str = ""
        self._current_exe: str = ""
        self._current_proc_name: str = ""
        self._current_tree: Optional[dict] = None
        self._current_node_count: int = 0
        self._all_processes: List[Tuple[int, str, str, str]] = []
        self._generated_rule: Optional[dict] = None
        self._populating_tree: bool = False  # guard against signals during build

        # Rule builder — accumulated steps
        self._rule_steps: List[dict] = []
        self._step_source_depths: List[int] = []  # track absolute depth of each step's target

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

        self._proc_table = QTableWidget(0, 5)
        self._proc_table.setHorizontalHeaderLabels(
            ["App Name", "Window Titles", "PID", "Process Name", "Command Path"]
        )
        hdr = self._proc_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        hdr.resizeSection(0, 160)
        hdr.resizeSection(3, 180)
        hdr.resizeSection(4, 240)
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

        self._proc_info_label = QLabel("")
        self._proc_info_label.setObjectName("secondary_label")
        self._proc_info_label.setWordWrap(True)
        self._proc_info_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self._proc_info_label)

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

        # --- Rule builder area (tabbed) ---
        builder_container = QWidget()
        builder_layout = QVBoxLayout(builder_container)
        builder_layout.setContentsMargins(0, 4, 0, 0)
        builder_layout.setSpacing(4)

        self._builder_tabs = QTabWidget()

        # ---- Tab 1: Steps ----
        steps_tab = QWidget()
        steps_layout = QVBoxLayout(steps_tab)
        steps_layout.setContentsMargins(8, 8, 8, 8)
        steps_layout.setSpacing(6)

        steps_info = QLabel(
            "Select a node in the tree and click \u201cAdd Step\u201d to build "
            "a search path. Steps execute in order — each narrows from "
            "the previous step\u2019s result."
        )
        steps_info.setWordWrap(True)
        steps_info.setObjectName("secondary_label")
        steps_layout.addWidget(steps_info)

        self._steps_list = QListWidget()
        self._steps_list.setFont(QFont("Menlo", 11))
        self._steps_list.setAlternatingRowColors(True)
        self._steps_list.setMaximumHeight(140)
        steps_layout.addWidget(self._steps_list)

        step_btns = QHBoxLayout()
        step_btns.setSpacing(6)

        self._add_step_btn = QPushButton("+ Add Step")
        self._add_step_btn.setProperty("class", "secondary-action")
        self._add_step_btn.setEnabled(False)
        self._add_step_btn.setToolTip("Add the selected tree node as a search step")
        self._add_step_btn.clicked.connect(self._on_add_step)
        step_btns.addWidget(self._add_step_btn)

        self._remove_step_btn = QPushButton("Remove Last")
        self._remove_step_btn.setProperty("class", "danger-outline")
        self._remove_step_btn.setEnabled(False)
        self._remove_step_btn.clicked.connect(self._on_remove_step)
        step_btns.addWidget(self._remove_step_btn)

        self._clear_steps_btn = QPushButton("Clear Steps")
        self._clear_steps_btn.setProperty("class", "danger-outline")
        self._clear_steps_btn.setEnabled(False)
        self._clear_steps_btn.clicked.connect(self._on_clear_steps)
        step_btns.addWidget(self._clear_steps_btn)

        step_btns.addStretch()
        steps_layout.addLayout(step_btns)
        steps_layout.addStretch()

        self._builder_tabs.addTab(steps_tab, "Steps")

        # ---- Tab 2: Test Export ----
        test_tab = QWidget()
        test_scroll = QScrollArea()
        test_scroll.setWidgetResizable(True)
        test_inner = QWidget()
        test_layout = QVBoxLayout(test_inner)
        test_layout.setContentsMargins(8, 8, 8, 8)
        test_layout.setSpacing(8)

        # Serialization settings
        settings_group = QGroupBox("Export Settings")
        settings_form = QFormLayout(settings_group)
        settings_form.setContentsMargins(8, 12, 8, 8)
        settings_form.setSpacing(6)

        self._test_depth_spin = QSpinBox()
        self._test_depth_spin.setRange(1, 100)
        self._test_depth_spin.setValue(5)
        self._test_depth_spin.setFixedWidth(80)
        self._test_depth_spin.setToolTip(
            "How many levels deep from the transcript element to collect text"
        )
        self._test_depth_spin.valueChanged.connect(self._on_serialization_setting_changed)
        settings_form.addRow("Export Depth:", self._test_depth_spin)

        self._test_mode_combo = QComboBox()
        self._test_mode_combo.addItems(["bfs", "dfs"])
        self._test_mode_combo.setToolTip(
            "Traversal order: BFS (breadth-first) or DFS (depth-first)"
        )
        self._test_mode_combo.currentTextChanged.connect(self._on_serialization_setting_changed)
        settings_form.addRow("Traversal Mode:", self._test_mode_combo)

        self._test_skip_roles_edit = QLineEdit("AXButton")
        self._test_skip_roles_edit.setPlaceholderText("Comma-separated, e.g. AXButton, AXImage")
        self._test_skip_roles_edit.setToolTip("Roles to skip during text collection")
        self._test_skip_roles_edit.textChanged.connect(self._on_serialization_setting_changed)
        settings_form.addRow("Roles to Skip:", self._test_skip_roles_edit)

        # Text element roles table
        roles_label = QLabel("Text Element Roles:")
        roles_label.setToolTip(
            "Map AX roles to the attribute that holds the text "
            "(e.g. AXTextArea \u2192 AXValue)"
        )
        self._test_roles_table = QTableWidget(2, 2)
        self._test_roles_table.setHorizontalHeaderLabels(["AX Role", "Attribute"])
        self._test_roles_table.horizontalHeader().setStretchLastSection(True)
        self._test_roles_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Interactive
        )
        self._test_roles_table.verticalHeader().setVisible(False)
        self._test_roles_table.setMinimumHeight(120)
        self._test_roles_table.setMaximumHeight(200)
        # Default entries
        self._test_roles_table.setItem(0, 0, QTableWidgetItem("AXTextArea"))
        self._test_roles_table.setItem(0, 1, QTableWidgetItem("AXValue"))
        self._test_roles_table.setItem(1, 0, QTableWidgetItem("AXStaticText"))
        self._test_roles_table.setItem(1, 1, QTableWidgetItem("AXValue"))
        self._test_roles_table.cellChanged.connect(self._on_serialization_setting_changed)
        settings_form.addRow(roles_label, self._test_roles_table)

        roles_btns = QHBoxLayout()
        roles_btns.setSpacing(6)
        add_role_btn = QPushButton("+ Role")
        add_role_btn.setProperty("class", "secondary-action")
        add_role_btn.clicked.connect(self._on_add_text_role)
        roles_btns.addWidget(add_role_btn)
        remove_role_btn = QPushButton("- Role")
        remove_role_btn.setProperty("class", "danger-outline")
        remove_role_btn.clicked.connect(self._on_remove_text_role)
        roles_btns.addWidget(remove_role_btn)
        roles_btns.addStretch()
        settings_form.addRow("", roles_btns)

        test_layout.addWidget(settings_group)

        # Test button
        test_btn_row = QHBoxLayout()
        test_btn_row.setSpacing(8)
        self._test_export_btn = QPushButton("Test Export")
        self._test_export_btn.setProperty("class", "action")
        self._test_export_btn.setEnabled(False)
        self._test_export_btn.setToolTip(
            "Find the transcript element using your steps, then extract text "
            "with the configured serialization settings"
        )
        self._test_export_btn.clicked.connect(self._on_test_export)
        test_btn_row.addWidget(self._test_export_btn)
        self._test_status_label = QLabel("")
        self._test_status_label.setObjectName("secondary_label")
        test_btn_row.addWidget(self._test_status_label, stretch=1)
        test_layout.addLayout(test_btn_row)

        # Test results
        self._test_results = QTextEdit()
        self._test_results.setReadOnly(True)
        self._test_results.setFont(QFont("Menlo", 11))
        self._test_results.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._test_results.setPlaceholderText(
            "Test results will appear here after clicking Test Export\u2026"
        )
        test_layout.addWidget(self._test_results, stretch=1)

        test_scroll.setWidget(test_inner)

        self._builder_tabs.addTab(test_scroll, "Test Export")

        # ---- Tab 3: Rule JSON ----
        json_tab = QWidget()
        json_layout = QVBoxLayout(json_tab)
        json_layout.setContentsMargins(8, 8, 8, 8)
        json_layout.setSpacing(4)

        self._rule_preview = QTextEdit()
        self._rule_preview.setReadOnly(True)
        self._rule_preview.setFont(QFont("Menlo", 11))
        self._rule_preview.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._rule_preview.setPlaceholderText(
            "Add steps and the full source rule JSON will appear here\u2026"
        )
        json_layout.addWidget(self._rule_preview, stretch=1)

        self._builder_tabs.addTab(json_tab, "Rule JSON")

        builder_layout.addWidget(self._builder_tabs)
        self._splitter.addWidget(builder_container)
        self._splitter.setStretchFactor(0, 3)
        self._splitter.setStretchFactor(1, 2)

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
        for row_idx, (pid, display_name, titles_str, exe, proc_name) in enumerate(results):
            self._proc_table.insertRow(row_idx)
            name_item = QTableWidgetItem(display_name)
            name_item.setData(Qt.ItemDataRole.UserRole, pid)
            name_item.setData(Qt.ItemDataRole.UserRole + 1, exe)
            name_item.setData(Qt.ItemDataRole.UserRole + 2, proc_name)
            self._proc_table.setItem(row_idx, 0, name_item)
            self._proc_table.setItem(row_idx, 1, QTableWidgetItem(titles_str))
            self._proc_table.setItem(row_idx, 2, QTableWidgetItem(str(pid)))
            self._proc_table.setItem(row_idx, 3, QTableWidgetItem(proc_name))
            self._proc_table.setItem(row_idx, 4, QTableWidgetItem(exe))

    def _apply_process_filter(self, text: str):
        needle = text.strip().lower()
        if not needle:
            self._populate_process_table(self._all_processes)
            return
        filtered = [
            entry for entry in self._all_processes
            if (needle in entry[1].lower()
                or needle in entry[2].lower()
                or needle in entry[3].lower()
                or needle in entry[4].lower())
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
        proc_name = name_item.data(Qt.ItemDataRole.UserRole + 2) or ""

        self._current_pid = pid
        self._current_app_name = app_name
        self._current_exe = exe
        self._current_proc_name = proc_name
        self._tree_heading.setText(f"Accessibility Tree \u2014 {app_name} (PID {pid})")
        self._proc_info_label.setText(
            f"Process Name: {proc_name}    Command Path: {exe}"
        )
        self._proc_info_label.setToolTip(
            f"Process Name (app_names): {proc_name}\n"
            f"Command Path (command_paths): {exe}\n\n"
            "These values are used in source.json to identify the application.\n"
            "If command_paths doesn't match (e.g. code-sign clones),\n"
            "add app_names to match by process name instead."
        )
        self._stack.setCurrentIndex(1)
        self._fetch_tree()

    def _on_back(self):
        self._stack.setCurrentIndex(0)
        self._tree_widget.clear()
        self._rule_preview.clear()
        self._test_results.clear()
        self._current_tree = None
        self._generated_rule = None
        self._copy_json_btn.setEnabled(False)
        self._copy_rule_btn.setEnabled(False)
        self._add_step_btn.setEnabled(False)
        self._text_filter.clear()
        self._match_count_label.clear()
        self._proc_info_label.clear()
        self._on_clear_steps()
        self._test_status_label.clear()

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
            raw_val = current_node.get("value", "")
            ident_col = title or desc or (str(raw_val) if raw_val and not isinstance(raw_val, str) else (raw_val or ""))

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
            self._add_step_btn.setEnabled(False)
            return

        node = current.data(0, Qt.ItemDataRole.UserRole)
        if not node or not self._current_tree:
            self._add_step_btn.setEnabled(False)
            return

        # Enable "Add Step" when a node is selected
        self._add_step_btn.setEnabled(True)

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
    # Step management (rule builder)
    # ------------------------------------------------------------------

    def _on_add_step(self):
        """Add the currently selected tree node as a search step."""
        current = self._tree_widget.currentItem()
        if current is None:
            return
        node = current.data(0, Qt.ItemDataRole.UserRole)
        if not node:
            return

        role = node.get("role", "")
        title = node.get("title", "")
        desc = node.get("description", "")
        node_depth = node.get("_depth_", 0)

        # Calculate levels_deep relative to the previous step
        if self._step_source_depths:
            gap = node_depth - self._step_source_depths[-1]
        else:
            gap = node_depth  # from root (depth 0)

        step: Dict[str, Any] = {"role": role}
        if desc:
            step["description_contains"] = desc
        elif title:
            step["title_contains"] = title
        step["search_scope"] = {"levels_deep": max(gap, 1)}

        # Store the step metadata
        step["_source_depth_"] = node_depth  # internal, stripped from export
        self._rule_steps.append(step)
        self._step_source_depths.append(node_depth)

        self._update_steps_display()
        self._update_rule_from_steps()
        self._set_tree_status(
            f"Added step {len(self._rule_steps)}: {role}"
            + (f' "{title or desc}"' if (title or desc) else ""),
            "info",
        )

    def _on_remove_step(self):
        """Remove the last search step."""
        if self._rule_steps:
            self._rule_steps.pop()
            self._step_source_depths.pop()
            self._update_steps_display()
            self._update_rule_from_steps()

    def _on_clear_steps(self):
        """Clear all accumulated search steps."""
        self._rule_steps.clear()
        self._step_source_depths.clear()
        self._steps_list.clear()
        self._update_rule_from_steps()
        self._remove_step_btn.setEnabled(False)
        self._clear_steps_btn.setEnabled(False)
        self._test_export_btn.setEnabled(False)

    def _update_steps_display(self):
        """Refresh the steps list widget from the internal list."""
        self._steps_list.clear()
        for i, step in enumerate(self._rule_steps):
            role = step.get("role", "?")
            title_c = step.get("title_contains", "")
            desc_c = step.get("description_contains", "")
            levels = step.get("search_scope", {}).get("levels_deep", "?")
            match_str = ""
            if desc_c:
                match_str = f'desc\u2248"{desc_c}"'
            elif title_c:
                match_str = f'title\u2248"{title_c}"'
            label = f"Step {i+1}: {role}  {match_str}  (depth: {levels})"
            self._steps_list.addItem(label)

        has_steps = len(self._rule_steps) > 0
        self._remove_step_btn.setEnabled(has_steps)
        self._clear_steps_btn.setEnabled(has_steps)
        self._test_export_btn.setEnabled(has_steps)

    def _update_rule_from_steps(self):
        """Regenerate the full rule JSON from the accumulated steps."""
        if not self._rule_steps:
            self._rule_preview.clear()
            self._generated_rule = None
            self._copy_rule_btn.setEnabled(False)
            return

        # Build clean steps (strip _source_depth_)
        clean_steps = []
        for step in self._rule_steps:
            clean = {k: v for k, v in step.items() if k != "_source_depth_"}
            clean_steps.append(clean)

        skip_roles = self._parse_skip_roles()
        text_roles = self._get_test_text_roles()

        rule: Dict[str, Any] = {
            "display_name": self._current_app_name,
            "command_paths": [self._current_exe] if self._current_exe else [],
            "app_names": [self._current_proc_name] if self._current_proc_name else [],
            "transcript_search_paths": [
                {
                    "path_name": "Inspector Generated Path",
                    "steps": clean_steps,
                }
            ],
            "traversal_roles_to_skip": skip_roles,
            "traversal_mode": self._test_mode_combo.currentText(),
            "serialization_text_element_roles": text_roles,
            "serialization_export_depth": self._test_depth_spin.value(),
            "serialization_save_json": False,
            "monitor_interval_seconds": 30,
        }

        self._generated_rule = rule
        self._rule_preview.setPlainText(
            json.dumps(rule, indent=2, ensure_ascii=False)
        )
        self._copy_rule_btn.setEnabled(True)

    def _on_serialization_setting_changed(self, *_args):
        """Re-generate the rule JSON whenever a serialization setting changes."""
        if self._rule_steps:
            self._update_rule_from_steps()

    # ------------------------------------------------------------------
    # Text element roles table helpers
    # ------------------------------------------------------------------

    def _on_add_text_role(self):
        """Add a new row to the text element roles table."""
        row = self._test_roles_table.rowCount()
        self._test_roles_table.insertRow(row)
        self._test_roles_table.setItem(row, 0, QTableWidgetItem(""))
        self._test_roles_table.setItem(row, 1, QTableWidgetItem("AXValue"))
        self._test_roles_table.editItem(self._test_roles_table.item(row, 0))

    def _on_remove_text_role(self):
        """Remove the selected row from the text element roles table."""
        row = self._test_roles_table.currentRow()
        if row >= 0:
            self._test_roles_table.removeRow(row)

    def _get_test_text_roles(self) -> Dict[str, str]:
        """Read the text element roles from the table widget."""
        result: Dict[str, str] = {}
        for row in range(self._test_roles_table.rowCount()):
            role_item = self._test_roles_table.item(row, 0)
            attr_item = self._test_roles_table.item(row, 1)
            role = role_item.text().strip() if role_item else ""
            attr = attr_item.text().strip() if attr_item else ""
            if role and attr:
                result[role] = attr
        return result

    def _parse_test_skip_roles(self) -> List[str]:
        """Parse the comma-separated skip roles for test export."""
        raw = self._test_skip_roles_edit.text()
        return [r.strip() for r in raw.split(",") if r.strip()]

    # ------------------------------------------------------------------
    # Test export
    # ------------------------------------------------------------------

    def _on_test_export(self):
        """Run a test export using the configured steps and settings."""
        if not self._rule_steps:
            self._set_tree_status("No steps defined. Add steps first.", "warn")
            return
        if self._current_pid is None:
            self._set_tree_status("No application selected.", "warn")
            return

        # Build clean steps
        clean_steps = []
        for step in self._rule_steps:
            clean = {k: v for k, v in step.items() if k != "_source_depth_"}
            clean_steps.append(clean)

        text_roles = self._get_test_text_roles()
        if not text_roles:
            self._set_tree_status(
                "No text element roles configured. Add at least one.",
                "warn",
            )
            return

        self._test_export_btn.setEnabled(False)
        self._test_results.clear()
        self._test_status_label.setText("Running test export\u2026")
        self._set_tree_status("Running test export\u2026", "info")
        QApplication.processEvents()

        self._test_export_worker = _TestExportWorker(
            pid=self._current_pid,
            steps=clean_steps,
            export_depth=self._test_depth_spin.value(),
            traversal_mode=self._test_mode_combo.currentText(),
            text_element_roles=text_roles,
            roles_to_skip=self._parse_test_skip_roles(),
        )
        self._test_export_worker.finished.connect(self._on_test_export_finished)
        self._test_export_worker.error.connect(self._on_test_export_error)
        self._test_export_worker.start()

    def _on_test_export_finished(self, lines: list, descriptor: str):
        self._test_export_btn.setEnabled(True)
        count = len(lines)
        if count == 0:
            self._test_results.setPlainText(
                "No text values found.\n\n"
                "Try:\n"
                "  - Increasing Export Depth\n"
                "  - Adding more text element roles\n"
                "  - Checking Roles to Skip isn't excluding text containers\n"
                "  - Switching traversal mode (bfs/dfs)"
            )
            self._test_status_label.setText("0 lines found")
            self._set_tree_status(
                f"Test export found element ({descriptor}) but no text. "
                "Adjust serialization settings.",
                "warn",
            )
        else:
            display = "\n".join(lines)
            self._test_results.setPlainText(display)
            self._test_status_label.setText(
                f"{count} line{'s' if count != 1 else ''} from {descriptor}"
            )
            self._set_tree_status(
                f"Test export: {count} text line{'s' if count != 1 else ''} "
                f"from {descriptor}.",
                "success",
            )

    def _on_test_export_error(self, message: str):
        self._test_export_btn.setEnabled(True)
        self._test_results.setPlainText(f"Error: {message}")
        self._test_status_label.setText("Test failed")
        self._set_tree_status(f"Test export error: {message}", "error")
        logger.error(f"AX Inspector: test export error: {message}")

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
