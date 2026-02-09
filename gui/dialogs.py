"""
Dialog windows for log viewing, first-launch welcome, and themed message boxes.
"""
from __future__ import annotations

from enum import IntEnum
from pathlib import Path

from PyQt6.QtCore import QByteArray, QRectF, Qt, QUrl
from PyQt6.QtGui import QBrush, QColor, QDesktopServices, QFont, QPainter, QPainterPath, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QApplication, QDialog, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QFileDialog, QFrame,
    QSizePolicy,
)

import gui.constants as _constants
from gui.constants import logger, resource_path, DEFAULT_EXPORT_DIR, APP_NAME
from gui.icons import IconManager


class WelcomeDialog(QDialog):
    """First-launch welcome dialog that prompts the user to choose an export directory.

    Displays the app icon, a friendly welcome message, and offers three options:
    - Choose Folder… — open a native directory picker
    - Use Default    — accept ~/Documents/TranscriptRecordings
    - Cancel         — close without choosing (the app will exit)

    After the dialog is accepted, call :meth:`chosen_directory` to get the path.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Welcome to {APP_NAME}")
        self.setFixedWidth(460)
        self.setModal(True)

        self._chosen_dir: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(0)

        # --- App icon (SVG on branded background) ---
        icon_label = QLabel()
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_pixmap = self._render_app_icon(80)
        if icon_pixmap and not icon_pixmap.isNull():
            icon_label.setPixmap(icon_pixmap)
        layout.addWidget(icon_label)
        layout.addSpacing(14)

        # --- Heading ---
        heading = QLabel(f"Welcome to {APP_NAME}")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading.setStyleSheet("font-size: 20px; font-weight: 700; background: transparent;")
        layout.addWidget(heading)
        layout.addSpacing(10)

        # --- Description ---
        desc = QLabel(
            "Before you get started, choose a folder where your "
            "meeting recordings, transcripts, and tool data will be saved."
        )
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 13px; background: transparent;")
        layout.addWidget(desc)
        layout.addSpacing(18)

        # --- Default path hint ---
        default_str = str(DEFAULT_EXPORT_DIR).replace(str(Path.home()), "~")
        hint = QLabel(f"Default location:  {default_str}")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setObjectName("secondary_label")
        hint.setStyleSheet("background: transparent;")
        layout.addWidget(hint)
        layout.addSpacing(22)

        # --- Buttons ---
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedWidth(90)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        btn_layout.addStretch()

        use_default_btn = QPushButton("Use Default")
        use_default_btn.setProperty("class", "secondary-action")
        use_default_btn.setFixedWidth(120)
        use_default_btn.clicked.connect(self._use_default)
        btn_layout.addWidget(use_default_btn)

        choose_btn = QPushButton("Choose Folder…")
        choose_btn.setProperty("class", "primary")
        choose_btn.setFixedWidth(140)
        choose_btn.setDefault(True)
        choose_btn.clicked.connect(self._choose_folder)
        btn_layout.addWidget(choose_btn)

        layout.addLayout(btn_layout)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def chosen_directory(self) -> str | None:
        """The directory the user selected, or *None* if they cancelled."""
        return self._chosen_dir

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _use_default(self):
        """Accept the default export directory."""
        self._chosen_dir = str(DEFAULT_EXPORT_DIR)
        self.accept()

    def _choose_folder(self):
        """Open a native directory picker."""
        chosen = QFileDialog.getExistingDirectory(
            self,
            "Choose Export Directory",
            str(DEFAULT_EXPORT_DIR),
            QFileDialog.Option.ShowDirsOnly,
        )
        if chosen:
            self._chosen_dir = chosen
            self.accept()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _render_app_icon(size: int) -> QPixmap | None:
        """Render the app SVG icon on a rounded #4292B9 background.

        Returns a Retina-quality QPixmap, or *None* if the SVG file is
        missing or cannot be parsed.
        """
        svg_path = resource_path("transcript_recorder_icon.svg")
        if not svg_path.exists():
            return None

        svg_data = svg_path.read_text(encoding="utf-8")
        # Tint strokes to white so they pop against the blue background
        svg_data = svg_data.replace('stroke="#1e1e1e"', 'stroke="#FFFFFF"')

        renderer = QSvgRenderer(QByteArray(svg_data.encode("utf-8")))
        if not renderer.isValid():
            return None

        # Retina scaling
        dpr = 1.0
        app = QApplication.instance()
        if app is not None:
            screen = app.primaryScreen()
            if screen is not None:
                dpr = screen.devicePixelRatio()

        physical = int(size * dpr)
        pixmap = QPixmap(physical, physical)
        pixmap.fill(Qt.GlobalColor.transparent)
        pixmap.setDevicePixelRatio(dpr)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw rounded-rect background (#4292B9)
        corner = size * 0.22  # macOS-style rounding
        bg_path = QPainterPath()
        bg_path.addRoundedRect(QRectF(0, 0, size, size), corner, corner)
        painter.fillPath(bg_path, QBrush(QColor("#4292B9")))

        # Centre the SVG inside the background with padding
        padding = size * 0.12
        icon_rect = QRectF(padding, padding, size - 2 * padding, size - 2 * padding)
        renderer.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        renderer.render(painter, icon_rect)

        painter.end()
        return pixmap


class PermissionsDialog(QDialog):
    """Styled dialog explaining that Accessibility permission is required.

    Shows a two-step visual guide using the hand (Privacy & Security) and
    person-standing (Accessibility) Lucide icons, with an optional button
    to open System Settings directly.
    """

    def __init__(self, parent=None, *, is_dark: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Permission Required")
        self.setFixedWidth(480)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(0)

        # --- Heading ---
        heading = QLabel("Accessibility Permission Required")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading.setStyleSheet("font-size: 18px; font-weight: 700; background: transparent;")
        layout.addWidget(heading)
        layout.addSpacing(8)

        # --- Description ---
        desc = QLabel(
            f"{APP_NAME} needs Accessibility access to read live meeting "
            "transcripts. Without it, transcript capture won't work."
        )
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 13px; background: transparent;")
        layout.addWidget(desc)
        layout.addSpacing(20)

        # --- Step-by-step instructions ---
        steps_widget = QWidget()
        steps_widget.setStyleSheet("background: transparent;")
        steps_layout = QVBoxLayout(steps_widget)
        steps_layout.setContentsMargins(16, 0, 16, 0)
        steps_layout.setSpacing(12)

        # Step 1 — clickable link to open the settings pane directly
        _ax_url = "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
        step1 = self._make_step_row(
            icon_name="hand",
            is_dark=is_dark,
            step_num="1",
            text=(
                f'Open <a href="{_ax_url}">'
                "<b>System Settings → Privacy & Security</b></a>"
            ),
            open_links=True,
        )
        steps_layout.addWidget(step1)

        # Step 2
        step2 = self._make_step_row(
            icon_name="person_standing",
            is_dark=is_dark,
            step_num="2",
            text=f"Select <b>Accessibility</b> and enable <b>{APP_NAME}</b>",
        )
        steps_layout.addWidget(step2)

        layout.addWidget(steps_widget)
        layout.addSpacing(14)

        # --- Restart info banner ---
        banner = QFrame()
        banner.setObjectName("info_banner")
        banner_layout = QHBoxLayout(banner)
        banner_layout.setContentsMargins(12, 10, 12, 10)
        banner_layout.setSpacing(10)

        info_icon_lbl = QLabel()
        info_icon_lbl.setFixedSize(20, 20)
        info_icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_pixmap = IconManager.get_pixmap(
            "circle_alert", is_dark=is_dark, tint="primary", size=18,
        )
        info_icon_lbl.setPixmap(info_pixmap)
        banner_layout.addWidget(info_icon_lbl)

        banner_text = QLabel(
            "You will need to <b>restart</b> the app after granting permission."
        )
        banner_text.setWordWrap(True)
        banner_text.setStyleSheet("font-size: 12px;")
        banner_layout.addWidget(banner_text, 1)

        layout.addWidget(banner)
        layout.addSpacing(18)

        # --- Buttons ---
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        continue_btn = QPushButton("Continue Without Access")
        continue_btn.setFixedWidth(190)
        continue_btn.clicked.connect(self.accept)
        btn_layout.addWidget(continue_btn)

        btn_layout.addStretch()

        open_settings_btn = QPushButton("Open System Settings")
        open_settings_btn.setProperty("class", "primary")
        open_settings_btn.setFixedWidth(180)
        open_settings_btn.setDefault(True)
        open_settings_btn.clicked.connect(self._open_settings)
        btn_layout.addWidget(open_settings_btn)

        layout.addLayout(btn_layout)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    _AX_SETTINGS_URL = "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"

    @staticmethod
    def _make_step_row(
        icon_name: str, is_dark: bool, step_num: str, text: str,
        *, open_links: bool = False,
    ) -> QWidget:
        """Build a single instruction row: [icon]  1.  Instruction text."""
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)

        # Lucide icon
        icon_lbl = QLabel()
        icon_lbl.setFixedSize(28, 28)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon = IconManager.get_icon(icon_name, is_dark=is_dark, tint="primary", size=24)
        icon_lbl.setPixmap(icon.pixmap(24, 24))
        icon_lbl.setStyleSheet("background: transparent;")
        h.addWidget(icon_lbl)

        # Step text (optionally with a clickable link)
        lbl = QLabel(f"<span style='font-weight:600;'>{step_num}.</span>  {text}")
        lbl.setWordWrap(True)
        lbl.setStyleSheet("font-size: 13px; background: transparent;")
        if open_links:
            lbl.setOpenExternalLinks(True)
        h.addWidget(lbl, 1)

        return row

    def _open_settings(self):
        """Open macOS System Settings to the Accessibility pane."""
        QDesktopServices.openUrl(QUrl(self._AX_SETTINGS_URL))
        self.accept()


class ThemedMessageDialog(QDialog):
    """Modern, themed replacement for QMessageBox.

    Provides a consistent Slate & Charcoal styled dialog with Lucide circle
    icons for severity, word-wrapping message text, and buttons that follow
    the application style guide.

    Use the static convenience methods rather than instantiating directly:

        ThemedMessageDialog.info(parent, "Title", "message")
        ThemedMessageDialog.warning(parent, "Title", "message")
        ThemedMessageDialog.critical(parent, "Title", "message")
        if ThemedMessageDialog.question(parent, "Title", "question?"):
            ...
        result = ThemedMessageDialog.save_discard_cancel(parent, "Title", "msg")
        ThemedMessageDialog.about(parent, "About", "<h3>App</h3>...")
    """

    # ------------------------------------------------------------------
    # Result enum for save / discard / cancel
    # ------------------------------------------------------------------

    class Result(IntEnum):
        CANCEL = 0
        DISCARD = 1
        SAVE = 2

    # ------------------------------------------------------------------
    # Icon / tint mapping per severity level
    # ------------------------------------------------------------------

    _LEVEL_ICON: dict[str, tuple[str, str]] = {
        # level -> (icon_name, tint)
        "info":     ("circle_check", "primary"),
        "warning":  ("circle_alert", "danger_fill"),
        "critical": ("circle_x",     "danger"),
        "question": ("circle_help",  "warning"),
    }

    # ------------------------------------------------------------------
    # Constructor (prefer the static helpers below)
    # ------------------------------------------------------------------

    def __init__(
        self,
        parent: QWidget | None,
        title: str,
        message: str,
        level: str = "info",
        buttons: list[tuple[str, str, str | None]] | None = None,
        *,
        rich: bool = False,
    ):
        """Create a themed message dialog.

        Parameters
        ----------
        parent:
            Parent widget.
        title:
            Bold heading displayed in the dialog.
        message:
            Body text (word-wrapped automatically). If *rich* is True the
            text is rendered as HTML.
        level:
            One of ``"info"``, ``"warning"``, ``"critical"``, ``"question"``,
            or ``"about"`` (uses the app icon).
        buttons:
            List of ``(label, class_name_or_empty, result_key)`` tuples.
            *class_name_or_empty* maps to the QSS ``class`` property
            (e.g. ``"primary"``, ``""`` for default).  *result_key* is
            stored on the button and returned by :pymethod:`exec` as the
            dialog's ``result()`` value.  The **last** button in the list
            is made the default / focused button.
        rich:
            If True, render *message* as HTML.
        """
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedWidth(460)
        self.setModal(True)

        self._result_value: int = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 20)
        outer.setSpacing(0)

        # --- Content row: icon | title + message ---
        content_row = QHBoxLayout()
        content_row.setSpacing(16)
        content_row.setContentsMargins(0, 0, 0, 0)

        # Icon
        _ICON_SIZE = 56
        icon_label = QLabel()
        icon_label.setFixedSize(_ICON_SIZE, _ICON_SIZE)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        icon_label.setStyleSheet("background: transparent;")

        is_dark = self._detect_dark_mode()

        if level == "about":
            pixmap = WelcomeDialog._render_app_icon(_ICON_SIZE)
            if pixmap and not pixmap.isNull():
                icon_label.setPixmap(pixmap)
        else:
            icon_name, tint = self._LEVEL_ICON.get(level, ("circle_check", "primary"))
            pixmap = IconManager.get_pixmap(icon_name, is_dark=is_dark, tint=tint, size=_ICON_SIZE)
            icon_label.setPixmap(pixmap)

        content_row.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)

        # Text column
        text_col = QVBoxLayout()
        text_col.setSpacing(6)
        text_col.setContentsMargins(0, 2, 0, 0)

        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 16px; font-weight: 700; background: transparent;")
        title_label.setWordWrap(True)
        text_col.addWidget(title_label)

        msg_label = QLabel(message)
        msg_label.setWordWrap(True)
        msg_label.setStyleSheet("font-size: 13px; background: transparent;")
        if rich:
            msg_label.setTextFormat(Qt.TextFormat.RichText)
            msg_label.setOpenExternalLinks(True)
        text_col.addWidget(msg_label)

        text_col.addStretch()
        content_row.addLayout(text_col, 1)

        outer.addLayout(content_row)
        outer.addSpacing(20)

        # --- Buttons ---
        if buttons is None:
            buttons = [("OK", "primary", None)]

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.addStretch()

        last_btn: QPushButton | None = None
        for idx, (label, cls_name, _result_key) in enumerate(buttons):
            btn = QPushButton(label)
            if cls_name:
                btn.setProperty("class", cls_name)
            btn.setMinimumWidth(80)
            # Store the index so we can retrieve the result
            btn.clicked.connect(lambda checked=False, i=idx: self._on_button(i))
            btn_layout.addWidget(btn)
            last_btn = btn

        if last_btn is not None:
            last_btn.setDefault(True)
            last_btn.setFocus()

        outer.addLayout(btn_layout)
        self._buttons_spec = buttons

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_dark_mode() -> bool:
        """Return True if the application is currently in dark mode."""
        palette = QApplication.palette()
        return palette.window().color().lightness() < 128

    def _on_button(self, index: int):
        self._result_value = index
        self.accept()

    # ------------------------------------------------------------------
    # Static convenience methods
    # ------------------------------------------------------------------

    @staticmethod
    def info(parent: QWidget | None, title: str, message: str) -> None:
        """Show an informational dialog with an OK button."""
        dlg = ThemedMessageDialog(
            parent, title, message, level="info",
            buttons=[("OK", "primary", None)],
        )
        dlg.exec()

    @staticmethod
    def warning(parent: QWidget | None, title: str, message: str) -> None:
        """Show a warning dialog with an OK button."""
        dlg = ThemedMessageDialog(
            parent, title, message, level="warning",
            buttons=[("OK", "primary", None)],
        )
        dlg.exec()

    @staticmethod
    def critical(parent: QWidget | None, title: str, message: str) -> None:
        """Show a critical/error dialog with an OK button."""
        dlg = ThemedMessageDialog(
            parent, title, message, level="critical",
            buttons=[("OK", "primary", None)],
        )
        dlg.exec()

    @staticmethod
    def question(parent: QWidget | None, title: str, message: str) -> bool:
        """Show a Yes/No question dialog. Returns True if the user chose Yes."""
        dlg = ThemedMessageDialog(
            parent, title, message, level="question",
            buttons=[
                ("No", "", "no"),
                ("Yes", "primary", "yes"),
            ],
        )
        dlg.exec()
        return dlg._result_value == 1  # index of "Yes"

    @staticmethod
    def save_discard_cancel(
        parent: QWidget | None, title: str, message: str,
    ) -> "ThemedMessageDialog.Result":
        """Show a Save / Discard / Cancel dialog. Returns a Result enum."""
        dlg = ThemedMessageDialog(
            parent, title, message, level="warning",
            buttons=[
                ("Cancel", "", "cancel"),
                ("Discard", "danger-outline", "discard"),
                ("Save", "primary", "save"),
            ],
        )
        dlg.exec()
        return ThemedMessageDialog.Result(dlg._result_value)

    @staticmethod
    def about(parent: QWidget | None, title: str, html: str) -> None:
        """Show an About dialog with the app icon and rich HTML body."""
        dlg = ThemedMessageDialog(
            parent, title, html, level="about",
            buttons=[("OK", "primary", None)],
            rich=True,
        )
        dlg.exec()


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
        self.refresh_btn.setProperty("class", "action")
        self.refresh_btn.clicked.connect(self._load_log)
        btn_layout.addWidget(self.refresh_btn)
        
        self.clear_btn = QPushButton("Clear Log")
        self.clear_btn.setProperty("class", "danger-outline")
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
            
        if not ThemedMessageDialog.question(
            self, "Clear Log",
            "Are you sure you want to clear the log file?"
        ):
            return
        try:
            if log_path.exists():
                with open(log_path, 'w', encoding='utf-8') as f:
                    f.write("")
                self._load_log()
                logger.info("Log viewer: log file cleared by user")
        except Exception as e:
            ThemedMessageDialog.warning(self, "Error", f"Failed to clear log file: {e}")

