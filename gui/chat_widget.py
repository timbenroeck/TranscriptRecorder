"""
Meeting Chat widget — interactive LLM chat via a configurable CLI backend.

The widget is a self-contained QWidget that owns its own background
QThread worker (ChatCLIWorker).  It can run concurrently with the
recording worker, tool runner, and calendar fetcher without interference.
Tab switching does not destroy or pause it.

Chat sessions are persisted to JSON files so they can be reloaded and
continued later via the chat-selector dropdown.
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QFont, QKeyEvent, QTextCursor
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFrame,
    QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea,
    QSizePolicy, QSpinBox, QTextBrowser, QTextEdit, QToolButton,
    QVBoxLayout, QWidget,
)

from gui.chat_session import (
    ChatMessage, ChatSessionManager, ChatSessionMeta, SessionData,
)
from gui.constants import logger
from gui.icons import IconManager
from gui.workers import ChatCLIWorker


# ---------------------------------------------------------------------------
# Lightweight markdown -> HTML conversion
# ---------------------------------------------------------------------------

def _md_to_html(md: str) -> str:
    """Convert a markdown string to HTML suitable for QTextBrowser.

    Handles headings, bold, italic, inline code, fenced code blocks,
    unordered lists, ordered lists, and line breaks.  Not a full CommonMark
    parser, but good enough for typical LLM output.
    """
    html_parts: list[str] = []
    lines = md.split("\n")
    i = 0
    in_list = False
    list_type = ""

    while i < len(lines):
        line = lines[i]

        # Fenced code block
        if line.strip().startswith("```"):
            lang = line.strip()[3:].strip()
            code_lines: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing ```
            if in_list:
                html_parts.append(f"</{list_type}>")
                in_list = False
            escaped = _escape_html("\n".join(code_lines))
            html_parts.append(
                f'<pre style="background-color: rgba(128,128,128,0.12); '
                f'border-radius: 4px; padding: 8px; font-family: Menlo, monospace; '
                f'font-size: 12px; white-space: pre-wrap;">{escaped}</pre>'
            )
            continue

        # Close list if line is not a list item
        if in_list and not _is_list_item(line):
            html_parts.append(f"</{list_type}>")
            in_list = False

        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        if stripped.startswith("######"):
            html_parts.append(f"<h6>{_inline(stripped[6:].strip())}</h6>")
        elif stripped.startswith("#####"):
            html_parts.append(f"<h5>{_inline(stripped[5:].strip())}</h5>")
        elif stripped.startswith("####"):
            html_parts.append(f"<h4>{_inline(stripped[4:].strip())}</h4>")
        elif stripped.startswith("###"):
            html_parts.append(f"<h3>{_inline(stripped[3:].strip())}</h3>")
        elif stripped.startswith("##"):
            html_parts.append(f"<h2>{_inline(stripped[2:].strip())}</h2>")
        elif stripped.startswith("# "):
            html_parts.append(f"<h1>{_inline(stripped[2:].strip())}</h1>")
        elif re.match(r"^[-*+]\s", stripped):
            if not in_list or list_type != "ul":
                if in_list:
                    html_parts.append(f"</{list_type}>")
                html_parts.append("<ul>")
                in_list = True
                list_type = "ul"
            content = re.sub(r"^[-*+]\s", "", stripped)
            html_parts.append(f"<li>{_inline(content)}</li>")
        elif re.match(r"^\d+\.\s", stripped):
            if not in_list or list_type != "ol":
                if in_list:
                    html_parts.append(f"</{list_type}>")
                html_parts.append("<ol>")
                in_list = True
                list_type = "ol"
            content = re.sub(r"^\d+\.\s", "", stripped)
            html_parts.append(f"<li>{_inline(content)}</li>")
        elif re.match(r"^(---|\*\*\*|___)\s*$", stripped):
            html_parts.append("<hr>")
        else:
            html_parts.append(f"<p>{_inline(stripped)}</p>")

        i += 1

    if in_list:
        html_parts.append(f"</{list_type}>")

    return "\n".join(html_parts)


def _is_list_item(line: str) -> bool:
    s = line.strip()
    return bool(re.match(r"^[-*+]\s", s) or re.match(r"^\d+\.\s", s))


def _escape_html(text: str) -> str:
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


def _inline(text: str) -> str:
    """Apply inline markdown formatting: bold, italic, inline code, links."""
    text = _escape_html(text)
    text = re.sub(r"`([^`]+)`",
                  r'<code style="background-color: rgba(128,128,128,0.15); '
                  r'border-radius: 3px; padding: 1px 4px; '
                  r'font-family: Menlo, monospace; font-size: 12px;">\1</code>',
                  text)
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<b><i>\1</i></b>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


# ---------------------------------------------------------------------------
# Auto-sizing QTextBrowser that grows to fit its content
# ---------------------------------------------------------------------------

class _AutoSizingBrowser(QTextBrowser):
    """QTextBrowser that reports its ideal height so the parent layout can
    size it without an internal scrollbar.  The outer QScrollArea handles
    scrolling for the entire chat history."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Minimum)
        self.document().contentsChanged.connect(self._update_height)
        self.setReadOnly(True)
        self.setOpenExternalLinks(True)
        self.document().setDocumentMargin(2)

    def _update_height(self):
        doc_height = int(self.document().size().height()) + 6
        self.setMinimumHeight(doc_height)
        self.setMaximumHeight(doc_height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_height()


# ---------------------------------------------------------------------------
# Individual message bubble widget
# ---------------------------------------------------------------------------

class _MessageBubble(QFrame):
    """A single message bubble in the chat history."""

    def __init__(self, role: str, is_dark: bool,
                 assistant_name: str = "Assistant", parent=None):
        super().__init__(parent)
        self._role = role
        self._is_dark = is_dark
        self._raw_thinking = ""
        self._raw_text = ""
        self._raw_transcript = ""
        self._thinking_visible = False
        self._transcript_visible = False
        self._loading_visible = False

        self.setObjectName("chat_bubble_user" if role == "user"
                           else "chat_bubble_assistant")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Maximum)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(4)

        label_text = "You" if role == "user" else assistant_name
        role_label = QLabel(label_text)
        role_label.setObjectName("chat_role_label")
        font = role_label.font()
        font.setWeight(QFont.Weight.DemiBold)
        font.setPointSize(11)
        role_label.setFont(font)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.addWidget(role_label)
        header_row.addStretch()

        self._copy_btn = QPushButton()
        self._copy_btn.setIcon(
            IconManager.get_icon("copy", is_dark=is_dark, size=14))
        self._copy_btn.setFixedSize(24, 24)
        self._copy_btn.setToolTip("Copy message to clipboard")
        self._copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_btn.setObjectName("chat_copy_btn")
        self._copy_btn.clicked.connect(self._copy_content)
        header_row.addWidget(self._copy_btn)

        outer.addLayout(header_row)

        if role == "assistant":
            self._thinking_toggle = QPushButton("▶ Thinking")
            self._thinking_toggle.setObjectName("chat_thinking_toggle")
            self._thinking_toggle.setFlat(True)
            self._thinking_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
            self._thinking_toggle.setVisible(False)
            self._thinking_toggle.clicked.connect(self._toggle_thinking)
            outer.addWidget(self._thinking_toggle)

            self._thinking_browser = QTextBrowser()
            self._thinking_browser.setObjectName("chat_thinking_content")
            self._thinking_browser.setOpenExternalLinks(True)
            self._thinking_browser.setReadOnly(True)
            self._thinking_browser.setVisible(False)
            self._thinking_browser.setFont(QFont("Menlo", 11))
            self._thinking_browser.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self._thinking_browser.setMaximumHeight(200)
            outer.addWidget(self._thinking_browser)

            self._loading_label = QLabel("Waiting for response")
            self._loading_label.setObjectName("chat_loading_label")
            self._loading_label.setStyleSheet(
                "color: palette(mid); font-size: 12px; font-style: italic; "
                "background: transparent; border: none; padding: 4px 0;")
            self._loading_label.setVisible(False)
            outer.addWidget(self._loading_label)
            self._loading_dots = 0
            self._loading_timer = QTimer(self)
            self._loading_timer.timeout.connect(self._animate_loading)

        self._content_browser = _AutoSizingBrowser()
        self._content_browser.setObjectName("chat_content")
        self._content_browser.setFont(QFont("SF Pro", 13))
        outer.addWidget(self._content_browser)

        if role == "user":
            self._transcript_toggle = QPushButton("▶ Transcript")
            self._transcript_toggle.setObjectName("chat_transcript_toggle")
            self._transcript_toggle.setFlat(True)
            self._transcript_toggle.setCursor(
                Qt.CursorShape.PointingHandCursor)
            self._transcript_toggle.setVisible(False)
            self._transcript_toggle.clicked.connect(
                self._toggle_transcript)
            outer.addWidget(self._transcript_toggle)

            self._transcript_browser = QTextBrowser()
            self._transcript_browser.setObjectName("chat_transcript_content")
            self._transcript_browser.setOpenExternalLinks(False)
            self._transcript_browser.setReadOnly(True)
            self._transcript_browser.setVisible(False)
            self._transcript_browser.setFont(QFont("Menlo", 11))
            self._transcript_browser.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self._transcript_browser.setMaximumHeight(200)
            outer.addWidget(self._transcript_browser)

    # -- public API --

    def show_loading(self):
        if self._role != "assistant":
            return
        self._loading_visible = True
        self._loading_dots = 0
        self._loading_label.setText("Waiting for response")
        self._loading_label.setVisible(True)
        self._content_browser.setVisible(False)
        self._loading_timer.start(500)

    def hide_loading(self):
        if self._role != "assistant":
            return
        self._loading_visible = False
        self._loading_timer.stop()
        self._loading_label.setVisible(False)
        self._content_browser.setVisible(True)

    def set_content(self, text: str):
        self._raw_text = text
        if self._loading_visible:
            self.hide_loading()
        self._content_browser.setHtml(_md_to_html(text))

    def append_text(self, chunk: str):
        if self._loading_visible:
            self.hide_loading()
        self._raw_text += chunk
        self._content_browser.setHtml(_md_to_html(self._raw_text))

    def set_thinking(self, text: str):
        if self._role != "assistant":
            return
        if self._loading_visible:
            self.hide_loading()
        self._raw_thinking = text
        self._thinking_toggle.setVisible(bool(text))
        self._thinking_browser.setPlainText(text)
        if self._thinking_visible:
            self._thinking_browser.setVisible(True)

    def append_thinking(self, chunk: str):
        if self._role != "assistant":
            return
        if self._loading_visible:
            self.hide_loading()
        self._raw_thinking += chunk
        self._thinking_toggle.setVisible(True)
        if not self._thinking_visible:
            self._thinking_visible = True
            self._thinking_toggle.setText("▼ Thinking")
            self._thinking_browser.setVisible(True)
        self._thinking_browser.setPlainText(self._raw_thinking)

    def collapse_thinking(self):
        if self._role != "assistant":
            return
        self._thinking_visible = False
        self._thinking_toggle.setText("▶ Thinking")
        self._thinking_browser.setVisible(False)

    def set_transcript(self, text: str, label: str = "Transcript"):
        """Set the collapsible transcript section (user bubbles only)."""
        if self._role != "user":
            return
        self._raw_transcript = text
        self._transcript_toggle.setText(f"▶ {label}")
        self._transcript_toggle.setVisible(bool(text))
        self._transcript_browser.setPlainText(text)
        self._transcript_toggle.setProperty("_label", label)

    def collapse_transcript(self):
        if self._role != "user":
            return
        self._transcript_visible = False
        label = (self._transcript_toggle.property("_label")
                 or "Transcript")
        self._transcript_toggle.setText(f"▶ {label}")
        self._transcript_browser.setVisible(False)

    def set_tool_status(self, status: str):
        if self._role != "assistant":
            return
        if self._loading_visible:
            self.hide_loading()
        display = self._raw_text + f"\n\n*{status}...*"
        self._content_browser.setHtml(_md_to_html(display))

    # -- private --

    def _animate_loading(self):
        self._loading_dots = (self._loading_dots + 1) % 4
        dots = "." * self._loading_dots
        self._loading_label.setText(f"Waiting for response{dots}")

    def _toggle_thinking(self):
        self._thinking_visible = not self._thinking_visible
        self._thinking_browser.setVisible(self._thinking_visible)
        self._thinking_toggle.setText(
            "▼ Thinking" if self._thinking_visible else "▶ Thinking")

    def _toggle_transcript(self):
        self._transcript_visible = not self._transcript_visible
        self._transcript_browser.setVisible(self._transcript_visible)
        label = (self._transcript_toggle.property("_label")
                 or "Transcript")
        self._transcript_toggle.setText(
            f"▼ {label}" if self._transcript_visible else f"▶ {label}")

    def _copy_content(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self._raw_text)
        self._copy_btn.setToolTip("Copied!")
        QTimer.singleShot(1500,
                          lambda: self._copy_btn.setToolTip("Copy message to clipboard"))


