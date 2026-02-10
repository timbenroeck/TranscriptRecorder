"""
Calendar configuration and event-picker dialogs for Google Calendar integration.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path
from typing import Dict, List, Optional

from PyQt6.QtCore import QDate, QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCalendarWidget,
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui.calendar_integration import (
    _HAS_GOOGLE,
    filter_events,
    format_event_label,
    is_all_day,
    parse_event_for_meeting,
)
from gui.constants import APP_SUPPORT_DIR, logger
from gui.icons import IconManager


class CalendarConfigDialog(QDialog):
    """Simple dialog for configuring Google Calendar integration.

    Provides:
    - An "Enable Google Calendar" checkbox
    - A file picker for the client_secret.json path
    - Save / Cancel buttons
    """

    def __init__(self, current_settings: Dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Google Calendar Configuration")
        self.setMinimumWidth(520)
        self.setModal(True)

        self._settings = dict(current_settings)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)

        # Warning when libraries are missing
        if not _HAS_GOOGLE:
            is_bundled_app = getattr(sys, "frozen", False)
            if is_bundled_app:
                warn_text = (
                    "The Google API libraries could not be loaded in this "
                    "build. Calendar integration will not work.\n\n"
                    "Please update to a newer release that includes the "
                    "Google Calendar libraries."
                )
            else:
                warn_text = (
                    "The Google API libraries could not be loaded. "
                    "Calendar integration will not work.\n\n"
                    "Install them with:\n"
                    "  pip install google-auth google-auth-oauthlib "
                    "google-api-python-client"
                )
            warn = QLabel(warn_text)
            warn.setObjectName("secondary_label")
            warn.setWordWrap(True)
            warn.setStyleSheet("color: #B78B00; font-style: italic;")
            layout.addWidget(warn)

        info = QLabel(
            "Connect your Google Calendar to populate meeting details "
            "(date/time, name, attendees, description) from today's events.\n\n"
            "You need a Google Cloud OAuth client secret file (JSON). "
            "You can create one at console.cloud.google.com or use one "
            "provided by your administrator."
        )
        info.setObjectName("secondary_label")
        info.setWordWrap(True)
        layout.addWidget(info)

        # Enable checkbox
        self.enable_cb = QCheckBox("Enable Google Calendar integration")
        self.enable_cb.setChecked(self._settings.get("enabled", False))
        layout.addWidget(self.enable_cb)

        # Client secret path
        path_layout = QHBoxLayout()
        path_layout.setSpacing(6)

        path_label = QLabel("Client Secret:")
        path_layout.addWidget(path_label)

        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Path to client_secret.json...")
        self.path_edit.setText(self._settings.get("client_secret_path", ""))
        path_layout.addWidget(self.path_edit, stretch=1)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse)
        path_layout.addWidget(browse_btn)

        layout.addLayout(path_layout)

        # Validation hint
        self.hint_label = QLabel("")
        self.hint_label.setObjectName("secondary_label")
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label)

        layout.addStretch()

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        save_btn = QPushButton("Save")
        save_btn.setProperty("class", "primary")
        save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(save_btn)

        layout.addLayout(btn_layout)

        # Validate initial state
        self._validate()
        self.path_edit.textChanged.connect(self._validate)
        self.enable_cb.toggled.connect(self._validate)

    def _browse(self):
        """Open a file dialog to select the client_secret.json file."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Google Client Secret File",
            str(Path.home()),
            "JSON Files (*.json);;All Files (*)",
        )
        if path:
            self.path_edit.setText(path)

    def _is_path_in_app_support(self, path: str) -> bool:
        """Return True if *path* already lives inside the App Support dir."""
        try:
            return str(Path(path).resolve()).startswith(
                str(APP_SUPPORT_DIR.resolve())
            )
        except (OSError, ValueError):
            return False

    def _validate(self):
        """Update the hint label based on current input."""
        enabled = self.enable_cb.isChecked()
        path = self.path_edit.text().strip()

        if not enabled:
            self.hint_label.setText("Integration is disabled.")
            self.hint_label.setStyleSheet("")
            return

        if not path:
            self.hint_label.setText(
                "Please provide a path to your client_secret.json file."
            )
            self.hint_label.setStyleSheet("color: #B78B00;")
            return

        if not Path(path).is_file():
            self.hint_label.setText("File not found at the specified path.")
            self.hint_label.setStyleSheet("color: #C62828;")
            return

        if not _HAS_GOOGLE:
            self.hint_label.setText(
                "Configuration is valid, but Google API libraries are not "
                "available in this build."
            )
            self.hint_label.setStyleSheet("color: #B78B00;")
            return

        # Good to go
        if self._is_path_in_app_support(path):
            self.hint_label.setText("Configuration looks good.")
        else:
            self.hint_label.setText(
                "Configuration looks good. The file will be copied to "
                "application storage on save."
            )
        self.hint_label.setStyleSheet("color: #388E3C;")

    def _on_save(self):
        """Save and accept the dialog."""
        self.accept()

    def get_settings(self) -> Dict:
        """Return the configured settings as a dict for config.json."""
        return {
            "enabled": self.enable_cb.isChecked(),
            "client_secret_path": self.path_edit.text().strip(),
        }