# ---------------------------------------------------------------------------
# System prompt banner (collapsible, at top of chat history)
# ---------------------------------------------------------------------------

class _SystemPromptBanner(QFrame):
    """A collapsible banner showing the system prompt used for the session."""

    def __init__(self, prompt_text: str, parent=None):
        super().__init__(parent)
        self.setObjectName("system_prompt_banner")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Maximum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(4)

        self._toggle = QPushButton("▶ System Prompt")
        self._toggle.setObjectName("chat_system_prompt_toggle")
        self._toggle.setFlat(True)
        self._toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle.clicked.connect(self._on_toggle)
        layout.addWidget(self._toggle)

        self._browser = QTextBrowser()
        self._browser.setObjectName("chat_system_prompt_content")
        self._browser.setReadOnly(True)
        self._browser.setVisible(False)
        self._browser.setFont(QFont("Menlo", 11))
        self._browser.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._browser.setMaximumHeight(160)
        self._browser.setPlainText(prompt_text)
        layout.addWidget(self._browser)

        self._visible = False

    def _on_toggle(self):
        self._visible = not self._visible
        self._browser.setVisible(self._visible)
        self._toggle.setText(
            "▼ System Prompt" if self._visible else "▶ System Prompt")

    def update_prompt(self, text: str):
        self._browser.setPlainText(text)


# ---------------------------------------------------------------------------
# Chat input widget (handles Enter-to-send, Shift+Enter for newline)
# ---------------------------------------------------------------------------

class _ChatInput(QTextEdit):
    """Text input that emits ``submitted`` on Enter and inserts newlines
    on Shift+Enter."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._submit_callback: Optional[Callable] = None
        self.setAcceptRichText(False)
        self.setPlaceholderText("Type your message...")
        self.setFont(QFont("SF Pro", 13))
        self.setFixedHeight(60)

    def set_submit_callback(self, fn: Callable):
        self._submit_callback = fn

    def keyPressEvent(self, event: QKeyEvent):
        if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            if self._submit_callback:
                self._submit_callback()
            return
        super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _transcript_mode_label(mode: str, lines_sent: int = 0) -> str:
    """Human-readable label for the transcript collapsible toggle."""
    if mode == "last_n" and lines_sent:
        return f"Transcript (last {lines_sent} lines)"
    if mode == "updates":
        return "Transcript Update (new content)"
    return "Full Transcript"


# ---------------------------------------------------------------------------
# Main chat widget
# ---------------------------------------------------------------------------

_NEW_CHAT_LABEL = "New Chat"


class MeetingChatWidget(QWidget):
    """Self-contained chat widget that communicates with a CLI backend.

    Owns its own ``ChatCLIWorker`` QThread.  All state (message history,
    accumulated streaming text, worker reference) is local to this widget
    and persists across tab switches.
    """

    def __init__(self, transcript_accessor: Callable[[], str],
                 is_dark_fn: Callable[[], bool],
                 recording_path_fn: Callable[[], Optional[Path]],
                 parent=None):
        super().__init__(parent)
        self._transcript_accessor = transcript_accessor
        self._is_dark_fn = is_dark_fn
        self._recording_path_fn = recording_path_fn
        self._messages: List[ChatMessage] = []
        self._chat_worker: Optional[ChatCLIWorker] = None
        self._current_bubble: Optional[_MessageBubble] = None
        self._model = ""
        self._connection = ""
        self._cli_binary = "cortex"
        self._cli_extra_args: List[str] = ["--bypass"]
        self._assistant_name = "Assistant"
        self._chat_export_directory = ""
        self._system_prompt = (
            "You are a helpful assistant analyzing a meeting transcript. "
            "Respond in well-formatted markdown. Be concise and specific."
        )
        self._first_message_sent = False
        self._auto_save = False
        self._chat_logging = False
        self._max_history = 5
        self._force_include_transcript = False
        self._last_transcript_line_count: int = 0
        self._force_transcript_mode: Optional[str] = None
        self._force_transcript_lines: int = 0
        self._skip_transcript: bool = False
        self._session_id: Optional[str] = None
        self._last_prompt: Optional[str] = None
        self._populating_dropdown = False
        self._prompts: List[dict] = []
        self._system_prompt_banner: Optional[_SystemPromptBanner] = None

        self._setup_ui()

    # -- public config API called by main_window --

    def set_model(self, model: str):
        self._model = model

    def set_connection(self, connection: str):
        self._connection = connection

    def set_cli_binary(self, binary: str):
        self._cli_binary = binary

    def set_cli_extra_args(self, args: List[str]):
        self._cli_extra_args = list(args)

    def set_assistant_name(self, name: str):
        self._assistant_name = name

    def set_chat_export_directory(self, path: str):
        self._chat_export_directory = path

    def get_model(self) -> str:
        return self._model

    def get_connection(self) -> str:
        return self._connection

    def get_cli_binary(self) -> str:
        return self._cli_binary

    def get_cli_extra_args(self) -> List[str]:
        return list(self._cli_extra_args)

    def get_assistant_name(self) -> str:
        return self._assistant_name

    def get_chat_export_directory(self) -> str:
        return self._chat_export_directory

    def set_system_prompt(self, prompt: str):
        self._system_prompt = prompt

    def get_system_prompt(self) -> str:
        return self._system_prompt

    def set_auto_save(self, enabled: bool):
        self._auto_save = enabled

    def get_auto_save(self) -> bool:
        return self._auto_save

    def set_chat_logging(self, enabled: bool):
        self._chat_logging = enabled

    def get_chat_logging(self) -> bool:
        return self._chat_logging

    def set_max_history(self, count: int):
        self._max_history = max(1, count)

    def get_max_history(self) -> int:
        return self._max_history

    def set_prompts(self, prompts: List[dict]):
        self._prompts = list(prompts)
        self._populate_prompts_combo()

    def get_prompts(self) -> List[dict]:
        return list(self._prompts)

    # -- public notifications --

    def notify_transcript_changed(self):
        """Called by the main window after a transcript capture to refresh
        the line-count diff indicator in real time."""
        self._update_transcript_indicator()

    # -- session management --

    def clear_chat(self):
        """Cancel any running worker and reset all state."""
        if self._chat_worker and self._chat_worker.isRunning():
            self._chat_worker.cancel()
            self._chat_worker.wait(5000)
        self._chat_worker = None
        self._current_bubble = None
        self._messages.clear()
        self._first_message_sent = False
        self._force_include_transcript = False
        self._last_transcript_line_count = 0
        self._force_transcript_mode = None
        self._force_transcript_lines = 0
        self._skip_transcript = False
        self._session_id = None
        self._last_prompt = None
        self._system_prompt_banner = None
        self._clear_bubbles()
        self._update_transcript_indicator()
        self._send_btn.setEnabled(True)
        self._input.setEnabled(True)
        self._input.clear()

    def _clear_bubbles(self):
        while self._history_layout.count() > 0:
            item = self._history_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def is_chat_running(self) -> bool:
        return self._chat_worker is not None and self._chat_worker.isRunning()

    def refresh_sessions_dropdown(self):
        """Reload the chat-selector dropdown from chats.json."""
        recording_path = self._recording_path_fn()
        self._populating_dropdown = True
        current_id = self._session_id

        self._chat_selector.clear()
        self._chat_selector.addItem(_NEW_CHAT_LABEL, userData=None)

        if recording_path:
            sessions = ChatSessionManager.list_sessions(recording_path)
            for meta in sessions:
                dt = meta.created[:10] if len(meta.created) >= 10 else meta.created
                title = meta.title[:60] if meta.title else meta.id
                label = f"{title} — {dt}"
                self._chat_selector.addItem(label, userData=meta.id)

        if current_id:
            for i in range(self._chat_selector.count()):
                if self._chat_selector.itemData(i) == current_id:
                    self._chat_selector.setCurrentIndex(i)
                    break
        self._populating_dropdown = False

    def load_session(self, session_id: str):
        """Load a previous chat session and rebuild the UI."""
        recording_path = self._recording_path_fn()
        if not recording_path:
            return
        session = ChatSessionManager.load_session(recording_path, session_id)
        if not session:
            self._show_status(f"Could not load session {session_id}")
            return

        self.clear_chat()
        self._session_id = session.id
        self._messages = list(session.messages)
        if self._messages:
            self._first_message_sent = True
            self._force_include_transcript = False
            last_tx = self._find_last_transcript_message()
            if last_tx:
                self._last_transcript_line_count = last_tx.transcript_line_count
            self._update_transcript_indicator()

        banner_prompt = session.system_prompt or self._system_prompt
        if banner_prompt and self._messages:
            self._ensure_system_prompt_banner(banner_prompt)

        is_dark = self._is_dark_fn()
        for msg in self._messages:
            bubble = _MessageBubble(
                msg.role, is_dark,
                assistant_name=self._assistant_name)
            bubble.set_content(msg.content)
            if msg.role == "assistant" and msg.thinking:
                bubble.set_thinking(msg.thinking)
                bubble.collapse_thinking()
            if msg.role == "user" and msg.has_transcript:
                tx_text = self._reconstruct_transcript(
                    recording_path, msg)
                tx_label = _transcript_mode_label(
                    msg.transcript_mode, msg.transcript_lines_sent)
                bubble.set_transcript(tx_text, tx_label)
            idx = max(0, self._history_layout.count() - 1)
            self._history_layout.insertWidget(idx, bubble)

        QTimer.singleShot(50, self._scroll_to_bottom)

    @staticmethod
    def _reconstruct_transcript(recording_path: Path,
                                msg: ChatMessage) -> str:
        """Try to reconstruct transcript text from the backup file."""
        if not msg.transcript_backup_file:
            return ("(Transcript reference not available — "
                    "older session format)")
        backup_path = recording_path / msg.transcript_backup_file
        if not backup_path.exists():
            return ("(Transcript snapshot unavailable — "
                    "backup may have been overwritten "
                    "by a later inclusion)")
        try:
            all_lines = backup_path.read_text(
                encoding="utf-8").splitlines()
            start = msg.transcript_start_line
            count = msg.transcript_lines_sent
            if count and start + count <= len(all_lines):
                return "\n".join(all_lines[start:start + count])
            return "\n".join(all_lines)
        except Exception:
            return "(Failed to read transcript backup)"

    # -- save / export --

    def save_chat(self) -> Optional[Path]:
        """Save chat as markdown with YAML frontmatter, persist session, update manifest."""
        if not self._messages:
            return None

        recording_path = self._recording_path_fn()
        if not recording_path:
            logger.warning("Chat save: no recording directory available")
            return None

        if not self._session_id:
            self._session_id = ChatSessionManager.generate_id()

        sid = self._session_id
        filename = f"chat_{sid}.md"

        if self._chat_export_directory:
            dest_dir = Path(self._chat_export_directory)
        else:
            dest_dir = recording_path / "chats"
        dest_dir.mkdir(parents=True, exist_ok=True)
        filepath = dest_dir / filename

        now = datetime.now()
        lines: list[str] = []
        lines.append("---")
        lines.append(f"date: {now.strftime('%Y-%m-%d %I:%M %p')}")
        lines.append(f"model: {self._model or 'auto'}")
        lines.append(f"assistant_name: {self._assistant_name}")
        lines.append(f'chat_id: "{sid}"')
        lines.append(f"transcript_directory: {recording_path}")
        lines.append("---")
        lines.append("")

        lines.append(f"# Meeting Chat — {sid}")
        lines.append("")

        for msg in self._messages:
            lines.append("---")
            lines.append("")
            if msg.role == "user":
                lines.append("**You:**")
            else:
                lines.append(f"**{self._assistant_name}:**")
            lines.append("")
            if msg.role == "assistant" and msg.thinking:
                lines.append("<details><summary>Thinking</summary>")
                lines.append("")
                lines.append(msg.thinking)
                lines.append("")
                lines.append("</details>")
                lines.append("")
            lines.append(msg.content)
            lines.append("")

        md_text = "\n".join(lines)
        filepath.write_text(md_text, encoding="utf-8")
        logger.info(f"Chat saved to {filepath}")

        session_data = SessionData(
            id=sid,
            model=self._model,
            connection=self._connection,
            assistant_name=self._assistant_name,
            cli_binary=self._cli_binary,
            messages=list(self._messages),
        )
        ChatSessionManager.save_session(recording_path, session_data)

        first_user = next(
            (m.content for m in self._messages if m.role == "user"), "")
        title = first_user[:80].replace("\n", " ").strip() or sid

        existing = ChatSessionManager.list_sessions(recording_path)
        created = now.isoformat()
        for entry in existing:
            if entry.id == sid:
                created = entry.created
                break

        meta = ChatSessionMeta(
            id=sid,
            created=created,
            updated=now.isoformat(),
            title=title,
            model=self._model,
            cli_binary=self._cli_binary,
            assistant_name=self._assistant_name,
            message_count=len(self._messages),
            markdown_file=str(filepath),
            session_file=f"sessions/{sid}.json",
            transcript_directory=str(recording_path),
        )

        ChatSessionManager.update_manifest(recording_path, meta)
        self.refresh_sessions_dropdown()

        return filepath

    def copy_all_chat(self) -> str:
        """Return all chat messages as markdown and copy to clipboard."""
        if not self._messages:
            return ""

        lines: list[str] = []
        for msg in self._messages:
            if msg.role == "user":
                lines.append("**You:**\n")
                lines.append(msg.content)
                lines.append("")
            else:
                lines.append(f"**{self._assistant_name}:**\n")
                if msg.thinking:
                    lines.append(f"<details><summary>Thinking</summary>"
                                 f"\n\n{msg.thinking}\n\n</details>\n")
                lines.append(msg.content)
                lines.append("")

        text = "\n".join(lines)
        QApplication.clipboard().setText(text)
        return text

    def open_chats_folder(self):
        if self._chat_export_directory:
            target = Path(self._chat_export_directory)
        else:
            recording_path = self._recording_path_fn()
            if not recording_path:
                self._show_status("No recording directory available")
                return
            target = recording_path / "chats"
        target.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["open", str(target)])

    # -- UI setup --

    def _setup_ui(self):
        is_dark = self._is_dark_fn()
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 8, 0, 0)
        main_layout.setSpacing(6)

        # Header row: chat selector dropdown + button bar
        header = QHBoxLayout()
        header.setContentsMargins(4, 0, 4, 0)

        self._chat_selector = QComboBox()
        self._chat_selector.setObjectName("chat_selector")
        self._chat_selector.setMinimumWidth(200)
        self._chat_selector.setSizePolicy(QSizePolicy.Policy.Expanding,
                                          QSizePolicy.Policy.Fixed)
        self._chat_selector.addItem(_NEW_CHAT_LABEL, userData=None)
        self._chat_selector.currentIndexChanged.connect(
            self._on_chat_selector_changed)
        header.addWidget(self._chat_selector, stretch=1)

        header.addSpacing(8)

        # Horizontal button bar
        btn_bar = QFrame()
        btn_bar.setObjectName("chat_btn_bar")
        btn_bar.setFrameShape(QFrame.Shape.StyledPanel)
        btn_bar.setStyleSheet(
            "QFrame#chat_btn_bar { border: 1px solid palette(mid); "
            "border-radius: 4px; }"
        )
        btn_bar_layout = QHBoxLayout(btn_bar)
        btn_bar_layout.setContentsMargins(4, 2, 4, 2)
        btn_bar_layout.setSpacing(2)

        btn_style = (
            "QPushButton { background: transparent; border: none; "
            "padding: 4px; }"
            "QPushButton:hover { background: palette(mid); "
            "border-radius: 4px; }"
        )

        def _add_btn(icon_name, tooltip, callback):
            btn = QPushButton()
            btn.setIcon(IconManager.get_icon(icon_name, is_dark=is_dark,
                                             size=16))
            btn.setIconSize(QSize(16, 16))
            btn.setFixedSize(28, 28)
            btn.setToolTip(tooltip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(btn_style)
            btn.clicked.connect(callback)
            btn_bar_layout.addWidget(btn)
            return btn

        self._save_btn = _add_btn("save", "Save chat", self._on_save_chat)
        self._delete_btn = _add_btn("trash", "Delete chat", self._on_delete_chat)
        self._copy_all_btn = _add_btn("copy", "Copy entire chat to clipboard",
                                      self._on_copy_all)
        self._open_folder_btn = _add_btn("folder_open",
                                         "Open chats folder in Finder",
                                         self.open_chats_folder)

        header.addWidget(btn_bar)
        main_layout.addLayout(header)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Plain)
        sep.setFixedHeight(1)
        main_layout.addWidget(sep)

        # Scrollable chat history
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_area.setObjectName("chat_scroll_area")

        self._history_container = QWidget()
        self._history_container.setObjectName("chat_history_container")
        self._history_layout = QVBoxLayout(self._history_container)
        self._history_layout.setContentsMargins(8, 8, 8, 8)
        self._history_layout.setSpacing(10)
        self._history_layout.addStretch()

        self._scroll_area.setWidget(self._history_container)
        main_layout.addWidget(self._scroll_area, stretch=1)

        # Input area
        input_frame = QFrame()
        input_frame.setObjectName("chat_input_frame")
        input_layout = QVBoxLayout(input_frame)
        input_layout.setContentsMargins(8, 6, 8, 6)
        input_layout.setSpacing(6)

        # Options row: prompts dropdown + transcript indicator + transcript btn + info btn
        options_row = QHBoxLayout()
        options_row.setSpacing(8)

        self._prompts_combo = QComboBox()
        self._prompts_combo.setObjectName("chat_prompts_combo")
        self._prompts_combo.setMinimumWidth(140)
        self._prompts_combo.setMaximumWidth(260)
        self._prompts_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._prompts_combo.addItem("Prompts...")
        self._prompts_combo.model().item(0).setEnabled(False)
        self._prompts_combo.currentIndexChanged.connect(
            self._on_prompt_selected)
        options_row.addWidget(self._prompts_combo)

        options_row.addStretch()

        self._transcript_label = QLabel()
        self._transcript_label.setObjectName("chat_transcript_label")
        self._transcript_label.setStyleSheet(
            "font-size: 11px; color: palette(mid);")
        options_row.addWidget(self._transcript_label)

        transcript_btn_style = (
            "QToolButton { font-size: 11px; padding: 2px 8px; "
            "border: 1px solid palette(mid); border-radius: 3px; "
            "background: transparent; }"
            "QToolButton:hover { background: palette(mid); }"
            "QToolButton::menu-indicator { width: 0px; }")
        self._transcript_menu = QMenu(self)
        if is_dark:
            menu_qss = (
                "QMenu { background-color: #252529; color: #E1E1E6; "
                "border: 1px solid #2C2C2C; border-radius: 6px; "
                "padding: 4px 0; }"
                "QMenu::item { padding: 6px 24px 6px 12px; "
                "min-height: 20px; }"
                "QMenu::item:selected { background-color: #7AA2FF; "
                "color: white; }"
                "QMenu::item:disabled { color: #636366; "
                "font-style: italic; }"
                "QMenu::separator { height: 1px; background: #2C2C2C; "
                "margin: 4px 8px; }")
        else:
            menu_qss = (
                "QMenu { background-color: #FFFFFF; color: #333333; "
                "border: 1px solid #E0E0E0; border-radius: 6px; "
                "padding: 4px 0; }"
                "QMenu::item { padding: 6px 24px 6px 12px; "
                "min-height: 20px; }"
                "QMenu::item:selected { background-color: #4A67AD; "
                "color: white; }"
                "QMenu::item:disabled { color: #8E8E93; "
                "font-style: italic; }"
                "QMenu::separator { height: 1px; background: #E0E0E0; "
                "margin: 4px 8px; }")
        self._transcript_menu.setStyleSheet(menu_qss)
        self._transcript_full_action = self._transcript_menu.addAction(
            "Full Transcript")
        self._transcript_updates_action = self._transcript_menu.addAction(
            "New Since Last Include")
        self._transcript_last_n_action = self._transcript_menu.addAction(
            "Last N Lines\u2026")
        self._transcript_menu.addSeparator()
        self._transcript_none_action = self._transcript_menu.addAction(
            "No Transcript")
        self._transcript_full_action.triggered.connect(
            lambda: self._on_reinclude_transcript("full"))
        self._transcript_updates_action.triggered.connect(
            lambda: self._on_reinclude_transcript("updates"))
        self._transcript_last_n_action.triggered.connect(
            self._on_last_n_lines)
        self._transcript_none_action.triggered.connect(
            self._on_no_transcript)
        self._transcript_menu.aboutToShow.connect(
            self._update_transcript_indicator)

        self._reinclude_btn = QToolButton()
        self._reinclude_btn.setObjectName("chat_reinclude_btn")
        self._reinclude_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reinclude_btn.setFixedHeight(24)
        self._reinclude_btn.setStyleSheet(transcript_btn_style)
        self._reinclude_btn.setToolTip(
            "Include or update the meeting transcript in the next message")
        self._reinclude_btn.setText("Transcript \u25BE")
        self._reinclude_btn.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup)
        self._reinclude_btn.setMenu(self._transcript_menu)
        options_row.addWidget(self._reinclude_btn)

        self._transcript_info_btn = QPushButton()
        self._transcript_info_btn.setIcon(
            IconManager.get_icon("circle_help", is_dark=is_dark, size=14))
        self._transcript_info_btn.setFixedSize(20, 20)
        self._transcript_info_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._transcript_info_btn.setToolTip("How transcript context works")
        self._transcript_info_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; }"
            "QPushButton:hover { background: palette(mid); "
            "border-radius: 3px; }")
        self._transcript_info_btn.clicked.connect(self._on_transcript_info)
        options_row.addWidget(self._transcript_info_btn)

        self._update_transcript_indicator()
        input_layout.addLayout(options_row)

        # Text input + send button row
        input_row = QHBoxLayout()
        input_row.setSpacing(6)
        self._input = _ChatInput()
        input_row.addWidget(self._input, stretch=1)

        self._send_btn = QPushButton("Send")
        self._send_btn.setProperty("class", "action")
        self._send_btn.setFixedWidth(80)
        self._send_btn.setFixedHeight(60)
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.clicked.connect(self._on_send)
        input_row.addWidget(self._send_btn)

        self._input.set_submit_callback(self._on_send)
        input_layout.addLayout(input_row)

        main_layout.addWidget(input_frame)

    # -- dropdown handler --

    def _on_chat_selector_changed(self, index: int):
        if self._populating_dropdown:
            return
        session_id = self._chat_selector.itemData(index)
        if session_id is None:
            self.clear_chat()
        else:
            self.load_session(session_id)

    # -- prompts dropdown --

    def _populate_prompts_combo(self):
        """Rebuild the prompts dropdown from the current _prompts list."""
        self._prompts_combo.blockSignals(True)
        self._prompts_combo.clear()
        self._prompts_combo.addItem("Prompts...")
        self._prompts_combo.model().item(0).setEnabled(False)
        for p in self._prompts:
            label = p.get("label", p.get("text", "")[:40])
            self._prompts_combo.addItem(label)
        self._prompts_combo.setCurrentIndex(0)
        self._prompts_combo.blockSignals(False)
        # Widen the popup so long prompt labels aren't clipped
        fm = self._prompts_combo.fontMetrics()
        max_w = 0
        for i in range(self._prompts_combo.count()):
            w = fm.horizontalAdvance(self._prompts_combo.itemText(i))
            if w > max_w:
                max_w = w
        self._prompts_combo.view().setMinimumWidth(max_w + 40)

    def _on_prompt_selected(self, index: int):
        if index <= 0 or index - 1 >= len(self._prompts):
            return
        text = self._prompts[index - 1].get("text", "")
        if text:
            self._input.setPlainText(text)
            cursor = self._input.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self._input.setTextCursor(cursor)
            self._input.setFocus()
        self._prompts_combo.blockSignals(True)
        self._prompts_combo.setCurrentIndex(0)
        self._prompts_combo.blockSignals(False)

    # -- button bar actions --

    def _on_save_chat(self):
        path = self.save_chat()
        if path:
            self._show_status(f"Chat saved to {path.name}")
        else:
            self._show_status("Nothing to save")

    def _on_copy_all(self):
        text = self.copy_all_chat()
        if text:
            self._show_status("Chat copied to clipboard")
        else:
            self._show_status("No messages to copy")

    def _on_delete_chat(self):
        """Delete the current chat session, or just reset if no session exists."""
        if not self._session_id or not self._messages:
            self.clear_chat()
            self._show_status("Chat cleared")
            return

        from gui.dialogs import ThemedMessageDialog
        if not ThemedMessageDialog.question(
            self.window(),
            "Delete Chat",
            f"Delete this chat session ({self._session_id})?\n"
            "This will remove the session file, markdown export, and "
            "manifest entry. This cannot be undone."
        ):
            return

        recording_path = self._recording_path_fn()
        if recording_path:
            backup_file = recording_path / ".backup" / f"transcript_{self._session_id}.txt"
            if backup_file.exists():
                try:
                    backup_file.unlink()
                    logger.debug(f"Chat delete: removed backup {backup_file}")
                except Exception as e:
                    logger.warning(f"Chat delete: failed to remove backup: {e}")

            ChatSessionManager.delete_session(recording_path, self._session_id)

        self.clear_chat()
        self.refresh_sessions_dropdown()
        self._show_status("Chat deleted")

    def _show_status(self, text: str):
        from PyQt6.QtWidgets import QMainWindow
        parent = self.window()
        if isinstance(parent, QMainWindow):
            parent.statusBar().showMessage(text, 3000)

    # -- system prompt banner --

    def _ensure_system_prompt_banner(self, prompt_text: str):
        """Insert or update the system prompt banner at the top of the chat."""
        if not prompt_text:
            return
        if self._system_prompt_banner is None:
            self._system_prompt_banner = _SystemPromptBanner(prompt_text)
            self._history_layout.insertWidget(0, self._system_prompt_banner)
        else:
            self._system_prompt_banner.update_prompt(prompt_text)

    def _remove_system_prompt_banner(self):
        if self._system_prompt_banner is not None:
            self._system_prompt_banner.setParent(None)
            self._system_prompt_banner.deleteLater()
            self._system_prompt_banner = None

    # -- transcript context tracking --

    def _find_last_transcript_message(self) -> Optional[ChatMessage]:
        """Return the most recent transcript-bearing message, or None."""
        for msg in reversed(self._messages):
            if msg.has_transcript:
                return msg
        return None

    def _transcript_in_history_window(self) -> Optional[int]:
        """Return 1-based position of the most recent transcript-bearing
        message within the current history window, or None."""
        if not self._messages:
            return None
        window = self._messages[-self._max_history:]
        for i, msg in enumerate(window):
            if msg.has_transcript:
                return i + 1
        return None

    def _current_transcript_line_count(self) -> int:
        transcript = self._transcript_accessor()
        if not transcript or not transcript.strip():
            return 0
        return len(transcript.splitlines())

    def _update_transcript_indicator(self):
        """Refresh the transcript status label and enable/disable the
        transcript menu actions.  The button itself always stays visible
        with a fixed 'Transcript' label."""
        active_style = "font-size: 11px; color: palette(text);"
        muted_style = "font-size: 11px; color: palette(mid);"
        has_transcript = self._current_transcript_line_count() > 0

        last_tx_msg = self._find_last_transcript_message()
        current_lines = self._current_transcript_line_count()
        has_updates = (
            last_tx_msg is not None
            and current_lines > last_tx_msg.transcript_line_count)
        if last_tx_msg:
            self._last_transcript_line_count = last_tx_msg.transcript_line_count

        active_mode: str | None = None

        if self._skip_transcript:
            self._transcript_label.setText(
                "Chat History: no transcript")
            self._transcript_label.setStyleSheet(muted_style)
            active_mode = "none"
        elif self._force_include_transcript:
            if self._force_transcript_mode == "last_n":
                mode_label = (
                    f"last {self._force_transcript_lines} lines queued")
            elif self._force_transcript_mode == "updates":
                mode_label = "transcript update queued"
            else:
                mode_label = "full transcript queued"
            self._transcript_label.setText(f"Chat History: {mode_label}")
            self._transcript_label.setStyleSheet(active_style)
            active_mode = self._force_transcript_mode or "full"
        elif not self._first_message_sent:
            self._transcript_label.setText(
                "Chat History: full transcript auto-included on first send")
            self._transcript_label.setStyleSheet(active_style)
            active_mode = "auto_full"
        else:
            pos = self._transcript_in_history_window()
            total_msgs = len(self._messages)
            window_size = min(self._max_history, total_msgs)
            if pos is not None:
                time_str = (last_tx_msg.transcript_included_at
                            if last_tx_msg else "")
                mode = (last_tx_msg.transcript_mode
                        if last_tx_msg else "full")
                lines_sent = (last_tx_msg.transcript_lines_sent
                              if last_tx_msg else 0)

                if mode == "last_n" and lines_sent:
                    what = f"last {lines_sent} lines"
                elif mode == "updates":
                    what = "transcript update"
                else:
                    what = "transcript"

                base = f"Transcript in msg {pos} of {window_size}"
                if time_str:
                    base += f" ({time_str})"
                if has_updates:
                    new_count = current_lines - self._last_transcript_line_count
                    base += (f", +{new_count} new "
                             f"line{'s' if new_count != 1 else ''}")
                self._transcript_label.setText(base)
                self._transcript_label.setToolTip(
                    f"The {what} is in message {pos} of the "
                    f"{window_size}-message history window "
                    f"(max {self._max_history})")
                self._transcript_label.setStyleSheet(active_style)
            else:
                self._transcript_label.setText(
                    f"Transcript not in last {window_size} msgs")
                self._transcript_label.setToolTip(
                    f"The transcript was included earlier but has "
                    f"scrolled out of the {self._max_history}-message "
                    f"history window. Use the Transcript menu to "
                    f"re-include it.")
                self._transcript_label.setStyleSheet(muted_style)

        self._transcript_full_action.setEnabled(has_transcript)
        self._transcript_updates_action.setEnabled(has_updates)
        self._transcript_last_n_action.setEnabled(has_transcript)
        self._transcript_none_action.setEnabled(
            active_mode is not None and active_mode != "none")

    def _on_reinclude_transcript(self, mode: str = "full"):
        self._force_include_transcript = True
        self._force_transcript_mode = mode
        self._force_transcript_lines = 0
        self._skip_transcript = False
        self._update_transcript_indicator()

    def _on_no_transcript(self):
        """Opt out of transcript inclusion for the next message."""
        self._skip_transcript = True
        self._force_include_transcript = False
        self._force_transcript_mode = None
        self._force_transcript_lines = 0
        self._update_transcript_indicator()

    def _on_last_n_lines(self):
        """Open a dialog for the user to choose how many trailing lines to include."""
        total = self._current_transcript_line_count()
        if total <= 0:
            self._show_status("No transcript available")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Include Last N Lines")
        dlg.setFixedWidth(320)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(12)

        info_label = QLabel(f"The transcript currently has <b>{total}</b> lines.")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        prompt_label = QLabel("Include the last:")
        layout.addWidget(prompt_label)

        spin = QSpinBox()
        spin.setRange(1, total)
        spin.setValue(min(50, total))
        spin.setSuffix(" lines")
        spin.setFixedWidth(160)
        layout.addWidget(spin)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(dlg.accept)
        btn_box.rejected.connect(dlg.reject)
        layout.addWidget(btn_box)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._force_include_transcript = True
            self._force_transcript_mode = "last_n"
            self._force_transcript_lines = spin.value()
            self._skip_transcript = False
            self._update_transcript_indicator()

    def _on_transcript_info(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("How Transcript Context Works")
        dlg.setFixedSize(460, 420)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(12, 12, 12, 12)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setReadOnly(True)
        browser.setHtml(
            "<h3>How Transcript Context Works</h3>"
            "<p>The meeting transcript is automatically included with your "
            "<b>first message</b> in a new chat session.</p>"
            "<p>As the conversation grows, older messages leave the "
            "chat history window (controlled by "
            "<code>max_history_messages</code> in config). The status "
            "indicator shows whether the transcript is still within "
            "that window.</p>"
            "<h3>Re-including the Transcript</h3>"
            "<p>Use the <b>Transcript</b> dropdown button to re-attach "
            "the transcript at any time:</p>"
            "<ul>"
            "<li><b>Full Transcript</b> &mdash; sends the "
            "entire current transcript with the next message.</li>"
            "<li><b>New Since Last Include</b> &mdash; sends only "
            "lines added since the transcript was last included. "
            "This option is enabled when the transcript has grown "
            "(e.g. after a new capture).</li>"
            "<li><b>Last N Lines&hellip;</b> &mdash; opens a dialog "
            "where you choose how many trailing lines to include. "
            "The dialog shows the total line count so you can "
            "decide how much context to send.</li>"
            "<li><b>No Transcript</b> &mdash; skips transcript "
            "inclusion entirely for the next message. Useful when "
            "you want to ask the LLM a question unrelated to the "
            "meeting, or if you want to start chatting without any "
            "transcript context.</li>"
            "</ul>"
            "<h3>Capture Updates</h3>"
            "<p>When a transcript capture completes (manual or auto), "
            "the status indicator updates automatically to show how "
            "many new lines are available.</p>"
            "<h3>Transcript in Chat Bubbles</h3>"
            "<p>Each user message that included a transcript shows a "
            "collapsible <b>Transcript</b> section below the message "
            "text. Click the toggle to see exactly what was sent. "
            "The label indicates the mode (Full Transcript, last N "
            "lines, or Transcript Update).</p>"
            "<h3>System Prompt</h3>"
            "<p>A collapsible <b>System Prompt</b> banner at the top "
            "of the chat history shows the preamble that is prepended "
            "to every prompt.</p>"
            "<h3>Backups</h3>"
            "<p>A full copy of the transcript is saved to the "
            "recording&rsquo;s <code>.backup/</code> folder each time "
            "it is included in a chat message.</p>"
            "<h3>Starting Fresh</h3>"
            "<p>Select <b>New Chat</b> from the session dropdown to "
            "start a new conversation with a fresh context and no "
            "history.</p>"
        )
        layout.addWidget(browser)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn_box.rejected.connect(dlg.accept)
        layout.addWidget(btn_box)

        dlg.exec()

    # -- transcript backup --

    def _save_transcript_backup(self, transcript_text: str):
        """Write the full transcript to <recording>/.backup/transcript_<session_id>.txt."""
        recording_path = self._recording_path_fn()
        if not recording_path or not self._session_id:
            return
        backup_dir = recording_path / ".backup"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_file = backup_dir / f"transcript_{self._session_id}.txt"
        try:
            backup_file.write_text(transcript_text, encoding="utf-8")
            logger.debug(f"Chat: transcript backup saved to {backup_file}")
        except Exception as e:
            logger.warning(f"Chat: failed to save transcript backup: {e}")

    # -- send / receive --

    def _on_send(self):
        text = self._input.toPlainText().strip()
        if not text:
            return
        if self._chat_worker and self._chat_worker.isRunning():
            return

        if not self._session_id:
            self._session_id = ChatSessionManager.generate_id()

        include_transcript = (
            (not self._first_message_sent and not self._skip_transcript)
            or self._force_include_transcript
        )

        transcript_text_to_send = ""
        transcript_line_count = 0
        transcript_included_at = ""
        transcript_mode = self._force_transcript_mode or "full"

        transcript_start_line = 0
        transcript_lines_sent = 0

        if include_transcript:
            full_transcript = self._transcript_accessor()
            if full_transcript and full_transcript.strip():
                lines = full_transcript.splitlines()
                transcript_line_count = len(lines)
                transcript_included_at = datetime.now().strftime("%I:%M %p")

                self._save_transcript_backup(full_transcript)

                if (transcript_mode == "last_n"
                        and self._force_transcript_lines > 0):
                    n = min(self._force_transcript_lines, len(lines))
                    transcript_text_to_send = "\n".join(lines[-n:])
                    transcript_start_line = len(lines) - n
                    transcript_lines_sent = n
                elif (transcript_mode == "updates"
                        and self._last_transcript_line_count > 0
                        and self._last_transcript_line_count < len(lines)):
                    transcript_text_to_send = "\n".join(
                        lines[self._last_transcript_line_count:])
                    transcript_start_line = self._last_transcript_line_count
                    transcript_lines_sent = (len(lines)
                                             - self._last_transcript_line_count)
                else:
                    transcript_text_to_send = full_transcript.strip()
                    transcript_mode = "full"
                    transcript_start_line = 0
                    transcript_lines_sent = len(lines)

                self._last_transcript_line_count = transcript_line_count

        is_dark = self._is_dark_fn()

        user_msg = ChatMessage(
            "user", text,
            has_transcript=bool(transcript_text_to_send),
            transcript_line_count=transcript_line_count,
            transcript_included_at=transcript_included_at,
            transcript_mode=transcript_mode if transcript_text_to_send else "",
            transcript_lines_sent=transcript_lines_sent,
            transcript_start_line=transcript_start_line,
            transcript_backup_file=(
                f".backup/transcript_{self._session_id}.txt"
                if transcript_text_to_send else ""),
        )
        self._messages.append(user_msg)

        if not self._first_message_sent:
            self._ensure_system_prompt_banner(self._system_prompt)

        user_bubble = _MessageBubble("user", is_dark,
                                     assistant_name=self._assistant_name)
        user_bubble.set_content(text)

        if transcript_text_to_send:
            tx_label = _transcript_mode_label(transcript_mode,
                                              transcript_lines_sent)
            user_bubble.set_transcript(transcript_text_to_send, tx_label)

        idx = max(0, self._history_layout.count() - 1)
        self._history_layout.insertWidget(idx, user_bubble)

        self._input.clear()

        assistant_bubble = _MessageBubble(
            "assistant", is_dark, assistant_name=self._assistant_name)
        assistant_bubble.show_loading()
        idx = max(0, self._history_layout.count() - 1)
        self._history_layout.insertWidget(idx, assistant_bubble)
        self._current_bubble = assistant_bubble

        self._send_btn.setEnabled(False)
        self._input.setEnabled(False)

        prompt = self._build_prompt(
            text,
            transcript_text=transcript_text_to_send,
            transcript_mode=transcript_mode,
        )
        self._last_prompt = prompt

        logger.info(f"Chat: sending prompt to {self._cli_binary}, "
                    f"model={self._model or 'auto'}, "
                    f"include_transcript={bool(transcript_text_to_send)}, "
                    f"transcript_mode={transcript_mode}")
        if self._chat_logging:
            logger.debug(f"Chat prompt --- CLI: {self._cli_binary}, "
                         f"Model: {self._model or 'auto'}, "
                         f"Connection: {self._connection or '(default)'}\n"
                         f"{prompt}")

        self._first_message_sent = True
        self._force_include_transcript = False
        self._force_transcript_mode = None
        self._force_transcript_lines = 0
        self._skip_transcript = False
        self._update_transcript_indicator()

        QTimer.singleShot(50, self._scroll_to_bottom)

        self._chat_worker = ChatCLIWorker(
            prompt=prompt,
            model=self._model,
            connection=self._connection,
            cli_binary=self._cli_binary,
            cli_extra_args=self._cli_extra_args,
        )
        self._chat_worker.thinking_update.connect(self._on_thinking_update)
        self._chat_worker.text_update.connect(self._on_text_update)
        self._chat_worker.tool_use_update.connect(self._on_tool_use_update)
        self._chat_worker.finished.connect(self._on_finished)
        self._chat_worker.start()

    def _build_prompt(self, user_text: str, *,
                      transcript_text: str = "",
                      transcript_mode: str = "full") -> str:
        parts: list[str] = []

        if self._system_prompt:
            parts.append(self._system_prompt)

        history_window = self._messages[:-1][-self._max_history:]
        for msg in history_window:
            if msg.is_error:
                continue
            role_tag = "User" if msg.role == "user" else "Assistant"
            parts.append(f"\n{role_tag}: {msg.content}")

        parts.append(f"\nUser: {user_text}")

        if transcript_text and transcript_text.strip():
            if transcript_mode == "last_n":
                n = len(transcript_text.strip().splitlines())
                header = f"--- Transcript (last {n} lines) ---"
            elif transcript_mode == "updates":
                header = "--- Transcript Update (new content) ---"
            else:
                header = "--- Meeting Transcript ---"
            parts.append(f"\n\n{header}\n{transcript_text.strip()}")

        return "\n".join(parts)

    def _on_thinking_update(self, chunk: str):
        if self._current_bubble:
            self._current_bubble.append_thinking(chunk)
            QTimer.singleShot(10, self._scroll_to_bottom)

    def _on_text_update(self, chunk: str):
        if self._current_bubble:
            self._current_bubble.collapse_thinking()
            self._current_bubble.append_text(chunk)
            QTimer.singleShot(10, self._scroll_to_bottom)

    def _on_tool_use_update(self, status: str):
        if self._current_bubble:
            self._current_bubble.set_tool_status(status)
            QTimer.singleShot(10, self._scroll_to_bottom)

    def _on_finished(self, full_thinking: str, full_text: str,
                     stderr: str, exit_code: int):
        logger.debug(f"Chat finished: exit_code={exit_code}, "
                     f"text_len={len(full_text)}, stderr_len={len(stderr)}")

        is_error = False

        if self._current_bubble:
            self._current_bubble.hide_loading()
            self._current_bubble.collapse_thinking()
            if exit_code == -2:
                is_error = True
                self._current_bubble.set_content("*Chat cancelled.*")
            elif exit_code != 0 and not full_text.strip():
                is_error = True
                error_summary = self._extract_error_summary(stderr, exit_code)
                self._current_bubble.set_content(error_summary)

        if is_error:
            error_content = (
                full_text.strip() if full_text.strip()
                else self._extract_error_summary(stderr, exit_code))
            assistant_msg = ChatMessage(
                "assistant", error_content, full_thinking, is_error=True)
        else:
            assistant_msg = ChatMessage(
                "assistant", full_text, full_thinking)
        self._messages.append(assistant_msg)

        if self._chat_logging:
            logger.debug(
                f"Chat response --- Exit code: {exit_code}\n"
                + (f"Thinking:\n{full_thinking}\n\n" if full_thinking else "")
                + f"Response:\n{full_text}"
                + (f"\nStderr:\n{stderr}" if stderr.strip() else ""))

        self._current_bubble = None
        self._chat_worker = None
        self._send_btn.setEnabled(True)
        self._input.setEnabled(True)
        self._input.setFocus()
        self._update_transcript_indicator()

        self._persist_session()

        if self._auto_save:
            self.save_chat()

        QTimer.singleShot(50, self._scroll_to_bottom)

    @staticmethod
    def _extract_error_summary(stderr: str, exit_code: int) -> str:
        """Extract a concise error message from stderr.

        Returns the last non-empty line (typically the actual error) as the
        summary, with the full output in a collapsible details block.
        """
        if not stderr.strip():
            return f"**Error:** CLI exited with code {exit_code}"
        lines = [ln for ln in stderr.strip().splitlines() if ln.strip()]
        summary = lines[-1] if lines else f"Exit code {exit_code}"
        if len(lines) <= 3:
            return f"**Error:** {stderr.strip()}"
        return (
            f"**Error:** {summary}\n\n"
            f"<details><summary>Full output</summary>\n\n"
            f"```\n{stderr.strip()}\n```\n\n</details>"
        )

    def _persist_session(self):
        """Save session JSON and update manifest after each turn."""
        recording_path = self._recording_path_fn()
        if not recording_path or not self._session_id:
            return
        try:
            session_data = SessionData(
                id=self._session_id,
                model=self._model,
                connection=self._connection,
                assistant_name=self._assistant_name,
                cli_binary=self._cli_binary,
                system_prompt=self._system_prompt,
                messages=list(self._messages),
            )
            ChatSessionManager.save_session(recording_path, session_data)

            first_user = next(
                (m.content for m in self._messages if m.role == "user"), "")
            title = first_user[:80].replace("\n", " ").strip() or self._session_id
            now = datetime.now()

            existing = ChatSessionManager.list_sessions(recording_path)
            created = now.isoformat()
            prev_md = ""
            for entry in existing:
                if entry.id == self._session_id:
                    created = entry.created
                    prev_md = entry.markdown_file
                    break

            md_file_str = prev_md
            if not md_file_str or not Path(md_file_str).exists():
                if self._chat_export_directory:
                    candidate = (Path(self._chat_export_directory)
                                 / f"chat_{self._session_id}.md")
                else:
                    candidate = (recording_path / "chats"
                                 / f"chat_{self._session_id}.md")
                if candidate.exists():
                    md_file_str = str(candidate)
                else:
                    md_file_str = ""

            meta = ChatSessionMeta(
                id=self._session_id,
                created=created,
                updated=now.isoformat(),
                title=title,
                model=self._model,
                cli_binary=self._cli_binary,
                assistant_name=self._assistant_name,
                message_count=len(self._messages),
                markdown_file=md_file_str,
                session_file=f"sessions/{self._session_id}.json",
                transcript_directory=str(recording_path),
            )
            ChatSessionManager.update_manifest(recording_path, meta)
            self.refresh_sessions_dropdown()
        except Exception as e:
            logger.warning(f"Chat: failed to persist session: {e}")

    def _scroll_to_bottom(self):
        sb = self._scroll_area.verticalScrollBar()
        sb.setValue(sb.maximum())