# ---------------------------------------------------------------------------
# Event picker dialog
# ---------------------------------------------------------------------------

class CalendarEventsDialog(QDialog):
    """Dialog that displays calendar events for a selected date.

    Layout (top → bottom):

    1. Header row: **[date-picker button]** | refreshed label | refresh icon
    2. Filter row: Show all-day | Show declined
    3. Event list (stretch)
    4. Bottom row: Filter Conference Info | stretch | Cancel | Select
    5. Hidden QCalendarWidget (toggled by the date button)

    Signals
    -------
    refresh_requested(str)
        Emitted when the user clicks the refresh button or changes the
        date via the calendar picker.  The argument is the target date
        as an ISO string (``YYYY-MM-DD``).
    """

    refresh_requested = pyqtSignal(str)

    # Blue used for the date-picker button outline / hover
    _DATE_BTN_STYLE = (
        "QPushButton {"
        "  background: transparent;"
        "  border: 1px solid #1976D2;"
        "  border-radius: 4px;"
        "  padding: 2px 8px;"
        "  font-size: 15px;"
        "  font-weight: 600;"
        "  color: palette(text);"
        "}"
        "QPushButton:hover {"
        "  background: rgba(25, 118, 210, 0.08);"
        "  border-color: #1565C0;"
        "}"
    )

    def __init__(
        self,
        raw_events: List[dict],
        last_refreshed: Optional[str],
        *,
        target_date: Optional[datetime.date] = None,
        hint_time: Optional[datetime.time] = None,
        is_dark: bool = False,
        parent: Optional[QWidget] = None,
    ):
        """
        Parameters
        ----------
        hint_time:
            If provided, the event list will pre-select the event whose
            start time is closest to (but not after) *hint_time*.
        """
        super().__init__(parent)
        self._target_date = target_date or datetime.date.today()
        self._hint_time = hint_time
        self.setMinimumSize(460, 380)
        self.resize(520, 460)
        self.setModal(True)

        self._raw_events = raw_events
        self._is_dark = is_dark
        self._selected_event: Optional[dict] = None

        self._update_window_title()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(10)

        # --- Header row: [date button] | stretch | refreshed label | refresh ---
        header = QHBoxLayout()
        header.setSpacing(8)

        self._date_btn = QPushButton()
        self._date_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._date_btn.setStyleSheet(self._DATE_BTN_STYLE)
        self._date_btn.setToolTip("Click to pick a different date")
        self._date_btn.clicked.connect(self._toggle_calendar)
        self._update_date_button_text()
        header.addWidget(self._date_btn)

        header.addStretch()

        self._refreshed_label = QLabel()
        self._refreshed_label.setObjectName("secondary_label")
        self._refreshed_label.setStyleSheet("font-size: 12px;")
        header.addWidget(self._refreshed_label)
        self._update_refreshed_label(last_refreshed)

        self._refresh_btn = QPushButton()
        self._refresh_btn.setIcon(
            IconManager.get_icon("calendar_sync", is_dark=is_dark, size=18)
        )
        self._refresh_btn.setFixedSize(28, 28)
        self._refresh_btn.setIconSize(QSize(18, 18))
        self._refresh_btn.setToolTip("Refresh calendar events")
        self._refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; padding: 4px; }"
            "QPushButton:hover { background: palette(mid); border-radius: 4px; }"
        )
        self._refresh_btn.clicked.connect(self._on_refresh)
        header.addWidget(self._refresh_btn)

        layout.addLayout(header)

        # --- Filter checkboxes (all-day / declined) ---
        filter_row = QHBoxLayout()
        filter_row.setSpacing(16)

        self._show_all_day_cb = QCheckBox("Show all-day events")
        self._show_all_day_cb.setChecked(False)
        self._show_all_day_cb.toggled.connect(self._rebuild_list)
        filter_row.addWidget(self._show_all_day_cb)

        self._show_declined_cb = QCheckBox("Show declined")
        self._show_declined_cb.setChecked(False)
        self._show_declined_cb.toggled.connect(self._rebuild_list)
        filter_row.addWidget(self._show_declined_cb)

        filter_row.addStretch()
        layout.addLayout(filter_row)

        # --- Event list ---
        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        self._list.setSpacing(2)
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self._list, stretch=1)

        # --- Bottom row: conference-info filter | stretch | Cancel | Select ---
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)

        self._filter_conference_cb = QCheckBox("Filter conference info")
        self._filter_conference_cb.setChecked(True)
        self._filter_conference_cb.setToolTip(
            "When checked, Zoom/Teams/WebEx join links and boilerplate "
            "are removed from the meeting notes"
        )
        self._filter_conference_cb.toggled.connect(self._rebuild_list)
        bottom_row.addWidget(self._filter_conference_cb)

        bottom_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        bottom_row.addWidget(cancel_btn)

        self._select_btn = QPushButton("Select")
        self._select_btn.setProperty("class", "primary")
        self._select_btn.setEnabled(False)
        self._select_btn.clicked.connect(self._on_select)
        bottom_row.addWidget(self._select_btn)

        layout.addLayout(bottom_row)

        # --- Hidden calendar widget — toggled by date button ---
        self._calendar_widget = QCalendarWidget()
        self._calendar_widget.setSelectedDate(
            QDate(self._target_date.year, self._target_date.month, self._target_date.day)
        )
        self._calendar_widget.setGridVisible(True)
        self._calendar_widget.setVisible(False)
        self._calendar_widget.clicked.connect(self._on_date_picked)
        layout.addWidget(self._calendar_widget)

        # Wire selection change
        self._list.currentItemChanged.connect(self._on_selection_changed)

        # Build initial list
        self._rebuild_list()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def selected_event_data(self) -> Optional[dict]:
        """Return the parsed event dict for the selected event, or None."""
        return self._selected_event

    def target_date(self) -> datetime.date:
        """Return the date currently being viewed."""
        return self._target_date

    def update_events(
        self,
        raw_events: List[dict],
        last_refreshed: str,
        target_date_iso: Optional[str] = None,
    ):
        """Replace the event list with fresh data (called after a refresh)."""
        self._raw_events = raw_events
        if target_date_iso:
            self._target_date = datetime.date.fromisoformat(target_date_iso)
            self._update_window_title()
            self._update_date_button_text()
        self._update_refreshed_label(last_refreshed)
        self._rebuild_list()
        self._refresh_btn.setEnabled(True)

    def set_refreshing(self, refreshing: bool):
        """Toggle the refresh button enabled state while a fetch is running."""
        self._refresh_btn.setEnabled(not refreshing)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _update_window_title(self):
        self.setWindowTitle(
            self._target_date.strftime("Calendar Events — %A, %b %-d")
        )

    def _date_display_text(self) -> str:
        """Return a human-friendly date string for the date-picker button."""
        today = datetime.date.today()
        if self._target_date == today:
            return self._target_date.strftime("Today — %A, %B %-d")
        if self._target_date == today - datetime.timedelta(days=1):
            return self._target_date.strftime("Yesterday — %A, %B %-d")
        if self._target_date == today + datetime.timedelta(days=1):
            return self._target_date.strftime("Tomorrow — %A, %B %-d")
        return self._target_date.strftime("%A, %B %-d, %Y")

    def _update_date_button_text(self):
        self._date_btn.setText(self._date_display_text())

    def _update_refreshed_label(self, iso_ts: Optional[str]):
        if not iso_ts:
            self._refreshed_label.setText("Not yet refreshed")
            return
        try:
            dt = datetime.datetime.fromisoformat(iso_ts)
            self._refreshed_label.setText(
                f"Last refreshed: {dt.strftime('%I:%M %p').lstrip('0')}"
            )
        except (ValueError, TypeError):
            self._refreshed_label.setText(f"Last refreshed: {iso_ts}")

    def _rebuild_list(self, _toggled_value=None):
        """Refilter raw events and repopulate the list widget."""
        self._list.clear()
        self._select_btn.setEnabled(False)
        self._selected_event = None

        include_all_day = self._show_all_day_cb.isChecked()
        include_declined = self._show_declined_cb.isChecked()
        filter_conf = self._filter_conference_cb.isChecked()

        logger.debug(
            f"CalendarEventsDialog._rebuild_list: "
            f"raw={len(self._raw_events)}, "
            f"include_all_day={include_all_day}, "
            f"include_declined={include_declined}, "
            f"filter_conference={filter_conf}"
        )

        filtered = filter_events(
            self._raw_events,
            include_all_day=include_all_day,
            include_declined=include_declined,
        )

        if not filtered:
            item = QListWidgetItem("No events for this day")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(item)
            return

        best_item: Optional[QListWidgetItem] = None
        best_delta: Optional[float] = None

        for raw_ev in filtered:
            parsed = parse_event_for_meeting(
                raw_ev, filter_conference_info=filter_conf,
            )
            label = format_event_label(raw_ev)
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, parsed)

            if is_all_day(raw_ev):
                item.setToolTip("All-day event")

            self._list.addItem(item)

            # Track the best match for hint_time pre-selection
            if self._hint_time and not is_all_day(raw_ev):
                ev_time = self._event_start_time(raw_ev)
                if ev_time is not None:
                    # Seconds from hint_time to event start
                    delta = (
                        ev_time.hour * 3600 + ev_time.minute * 60 + ev_time.second
                    ) - (
                        self._hint_time.hour * 3600
                        + self._hint_time.minute * 60
                        + self._hint_time.second
                    )
                    abs_delta = abs(delta)
                    if best_delta is None or abs_delta < best_delta:
                        best_delta = abs_delta
                        best_item = item

        # Pre-select the closest event
        if best_item is not None:
            self._list.setCurrentItem(best_item)
            self._list.scrollToItem(best_item)

    @staticmethod
    def _event_start_time(raw_ev: dict) -> Optional[datetime.time]:
        """Extract the start time from a timed event, or None."""
        dt_str = raw_ev.get("start", {}).get("dateTime", "")
        if not dt_str:
            return None
        try:
            return datetime.datetime.fromisoformat(dt_str).time()
        except (ValueError, TypeError):
            return None

    def _on_selection_changed(self, current: Optional[QListWidgetItem], _prev):
        has_sel = current is not None and current.flags() & Qt.ItemFlag.ItemIsSelectable
        self._select_btn.setEnabled(bool(has_sel))

    def _on_item_double_clicked(self, item: QListWidgetItem):
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
            self._selected_event = data
            self.accept()

    def _on_select(self):
        item = self._list.currentItem()
        if item:
            data = item.data(Qt.ItemDataRole.UserRole)
            if data:
                self._selected_event = data
                self.accept()

    def _on_refresh(self):
        self._refresh_btn.setEnabled(False)
        self.refresh_requested.emit(self._target_date.isoformat())

    def _toggle_calendar(self):
        vis = not self._calendar_widget.isVisible()
        self._calendar_widget.setVisible(vis)

    def _on_date_picked(self, qdate: QDate):
        new_date = datetime.date(qdate.year(), qdate.month(), qdate.day())
        if new_date == self._target_date:
            return
        self._target_date = new_date
        self._update_window_title()
        self._update_date_button_text()
        self._calendar_widget.setVisible(False)
        # Clear current events and request a fetch for the new date
        self._raw_events = []
        self._rebuild_list()
        self._refresh_btn.setEnabled(False)
        self.refresh_requested.emit(self._target_date.isoformat())
