"""
Main application window for Transcript Recorder.
"""
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPoint, QSize
from PyQt6.QtGui import QAction, QActionGroup, QFont, QIcon, QPalette, QColor
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QTextEdit, QProgressBar,
    QFileDialog, QStatusBar, QGroupBox, QSpinBox,
    QSplitter, QFrame, QSizePolicy, QSystemTrayIcon, QMenu,
    QTabWidget, QLineEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QCheckBox, QInputDialog, QDialog,
)

from transcript_recorder import TranscriptRecorder, AXIsProcessTrusted
from transcript_utils import smart_merge
from version import __version__, GITHUB_OWNER, GITHUB_REPO

import gui.constants as _constants
from gui.constants import (
    APP_NAME, APP_VERSION, APP_SUPPORT_DIR, CONFIG_PATH, LOG_DIR,
    DEFAULT_EXPORT_DIR, MANUAL_RECORDING_KEY, MANUAL_RECORDING_SOURCE,
    logger, setup_logging, resource_path, _HAS_APPKIT,
)
from gui.styles import get_application_stylesheet
from gui.icons import IconManager
from gui.workers import (
    RecordingWorker, ToolRunnerWorker, StreamingToolRunnerWorker,
    UpdateCheckWorker, ToolFetchWorker, CalendarFetchWorker,
    STREAM_PARSERS, _stream_parser_raw, strip_ansi,
)
from gui.dialogs import LogViewerDialog, PermissionsDialog, ThemedMessageDialog, WelcomeDialog
from gui.tool_dialogs import ToolImportDialog, ToolJsonEditorDialog
from gui.data_editors import DataFileEditorDialog
from gui.calendar_integration import (
    _HAS_GOOGLE, CalendarConfig, calendar_config_from_dict,
    filter_events,
)


class DropDownComboBox(QComboBox):
    """QComboBox that always opens its popup below the widget.

    The default QComboBox on macOS positions the popup so the currently
    selected item aligns with the widget, which causes a "drop-up" effect
    when items near the end of the list are selected.  This subclass
    overrides ``showPopup`` to anchor the popup's top edge to the widget's
    bottom edge so the list always drops *down*.
    """

    def showPopup(self) -> None:
        super().showPopup()
        popup = self.view().parent()
        if popup is not None:
            # Anchor the popup top-left to the combo box bottom-left
            below = self.mapToGlobal(QPoint(0, self.height()))
            popup.move(below)


class TranscriptRecorderApp(QMainWindow):
    """Main application window for Transcript Recorder."""
    
    def __init__(self):
        super().__init__()
        
        # State
        self.config: Optional[Dict[str, Any]] = None
        self.selected_app_key: Optional[str] = None
        self.recorder_instance: Optional[TranscriptRecorder] = None
        self.recording_worker: Optional[RecordingWorker] = None
        self.current_recording_path: Optional[Path] = None
        self.snapshots_path: Optional[Path] = None  # Hidden .snapshots folder
        self.merged_transcript_path: Optional[Path] = None  # meeting_transcript.txt
        self.export_base_dir: Path = DEFAULT_EXPORT_DIR
        self.is_recording = False
        self.snapshot_count = 0
        self._is_capturing = False  # True while a capture+merge is in progress
        self._last_merged_line_count = 0  # Track line count for delta display
        self.capture_interval = 30  # Default capture interval in seconds
        self.theme_mode = "system"  # "light", "dark", or "system"
        self.meeting_details_dirty = False  # Track if meeting details need saving
        self._discovered_sources: Dict[str, dict] = {}  # source_key -> parsed source.json
        self._sources_dir: Optional[Path] = None
        self._discovered_tools: Dict[str, dict] = {}  # tool_key -> parsed JSON definition
        self._tool_scripts_dir: Optional[Path] = None
        self._tool_runner: Optional[ToolRunnerWorker] = None
        self._data_file_editors: List[DataFileEditorDialog] = []  # keep refs alive
        self._tool_start_time: float = 0.0  # time.time() when tool started
        self._tool_elapsed_timer: Optional[QTimer] = None  # ticks every second while tool runs
        self._idle_warning_seconds: int = 30   # overwritten per-tool from tool.json
        self._idle_kill_seconds: int = 120     # overwritten per-tool from tool.json
        self._compact_mode = False  # Track compact/expanded view state
        self._maximized_view = False  # Track maximize/restore view state
        self._expanded_size = None  # Remember window size before compacting
        self._default_size = QSize(600, 450)
        self._maximized_size = QSize(960, 720)
        self._has_accessibility = True  # Assume granted; _check_permissions will update
        self._closing = False  # Set when the app is about to exit (e.g. user cancelled setup)
        self._is_manual_mode = False  # True when the built-in Manual Recording source is active
        self._transcript_edit_mode = False  # True when the transcript is user-editable
        self._transcript_modified = False  # True when transcript has unsaved edits
        self._is_history_session = False  # True when session was loaded from history
        self._loading_transcript = False  # Guard against textChanged during programmatic loads
        self._calendar_config: Optional[CalendarConfig] = None  # Google Calendar config
        self._calendar_worker: Optional[CalendarFetchWorker] = None  # Background fetch thread
        self._calendar_raw_events: list = []  # Cached raw events from last fetch
        self._calendar_last_refreshed: Optional[str] = None  # ISO timestamp of last fetch
        self._calendar_date_iso: Optional[str] = None  # ISO date of last fetch
        self._calendar_events_dialog: Optional[QDialog] = None  # Open events dialog ref
        self._calendar_fetch_silent: bool = False  # True when auto-fetching on launch
        
        # Setup UI
        self._setup_window()
        self._setup_ui()
        self._setup_menubar()
        self._setup_tray()
        self._load_config()
        if self._closing:
            return

        self._update_button_states()  # Set initial disabled state before permission check
        self._check_permissions()
        
        # Default window size (4:3 aspect ratio)
        self.resize(600, 450)
        
        # Start non-blocking update check in the background
        self._startup_update_worker = UpdateCheckWorker()
        self._startup_update_worker.update_available.connect(self._on_startup_update_available)
        self._startup_update_worker.start()
        
        # Apply screen sharing privacy default from config (defaults to hidden)
        if _HAS_APPKIT:
            privacy_default = True  # hidden by default
            if self.config:
                privacy_default = self.config.get("client_settings", {}).get(
                    "screen_sharing_hidden", True
                )
            QTimer.singleShot(100, lambda: self._set_privacy_mode(privacy_default))
        
    def _setup_window(self):
        """Configure main window properties."""
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(350, 300)
        # Will be adjusted to fit content after UI is built
        
        # Try to load app icon
        icon_path = resource_path("appicon.icns")
        if icon_path.exists():
            # On macOS, the app bundle's CFBundleIconFile provides the Dock
            # icon natively.  Calling setWindowIcon() overrides the native
            # rendering and strips the system-provided background that macOS
            # adds behind transparent icons, making the icon hard to see.
            # Only set the window icon on non-macOS platforms.
            if sys.platform != "darwin":
                self.setWindowIcon(QIcon(str(icon_path)))
        
        # macOS specific settings
        if sys.platform == "darwin":
            self.setUnifiedTitleAndToolBarOnMac(True)
    
    def _setup_ui(self):
        """Build the user interface."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(12, 8, 12, 4)
        main_layout.setSpacing(6)
        
        # === Application Selection Section ===
        app_group = QWidget()
        app_layout = QHBoxLayout(app_group)
        app_layout.setContentsMargins(0, 0, 0, 0)
        app_layout.setSpacing(8)
        
        is_dark = self._is_dark_mode()

        self.app_combo = DropDownComboBox()
        self.app_combo.setMinimumWidth(120)
        self.app_combo.currentIndexChanged.connect(self._on_app_changed)
        app_layout.addWidget(self.app_combo, stretch=1)
        
        self.new_btn = QPushButton("New")
        self.new_btn.setProperty("class", "primary")
        self.new_btn.setToolTip("Create a new meeting recording")
        self.new_btn.clicked.connect(self._on_new_recording)
        app_layout.addWidget(self.new_btn)
        
        self.load_previous_btn = QPushButton("History")
        self.load_previous_btn.setProperty("class", "secondary-action")
        self.load_previous_btn.setToolTip("Open a previous meeting and transcript")
        self.load_previous_btn.clicked.connect(self._on_load_previous_meeting)
        app_layout.addWidget(self.load_previous_btn)
        
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setProperty("class", "danger-outline")
        self.reset_btn.setEnabled(False)
        self.reset_btn.setToolTip("Clear the current meeting recording")
        self.reset_btn.clicked.connect(self._on_reset_recording)
        app_layout.addWidget(self.reset_btn)
        
        main_layout.addWidget(app_group)
        
        # === Recording Controls Section ===
        controls_group = QWidget()
        controls_layout = QHBoxLayout(controls_group)
        controls_layout.setContentsMargins(0, 4, 0, 4)
        controls_layout.setSpacing(8)
        
        self.capture_btn = QPushButton("Capture")
        self.capture_btn.setProperty("class", "action")
        self.capture_btn.setEnabled(False)
        self.capture_btn.setToolTip("Capture a single transcript snapshot")
        self.capture_btn.clicked.connect(self._on_capture_now)
        controls_layout.addWidget(self.capture_btn)
        
        self.auto_capture_btn = QPushButton("Auto Capture")
        self.auto_capture_btn.setProperty("class", "toggle_off")
        self.auto_capture_btn.setEnabled(False)
        self.auto_capture_btn.setMinimumWidth(120)  # Accommodate "Auto Capture" and "Stop (120s)"
        self.auto_capture_btn.setToolTip("Start continuous transcript capture")
        self.auto_capture_btn.clicked.connect(self._on_toggle_auto_capture)
        controls_layout.addWidget(self.auto_capture_btn)
        
        main_layout.addWidget(controls_group)
        
        # === Separator between controls and tab section ===
        self.separator_top = QFrame()
        self.separator_top.setFrameShape(QFrame.Shape.HLine)
        self.separator_top.setFrameShadow(QFrame.Shadow.Plain)
        self.separator_top.setFixedHeight(1)
        main_layout.addWidget(self.separator_top)
        
        # === Tabbed Section (Meeting Details & Transcript) ===
        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(False)
        self.tab_widget.tabBar().setExpanding(False)  # Left-align tabs
        self.tab_widget.tabBar().setDrawBase(False)  # Remove the line under tabs
        self.tab_widget.tabBar().setAutoFillBackground(False)
        self.tab_widget.setAutoFillBackground(False)
        
        # --- Meeting Details Tab (first/default) ---
        details_tab = QWidget()
        details_tab.setAutoFillBackground(False)
        details_layout = QVBoxLayout(details_tab)
        details_layout.setContentsMargins(0, 8, 0, 0)
        details_layout.setSpacing(8)
        
        # Meeting Date/Time
        datetime_layout = QHBoxLayout()
        datetime_layout.setSpacing(4)
        
        self.meeting_datetime_input = QLineEdit()
        self.meeting_datetime_input.setPlaceholderText("Date/Time...")
        self.meeting_datetime_input.textChanged.connect(self._on_meeting_details_changed)
        datetime_layout.addWidget(self.meeting_datetime_input, stretch=1)
        
        # Round time buttons -- side by side next to the text field
        is_dark = self._is_dark_mode()
        
        self.time_down_btn = QPushButton()
        self.time_down_btn.setObjectName("time_btn")
        self.time_down_btn.setIcon(IconManager.get_icon("arrow_down", is_dark=is_dark, size=20))
        self.time_down_btn.setFixedSize(28, 28)
        self.time_down_btn.setIconSize(QSize(20, 20))
        self.time_down_btn.setToolTip("Round meeting time down by 5 minutes")
        self.time_down_btn.clicked.connect(self._on_round_time_down)
        datetime_layout.addWidget(self.time_down_btn)
        
        self.time_up_btn = QPushButton()
        self.time_up_btn.setObjectName("time_btn")
        self.time_up_btn.setIcon(IconManager.get_icon("arrow_up", is_dark=is_dark, size=20))
        self.time_up_btn.setFixedSize(28, 28)
        self.time_up_btn.setIconSize(QSize(20, 20))
        self.time_up_btn.setToolTip("Round meeting time up by 5 minutes")
        self.time_up_btn.clicked.connect(self._on_round_time_up)
        datetime_layout.addWidget(self.time_up_btn)
        
        details_layout.addLayout(datetime_layout)
        
        # Meeting Name
        name_layout = QHBoxLayout()
        name_layout.setSpacing(4)
        
        self.meeting_name_input = QLineEdit()
        self.meeting_name_input.setPlaceholderText("Enter meeting name...")
        self.meeting_name_input.textChanged.connect(self._on_meeting_details_changed)
        name_layout.addWidget(self.meeting_name_input)
        
        details_layout.addLayout(name_layout)
        
        # Notes text area with vertical button bar on the right
        details_notes_row = QHBoxLayout()
        details_notes_row.setSpacing(6)
        
        self.meeting_notes_input = QTextEdit()
        self.meeting_notes_input.setPlaceholderText("Enter meeting notes, attendees, action items, etc...")
        self.meeting_notes_input.setFont(QFont("SF Pro", 12))
        self.meeting_notes_input.textChanged.connect(self._on_meeting_details_changed)
        details_notes_row.addWidget(self.meeting_notes_input)
        
        # Vertical button bar
        details_btn_bar = QFrame()
        details_btn_bar.setFrameShape(QFrame.Shape.StyledPanel)
        details_btn_bar.setStyleSheet(
            "QFrame { border: 1px solid palette(mid); border-radius: 4px; }"
        )
        details_btn_bar_layout = QVBoxLayout(details_btn_bar)
        details_btn_bar_layout.setContentsMargins(2, 4, 2, 4)
        details_btn_bar_layout.setSpacing(2)
        
        btn_style = (
            "QPushButton { background: transparent; border: none; padding: 4px; }"
            "QPushButton:hover { background: palette(mid); border-radius: 4px; }"
        )
        
        self.save_details_btn = QPushButton()
        self.save_details_btn.setIcon(
            IconManager.get_icon("save", is_dark=is_dark, size=16))
        self.save_details_btn.setIconSize(QSize(16, 16))
        self.save_details_btn.setFixedSize(28, 28)
        self.save_details_btn.setToolTip("Save meeting details to disk")
        self.save_details_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_details_btn.setStyleSheet(btn_style)
        self.save_details_btn.setEnabled(False)
        self.save_details_btn.clicked.connect(self._on_save_details_clicked)
        details_btn_bar_layout.addWidget(self.save_details_btn)
        
        self.open_folder_btn2 = QPushButton()
        self.open_folder_btn2.setIcon(
            IconManager.get_icon("folder_open", is_dark=is_dark, size=16))
        self.open_folder_btn2.setIconSize(QSize(16, 16))
        self.open_folder_btn2.setFixedSize(28, 28)
        self.open_folder_btn2.setToolTip("Open meeting folder in Finder")
        self.open_folder_btn2.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_folder_btn2.setStyleSheet(btn_style)
        self.open_folder_btn2.setEnabled(False)
        self.open_folder_btn2.clicked.connect(self._on_open_folder)
        details_btn_bar_layout.addWidget(self.open_folder_btn2)

        # Calendar button — visible when Google Calendar is configured
        self.calendar_btn = QPushButton()
        self.calendar_btn.setObjectName("calendar_btn")
        self.calendar_btn.setIcon(
            IconManager.get_icon("calendar", is_dark=is_dark, size=16))
        self.calendar_btn.setIconSize(QSize(16, 16))
        self.calendar_btn.setFixedSize(28, 28)
        self.calendar_btn.setToolTip("Load meeting details from Google Calendar")
        self.calendar_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.calendar_btn.setStyleSheet(btn_style)
        self.calendar_btn.setVisible(False)
        self.calendar_btn.clicked.connect(self._on_calendar_clicked)
        details_btn_bar_layout.addWidget(self.calendar_btn)

        details_notes_row.addWidget(details_btn_bar, alignment=Qt.AlignmentFlag.AlignTop)
        
        details_layout.addLayout(details_notes_row)
        
        self.tab_widget.addTab(details_tab, "Meeting Details")
        
        # --- Meeting Transcript Tab ---
        transcript_tab = QWidget()
        transcript_tab.setAutoFillBackground(False)
        transcript_layout = QVBoxLayout(transcript_tab)
        transcript_layout.setContentsMargins(0, 8, 0, 0)
        
        # Transcript text area with vertical button bar on the right
        transcript_row = QHBoxLayout()
        transcript_row.setSpacing(6)
        
        self.transcript_text = QTextEdit()
        self.transcript_text.setReadOnly(True)
        self.transcript_text.setPlaceholderText(
            "Transcript will appear here after recording starts...\n\n"
            "To begin:\n"
            "1. Select your meeting application above\n"
            "2. Make sure your meeting has captions/transcript enabled\n"
            "3. Click 'New' then 'Capture' or 'Auto Capture'"
        )
        self.transcript_text.setFont(QFont("SF Pro", 12))
        transcript_row.addWidget(self.transcript_text)
        
        # Vertical button bar
        transcript_btn_bar = QFrame()
        transcript_btn_bar.setFrameShape(QFrame.Shape.StyledPanel)
        transcript_btn_bar.setStyleSheet(
            "QFrame { border: 1px solid palette(mid); border-radius: 4px; }"
        )
        transcript_btn_bar_layout = QVBoxLayout(transcript_btn_bar)
        transcript_btn_bar_layout.setContentsMargins(2, 4, 2, 4)
        transcript_btn_bar_layout.setSpacing(2)
        
        btn_style = (
            "QPushButton { background: transparent; border: none; padding: 4px; }"
            "QPushButton:hover { background: palette(mid); border-radius: 4px; }"
        )
        
        self.edit_transcript_btn = QPushButton()
        self.edit_transcript_btn.setIcon(
            IconManager.get_icon("pencil", is_dark=is_dark, size=16))
        self.edit_transcript_btn.setIconSize(QSize(16, 16))
        self.edit_transcript_btn.setFixedSize(28, 28)
        self.edit_transcript_btn.setToolTip("Enable transcript editing")
        self.edit_transcript_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.edit_transcript_btn.setStyleSheet(btn_style)
        self.edit_transcript_btn.setEnabled(False)
        self.edit_transcript_btn.clicked.connect(self._on_edit_transcript_clicked)
        transcript_btn_bar_layout.addWidget(self.edit_transcript_btn)
        
        self.save_transcript_btn = QPushButton()
        self.save_transcript_btn.setIcon(
            IconManager.get_icon("save", is_dark=is_dark, size=16))
        self.save_transcript_btn.setIconSize(QSize(16, 16))
        self.save_transcript_btn.setFixedSize(28, 28)
        self.save_transcript_btn.setToolTip("Save transcript to disk")
        self.save_transcript_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_transcript_btn.setStyleSheet(btn_style)
        self.save_transcript_btn.setEnabled(False)
        self.save_transcript_btn.clicked.connect(self._on_save_transcript_clicked)
        transcript_btn_bar_layout.addWidget(self.save_transcript_btn)
        
        self.copy_btn = QPushButton()
        self.copy_btn.setIcon(
            IconManager.get_icon("copy", is_dark=is_dark, size=16))
        self.copy_btn.setIconSize(QSize(16, 16))
        self.copy_btn.setFixedSize(28, 28)
        self.copy_btn.setToolTip("Copy transcript to clipboard")
        self.copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_btn.setStyleSheet(btn_style)
        self.copy_btn.setEnabled(False)
        self.copy_btn.clicked.connect(self._on_copy_transcript)
        transcript_btn_bar_layout.addWidget(self.copy_btn)
        
        self.refresh_transcript_btn = QPushButton()
        self.refresh_transcript_btn.setIcon(
            IconManager.get_icon("refresh", is_dark=is_dark, size=16))
        self.refresh_transcript_btn.setIconSize(QSize(16, 16))
        self.refresh_transcript_btn.setFixedSize(28, 28)
        self.refresh_transcript_btn.setToolTip("Reload transcript from disk")
        self.refresh_transcript_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_transcript_btn.setStyleSheet(btn_style)
        self.refresh_transcript_btn.setEnabled(False)
        self.refresh_transcript_btn.clicked.connect(self._on_refresh_transcript)
        transcript_btn_bar_layout.addWidget(self.refresh_transcript_btn)
        
        self.open_folder_btn = QPushButton()
        self.open_folder_btn.setIcon(
            IconManager.get_icon("folder_open", is_dark=is_dark, size=16))
        self.open_folder_btn.setIconSize(QSize(16, 16))
        self.open_folder_btn.setFixedSize(28, 28)
        self.open_folder_btn.setToolTip("Open meeting folder in Finder")
        self.open_folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_folder_btn.setStyleSheet(btn_style)
        self.open_folder_btn.setEnabled(False)
        self.open_folder_btn.clicked.connect(self._on_open_folder)
        transcript_btn_bar_layout.addWidget(self.open_folder_btn)
        
        transcript_row.addWidget(transcript_btn_bar, alignment=Qt.AlignmentFlag.AlignTop)
        
        transcript_layout.addLayout(transcript_row)
        
        # Connect textChanged once; guarded by _loading_transcript and _transcript_edit_mode
        self.transcript_text.textChanged.connect(self._on_transcript_text_changed)
        
        self.tab_widget.addTab(transcript_tab, "Meeting Transcript")
        
        # --- Meeting Tools Tab ---
        tools_tab = QWidget()
        tools_tab.setAutoFillBackground(False)
        tools_layout = QVBoxLayout(tools_tab)
        tools_layout.setContentsMargins(0, 8, 0, 0)
        tools_layout.setSpacing(6)
        
        # Tool selection row
        tool_select_layout = QHBoxLayout()
        self.tool_combo = DropDownComboBox()
        self.tool_combo.setMinimumWidth(200)
        self.tool_combo.addItem("Select a tool...", None)
        self.tool_combo.currentIndexChanged.connect(self._on_tool_changed)
        tool_select_layout.addWidget(self.tool_combo, stretch=1)
        
        self.run_tool_btn = QPushButton("Run")
        self.run_tool_btn.setProperty("class", "action")
        self.run_tool_btn.setFixedWidth(100)
        self.run_tool_btn.setEnabled(False)
        self.run_tool_btn.clicked.connect(self._on_run_cancel_toggle)
        tool_select_layout.addWidget(self.run_tool_btn)
        
        self.tool_elapsed_label = QLabel("")
        self.tool_elapsed_label.setFixedWidth(52)
        self.tool_elapsed_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tool_select_layout.addWidget(self.tool_elapsed_label)
        
        tool_select_layout.addStretch()
        tools_layout.addLayout(tool_select_layout)
        
        # --- Separator above tool description ---
        self.tool_separator = QFrame()
        self.tool_separator.setFrameShape(QFrame.Shape.HLine)
        self.tool_separator.setFrameShadow(QFrame.Shadow.Plain)
        self.tool_separator.setFixedHeight(1)
        self.tool_separator.setVisible(False)
        tools_layout.addWidget(self.tool_separator)
        
        # --- Tool description (no border) ---
        self.tool_description_label = QLabel("")
        self.tool_description_label.setObjectName("tool_description")
        self.tool_description_label.setWordWrap(True)
        self.tool_description_label.setVisible(False)
        tools_layout.addWidget(self.tool_description_label)
        
        # --- Parameters section (unframed, with spacing above/below) ---
        tools_layout.addSpacing(6)
        
        self.tool_params_toggle = QPushButton("▶ Parameters")
        self.tool_params_toggle.setObjectName("section_toggle")
        self.tool_params_toggle.setFlat(True)
        self.tool_params_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tool_params_toggle.setVisible(False)
        self.tool_params_toggle.clicked.connect(self._toggle_tool_params)
        tools_layout.addWidget(self.tool_params_toggle)
        
        self.tool_params_table = QTableWidget(0, 3)
        self.tool_params_table.setObjectName("tool_params_table")
        self.tool_params_table.setHorizontalHeaderLabels(["Flag", "Parameter", "Value"])
        self.tool_params_table.horizontalHeader().setStretchLastSection(True)
        self.tool_params_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.tool_params_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.tool_params_table.verticalHeader().setVisible(False)
        self.tool_params_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tool_params_table.setMaximumHeight(160)
        self.tool_params_table.setVisible(False)
        self.tool_params_table.cellChanged.connect(self._on_tool_param_edited)
        tools_layout.addWidget(self.tool_params_table)
        
        # --- Command preview (inside collapsible section) ---
        self.tool_command_frame = QFrame()
        self.tool_command_frame.setFrameShape(QFrame.Shape.StyledPanel)
        self.tool_command_frame.setFrameShadow(QFrame.Shadow.Plain)
        self.tool_command_frame.setObjectName("collapsible_panel")
        self.tool_command_frame.setVisible(False)
        cmd_inner = QVBoxLayout(self.tool_command_frame)
        cmd_inner.setContentsMargins(8, 6, 8, 6)
        
        self.tool_command_label = QLabel("")
        self.tool_command_label.setObjectName("secondary_label")
        self.tool_command_label.setWordWrap(True)
        self.tool_command_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.tool_command_label.setStyleSheet("border: none;")
        cmd_inner.addWidget(self.tool_command_label)
        
        tools_layout.addWidget(self.tool_command_frame)
        
        # --- Data Files section (collapsible, shown when tool has data_files) ---
        self.tool_data_files_toggle = QPushButton("▶ Data Files")
        self.tool_data_files_toggle.setObjectName("section_toggle")
        self.tool_data_files_toggle.setFlat(True)
        self.tool_data_files_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tool_data_files_toggle.setVisible(False)
        self.tool_data_files_toggle.clicked.connect(self._toggle_tool_data_files)
        tools_layout.addWidget(self.tool_data_files_toggle)
        
        self.tool_data_files_widget = QWidget()
        self.tool_data_files_widget.setObjectName("collapsible_panel")
        self.tool_data_files_layout = QVBoxLayout(self.tool_data_files_widget)
        self.tool_data_files_layout.setContentsMargins(8, 6, 8, 6)
        self.tool_data_files_layout.setSpacing(4)
        self.tool_data_files_widget.setVisible(False)
        tools_layout.addWidget(self.tool_data_files_widget)
        
        # Output area (always visible) with vertical button bar on the right
        tool_output_row = QHBoxLayout()
        tool_output_row.setSpacing(6)
        
        self.tool_output_area = QTextEdit()
        self.tool_output_area.setReadOnly(True)
        self.tool_output_area.setPlaceholderText(
            "Select a tool from the dropdown above and click Run.\n\n"
            "Tool output will appear here."
        )
        self.tool_output_area.setFont(QFont("Menlo", 11))
        tool_output_row.addWidget(self.tool_output_area)
        
        # Vertical button bar
        tool_btn_bar = QFrame()
        tool_btn_bar.setFrameShape(QFrame.Shape.StyledPanel)
        tool_btn_bar.setStyleSheet(
            "QFrame { border: 1px solid palette(mid); border-radius: 4px; }"
        )
        tool_btn_bar_layout = QVBoxLayout(tool_btn_bar)
        tool_btn_bar_layout.setContentsMargins(2, 4, 2, 4)
        tool_btn_bar_layout.setSpacing(2)
        
        btn_style = (
            "QPushButton { background: transparent; border: none; padding: 4px; }"
            "QPushButton:hover { background: palette(mid); border-radius: 4px; }"
        )
        
        self.tool_copy_btn = QPushButton()
        self.tool_copy_btn.setIcon(
            IconManager.get_icon("copy", is_dark=is_dark, size=16))
        self.tool_copy_btn.setIconSize(QSize(16, 16))
        self.tool_copy_btn.setFixedSize(28, 28)
        self.tool_copy_btn.setToolTip("Copy tool output to clipboard")
        self.tool_copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tool_copy_btn.setStyleSheet(btn_style)
        self.tool_copy_btn.clicked.connect(self._copy_tool_output)
        tool_btn_bar_layout.addWidget(self.tool_copy_btn)
        
        self.tool_download_btn = QPushButton()
        self.tool_download_btn.setIcon(
            IconManager.get_icon("download", is_dark=is_dark, size=16))
        self.tool_download_btn.setIconSize(QSize(16, 16))
        self.tool_download_btn.setFixedSize(28, 28)
        self.tool_download_btn.setToolTip("Save tool output to file")
        self.tool_download_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tool_download_btn.setStyleSheet(btn_style)
        self.tool_download_btn.clicked.connect(self._download_tool_output)
        tool_btn_bar_layout.addWidget(self.tool_download_btn)
        
        tool_output_row.addWidget(tool_btn_bar, alignment=Qt.AlignmentFlag.AlignTop)
        
        tools_layout.addLayout(tool_output_row, stretch=1)
        
        self.tab_widget.addTab(tools_tab, "Meeting Tools")
        
        main_layout.addWidget(self.tab_widget, stretch=1)
        
        # === Separator before status bar ===
        self.separator_bottom = QFrame()
        self.separator_bottom.setFrameShape(QFrame.Shape.HLine)
        self.separator_bottom.setFrameShadow(QFrame.Shadow.Plain)
        self.separator_bottom.setFixedHeight(1)
        main_layout.addWidget(self.separator_bottom)
        
        # === Apply Modern Styling ===
        self._apply_styles()
        
        # === Status Bar ===
        # Build a custom status bar layout: [compact_btn] [status_label] ... [version]
        # We avoid QStatusBar.showMessage() because it hides addWidget items.
        # Instead, use a permanent widget container on the left with a label we
        # control ourselves, so the compact button is always visible.
        status_container = QWidget()
        status_hlayout = QHBoxLayout(status_container)
        status_hlayout.setContentsMargins(12, 0, 12, 2)  # match main_layout L/R, 2px bottom gap
        status_hlayout.setSpacing(8)
        
        is_dark = self._is_dark_mode()
        
        # --- Left zone: compact / expand button ---
        self.compact_btn = QPushButton()
        self.compact_btn.setFixedSize(20, 20)
        self.compact_btn.setToolTip("Compact view")
        self.compact_btn.setIcon(IconManager.get_icon(
            "chevrons_up", is_dark=is_dark, size=16))
        self.compact_btn.setFlat(True)
        self.compact_btn.clicked.connect(self._toggle_compact_mode)
        status_hlayout.addWidget(self.compact_btn)
        
        # --- Centre zone: status message ---
        self._status_msg_label = QLabel("Ready")
        self._status_msg_label.setObjectName("status_msg")
        self._status_msg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_hlayout.addWidget(self._status_msg_label, stretch=1)
        
        # --- Right zone: maximize / restore button ---
        self.maximize_btn = QPushButton()
        self.maximize_btn.setFixedSize(20, 20)
        self.maximize_btn.setToolTip("Maximize window")
        self.maximize_btn.setIcon(IconManager.get_icon(
            "maximize", is_dark=is_dark, size=16))
        self.maximize_btn.setFlat(True)
        self.maximize_btn.clicked.connect(self._toggle_maximized_view)
        status_hlayout.addWidget(self.maximize_btn)
        
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().addWidget(status_container, stretch=1)
        
        # Redirect statusBar().showMessage() to our custom label so the
        # compact button is never hidden by temporary messages.
        self.statusBar().showMessage = self._show_status_message
    
    def _show_status_message(self, text: str, timeout: int = 0):
        """Set status bar text via the custom label (keeps compact button visible).
        
        Also resets the ``status_state`` property to neutral so that a
        previous warn/error tint does not bleed into the next message.
        """
        self._status_msg_label.setText(text)
        self._status_msg_label.setProperty("status_state", "")
        self._status_msg_label.style().unpolish(self._status_msg_label)
        self._status_msg_label.style().polish(self._status_msg_label)
    
    def _is_dark_mode(self) -> bool:
        """Determine if dark mode should be used based on theme setting."""
        if self.theme_mode == "dark":
            return True
        elif self.theme_mode == "light":
            return False
        else:  # "system"
            palette = QApplication.palette()
            return palette.window().color().lightness() < 128
    
    def _set_theme(self, mode: str):
        """Change the application theme."""
        self.theme_mode = mode
        self._apply_styles()
        self.statusBar().showMessage(f"Appearance: {mode.capitalize()}")
    
    def _apply_styles(self):
        """Apply the global application stylesheet.
        
        Sets a single comprehensive QSS on QApplication so that every
        window, dialog, and popup inherits the theme automatically.
        After swapping the stylesheet, unpolish/polish the entire widget
        tree so the change takes effect immediately (required for live
        Light / Dark toggling).
        """
        is_dark = self._is_dark_mode()
        app = QApplication.instance()
        combo_arrow = IconManager.render_to_file(
            "chevron_down", is_dark=is_dark, tint="secondary", size=12)
        app.setStyleSheet(get_application_stylesheet(is_dark, combo_arrow_path=combo_arrow))
        
        # Flush the icon cache so icons re-render with the new tint
        IconManager.refresh()
        
        # Re-apply themed icons (guard: _apply_styles is called early in
        # _setup_ui before these widgets exist)
        if hasattr(self, "compact_btn"):
            self.time_up_btn.setIcon(
                IconManager.get_icon("arrow_up", is_dark=is_dark, size=20))
            self.time_down_btn.setIcon(
                IconManager.get_icon("arrow_down", is_dark=is_dark, size=20))
            self.calendar_btn.setIcon(
                IconManager.get_icon("calendar", is_dark=is_dark, size=16))
            compact_icon = "chevrons_down" if self._compact_mode else "chevrons_up"
            self.compact_btn.setIcon(
                IconManager.get_icon(compact_icon, is_dark=is_dark, size=16))
            max_icon = "minimize" if self._maximized_view else "maximize"
            self.maximize_btn.setIcon(
                IconManager.get_icon(max_icon, is_dark=is_dark, size=16))
            
            # Button bar icons
            self.save_details_btn.setIcon(
                IconManager.get_icon("save", is_dark=is_dark, size=16))
            self.open_folder_btn2.setIcon(
                IconManager.get_icon("folder_open", is_dark=is_dark, size=16))
            self._update_edit_button_icon()
            self.save_transcript_btn.setIcon(
                IconManager.get_icon("save", is_dark=is_dark, size=16))
            self.copy_btn.setIcon(
                IconManager.get_icon("copy", is_dark=is_dark, size=16))
            self.refresh_transcript_btn.setIcon(
                IconManager.get_icon("refresh", is_dark=is_dark, size=16))
            self.open_folder_btn.setIcon(
                IconManager.get_icon("folder_open", is_dark=is_dark, size=16))
            self.tool_copy_btn.setIcon(
                IconManager.get_icon("copy", is_dark=is_dark, size=16))
            self.tool_download_btn.setIcon(
                IconManager.get_icon("download", is_dark=is_dark, size=16))
        
        # Force every widget in the app to re-read the new stylesheet
        for widget in app.allWidgets():
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self.update()
        
    def _setup_menubar(self):
        """Create the application menu bar."""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("File")
        
        new_action = QAction("New", self)
        new_action.triggered.connect(self._on_new_recording)
        file_menu.addAction(new_action)
        
        reset_action = QAction("Reset", self)
        reset_action.triggered.connect(self._on_reset_recording)
        file_menu.addAction(reset_action)
        
        file_menu.addSeparator()
        
        open_folder_action = QAction("Open Export Folder", self)
        open_folder_action.triggered.connect(self._on_open_export_folder)
        file_menu.addAction(open_folder_action)
        
        # Edit menu
        edit_menu = menubar.addMenu("Edit")
        
        copy_action = QAction("Copy Transcript", self)
        copy_action.triggered.connect(self._on_copy_transcript)
        edit_menu.addAction(copy_action)
        
        # View menu
        view_menu = menubar.addMenu("View")
        
        appearance_menu = view_menu.addMenu("Appearance")
        
        # Create action group for exclusive selection
        appearance_group = QActionGroup(self)
        appearance_group.setExclusive(True)
        
        self.theme_system_action = QAction("System", self)
        self.theme_system_action.setCheckable(True)
        self.theme_system_action.setChecked(True)
        self.theme_system_action.triggered.connect(lambda: self._set_theme("system"))
        appearance_group.addAction(self.theme_system_action)
        appearance_menu.addAction(self.theme_system_action)
        
        self.theme_light_action = QAction("Light", self)
        self.theme_light_action.setCheckable(True)
        self.theme_light_action.triggered.connect(lambda: self._set_theme("light"))
        appearance_group.addAction(self.theme_light_action)
        appearance_menu.addAction(self.theme_light_action)
        
        self.theme_dark_action = QAction("Dark", self)
        self.theme_dark_action.setCheckable(True)
        self.theme_dark_action.triggered.connect(lambda: self._set_theme("dark"))
        appearance_group.addAction(self.theme_dark_action)
        appearance_menu.addAction(self.theme_dark_action)
        
        # Screen Sharing Privacy submenu
        privacy_menu = view_menu.addMenu("Screen Sharing Privacy")
        privacy_menu.setEnabled(_HAS_APPKIT)
        
        privacy_group = QActionGroup(self)
        privacy_group.setExclusive(True)
        
        self.privacy_show_action = QAction("Show", self)
        self.privacy_show_action.setCheckable(True)
        self.privacy_show_action.triggered.connect(lambda: self._set_privacy_mode(False))
        privacy_group.addAction(self.privacy_show_action)
        privacy_menu.addAction(self.privacy_show_action)
        
        self.privacy_hide_action = QAction("Hide", self)
        self.privacy_hide_action.setCheckable(True)
        self.privacy_hide_action.triggered.connect(lambda: self._set_privacy_mode(True))
        privacy_group.addAction(self.privacy_hide_action)
        privacy_menu.addAction(self.privacy_hide_action)
        
        # Default is hidden; will be updated after config is loaded
        self.privacy_hide_action.setChecked(True)
        
        privacy_menu.addSeparator()
        
        privacy_default_action = QAction("Change Default", self)
        privacy_default_action.triggered.connect(self._change_privacy_default)
        privacy_menu.addAction(privacy_default_action)
        
        log_action = QAction("Log File", self)
        log_action.triggered.connect(self._show_log_viewer)
        view_menu.addAction(log_action)
        
        # Separator keeps macOS-injected items (e.g. "Enter Full Screen")
        # below our items so their icon column doesn't indent ours.
        view_menu.addSeparator()
        
        # Preferences placeholder — macOS places this in the app menu automatically
        # (No longer needed since the config editor was removed)
        
        # Tools menu
        tools_menu = menubar.addMenu("Tools")
        
        import_tools_action = QAction("Import Tools", self)
        import_tools_action.triggered.connect(self._show_tool_import)
        tools_menu.addAction(import_tools_action)
        
        edit_tool_config_action = QAction("Edit Tool Configuration", self)
        edit_tool_config_action.triggered.connect(self._show_tool_json_editor)
        tools_menu.addAction(edit_tool_config_action)
        
        edit_data_files_action = QAction("Edit Tool Data Files", self)
        edit_data_files_action.triggered.connect(self._show_tool_data_file_picker)
        tools_menu.addAction(edit_data_files_action)
        
        tools_menu.addSeparator()
        
        open_tools_folder_action = QAction("Open Tools Folder", self)
        open_tools_folder_action.triggered.connect(self._open_tools_folder)
        tools_menu.addAction(open_tools_folder_action)
        
        refresh_tools_action = QAction("Refresh Tools", self)
        refresh_tools_action.triggered.connect(self._scan_tools)
        tools_menu.addAction(refresh_tools_action)
        
        # Sources menu
        sources_menu = menubar.addMenu("Sources")
        
        import_sources_action = QAction("Import Sources", self)
        import_sources_action.triggered.connect(self._show_source_import)
        sources_menu.addAction(import_sources_action)
        
        edit_source_action = QAction("Edit Source", self)
        edit_source_action.triggered.connect(self._show_source_editor)
        sources_menu.addAction(edit_source_action)
        
        ax_inspector_action = QAction("Accessibility Inspector", self)
        ax_inspector_action.triggered.connect(self._show_ax_inspector)
        sources_menu.addAction(ax_inspector_action)
        
        sources_menu.addSeparator()
        
        set_default_source_action = QAction("Set Current as Default", self)
        set_default_source_action.triggered.connect(self._on_set_default_source)
        sources_menu.addAction(set_default_source_action)
        
        clear_default_source_action = QAction("Clear Default", self)
        clear_default_source_action.triggered.connect(self._on_clear_default_source)
        sources_menu.addAction(clear_default_source_action)
        
        sources_menu.addSeparator()
        
        open_sources_folder_action = QAction("Open Sources Folder", self)
        open_sources_folder_action.triggered.connect(self._open_sources_folder)
        sources_menu.addAction(open_sources_folder_action)
        
        refresh_sources_action = QAction("Refresh Sources", self)
        refresh_sources_action.triggered.connect(self._scan_sources)
        sources_menu.addAction(refresh_sources_action)
        
        # Integrations menu
        integrations_menu = menubar.addMenu("Integrations")

        # Google Calendar submenu
        google_cal_menu = integrations_menu.addMenu("Google Calendar")

        calendar_configure_action = QAction("Configuration", self)
        calendar_configure_action.setMenuRole(QAction.MenuRole.NoRole)
        calendar_configure_action.triggered.connect(self._on_calendar_configure)
        google_cal_menu.addAction(calendar_configure_action)

        self._calendar_sign_out_action = QAction("Sign Out", self)
        self._calendar_sign_out_action.setMenuRole(QAction.MenuRole.NoRole)
        self._calendar_sign_out_action.triggered.connect(self._on_calendar_sign_out)
        self._calendar_sign_out_action.setVisible(False)
        google_cal_menu.addAction(self._calendar_sign_out_action)
        
        # Maintenance menu
        maint_menu = menubar.addMenu("Maintenance")
        
        change_export_action = QAction("Change Export Directory", self)
        change_export_action.triggered.connect(self._change_export_directory)
        maint_menu.addAction(change_export_action)
        
        # Log Level submenu
        log_level_menu = maint_menu.addMenu("Log Level")
        self._log_level_group = QActionGroup(self)
        self._log_level_group.setExclusive(True)
        
        current_level = "INFO"
        if self.config:
            current_level = self.config.get("logging", {}).get("level", "INFO").upper()
        
        for level_name in ("DEBUG", "INFO", "WARNING", "ERROR", "NONE"):
            action = QAction(level_name, self)
            action.setCheckable(True)
            action.setChecked(level_name == current_level)
            action.triggered.connect(lambda checked, lvl=level_name: self._set_log_level(lvl))
            self._log_level_group.addAction(action)
            log_level_menu.addAction(action)
        
        log_level_menu.addSeparator()
        
        change_default_log_action = QAction("Change Default", self)
        change_default_log_action.triggered.connect(self._change_log_level_default)
        log_level_menu.addAction(change_default_log_action)
        
        maint_menu.addSeparator()
        
        clear_log_action = QAction("Clear Log File", self)
        clear_log_action.triggered.connect(self._clear_log_file)
        maint_menu.addAction(clear_log_action)
        
        clear_snapshots_action = QAction("Clear All Snapshots", self)
        clear_snapshots_action.triggered.connect(self._clear_all_snapshots)
        maint_menu.addAction(clear_snapshots_action)
        
        clear_empty_action = QAction("Clear Empty Recordings", self)
        clear_empty_action.triggered.connect(self._clear_empty_recordings)
        maint_menu.addAction(clear_empty_action)
        
        maint_menu.addSeparator()
        
        permissions_action = QAction("Check Permissions", self)
        permissions_action.triggered.connect(self._check_permissions)
        maint_menu.addAction(permissions_action)
        
        update_action = QAction("Check for Updates", self)
        update_action.triggered.connect(self._check_for_updates)
        maint_menu.addAction(update_action)
        
        # Help menu
        help_menu = menubar.addMenu("Help")
        
        about_action = QAction(f"About {APP_NAME}", self)
        about_action.setMenuRole(QAction.MenuRole.AboutRole)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)
        
    def _setup_tray(self):
        """Setup system tray icon (optional)."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
            
        icon_path = resource_path("appicon.icns")
        if not icon_path.exists():
            return
            
        self.tray_icon = QSystemTrayIcon(QIcon(str(icon_path)), self)
        
        tray_menu = QMenu()
        show_action = tray_menu.addAction("Show Window")
        show_action.triggered.connect(self.show)
        
        tray_menu.addSeparator()
        
        quit_action = tray_menu.addAction("Quit")
        quit_action.triggered.connect(self.close)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()
        
    def _load_config(self):
        """Load application configuration.
        
        On first launch the bundled config.json is copied to App Support.
        The bundled config has a blank export_directory, so the user will
        be prompted to pick one before the app can proceed.
        """
        try:
            APP_SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
            
            if not CONFIG_PATH.exists():
                # First-run: copy the bundled default config to App Support
                bundled_config = resource_path("config.json")
                if not bundled_config.exists():
                    ThemedMessageDialog.critical(
                        self, "Missing Configuration",
                        "Could not find the bundled configuration file. "
                        "Please reinstall the application."
                    )
                    self._closing = True
                    QTimer.singleShot(0, self.close)
                    return
                
                shutil.copy2(str(bundled_config), str(CONFIG_PATH))
                logger.info(f"Config: first run — copied bundled config to {CONFIG_PATH}")
            
            with open(CONFIG_PATH, 'r') as f:
                self.config = json.load(f)
                
            # Set export directory (blank means user must pick one)
            client_settings = self.config.get("client_settings", {})
            export_dir = client_settings.get("export_directory", "").strip()

            if not export_dir:
                export_dir = self._prompt_for_export_directory()
                if not export_dir:
                    self._closing = True
                    QTimer.singleShot(0, self.close)
                    return

            self.export_base_dir = Path(export_dir).expanduser().resolve()
            self.export_base_dir.mkdir(parents=True, exist_ok=True)

            # Ensure tools and sources directories exist
            (self.export_base_dir / "tools").mkdir(parents=True, exist_ok=True)
            (self.export_base_dir / "sources").mkdir(parents=True, exist_ok=True)
            
            # Copy bundled sources and tools if not already present (first run)
            self._install_bundled_sources()
            self._install_bundled_tools()
            
            # Configure logging from config
            setup_logging(self.config)
            
            # Sync Log Level menu radio buttons with the loaded config
            saved_level = self.config.get("logging", {}).get("level", "INFO").upper()
            for action in self._log_level_group.actions():
                action.setChecked(action.text() == saved_level)
            
            # Scan for sources and tools
            self._scan_sources()
            self._scan_tools()
            
            # Load Google Calendar integration config
            self._load_calendar_config()
            
            log_level = self.config.get("logging", {}).get("level", "INFO")
            file_sources = len(self._discovered_sources) - 1  # subtract built-in Manual Recording
            logger.info(f"Config: loaded from {CONFIG_PATH} ({file_sources} sources + Manual Recording, log_level={log_level})")
            self.statusBar().showMessage("Configuration loaded")
            
        except json.JSONDecodeError as e:
            ThemedMessageDialog.critical(
                self, "Configuration Error",
                f"Invalid configuration file: {e}"
            )
        except Exception as e:
            ThemedMessageDialog.critical(
                self, "Configuration Error",
                f"Failed to load configuration: {e}"
            )
            logger.error(f"Config load error: {e}", exc_info=True)
    
    def _install_bundled_sources(self):
        """Copy bundled source files from the app bundle into the export dir.

        Only copies sources that do not already exist locally, so user
        customisations are never overwritten.
        """
        sources_dir = self.export_base_dir / "sources"
        bundled_sources_dir = resource_path("sources")

        if not bundled_sources_dir.exists() or not bundled_sources_dir.is_dir():
            logger.debug("Bundled sources directory not found — skipping install")
            return

        for bundled_source_dir in sorted(bundled_sources_dir.iterdir()):
            if not bundled_source_dir.is_dir():
                continue
            src_source = bundled_source_dir / "source.json"
            if not src_source.exists():
                continue

            dest_dir = sources_dir / bundled_source_dir.name
            dest_source = dest_dir / "source.json"
            if dest_source.exists():
                continue  # Don't overwrite existing user sources

            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src_source), str(dest_source))
            # Also copy the .sha256 if present
            src_hash = bundled_source_dir / "source.json.sha256"
            if src_hash.exists():
                shutil.copy2(str(src_hash), str(dest_dir / "source.json.sha256"))
            logger.info(f"Bundled sources: installed {bundled_source_dir.name}")

    def _install_bundled_tools(self):
        """Copy bundled tool directories from the app bundle into the export dir.

        Only copies tools that do not already exist locally, so user
        customisations are never overwritten.  Sub-directories (e.g. ``data/``)
        are recreated as well.
        """
        tools_dir = self.export_base_dir / "tools"
        bundled_tools_dir = resource_path("tools")

        if not bundled_tools_dir.exists() or not bundled_tools_dir.is_dir():
            logger.debug("Bundled tools directory not found — skipping install")
            return

        for bundled_tool_dir in sorted(bundled_tools_dir.iterdir()):
            if not bundled_tool_dir.is_dir():
                continue
            src_tool_json = bundled_tool_dir / "tool.json"
            if not src_tool_json.exists():
                continue

            dest_dir = tools_dir / bundled_tool_dir.name
            dest_tool_json = dest_dir / "tool.json"
            if dest_tool_json.exists():
                continue  # Don't overwrite existing user tools

            # Recursively copy the entire tool directory
            shutil.copytree(str(bundled_tool_dir), str(dest_dir))

            # Ensure scripts are executable
            for script in dest_dir.glob("*.sh"):
                script.chmod(script.stat().st_mode | 0o111)
            for script in dest_dir.glob("*.py"):
                script.chmod(script.stat().st_mode | 0o111)

            logger.info(f"Bundled tools: installed {bundled_tool_dir.name}")

    def _scan_sources(self):
        """Scan ``<export_dir>/sources/`` for source definitions and populate the app combo.

        The built-in Manual Recording entry is always inserted first so the
        app is functional on first launch even without downloaded sources.
        """
        self._discovered_sources = {}
        self.app_combo.clear()

        # Always add the built-in Manual Recording entry first
        self._discovered_sources[MANUAL_RECORDING_KEY] = MANUAL_RECORDING_SOURCE
        self.app_combo.addItem(
            MANUAL_RECORDING_SOURCE["display_name"], MANUAL_RECORDING_KEY
        )

        if not self.export_base_dir:
            return

        self._sources_dir = self.export_base_dir / "sources"

        try:
            self._sources_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"Sources: failed to create sources directory: {e}")
            return

        try:
            subdirs = sorted(
                p for p in self._sources_dir.iterdir() if p.is_dir()
            )
        except OSError as e:
            logger.error(f"Sources: could not list sources directory: {e}")
            return

        for source_dir in subdirs:
            # Guard: the "manual" key is reserved for the built-in Manual Recording
            if source_dir.name == MANUAL_RECORDING_KEY:
                logger.warning(f"Sources: skipping sources/{source_dir.name}/ — "
                               f"'{MANUAL_RECORDING_KEY}' is a reserved name")
                continue

            json_path = source_dir / "source.json"
            if not json_path.exists():
                logger.debug(f"Sources: no source.json in {source_dir.name}/ — skipped")
                continue
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    source_def = json.load(f)

                if not source_def.get("display_name"):
                    logger.warning(f"Sources: {source_dir.name}/source.json missing 'display_name'")
                    continue

                source_def["_source_dir"] = str(source_dir)
                source_def["_json_path"] = str(json_path)

                source_key = source_dir.name
                self._discovered_sources[source_key] = source_def
                self.app_combo.addItem(source_def["display_name"], source_key)

                logger.debug(f"Sources: discovered '{source_def['display_name']}' in {source_dir.name}/")

            except json.JSONDecodeError as e:
                logger.warning(f"Sources: invalid JSON in {source_dir.name}/source.json: {e}")
            except Exception as e:
                logger.error(f"Sources: error loading {source_dir.name}/source.json: {e}")

        # Count excludes the built-in Manual Recording entry
        file_source_count = len(self._discovered_sources) - 1  # subtract built-in
        if file_source_count > 0:
            logger.info(f"Sources: discovered {file_source_count} source(s) in {self._sources_dir}")
        else:
            logger.debug(f"Sources: no sources found in {self._sources_dir}")

        if self.app_combo.count() > 0:
            self._apply_default_source()
    
    def _apply_default_source(self):
        """Select the default source in the app combo, or fall back to index 0."""
        default_key = ""
        if self.config:
            default_key = self.config.get("client_settings", {}).get("default_source", "")
        
        if default_key:
            for i in range(self.app_combo.count()):
                if self.app_combo.itemData(i) == default_key:
                    self.app_combo.setCurrentIndex(i)
                    self._on_app_changed(i)
                    logger.debug(f"Sources: selected default source '{default_key}'")
                    return
            # Default source not found among discovered sources
            logger.warning(f"Sources: configured default_source '{default_key}' not found, using first source")
        
        self.app_combo.setCurrentIndex(0)
        self._on_app_changed(0)
    
    def _on_set_default_source(self):
        """Save the currently selected source as the default in config."""
        current_key = self.app_combo.currentData()
        if not current_key:
            ThemedMessageDialog.info(self, "No Source Selected", "Please select a source first.")
            return
        
        display_name = self.app_combo.currentText()
        
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            
            if "client_settings" not in config_data:
                config_data["client_settings"] = {}
            config_data["client_settings"]["default_source"] = current_key
            
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2)
            
            self.config = config_data
            self.statusBar().showMessage(f"Default source set to '{display_name}'")
            logger.info(f"Config: default_source set to '{current_key}' ({display_name})")
        except Exception as e:
            logger.error(f"Config: failed to save default_source: {e}")
            ThemedMessageDialog.critical(self, "Error", f"Failed to save default source: {e}")
    
    def _on_clear_default_source(self):
        """Clear the default source setting from config."""
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            
            if "client_settings" not in config_data:
                config_data["client_settings"] = {}
            config_data["client_settings"]["default_source"] = ""
            
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2)
            
            self.config = config_data
            self.statusBar().showMessage("Default source cleared")
            logger.info("Config: default_source cleared")
        except Exception as e:
            logger.error(f"Config: failed to clear default_source: {e}")
            ThemedMessageDialog.critical(self, "Error", f"Failed to clear default source: {e}")
            
    def _check_permissions(self):
        """Check and warn about accessibility permissions."""
        try:
            if not AXIsProcessTrusted():
                self._has_accessibility = False
                dlg = PermissionsDialog(self, is_dark=self._is_dark_mode())
                dlg.exec()
                self._set_status("Accessibility permission required", "warn")
            else:
                self._has_accessibility = True
                logger.info("Permissions: accessibility access granted")
        except Exception as e:
            logger.error(f"Permissions: check failed: {e}")
        self._update_button_states()
            
    def _on_startup_update_available(self, version: str, release_url: str, notes: str, assets: list):
        """Handle notification that a new version is available (from background check)."""
        ThemedMessageDialog.info(
            self,
            "Update Available",
            f"A new version of {APP_NAME} is available! "
            f"Current version: {APP_VERSION}. "
            f"Latest version: {version}. "
            f"You can download it from the Maintenance menu → Check for Updates."
        )
    
    def _on_app_changed(self, index: int):
        """Handle application selection change."""
        if index < 0:
            return
            
        self.selected_app_key = self.app_combo.currentData()
        self._is_manual_mode = (self.selected_app_key == MANUAL_RECORDING_KEY)

        if self.selected_app_key and self._discovered_sources:
            app_config = self._discovered_sources.get(self.selected_app_key, {})
            self.capture_interval = app_config.get("monitor_interval_seconds", 30)
            logger.debug(f"App selection changed: {self.selected_app_key} "
                         f"(manual={self._is_manual_mode}, capture interval: {self.capture_interval}s)")
            
    def _on_new_recording(self):
        """Start a new recording session.

        For the built-in Manual Recording source no ``TranscriptRecorder`` is
        created — the user edits the transcript text area directly.
        """
        if not self.selected_app_key or not self._discovered_sources:
            logger.warning("New session: no application selected")
            ThemedMessageDialog.warning(self, "No Application", "Please select a meeting application first.")
            return
            
        app_config = self._discovered_sources.get(self.selected_app_key, {})
        if not app_config:
            logger.error(f"New session: no source found for {self.selected_app_key}")
            ThemedMessageDialog.warning(self, "Source Error", f"No source found for {self.selected_app_key}")
            return
            
        # Reset state
        if self.is_recording:
            self._on_stop_recording()
            
        # Create recording directory with date-based structure
        timestamp = datetime.now()
        folder_name = f"recording_{timestamp.strftime('%Y-%m-%d_%H%M')}_{self.selected_app_key}"
        year_folder = timestamp.strftime('%Y')
        month_folder = timestamp.strftime('%m')
        self.current_recording_path = self.export_base_dir / "recordings" / year_folder / month_folder / folder_name
        self.snapshots_path = self.current_recording_path / ".snapshots"
        self.merged_transcript_path = self.current_recording_path / "meeting_transcript.txt"

        if self._is_manual_mode:
            # Manual Recording — no recorder instance; transcript is user-editable
            self.recorder_instance = None
            self.snapshot_count = 0
            self._loading_transcript = True
            self.transcript_text.clear()
            self._loading_transcript = False
            self.transcript_text.setReadOnly(False)
            self._transcript_edit_mode = True
            self._transcript_modified = False
            self._is_history_session = False
            self.transcript_text.setPlaceholderText(
                "Paste or type your transcript here...\n\n"
                "Click the save button to save your transcript."
            )
            self.transcript_text.setToolTip("Lines: 0")

            # Set default meeting date/time and clear other fields
            self.meeting_datetime_input.setText(timestamp.strftime("%m/%d/%Y %I:%M %p"))
            self.meeting_name_input.clear()
            self.meeting_notes_input.clear()
            self.meeting_details_dirty = False

            self._update_button_states()
            self.statusBar().showMessage(f"Manual recording — {folder_name}")
            self._set_status("Manual mode — paste or type your transcript", "info")
            logger.info(f"New session (manual): prepared (folder deferred: {self.current_recording_path})")

            # Switch to transcript tab and focus the text area for immediate pasting
            self.tab_widget.setCurrentIndex(1)
            self.transcript_text.setFocus()
            return
        
        # --- Standard capture-based recording ---
        # Create recorder instance - snapshots go to the hidden .snapshots folder
        tr_config = app_config.copy()
        tr_config["base_transcript_directory"] = str(self.snapshots_path)
        tr_config["name"] = self.selected_app_key
        
        try:
            self.recorder_instance = TranscriptRecorder(app_config=tr_config, logger=logger)
        except Exception as e:
            logger.error(f"New session: failed to initialize recorder: {e}", exc_info=True)
            ThemedMessageDialog.critical(self, "Error", f"Failed to initialize recorder: {e}")
            return
            
        # Update UI
        self.snapshot_count = 0
        self._loading_transcript = True
        self.transcript_text.clear()
        self._loading_transcript = False
        self.transcript_text.setReadOnly(True)
        self._disable_transcript_edit_mode()
        self._is_history_session = False
        self.transcript_text.setPlaceholderText(
            "Transcript will appear here after recording starts...\n\n"
            "To begin:\n"
            "1. Select your meeting application above\n"
            "2. Make sure your meeting has captions/transcript enabled\n"
            "3. Click 'New' then 'Capture' or 'Auto Capture'"
        )
        self.transcript_text.setToolTip("Lines: 0")
        
        # Set default meeting date/time and clear other fields
        self.meeting_datetime_input.setText(timestamp.strftime("%m/%d/%Y %I:%M %p"))
        self.meeting_name_input.clear()
        self.meeting_notes_input.clear()
        self.meeting_details_dirty = False
        
        self._update_button_states()
        self.statusBar().showMessage(f"Ready to record — {folder_name}")
        self._set_status("Recording ready", "info")
        logger.info(f"New session: prepared for {self.selected_app_key} (folder deferred: {self.current_recording_path})")
        
        # Set focus to Meeting Name field for quick entry
        self.meeting_name_input.setFocus()
    
    def _on_reset_recording(self):
        """Reset the current recording session."""
        if self.is_recording:
            if not ThemedMessageDialog.question(
                self, "Auto Capture Running",
                "Auto capture is currently running. Resetting will stop "
                "the capture and clear the current recording. Continue?"
            ):
                return
            self._on_stop_recording()

        # Prompt to save unsaved transcript edits
        if not self._check_unsaved_transcript():
            return

        self.recorder_instance = None
        self.current_recording_path = None
        self.snapshots_path = None
        self.merged_transcript_path = None
        self.snapshot_count = 0
        self._last_merged_line_count = 0
        self._loading_transcript = True
        self.transcript_text.clear()
        self._loading_transcript = False
        self.transcript_text.setReadOnly(True)
        self._disable_transcript_edit_mode()
        self._is_history_session = False
        self.transcript_text.setPlaceholderText(
            "Transcript will appear here after recording starts...\n\n"
            "To begin:\n"
            "1. Select your meeting application above\n"
            "2. Make sure your meeting has captions/transcript enabled\n"
            "3. Click 'New' then 'Capture' or 'Auto Capture'"
        )
        self.transcript_text.setToolTip("Lines: 0")
        
        # Clear meeting details
        self.meeting_name_input.clear()
        self.meeting_datetime_input.clear()
        self.meeting_notes_input.clear()
        self.meeting_details_dirty = False
        
        # Reset Meeting Tools panel to default state
        self.tool_combo.setCurrentIndex(0)
        self.tool_output_area.clear()
        self.tool_output_area.setPlaceholderText(
            "Select a tool from the dropdown above and click Run.\n\n"
            "Tool output will appear here."
        )
        
        # Switch back to Meeting Details tab
        self.tab_widget.setCurrentIndex(0)
        
        # Restore the default source selection
        if self.app_combo.count() > 0:
            self._apply_default_source()
        
        self._update_button_states()
        self._set_status("Ready")
        self.statusBar().showMessage("Recording reset")
        logger.info("Session reset")
        
    def _ensure_recorder(self) -> bool:
        """Create a recorder instance on-demand for a loaded session."""
        if self.recorder_instance:
            return True
        
        if not self.current_recording_path:
            return False
        
        if not self.selected_app_key or not self._discovered_sources:
            ThemedMessageDialog.warning(
                self, "No Application Selected",
                "Please select a meeting application before capturing."
            )
            return False
        
        app_config = self._discovered_sources.get(self.selected_app_key, {})
        if not app_config:
            ThemedMessageDialog.warning(
                self, "Source Error",
                f"No source found for {self.selected_app_key}"
            )
            return False
        
        self.snapshots_path = self.current_recording_path / ".snapshots"
        self.merged_transcript_path = self.current_recording_path / "meeting_transcript.txt"
        
        tr_config = app_config.copy()
        tr_config["base_transcript_directory"] = str(self.snapshots_path)
        tr_config["name"] = self.selected_app_key
        
        try:
            self.recorder_instance = TranscriptRecorder(app_config=tr_config, logger=logger)
        except Exception as e:
            logger.error(f"Failed to create recorder for loaded session: {e}", exc_info=True)
            ThemedMessageDialog.critical(self, "Error", f"Failed to initialize recorder: {e}")
            return False
        
        logger.info(f"Recorder created on-demand for loaded session: {self.selected_app_key}")
        self._update_button_states()
        return True
    
    def _on_start_recording(self):
        """Start continuous recording."""
        if not self._ensure_recorder():
            logger.warning("Start recording: no active session")
            return

        # If transcript is in edit mode, disable it — auto capture will conflict
        if self._transcript_edit_mode:
            if not self._check_unsaved_transcript():
                return
            self._disable_transcript_edit_mode()

        # Switch to transcript tab
        self.tab_widget.setCurrentIndex(1)  # Meeting Transcript tab
            
        self.recording_worker = RecordingWorker(self.capture_interval)
        self.recording_worker.capture_requested.connect(self._on_auto_capture_requested)
        self.recording_worker.countdown_tick.connect(self._on_countdown_tick)
        
        self.recording_worker.start()
        self.is_recording = True
        self._update_button_states()
        self._set_status("Auto capture started", "info")
        self.statusBar().showMessage(f"Auto capture running (every {self.capture_interval}s)")
        logger.info(f"Recording started: auto capture every {self.capture_interval}s")
        
    def _on_stop_recording(self):
        """Stop continuous recording."""
        logger.info(f"Recording stopped (snapshots taken: {self.snapshot_count})")
        if self.recording_worker:
            self.recording_worker.stop()
            self.recording_worker.wait(5000)  # Wait up to 5 seconds
            self.recording_worker = None
            
        self.is_recording = False
        self._update_button_states()
        self._set_status("Stopped", "warn")
        
        # Export index file to the .snapshots folder
        if self.recorder_instance and self.recorder_instance.snapshots:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(self.recorder_instance.export_snapshots_index())
                logger.debug("Snapshots index file exported")
            finally:
                loop.close()
                
        self.statusBar().showMessage("Auto capture stopped")
        
    def _on_capture_now(self):
        """Take a manual snapshot and merge into meeting transcript."""
        # If transcript is in edit mode with unsaved changes, warn the user
        if self._transcript_edit_mode and self._transcript_modified:
            result = ThemedMessageDialog.save_discard_cancel(
                self, "Unsaved Transcript Changes",
                "You have unsaved transcript edits. Capturing will overwrite "
                "the display with the merged result. "
                "Save your edits first, or discard them?"
            )
            if result == ThemedMessageDialog.Result.CANCEL:
                return
            if result == ThemedMessageDialog.Result.SAVE:
                self._on_save_transcript_clicked()
        self._do_capture_and_merge(auto=False)
    
    def _ensure_recording_folder(self) -> bool:
        """Create the recording folder on disk if it doesn't already exist."""
        if not self.current_recording_path:
            return False
        if self.current_recording_path.exists():
            return True
        try:
            self.current_recording_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Recording folder created: {self.current_recording_path}")
            return True
        except OSError as e:
            logger.error(f"Failed to create recording folder: {e}")
            ThemedMessageDialog.critical(self, "Error", f"Failed to create recording folder: {e}")
            return False
    
    def _do_capture_and_merge(self, auto: bool = False):
        """Unified capture and merge -- single code path for manual and auto capture."""
        if not self.recorder_instance:
            if not auto:
                if not self._ensure_recorder():
                    logger.warning("Manual capture: no active session")
                    return
            else:
                return
        
        if self._is_capturing:
            logger.debug("Capture already in progress, skipping")
            return
        
        # Ensure the recording folder exists on disk (deferred from New Recording)
        if not self._ensure_recording_folder():
            return
        
        self._is_capturing = True
        self._update_button_states()
        
        # Switch to transcript tab only on manual capture
        if not auto:
            self.tab_widget.setCurrentIndex(1)
        
        source = "Auto" if auto else "Manual"
        self.statusBar().showMessage("Capturing transcript...")
        QApplication.processEvents()  # Ensure UI updates before blocking call
        
        logger.debug(f"{source} capture: starting")
        
        loop = asyncio.new_event_loop()
        try:
            success, file_path, line_count = loop.run_until_complete(
                self.recorder_instance.export_transcript_text()
            )
            
            if success and file_path:
                self.snapshot_count += 1
                overlap_count = 0
                prev_line_count = self._last_merged_line_count
                
                if self.merged_transcript_path and self.merged_transcript_path.exists():
                    merge_ok, _, overlap_count = smart_merge(
                        str(self.merged_transcript_path),
                        file_path,
                        str(self.merged_transcript_path)
                    )
                    logger.info(
                        f"{source} capture: snapshot #{self.snapshot_count} merged "
                        f"({line_count} lines, {overlap_count} overlap)"
                    )
                else:
                    shutil.copy(file_path, str(self.merged_transcript_path))
                    logger.info(f"{source} capture: first snapshot saved ({line_count} lines)")
                
                # Save meeting details if modified
                self._save_meeting_details()
                
                # Display the merged transcript (updates _last_merged_line_count)
                self._update_transcript_display(str(self.merged_transcript_path), line_count or 0)
                
                # Build status message with line count and delta
                total_lines = self._last_merged_line_count
                delta = total_lines - prev_line_count
                self.statusBar().showMessage(
                    f"{source} capture: {line_count} lines (snapshot #{self.snapshot_count})"
                )
                if delta > 0:
                    self._set_status(f"Transcript: {total_lines} lines (+{delta} new)", "info")
                else:
                    self._set_status(f"Transcript: {total_lines} lines", "info")
            else:
                logger.warning(f"{source} capture: no transcript data returned")
                if not auto:
                    ThemedMessageDialog.warning(
                        self, "Capture Failed",
                        "Could not capture transcript. Make sure the meeting "
                        "application is running, captions/transcript is enabled, "
                        "and the transcript window is visible."
                    )
                self._set_status("Capture failed", "error")
        except Exception as e:
            logger.error(f"{source} capture failed: {e}", exc_info=True)
            if not auto:
                ThemedMessageDialog.critical(self, "Error", f"Capture failed: {e}")
            self._set_status("Error", "error")
        finally:
            loop.close()
            self._is_capturing = False
            self._update_button_states()
            
    def _on_auto_capture_requested(self):
        """Handle auto-capture timer requesting a snapshot."""
        if not self.is_recording:
            return  # Ignore stale signals after auto capture was stopped
        self._do_capture_and_merge(auto=True)
            
    def _on_countdown_tick(self, seconds: int):
        """Update countdown display in the auto capture button label."""
        if seconds == 0:
            self.auto_capture_btn.setText("Stop (\u2026)")
        else:
            self.auto_capture_btn.setText(f"Stop ({seconds}s)")
        
    def _update_transcript_display(self, file_path: str, line_count: int = 0):
        """Update the transcript preview from the merged transcript file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            self._loading_transcript = True
            self.transcript_text.setText(content)
            self._loading_transcript = False
            
            # Count actual lines in the merged file and track for delta display
            actual_lines = len(content.splitlines())
            self._last_merged_line_count = actual_lines
            self.transcript_text.setToolTip(f"Lines: {actual_lines}")
            
            # Scroll to bottom
            scrollbar = self.transcript_text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
            
            self.copy_btn.setEnabled(True)
            self.refresh_transcript_btn.setEnabled(True)
            self.open_folder_btn.setEnabled(True)
            logger.debug(f"Transcript display updated ({actual_lines} lines)")
        except Exception as e:
            logger.error(f"Failed to update transcript display: {e}")
            
    # --- Transcript editing helpers ---

    def _on_transcript_text_changed(self):
        """Track modifications when the user edits the transcript.

        Connected once in ``_setup_ui``.  Ignored during programmatic loads
        (guarded by ``_loading_transcript``) and when editing is off.
        """
        if self._loading_transcript or not self._transcript_edit_mode:
            return

        # Update line-count tooltip live
        line_count = len(self.transcript_text.toPlainText().splitlines())
        self.transcript_text.setToolTip(f"Lines: {line_count}")

        if not self._transcript_modified:
            self._transcript_modified = True
            self.save_transcript_btn.setEnabled(True)
            logger.debug("Transcript marked as modified")

    def _on_edit_transcript_clicked(self):
        """Toggle transcript edit mode on or off.

        * **Manual mode** — editing is toggled directly.
        * **Auto-capture active** — editing is blocked (button should already
          be disabled, but guard here as well).
        * **Active (non-history) session without auto-capture** — prompt the
          user to confirm the meeting is over before enabling edits, since
          further captures would merge-conflict with manual changes.
        * **History session** — editing is toggled directly.
        """
        if self._transcript_edit_mode:
            # Toggle OFF — leave current text as-is
            self._transcript_edit_mode = False
            self.transcript_text.setReadOnly(True)
            self._update_edit_button_icon()
            self._update_button_states()
            logger.debug("Transcript edit mode disabled")
            return

        # Guard: do not allow editing while auto-capture is running
        if self.is_recording:
            ThemedMessageDialog.info(
                self, "Editing Unavailable",
                "Cannot edit the transcript while auto capture is running. "
                "Stop auto capture first, then enable editing."
            )
            return

        # Non-manual, non-history active session — warn about merge conflicts
        if not self._is_manual_mode and not self._is_history_session and self.recorder_instance is not None:
            if not ThemedMessageDialog.question(
                self, "Enable Editing",
                "Is the meeting over? Editing the transcript while captures "
                "are still possible could cause merge conflicts with future "
                "captures. Continue?"
            ):
                return

        # Enable editing
        self._transcript_edit_mode = True
        self.transcript_text.setReadOnly(False)
        self._update_edit_button_icon()
        self._update_button_states()
        self.transcript_text.setFocus()
        logger.debug("Transcript edit mode enabled")

    def _on_save_transcript_clicked(self):
        """Save the current transcript text to meeting_transcript.txt."""
        if not self.current_recording_path or not self.merged_transcript_path:
            return

        # Ensure the recording folder exists (deferred from New Recording)
        if not self._ensure_recording_folder():
            return

        text = self.transcript_text.toPlainText()
        try:
            self.merged_transcript_path.write_text(text, encoding="utf-8")
            line_count = len(text.splitlines())
            self._last_merged_line_count = line_count
            self._transcript_modified = False
            self.save_transcript_btn.setEnabled(False)
            self.copy_btn.setEnabled(bool(text.strip()))
            self.refresh_transcript_btn.setEnabled(bool(text.strip()))
            self.open_folder_btn.setEnabled(bool(text.strip()))

            # Also persist meeting details if dirty
            self._save_meeting_details()

            self.statusBar().showMessage("Transcript saved")
            logger.info(f"Transcript saved ({line_count} lines)")
        except OSError as e:
            logger.error(f"Failed to save transcript: {e}")
            ThemedMessageDialog.warning(self, "Save Error", f"Failed to save transcript: {e}")

    def _update_edit_button_icon(self):
        """Update the edit transcript button icon based on current state."""
        is_dark = self._is_dark_mode()
        if self.is_recording:
            self.edit_transcript_btn.setIcon(
                IconManager.get_icon("pencil_off", is_dark=is_dark, size=16))
        elif self._transcript_edit_mode:
            self.edit_transcript_btn.setIcon(
                IconManager.get_icon("pencil", is_dark=is_dark, tint="primary", size=16))
        else:
            self.edit_transcript_btn.setIcon(
                IconManager.get_icon("pencil", is_dark=is_dark, size=16))

    def _check_unsaved_transcript(self) -> bool:
        """Prompt the user if there are unsaved transcript edits.

        Returns ``True`` if it is safe to proceed (saved, discarded, or no
        changes).  Returns ``False`` if the user chose to cancel.
        """
        if not self._transcript_modified:
            return True

        result = ThemedMessageDialog.save_discard_cancel(
            self, "Unsaved Transcript Changes",
            "You have unsaved changes to the transcript. "
            "Would you like to save before continuing?"
        )
        if result == ThemedMessageDialog.Result.CANCEL:
            return False
        if result == ThemedMessageDialog.Result.SAVE:
            self._on_save_transcript_clicked()
        return True

    def _disable_transcript_edit_mode(self):
        """Turn off transcript editing and reset modification tracking."""
        self._transcript_edit_mode = False
        self._transcript_modified = False
        self.transcript_text.setReadOnly(True)

    def _copy_tool_output(self):
        """Copy tool output text area contents to clipboard."""
        text = self.tool_output_area.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.statusBar().showMessage("Tool output copied to clipboard")
    
    def _download_tool_output(self):
        """Save tool output to a text file chosen by the user."""
        text = self.tool_output_area.toPlainText()
        if not text:
            self.statusBar().showMessage("No output to save")
            return
        
        tool_key = self.tool_combo.currentData() or "tool"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"{tool_key}_output_{timestamp}.txt"
        
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Tool Output", default_name,
            "Text Files (*.txt);;All Files (*)")
        if not path:
            return
        
        try:
            Path(path).write_text(text, encoding="utf-8")
            self.statusBar().showMessage(f"Output saved to {path}")
        except OSError as e:
            ThemedMessageDialog.warning(self, "Save Error", f"Could not save file: {e}")
    
    def _on_copy_transcript(self):
        """Copy transcript to clipboard."""
        text = self.transcript_text.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.statusBar().showMessage("Transcript copied to clipboard")
            
    def _on_refresh_transcript(self):
        """Reload the transcript from disk and update the display."""
        if not self._check_unsaved_transcript():
            return
        if self.merged_transcript_path and self.merged_transcript_path.exists():
            self._update_transcript_display(str(self.merged_transcript_path))
            self._transcript_modified = False
            self.save_transcript_btn.setEnabled(False)
            self.statusBar().showMessage("Transcript refreshed")
        else:
            self.statusBar().showMessage("No transcript file found to refresh")
    
    def _on_open_folder(self):
        """Open the current recording folder."""
        if self.current_recording_path and self.current_recording_path.exists():
            subprocess.run(["open", str(self.current_recording_path)])
            
    def _on_open_export_folder(self):
        """Open the main export folder."""
        if self.export_base_dir.exists():
            subprocess.run(["open", str(self.export_base_dir)])
    
    def _on_load_previous_meeting(self):
        """Load meeting details and transcript from a previous recording folder.

        The History button is disabled while a session is active, so we don't
        need to guard against active recordings or unsaved changes here.
        """
        # Default to the recordings directory
        start_dir = str(self.export_base_dir / "recordings")
        if not Path(start_dir).exists():
            start_dir = str(self.export_base_dir)
        
        selected_dir = QFileDialog.getExistingDirectory(
            self,
            "Select a Previous Recording Folder",
            start_dir,
            QFileDialog.Option.ShowDirsOnly
        )
        
        if not selected_dir:
            return  # User cancelled
        
        selected_path = Path(selected_dir)
        
        # Validate: must contain at least a meeting_transcript.txt or meeting_details.txt
        has_transcript = (selected_path / "meeting_transcript.txt").exists()
        has_details = (selected_path / "meeting_details.txt").exists()
        
        if not has_transcript and not has_details:
            ThemedMessageDialog.warning(
                self, "Invalid Recording Folder",
                "The selected folder does not contain a meeting_transcript.txt "
                "or meeting_details.txt file. "
                "Please select a valid recording folder."
            )
            return
        
        # Initialize session state
        self.recorder_instance = None
        self.snapshot_count = 0
        self._is_capturing = False
        self._disable_transcript_edit_mode()
        self._is_history_session = True
        
        # Set paths for the loaded recording
        self.current_recording_path = selected_path
        self.snapshots_path = selected_path / ".snapshots"
        self.merged_transcript_path = selected_path / "meeting_transcript.txt"
        
        # Parse meeting_details.txt if it exists
        self.meeting_datetime_input.clear()
        self.meeting_name_input.clear()
        self.meeting_notes_input.clear()
        
        if has_details:
            self._load_meeting_details_from_file(selected_path / "meeting_details.txt")
        
        # Load transcript if it exists
        self._loading_transcript = True
        self.transcript_text.clear()
        if has_transcript:
            try:
                transcript_content = (selected_path / "meeting_transcript.txt").read_text(encoding='utf-8')
                self.transcript_text.setPlainText(transcript_content)
                line_count = len(transcript_content.splitlines())
                self.transcript_text.setToolTip(f"Lines: {line_count}")
            except Exception as e:
                logger.error(f"Failed to load transcript: {e}")
                self.transcript_text.setToolTip("Lines: 0")
        else:
            self.transcript_text.setToolTip("Lines: 0")
        self._loading_transcript = False
        
        self.meeting_details_dirty = False
        
        # Reset Meeting Tools panel
        self.tool_combo.setCurrentIndex(0)
        self.tool_output_area.clear()
        
        self._update_button_states()
        
        folder_name = selected_path.name
        self._set_status("Loaded previous meeting", "info")
        self.statusBar().showMessage(f"Loaded — {folder_name}")
        logger.info(f"Loaded previous meeting from: {selected_path}")
        
        # Switch to Meeting Details tab
        self.tab_widget.setCurrentIndex(0)
    
    def _load_meeting_details_from_file(self, details_path: Path):
        """Parse a meeting_details.txt file and populate the UI fields."""
        try:
            content = details_path.read_text(encoding='utf-8')
        except Exception as e:
            logger.error(f"Failed to read meeting details: {e}")
            return
        
        lines = content.splitlines()
        meeting_name = ""
        meeting_datetime = ""
        notes_lines = []
        in_notes = False
        
        for i, line in enumerate(lines):
            if in_notes:
                # Skip the dashes separator line immediately after "Notes:"
                if i > 0 and lines[i - 1].strip() == "Notes:" and line.strip().startswith("---"):
                    continue
                notes_lines.append(line)
            elif line.startswith("Meeting Name:"):
                meeting_name = line[len("Meeting Name:"):].strip()
            elif line.startswith("Date/Time:"):
                meeting_datetime = line[len("Date/Time:"):].strip()
            elif line.strip() == "Notes:":
                in_notes = True
            # Skip separator lines (====)
        
        if meeting_name:
            self.meeting_name_input.setText(meeting_name)
        if meeting_datetime:
            # Normalize to GUI format (MM/DD/YYYY hh:mm AM/PM) if stored
            # in the older TUI format (YYYY-MM-DD HH:MM)
            meeting_datetime = self._normalize_datetime(meeting_datetime)
            self.meeting_datetime_input.setText(meeting_datetime)
        if notes_lines:
            # Strip trailing empty lines
            while notes_lines and not notes_lines[-1].strip():
                notes_lines.pop()
            self.meeting_notes_input.setPlainText("\n".join(notes_lines))
            
    def _update_button_states(self):
        """Update button enabled states based on current state."""
        has_recorder = self.recorder_instance is not None
        has_session = has_recorder or self.current_recording_path is not None
        has_content = self.snapshot_count > 0
        has_transcript_text = has_content or bool(self.transcript_text.toPlainText().strip())

        # Manual Recording doesn't require accessibility and allows New
        # without accessibility permissions, but does not support capture.
        if self._is_manual_mode:
            self.app_combo.setEnabled(not has_session)
            self.new_btn.setEnabled(not has_session)
        else:
            self.app_combo.setEnabled(not has_session and self._has_accessibility)
            self.new_btn.setEnabled(not has_session and self._has_accessibility)

        self.reset_btn.setEnabled(has_session)

        # History: disabled during an active session — user must Reset first
        self.load_previous_btn.setEnabled(not has_session)
        if has_session:
            self.load_previous_btn.setToolTip("Reset the current session before loading history")
        else:
            self.load_previous_btn.setToolTip("Open a previous meeting and transcript")

        # Capture buttons are disabled in manual mode — there is nothing to capture
        if self._is_manual_mode:
            self.capture_btn.setEnabled(False)
            self.auto_capture_btn.setEnabled(False)
        else:
            self.capture_btn.setEnabled(has_recorder and not self._is_capturing and self._has_accessibility)
            self.auto_capture_btn.setEnabled(has_recorder and not self._is_capturing and self._has_accessibility)
        
        self.tab_widget.setEnabled(has_session)
        
        # Transcript edit button: disabled when auto-capture is running or no session
        if self.is_recording:
            self.edit_transcript_btn.setEnabled(False)
            self.edit_transcript_btn.setToolTip("Cannot edit while auto capture is running")
        elif has_session:
            self.edit_transcript_btn.setEnabled(True)
            if self._transcript_edit_mode:
                self.edit_transcript_btn.setToolTip("Editing enabled — click to disable")
            else:
                self.edit_transcript_btn.setToolTip("Enable transcript editing")
        else:
            self.edit_transcript_btn.setEnabled(False)
            self.edit_transcript_btn.setToolTip("Enable transcript editing")
        self._update_edit_button_icon()

        # Transcript save button: enabled only when there are unsaved changes
        self.save_transcript_btn.setEnabled(
            has_session and self._transcript_modified)

        self.copy_btn.setEnabled(has_transcript_text)
        self.refresh_transcript_btn.setEnabled(has_transcript_text)
        self.open_folder_btn.setEnabled(has_transcript_text)
        
        self.save_details_btn.setEnabled(has_session)
        self.open_folder_btn2.setEnabled(has_session)
        
        self.time_up_btn.setEnabled(has_session)
        self.time_down_btn.setEnabled(has_session)
        
        has_tool = self.tool_combo.currentData() is not None
        self.run_tool_btn.setEnabled(has_session and has_tool)
        
        self._update_auto_capture_btn_style()
    
    def _update_auto_capture_btn_style(self):
        """Update the auto capture button text and color based on recording state."""
        if self.is_recording:
            self.auto_capture_btn.setText(f"Stop ({self.capture_interval}s)")
            self.auto_capture_btn.setToolTip("Stop continuous transcript capture")
            self.auto_capture_btn.setProperty("class", "toggle_on")
        else:
            self.auto_capture_btn.setText("Auto Capture")
            self.auto_capture_btn.setToolTip("Start continuous transcript capture")
            self.auto_capture_btn.setProperty("class", "toggle_off")
        
        self.auto_capture_btn.style().unpolish(self.auto_capture_btn)
        self.auto_capture_btn.style().polish(self.auto_capture_btn)
    
    def _toggle_maximized_view(self):
        """Toggle between default and maximized window sizes.

        If currently compact, expand first so the user never sees a
        compact + maximized state.
        """
        is_dark = self._is_dark_mode()
        
        # If compact, expand first before maximizing
        if self._compact_mode:
            self._compact_mode = False
            self.tab_widget.show()
            self.separator_bottom.show()
            self.compact_btn.setIcon(IconManager.get_icon(
                "chevrons_up", is_dark=is_dark, size=16))
            self.compact_btn.setToolTip("Compact view")
            self.setMinimumSize(350, 300)
        
        self._maximized_view = not self._maximized_view
        
        if self._maximized_view:
            self.resize(self._maximized_size)
            self.maximize_btn.setIcon(IconManager.get_icon(
                "minimize", is_dark=is_dark, size=16))
            self.maximize_btn.setToolTip("Restore window")
        else:
            self.resize(self._default_size)
            self.maximize_btn.setIcon(IconManager.get_icon(
                "maximize", is_dark=is_dark, size=16))
            self.maximize_btn.setToolTip("Maximize window")
    
    def _toggle_compact_mode(self):
        """Toggle between compact and expanded window views.

        If currently maximized, restore to default size first so the user
        never sees a compact + maximized state.

        Compact mode hides the tab section and shrinks both width and
        height to the tightest size that still fits the top-bar controls
        without wrapping.
        """
        is_dark = self._is_dark_mode()
        
        # If maximized, restore first before compacting
        if self._maximized_view:
            self._maximized_view = False
            self.maximize_btn.setIcon(IconManager.get_icon(
                "maximize", is_dark=is_dark, size=16))
            self.maximize_btn.setToolTip("Maximize window")
            self.resize(self._default_size)
        
        self._compact_mode = not self._compact_mode
        
        if self._compact_mode:
            self._expanded_size = self.size()
            self.tab_widget.hide()
            self.separator_bottom.hide()
            self.compact_btn.setIcon(IconManager.get_icon(
                "chevrons_down", is_dark=is_dark, size=16))
            self.compact_btn.setToolTip("Expand view")
            QApplication.processEvents()
            self.setMinimumSize(0, 0)
            hint = self.minimumSizeHint()
            self.resize(hint.width(), hint.height())
        else:
            self.tab_widget.show()
            self.separator_bottom.show()
            self.compact_btn.setIcon(IconManager.get_icon(
                "chevrons_up", is_dark=is_dark, size=16))
            self.compact_btn.setToolTip("Compact view")
            self.setMinimumSize(350, 300)
            self.resize(self._expanded_size)
    
    def _on_toggle_auto_capture(self):
        """Toggle auto capture on/off."""
        if self.is_recording:
            self._on_stop_recording()
        else:
            self._on_start_recording()
    
    def _on_meeting_details_changed(self):
        """Mark meeting details as modified."""
        self.meeting_details_dirty = True
    
    def _on_round_time_down(self):
        """Round the time down to the nearest 5 minutes."""
        self._round_time(-1)
    
    def _on_round_time_up(self):
        """Round the time up to the nearest 5 minutes."""
        self._round_time(1)
    
    # Datetime formats the app recognises (GUI format first, then TUI legacy)
    _DATETIME_FORMATS = [
        "%m/%d/%Y %I:%M %p",   # GUI: 02/07/2026 08:45 PM
        "%Y-%m-%d %H:%M",      # TUI: 2025-08-13 14:30
    ]
    _CANONICAL_DT_FMT = _DATETIME_FORMATS[0]
    
    def _normalize_datetime(self, text: str) -> str:
        """Parse a datetime string in any recognised format and return
        it in the canonical GUI format (MM/DD/YYYY hh:mm AM/PM)."""
        text = text.strip()
        for fmt in self._DATETIME_FORMATS:
            try:
                dt = datetime.strptime(text, fmt)
                return dt.strftime(self._CANONICAL_DT_FMT)
            except ValueError:
                continue
        # If nothing matched, return the original text unchanged
        return text
    
    def _parse_datetime(self, text: str):
        """Try to parse *text* using all recognised datetime formats.
        Returns a datetime on success or None on failure."""
        text = text.strip()
        for fmt in self._DATETIME_FORMATS:
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        return None
    
    def _round_time(self, direction: int):
        """Round the time in the datetime input by 5 minutes."""
        text = self.meeting_datetime_input.text().strip()
        if not text:
            return
        
        dt = self._parse_datetime(text)
        if dt is None:
            return
        
        current_minutes = dt.minute
        
        if direction < 0:
            new_minutes = (current_minutes // 5) * 5
            if new_minutes == current_minutes:
                new_minutes -= 5
        else:
            new_minutes = ((current_minutes + 4) // 5) * 5
            if new_minutes == current_minutes:
                new_minutes += 5
        
        if new_minutes >= 60:
            dt = dt.replace(minute=0) + timedelta(hours=1)
        elif new_minutes < 0:
            dt = dt.replace(minute=55) - timedelta(hours=1)
        else:
            dt = dt.replace(minute=new_minutes)
        
        self.meeting_datetime_input.setText(dt.strftime(self._CANONICAL_DT_FMT))
    
    def _save_meeting_details(self, force: bool = False):
        """Save meeting details to file if modified."""
        if not self.current_recording_path:
            return
        
        meeting_name = self.meeting_name_input.text().strip()
        meeting_datetime = self.meeting_datetime_input.text().strip()
        meeting_notes = self.meeting_notes_input.toPlainText().strip()
        
        if not meeting_name and not meeting_datetime and not meeting_notes:
            return
        
        if not self._ensure_recording_folder():
            return
        
        details_path = self.current_recording_path / "meeting_details.txt"
        file_missing = not details_path.exists()
        
        if not force and not self.meeting_details_dirty and not file_missing:
            return
        
        try:
            with open(details_path, 'w', encoding='utf-8') as f:
                if meeting_name:
                    f.write(f"Meeting Name: {meeting_name}\n")
                    f.write("=" * (len(meeting_name) + 14) + "\n\n")
                if meeting_datetime:
                    f.write(f"Date/Time: {meeting_datetime}\n\n")
                if meeting_notes:
                    f.write("Notes:\n")
                    f.write("-" * 40 + "\n")
                    f.write(meeting_notes + "\n")
            
            self.meeting_details_dirty = False
            logger.debug(f"Meeting details saved to {details_path}")
        except Exception as e:
            logger.error(f"Failed to save meeting details: {e}")
            return
        
        # After a successful save, rename the folder to reflect the datetime
        if meeting_datetime:
            self._rename_recording_folder_for_datetime(meeting_datetime)
    
    # Regex matching the timestamp portion of a recording folder name.
    # Handles both GUI style (recording_2026-02-07_2045) and
    # TUI style  (recording_2025-05-22_13-57).
    _FOLDER_TS_RE = re.compile(
        r'^(recording_)\d{4}-\d{2}-\d{2}_\d{2}-?\d{2}(.*)'
    )
    
    def _rename_recording_folder_for_datetime(self, meeting_datetime: str):
        """Rename the recording folder so its embedded timestamp matches
        the datetime shown in the UI.  Skipped when a capture is running
        or the folder hasn't been created yet."""
        if not self.current_recording_path or not self.current_recording_path.exists():
            return
        
        # Never rename while a background capture is in progress
        if self._is_capturing:
            return
        
        dt = self._parse_datetime(meeting_datetime)
        if dt is None:
            return
        
        old_name = self.current_recording_path.name
        match = self._FOLDER_TS_RE.match(old_name)
        if not match:
            return  # Folder doesn't follow the naming convention
        
        new_timestamp = dt.strftime('%Y-%m-%d_%H%M')
        new_name = f"{match.group(1)}{new_timestamp}{match.group(2)}"
        
        if new_name == old_name:
            return  # Already in sync
        
        new_path = self.current_recording_path.parent / new_name
        
        if new_path.exists():
            logger.warning(f"Cannot rename recording folder: target already exists: {new_path}")
            return
        
        try:
            self.current_recording_path.rename(new_path)
            logger.info(f"Recording folder renamed: {old_name} -> {new_name}")
            
            # Update all path references
            self.current_recording_path = new_path
            self.snapshots_path = new_path / ".snapshots"
            self.merged_transcript_path = new_path / "meeting_transcript.txt"
            
            # Keep the recorder's base directory in sync
            if self.recorder_instance:
                self.recorder_instance._transcript_base_dir = self.snapshots_path
            
            self.statusBar().showMessage(f"Folder renamed — {new_name}")
        except OSError as e:
            logger.error(f"Failed to rename recording folder: {e}")
    
    # ------------------------------------------------------------------
    #  Meeting Tools -- discovery, display, and execution
    # ------------------------------------------------------------------

    def _adjust_window_for_section(self, widget: QWidget, expanding: bool):
        """Grow or shrink the window to accommodate a collapsible section.

        When *expanding*, the window height increases by the widget's
        sizeHint (capped so the window never exceeds 90 % of the available
        screen height).  When *collapsing*, it shrinks by the widget's
        current height.
        """
        if self._compact_mode:
            return  # don't resize while in compact view
        
        delta = widget.sizeHint().height() if expanding else widget.height()
        if delta <= 0:
            return
        
        screen = self.screen()
        max_height = int(screen.availableGeometry().height() * 0.9) if screen else 900
        
        geo = self.geometry()
        if expanding:
            new_h = min(geo.height() + delta, max_height)
        else:
            new_h = max(geo.height() - delta, self.minimumHeight())
        
        geo.setHeight(new_h)
        self.setGeometry(geo)

    def _toggle_tool_params(self):
        """Toggle visibility of the parameters table."""
        visible = not self.tool_params_table.isVisible()
        self._adjust_window_for_section(self.tool_params_table, expanding=visible)
        self.tool_params_table.setVisible(visible)
        self.tool_params_toggle.setText(
            "▼ Parameters" if visible else "▶ Parameters"
        )

    def _toggle_tool_data_files(self):
        """Toggle visibility of the data files section."""
        visible = not self.tool_data_files_widget.isVisible()
        self._adjust_window_for_section(self.tool_data_files_widget, expanding=visible)
        self.tool_data_files_widget.setVisible(visible)
        self.tool_data_files_toggle.setText(
            "▼ Data Files" if visible else "▶ Data Files"
        )

    def _populate_tool_data_files(self, tool_def: dict):
        """Build the data files section for the currently selected tool."""
        while self.tool_data_files_layout.count():
            child = self.tool_data_files_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        data_files = tool_def.get("data_files", [])
        tool_dir = Path(tool_def.get("_tool_dir", ""))
        tool_name = tool_def.get("display_name", "")

        if not data_files:
            self.tool_data_files_toggle.setVisible(False)
            self.tool_data_files_widget.setVisible(False)
            return

        for df in data_files:
            file_name = df.get("file", "")
            label = df.get("label", file_name)
            description = df.get("description", "")
            editor_type = df.get("editor", "key_value_grid")
            file_path = tool_dir / file_name

            row = QHBoxLayout()
            row.setSpacing(8)

            desc_label = QLabel(f"<b>{label}</b>")
            if description:
                desc_label.setToolTip(description)
            row.addWidget(desc_label, stretch=1)

            edit_btn = QPushButton("Edit")
            edit_btn.setFixedWidth(60)
            edit_btn.clicked.connect(
                lambda checked=False, fp=file_path, et=editor_type,
                       lbl=label, tn=tool_name: self._open_data_file_editor(fp, et, lbl, tn)
            )
            row.addWidget(edit_btn)

            row_widget = QWidget()
            row_widget.setObjectName("panel_row")
            row_widget.setLayout(row)
            self.tool_data_files_layout.addWidget(row_widget)

        self.tool_data_files_toggle.setVisible(True)
        self.tool_data_files_widget.setVisible(False)
        self.tool_data_files_toggle.setText("▶ Data Files")

    def _open_data_file_editor(self, file_path: Path, editor_type: str,
                                label: str, tool_name: str):
        """Open a DataFileEditorDialog for the given data file."""
        dialog = DataFileEditorDialog(file_path, editor_type, label, tool_name, self)
        self._data_file_editors.append(dialog)
        dialog.show()

    def _scan_tools(self):
        """Scan ``<export_dir>/tools/`` for tool definitions."""
        self._discovered_tools = {}
        self.tool_combo.clear()
        self.tool_combo.addItem("Select a tool...", None)
        
        if not self.export_base_dir:
            return
        
        self._tool_scripts_dir = self.export_base_dir / "tools"
        
        try:
            self._tool_scripts_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"Tools: failed to create tools directory: {e}")
            return
        
        try:
            subdirs = sorted(
                p for p in self._tool_scripts_dir.iterdir() if p.is_dir()
            )
        except OSError as e:
            logger.error(f"Tools: could not list tools directory: {e}")
            return
        
        for tool_dir in subdirs:
            json_path = tool_dir / "tool.json"
            if not json_path.exists():
                json_files = sorted(tool_dir.glob("*.json"))
                if not json_files:
                    logger.debug(f"Tools: no .json definition in {tool_dir.name}/ — skipped")
                    continue
                json_path = json_files[0]
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    tool_def = json.load(f)
                
                if not tool_def.get("display_name") or not tool_def.get("script"):
                    logger.warning(f"Tools: {tool_dir.name}/{json_path.name} missing 'display_name' or 'script'")
                    continue
                
                script_path = tool_dir / tool_def["script"]
                if not script_path.exists():
                    logger.warning(f"Tools: script not found: {script_path}")
                    continue
                
                tool_def["_script_path"] = str(script_path)
                tool_def["_json_path"] = str(json_path)
                tool_def["_tool_dir"] = str(tool_dir)
                
                tool_key = tool_dir.name
                self._discovered_tools[tool_key] = tool_def
                self.tool_combo.addItem(tool_def["display_name"], tool_key)
                
                logger.debug(f"Tools: discovered '{tool_def['display_name']}' in {tool_dir.name}/")
                
            except json.JSONDecodeError as e:
                logger.warning(f"Tools: invalid JSON in {tool_dir.name}/{json_path.name}: {e}")
            except Exception as e:
                logger.error(f"Tools: error loading {tool_dir.name}/{json_path.name}: {e}")
        
        count = len(self._discovered_tools)
        if count:
            logger.info(f"Tools: discovered {count} tool(s) in {self._tool_scripts_dir}")
        else:
            logger.debug(f"Tools: no tools found in {self._tool_scripts_dir}")

    def _get_builtin_values(self) -> Dict[str, str]:
        """Return a mapping of built-in parameter names to current app values.

        Categories:
        - Session builtins: require an active recording (meeting_directory, etc.)
        - Meeting date builtins: parsed from the Date/Time GUI field
        - Current date builtins: always available from the system clock
        - Meeting details builtins: from the GUI Meeting Details fields
        - System builtins: paths and user info, always available
        - env:<VAR> builtins: resolved separately in _resolve_builtin()
        """
        values: Dict[str, str] = {}

        # --- Session builtins (require a loaded recording) ---
        if self.current_recording_path:
            values["meeting_directory"] = str(self.current_recording_path)
        if self.merged_transcript_path:
            values["meeting_transcript"] = str(self.merged_transcript_path)
        if self.current_recording_path:
            values["meeting_details"] = str(self.current_recording_path / "meeting_details.txt")
        if self.export_base_dir:
            values["export_directory"] = str(self.export_base_dir)
        if self.selected_app_key:
            values["app_name"] = self.selected_app_key

        # --- Meeting date builtins (parsed from the Date/Time field) ---
        meeting_dt = self._parse_datetime(self.meeting_datetime_input.text())
        if meeting_dt:
            values["meeting_date"] = meeting_dt.strftime("%Y-%m-%d")
            values["meeting_date_year_month"] = meeting_dt.strftime("%Y-%m")   # 2026-02
            values["meeting_date_year"] = meeting_dt.strftime("%Y")
            values["meeting_date_month"] = meeting_dt.strftime("%m")
            values["meeting_date_month_name"] = meeting_dt.strftime("%B")      # February
            values["meeting_date_month_short"] = meeting_dt.strftime("%b")     # Feb

        # --- Meeting details builtins (from the GUI fields) ---
        meeting_name = self.meeting_name_input.text().strip()
        if meeting_name:
            values["meeting_name"] = meeting_name
        meeting_datetime_raw = self.meeting_datetime_input.text().strip()
        if meeting_datetime_raw:
            values["meeting_datetime"] = meeting_datetime_raw

        # --- Current date builtins (always available) ---
        now = datetime.now()
        values["current_date"] = now.strftime("%Y-%m-%d")
        values["current_date_year_month"] = now.strftime("%Y-%m")
        values["current_date_year"] = now.strftime("%Y")
        values["current_date_month"] = now.strftime("%m")
        values["current_date_month_name"] = now.strftime("%B")
        values["current_date_month_short"] = now.strftime("%b")

        # --- System builtins (always available) ---
        values["home_directory"] = str(Path.home())
        values["user_name"] = os.environ.get("USER", os.environ.get("USERNAME", ""))
        if self._tool_scripts_dir:
            values["tools_directory"] = str(self._tool_scripts_dir)
        # tool_directory is added per-tool in _resolve_builtin()

        return values

    def _resolve_builtin(self, builtin_key: str, builtins: Dict[str, str],
                         tool_def: Optional[dict] = None) -> Optional[str]:
        """Resolve a single builtin key to its value.

        Handles the env:<VAR> prefix for environment variable lookups,
        the tool_directory key (per-tool), and plain builtin dict lookups.
        Returns None if the key cannot be resolved.
        """
        # env: prefix — look up an environment variable
        if builtin_key.startswith("env:"):
            var_name = builtin_key[4:]
            val = os.environ.get(var_name)
            return val  # None if not set → caller falls through to default

        # tool_directory — resolved per-tool from its definition
        if builtin_key == "tool_directory" and tool_def:
            tool_dir = tool_def.get("_tool_dir")
            if tool_dir:
                return str(tool_dir)
            return None

        return builtins.get(builtin_key)

    def _on_tool_changed(self, index: int):
        """Handle tool selection change -- populate the parameters table."""
        tool_key = self.tool_combo.currentData()
        has_tool = tool_key is not None
        has_session = self.recorder_instance is not None or self.current_recording_path is not None
        is_running = self._tool_runner is not None
        if not is_running:
            self.run_tool_btn.setEnabled(has_tool and has_session)
        
        if not has_tool:
            self.tool_separator.setVisible(False)
            self.tool_description_label.setVisible(False)
            self.tool_params_toggle.setVisible(False)
            self.tool_params_table.setVisible(False)
            self.tool_params_table.setRowCount(0)
            self.tool_command_frame.setVisible(False)
            self.tool_data_files_toggle.setVisible(False)
            self.tool_data_files_widget.setVisible(False)
            self.tool_output_area.clear()
            return
        
        tool_def = self._discovered_tools.get(tool_key, {})
        description = tool_def.get("description", "")
        parameters = tool_def.get("parameters", [])
        
        self.tool_separator.setVisible(True)
        self.tool_description_label.setText(description)
        self.tool_description_label.setVisible(bool(description))
        
        builtins = self._get_builtin_values()
        self.tool_params_table.setRowCount(len(parameters))
        
        for row, param in enumerate(parameters):
            flag = param.get("flag", "")
            label = param.get("label", flag)
            builtin_key = param.get("builtin")
            default = param.get("default", "")
            
            flag_item = QTableWidgetItem(flag)
            flag_item.setFlags(flag_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.tool_params_table.setItem(row, 0, flag_item)
            
            label_text = f"{label}  (auto)" if builtin_key else label
            label_item = QTableWidgetItem(label_text)
            label_item.setFlags(label_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.tool_params_table.setItem(row, 1, label_item)
            
            if builtin_key:
                resolved = self._resolve_builtin(builtin_key, builtins, tool_def)
                value = resolved if resolved is not None else f"<{builtin_key}>"
            else:
                value = str(default)
            value_item = QTableWidgetItem(value)
            self.tool_params_table.setItem(row, 2, value_item)
        
        has_params = len(parameters) > 0
        self.tool_params_toggle.setVisible(has_params)
        if has_params:
            self.tool_params_table.setVisible(False)
            self.tool_params_toggle.setText("▶ Parameters")
        
        self.tool_command_frame.setVisible(False)
        
        self._populate_tool_data_files(tool_def)
        
        self._update_tool_output_preview()
    
    def _on_tool_param_edited(self, row: int, column: int):
        """Refresh the command preview when the user edits a parameter value."""
        if column == 2:
            self._update_tool_output_preview()
    
    def _update_tool_command_preview(self):
        """Build the command from current table values and show it in the label."""
        command = self._build_tool_command(preview=True)
        if command:
            self.tool_command_label.setText(f"Command: {' '.join(command)}")
            self.tool_command_frame.setVisible(self.tool_params_table.isVisible())
        else:
            self.tool_command_frame.setVisible(False)
    
    def _update_tool_output_preview(self):
        """Show the tool name, run instruction, and command in the output area."""
        tool_key = self.tool_combo.currentData()
        if not tool_key:
            self.tool_output_area.clear()
            return
        
        tool_def = self._discovered_tools.get(tool_key, {})
        display_name = tool_def.get("display_name", tool_key)
        
        command = self._build_tool_command(preview=True)
        cmd_text = " ".join(command) if command else "<unable to build command>"
        
        separator = "—" * 40
        preview_text = (
            f"{separator}\n"
            f"{display_name}\n"
            f"{separator}\n"
            f"\n"
            f"Clicking Run will execute the following command.  "
            f"The output from {display_name} will be shown here when completed.\n"
            f"\n"
            f"command: {cmd_text}\n"
        )
        self.tool_output_area.setPlainText(preview_text)
    
    def _build_tool_command(self, preview: bool = False) -> Optional[List[str]]:
        """Read the parameters table and build the command list."""
        tool_key = self.tool_combo.currentData()
        if not tool_key:
            return None
        
        tool_def = self._discovered_tools.get(tool_key)
        if not tool_def:
            return None
        
        script_path = Path(tool_def["_script_path"])
        if not script_path.exists():
            if not preview:
                self.tool_output_area.setPlainText(f"Error: script not found: {script_path}")
            return None
        
        user_shell = os.environ.get("SHELL", "/bin/zsh")
        interpreters = {
            ".sh": user_shell, ".bash": "/bin/bash",
            ".zsh": "/bin/zsh",
            ".py": sys.executable,
        }
        interpreter = interpreters.get(script_path.suffix.lower())
        command: List[str] = [interpreter, str(script_path)] if interpreter else [str(script_path)]
        
        if not interpreter:
            try:
                mode = script_path.stat().st_mode
                if not (mode & 0o100):
                    script_path.chmod(mode | 0o755)
            except OSError as e:
                logger.warning(f"Tools: could not set execute permission: {e}")
        
        parameters = tool_def.get("parameters", [])
        for row in range(self.tool_params_table.rowCount()):
            if row >= len(parameters):
                break
            param = parameters[row]
            flag_item = self.tool_params_table.item(row, 0)
            value_item = self.tool_params_table.item(row, 2)
            flag = flag_item.text().strip() if flag_item else ""
            value = value_item.text().strip() if value_item else ""
            
            if not flag:
                continue
            
            if param.get("type") == "boolean":
                if value.lower() in ("true", "1", "yes"):
                    command.append(flag)
                continue
            
            if value and not value.startswith("<"):
                command.extend([flag, value])
            elif param.get("required", False):
                if not preview:
                    self.tool_output_area.setPlainText(
                        f"Error: required parameter '{param.get('label', flag)}' has no value.\n"
                        "Enter a value in the Parameters table above."
                    )
                return None
        
        return command
    
    @staticmethod
    def _format_elapsed(seconds: int) -> str:
        """Return a human-friendly elapsed time string."""
        if seconds < 60:
            return f"{seconds}s"
        minutes, secs = divmod(seconds, 60)
        if minutes < 60:
            return f"{minutes}m {secs}s"
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h {minutes}m {secs}s"
    
    def _on_tool_timer_tick(self):
        """Update the elapsed-time label while a tool is running."""
        elapsed = int(time.time() - self._tool_start_time)
        elapsed_str = self._format_elapsed(elapsed)
        self.tool_elapsed_label.setText(elapsed_str)
        
        runner = self._tool_runner
        if isinstance(runner, StreamingToolRunnerWorker):
            idle = time.time() - runner.last_output_time
            kill_timeout = getattr(self, "_idle_kill_seconds", 120)
            warn_timeout = getattr(self, "_idle_warning_seconds", 30)
            
            if idle > kill_timeout:
                logger.warning(f"Tools: idle timeout reached ({idle:.0f}s > {kill_timeout}s), "
                               f"auto-cancelling")
                self.statusBar().showMessage(
                    f"Agent idle for {int(idle)}s — auto-cancelling…"
                )
                self._on_cancel_tool()
                return
            elif idle > warn_timeout:
                remaining = int(kill_timeout - idle)
                self.statusBar().showMessage(
                    f"Running tool… {elapsed_str} — agent idle for {int(idle)}s "
                    f"(auto-cancel in {remaining}s)"
                )
                return
        
        self.statusBar().showMessage(f"Running tool… {elapsed_str}")
    
    def _on_run_cancel_toggle(self):
        """Dispatch the Run/Cancel toggle button click."""
        if self._tool_runner is not None:
            self._on_cancel_tool()
        else:
            self._on_run_tool()

    def _on_cancel_tool(self):
        """Cancel the currently running tool."""
        if self._tool_runner:
            logger.info("Tools: cancel requested by user")
            self.run_tool_btn.setEnabled(False)
            self.run_tool_btn.setText("Cancelling…")
            self._tool_runner.cancel()
            logger.debug("Tools: cancel() returned, waiting for worker thread to finish")
        else:
            logger.warning("Tools: cancel clicked but no _tool_runner active")
    
    def _on_run_tool(self):
        """Build the command line from the parameters table and run the script."""
        command = self._build_tool_command()
        if not command:
            return
        
        tool_key = self.tool_combo.currentData()
        tool_def = self._discovered_tools.get(tool_key, {})
        display_name = tool_def.get("display_name", tool_key)
        tool_dir = tool_def.get("_tool_dir", str(self._tool_scripts_dir))
        
        cmd_text = " ".join(command)
        self.tool_output_area.setPlainText(
            f"Running: {display_name}\n{'—' * 60}\n\n"
            f"command: {cmd_text}\n"
        )
        
        self.run_tool_btn.setText("Cancel")
        self.run_tool_btn.setProperty("class", "danger-outline")
        self.run_tool_btn.style().unpolish(self.run_tool_btn)
        self.run_tool_btn.style().polish(self.run_tool_btn)
        
        self._tool_start_time = time.time()
        self.tool_elapsed_label.setText("0s")
        if self._tool_elapsed_timer is None:
            self._tool_elapsed_timer = QTimer(self)
            self._tool_elapsed_timer.timeout.connect(self._on_tool_timer_tick)
        self._tool_elapsed_timer.start(1000)
        
        self.statusBar().showMessage(f"Running tool: {display_name}")
        QApplication.processEvents()
        
        logger.info(f"Tools: started '{display_name}' → {cmd_text}")
        
        self._idle_warning_seconds = tool_def.get("idle_warning_seconds", 30)
        self._idle_kill_seconds = tool_def.get("idle_kill_seconds", 120)
        
        if tool_def.get("streaming", False):
            parser_name = tool_def.get("stream_parser", "raw")
            parser_fn = STREAM_PARSERS.get(parser_name, _stream_parser_raw)
            logger.debug(f"Tools: using streaming worker with parser '{parser_name}'")
            self._tool_runner = StreamingToolRunnerWorker(
                command, cwd=tool_dir, parser_fn=parser_fn)
            self._tool_runner.output_line.connect(self._on_tool_output_line)
        else:
            self._tool_runner = ToolRunnerWorker(command, cwd=tool_dir)
        
        self._tool_runner.output_ready.connect(self._on_tool_finished)
        self._tool_runner.start()
    
    def _on_tool_output_line(self, text: str):
        """Append a single streaming line to the tool output area (real-time)."""
        text = strip_ansi(text)
        cursor = self.tool_output_area.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.tool_output_area.setTextCursor(cursor)
        self.tool_output_area.insertPlainText(text + "\n")
        scrollbar = self.tool_output_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def _on_tool_finished(self, stdout: str, stderr: str, exit_code: int):
        """Handle tool script completion."""
        logger.debug(f"Tools._on_tool_finished: exit_code={exit_code}, "
                     f"stdout_len={len(stdout)}, stderr_len={len(stderr)}")
        if self._tool_elapsed_timer:
            self._tool_elapsed_timer.stop()
        
        elapsed = int(time.time() - self._tool_start_time)
        elapsed_str = self._format_elapsed(elapsed)
        
        tool_key = self.tool_combo.currentData()
        display_name = self._discovered_tools.get(tool_key, {}).get("display_name", "Tool")
        
        cancelled = exit_code == -2
        is_streaming = isinstance(self._tool_runner, StreamingToolRunnerWorker)
        
        current = self.tool_output_area.toPlainText()
        parts = [current]
        if not is_streaming and stdout:
            parts.append(strip_ansi(stdout))
        if stderr:
            parts.append(f"\n--- stderr ---\n{strip_ansi(stderr)}")
        
        if cancelled:
            parts.append(f"\n{'—' * 60}\nCancelled after {elapsed_str}")
        else:
            parts.append(f"\n{'—' * 60}\nFinished in {elapsed_str} (exit code {exit_code})")
        
        self.tool_output_area.setPlainText("\n".join(parts))
        
        scrollbar = self.tool_output_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        
        self.run_tool_btn.setText("Run")
        self.run_tool_btn.setProperty("class", "action")
        self.run_tool_btn.setEnabled(True)
        self.run_tool_btn.style().unpolish(self.run_tool_btn)
        self.run_tool_btn.style().polish(self.run_tool_btn)
        self.tool_elapsed_label.setText("")
        self._tool_runner = None
        
        if cancelled:
            self.statusBar().showMessage(f"Tool cancelled: {display_name} ({elapsed_str})")
            logger.info(f"Tools: '{display_name}' cancelled after {elapsed_str}")
        elif exit_code == 0:
            self.statusBar().showMessage(f"Tool completed: {display_name} ({elapsed_str})")
            logger.info(f"Tools: '{display_name}' completed in {elapsed_str} (exit code 0)")
            self._apply_tool_refresh(tool_key)
        else:
            self.statusBar().showMessage(f"Tool failed: {display_name} (exit code {exit_code}, {elapsed_str})")
            logger.warning(f"Tools: '{display_name}' failed (exit code {exit_code}) after {elapsed_str}")
    
    def _apply_tool_refresh(self, tool_key: str):
        """Reload UI elements specified by a tool's ``refresh_on_complete`` list.

        Called after a tool exits successfully (exit code 0).  Recognised
        refresh targets:

        - ``"meeting_transcript"`` — reload ``meeting_transcript.txt`` into
          the Transcript tab.
        - ``"meeting_details"`` — reload ``meeting_details.txt`` into the
          Meeting Details fields.
        """
        tool_def = self._discovered_tools.get(tool_key, {})
        refresh_targets = tool_def.get("refresh_on_complete", [])
        if not refresh_targets:
            return

        refreshed: list[str] = []

        for target in refresh_targets:
            if target == "meeting_transcript":
                if (self.merged_transcript_path
                        and self.merged_transcript_path.exists()):
                    self._update_transcript_display(
                        str(self.merged_transcript_path))
                    self._transcript_modified = False
                    self.save_transcript_btn.setEnabled(False)
                    refreshed.append("transcript")
                    logger.info("Tools: refreshed meeting transcript from disk")
            elif target == "meeting_details":
                if self.current_recording_path:
                    details_path = (
                        self.current_recording_path / "meeting_details.txt"
                    )
                    if details_path.exists():
                        self._load_meeting_details_from_file(details_path)
                        self.meeting_details_dirty = False
                        refreshed.append("meeting details")
                        logger.info(
                            "Tools: refreshed meeting details from disk")
            else:
                logger.warning(
                    f"Tools: unknown refresh_on_complete target: {target!r}")

        if refreshed:
            label = " & ".join(refreshed)
            display_name = tool_def.get("display_name", tool_key)
            self.statusBar().showMessage(
                f"Tool completed: {display_name} — refreshed {label}")

    def _on_save_details_clicked(self):
        """Handle save details button click."""
        self._save_meeting_details(force=True)
        self.statusBar().showMessage("Meeting details saved")
    
    # ------------------------------------------------------------------
    # Google Calendar integration
    # ------------------------------------------------------------------

    def _load_calendar_config(self):
        """Load Google Calendar settings from config and update UI visibility.

        If the integration is ready and a token already exists (i.e. the
        user has previously authorised), kick off a background fetch so
        events are pre-loaded when the user first clicks the calendar icon.
        """
        if not self.config:
            return
        raw = self.config.get("google_calendar", {})
        token_dir = APP_SUPPORT_DIR / "google"
        self._calendar_config = calendar_config_from_dict(raw, token_dir)
        self._calendar_last_refreshed = raw.get("last_refreshed")
        self._update_calendar_button_visibility()
        if self._calendar_config.is_ready():
            logger.info("Calendar: integration enabled and ready")
            # Auto-fetch on launch only when a token exists (avoids opening
            # a browser window before the user asks for it).
            if self._calendar_config.has_token():
                self._start_calendar_fetch(silent=True)
        else:
            logger.debug("Calendar: integration not configured or packages missing")

    def _update_calendar_button_visibility(self):
        """Show/hide the calendar button and Sign Out action based on config state."""
        visible = (
            self._calendar_config is not None
            and self._calendar_config.is_ready()
        )
        self.calendar_btn.setVisible(visible)
        # Sign Out is only visible when a token file exists
        has_token = (
            self._calendar_config is not None
            and self._calendar_config.has_token()
        )
        self._calendar_sign_out_action.setVisible(has_token)

    # ------------------------------------------------------------------
    # Calendar fetch helpers
    # ------------------------------------------------------------------

    def _start_calendar_fetch(
        self,
        *,
        silent: bool = False,
        target_date_iso: Optional[str] = None,
    ):
        """Kick off a background fetch for calendar events.

        Parameters
        ----------
        silent:
            If True, don't update status bar and don't auto-open the
            events dialog when events arrive (used for auto-fetch on launch).
        target_date_iso:
            ISO date string (``YYYY-MM-DD``).  If ``None``, fetches today.
        """
        if self._calendar_worker and self._calendar_worker.isRunning():
            return  # already fetching

        self._calendar_fetch_silent = silent

        if not silent:
            self.statusBar().showMessage("Fetching calendar events...")
            self.calendar_btn.setEnabled(False)

        self._calendar_worker = CalendarFetchWorker(
            self._calendar_config,
            target_date_iso=target_date_iso,
            parent=self,
        )
        self._calendar_worker.raw_events_ready.connect(self._on_calendar_raw_events_ready)
        self._calendar_worker.auth_required.connect(self._on_calendar_auth_required)
        self._calendar_worker.error.connect(self._on_calendar_error)
        self._calendar_worker.start()

    def _on_calendar_clicked(self):
        """Handle click on the calendar icon — open the events dialog.

        If we already have cached events, open the dialog immediately.
        Otherwise, fetch first and open once ready.
        """
        if not self._calendar_config or not self._calendar_config.is_ready():
            ThemedMessageDialog.info(
                self, "Calendar Not Configured",
                "Google Calendar integration is not configured.\n\n"
                "Use Integrations > Google Calendar > Configuration to set it up."
            )
            return

        if self._calendar_raw_events:
            # We have cached events — show the dialog straight away
            self._show_calendar_events_dialog()
        else:
            # No cached events yet — trigger a fetch; open dialog when ready
            self._start_calendar_fetch()

    def _on_calendar_auth_required(self):
        """OAuth browser is about to open — notify the user."""
        self.statusBar().showMessage("Opening browser for Google sign-in...")

    def _on_calendar_raw_events_ready(self, raw_events: list, timestamp: str, date_iso: str):
        """Handle raw events arriving from background fetch."""
        self.calendar_btn.setEnabled(True)
        self._calendar_raw_events = raw_events
        self._calendar_last_refreshed = timestamp
        self._calendar_date_iso = date_iso
        was_silent = getattr(self, '_calendar_fetch_silent', False)

        # Persist the last_refreshed timestamp in config
        self._save_calendar_last_refreshed(timestamp)

        # Auth succeeded — a token now exists, so show Sign Out
        if self._calendar_config and self._calendar_config.has_token():
            self._calendar_sign_out_action.setVisible(True)

        # Apply default filters for the status message
        filtered = filter_events(raw_events)
        self.statusBar().showMessage(
            f"Found {len(filtered)} calendar event(s)" if filtered
            else "No calendar events for this day"
        )

        # If the events dialog is open, push the refresh into it
        if (self._calendar_events_dialog is not None
                and self._calendar_events_dialog.isVisible()):
            self._calendar_events_dialog.update_events(raw_events, timestamp, date_iso)
        elif not was_silent:
            # Fetch was triggered by a button click — open the dialog now
            self._show_calendar_events_dialog()

    def _on_calendar_error(self, message: str):
        """Handle calendar fetch failure."""
        self.calendar_btn.setEnabled(True)
        self.statusBar().showMessage(f"Calendar error: {message}")
        logger.error(f"Calendar: fetch error: {message}")
        if (self._calendar_events_dialog is not None
                and self._calendar_events_dialog.isVisible()):
            self._calendar_events_dialog.set_refreshing(False)

    def _save_calendar_last_refreshed(self, timestamp: str):
        """Persist the last_refreshed timestamp into config.json."""
        try:
            if self.config is None:
                return
            if "google_calendar" not in self.config:
                self.config["google_calendar"] = {}
            self.config["google_calendar"]["last_refreshed"] = timestamp
            with open(CONFIG_PATH, "w") as f:
                json.dump(self.config, f, indent=2)
        except Exception as exc:
            logger.warning(f"Calendar: failed to save last_refreshed: {exc}")

    def _calendar_default_date_and_time(self):
        """Derive the default date and optional hint time for the calendar dialog.

        Uses the date/time from the meeting date/time textbox when available,
        otherwise falls back to the date of the last fetch, or today.

        Returns ``(date, Optional[time])``.
        """
        import datetime as _dt

        # 1. Try the meeting date/time textbox
        dt_text = self.meeting_datetime_input.text().strip()
        if dt_text:
            for fmt in ("%m/%d/%Y %I:%M %p", "%m/%d/%Y", "%Y-%m-%d"):
                try:
                    parsed = _dt.datetime.strptime(dt_text, fmt)
                    hint_time = parsed.time() if "%I" in fmt or "%H" in fmt else None
                    return parsed.date(), hint_time
                except ValueError:
                    continue

        # 2. Fall back to the date of the last fetch
        date_iso = getattr(self, '_calendar_date_iso', None)
        if date_iso:
            try:
                return _dt.date.fromisoformat(date_iso), None
            except (ValueError, TypeError):
                pass

        # 3. Today
        return _dt.date.today(), None

    def _show_calendar_events_dialog(self):
        """Open (or re-focus) the calendar events picker dialog."""
        from gui.calendar_dialogs import CalendarEventsDialog
        import datetime as _dt

        is_dark = self._is_dark_mode()
        target_date, hint_time = self._calendar_default_date_and_time()

        # If the cached events are for a different date, clear them and
        # trigger a fetch for the correct date.
        cached_date_iso = getattr(self, '_calendar_date_iso', None)
        if cached_date_iso:
            try:
                cached_date = _dt.date.fromisoformat(cached_date_iso)
            except (ValueError, TypeError):
                cached_date = None
        else:
            cached_date = None

        raw_events = self._calendar_raw_events
        if cached_date != target_date:
            # Events are stale for the target date — show empty and fetch
            raw_events = []

        dlg = CalendarEventsDialog(
            raw_events=raw_events,
            last_refreshed=self._calendar_last_refreshed,
            target_date=target_date,
            hint_time=hint_time,
            is_dark=is_dark,
            parent=self,
        )
        self._calendar_events_dialog = dlg
        dlg.refresh_requested.connect(self._on_calendar_dialog_refresh)

        # If we opened with an empty list (different date), kick off a fetch
        if not raw_events:
            dlg.set_refreshing(True)
            self._start_calendar_fetch(
                silent=True, target_date_iso=target_date.isoformat(),
            )

        if dlg.exec() == QDialog.DialogCode.Accepted:
            event_data = dlg.selected_event_data()
            if event_data:
                self._on_calendar_event_selected(event_data)

        self._calendar_events_dialog = None

    def _on_calendar_dialog_refresh(self, target_date_iso: str):
        """Handle refresh / date-change inside the events dialog."""
        if self._calendar_events_dialog is not None:
            self._calendar_events_dialog.set_refreshing(True)
        self._start_calendar_fetch(
            silent=True, target_date_iso=target_date_iso,
        )

    def _has_meaningful_meeting_details(self) -> bool:
        """Return True if the meeting details have real content beyond the
        auto-populated date/time (i.e. a name or notes have been entered)."""
        name = self.meeting_name_input.text().strip()
        notes = self.meeting_notes_input.toPlainText().strip()
        return bool(name or notes)

    def _on_calendar_event_selected(self, event_data: dict):
        """Populate meeting details from a calendar event.

        - If meaningful meeting details already exist, prompts to overwrite.
        - Does NOT auto-start a new recording session or change the source.
        """
        # Only prompt if the user has entered real data (name or notes)
        if self._has_meaningful_meeting_details():
            if not ThemedMessageDialog.question(
                self, "Overwrite Meeting Details",
                "Meeting details already contain data.\n\n"
                "Do you want to overwrite with the selected calendar event?"
            ):
                return

        # --- Populate meeting details ---
        # Date/Time
        dt_str = event_data.get("datetime_str", "")
        if dt_str:
            self.meeting_datetime_input.setText(dt_str)

        # Meeting Name
        name = event_data.get("name", "")
        if name:
            self.meeting_name_input.setText(name)

        # Notes
        notes = event_data.get("notes", "")
        self.meeting_notes_input.setPlainText(notes)

        self.meeting_details_dirty = True

        # Serialize the full calendar event to event.json
        if self.current_recording_path and self._ensure_recording_folder():
            event_json_path = self.current_recording_path / "event.json"
            try:
                raw_event = event_data.get("raw", {})
                with open(event_json_path, 'w', encoding='utf-8') as f:
                    json.dump(raw_event, f, indent=2, default=str)
                logger.info(f"Calendar: saved event.json to {event_json_path}")
            except Exception as e:
                logger.error(f"Calendar: failed to save event.json: {e}")

        # Persist meeting details and rename the recording folder to match
        # the calendar event's date/time (otherwise the rename only happens
        # on the next capture cycle or manual transcript save).
        self._save_meeting_details()

        self._set_status(f"Loaded: {name}", "info")
        logger.info(f"Calendar: populated meeting details from '{name}'")

    def _on_calendar_configure(self):
        """Show the Google Calendar configuration dialog."""
        from gui.calendar_dialogs import CalendarConfigDialog

        current = self.config.get("google_calendar", {})
        dlg = CalendarConfigDialog(current, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_settings = dlg.get_settings()

            # Copy client_secret to App Support so the user can delete
            # the original from Downloads (or wherever they picked it).
            src_path = new_settings.get("client_secret_path", "")
            if src_path and Path(src_path).is_file():
                google_dir = APP_SUPPORT_DIR / "google"
                google_dir.mkdir(parents=True, exist_ok=True)
                dest_path = google_dir / "client_secret.json"
                # Only copy if the source is not already inside App Support
                if not str(Path(src_path).resolve()).startswith(
                    str(APP_SUPPORT_DIR.resolve())
                ):
                    try:
                        shutil.copy2(src_path, dest_path)
                        new_settings["client_secret_path"] = str(dest_path)
                        logger.info(
                            f"Calendar: copied client secret to {dest_path}"
                        )
                    except OSError as e:
                        logger.warning(
                            f"Calendar: could not copy client secret: {e}"
                        )
                        # Fall back to keeping the original path
                else:
                    # Already in App Support — just normalise the path
                    new_settings["client_secret_path"] = str(dest_path)

            # Persist to config
            try:
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                config_data["google_calendar"] = new_settings
                with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                    json.dump(config_data, f, indent=2)
                self.config = config_data
                self._load_calendar_config()

                # Give the user clear feedback about what happened
                from gui.calendar_integration import _HAS_GOOGLE
                if new_settings.get("enabled") and not _HAS_GOOGLE:
                    self._set_status(
                        "Settings saved — Google API libraries not available "
                        "(calendar will not work until a build includes them)",
                        "warn",
                    )
                elif new_settings.get("enabled"):
                    self._set_status(
                        "Google Calendar enabled — use the calendar button "
                        "in Meeting Details to load events",
                        "info",
                    )
                else:
                    self._set_status("Google Calendar disabled", "")

                logger.info("Calendar: configuration updated")
            except Exception as e:
                logger.error(f"Calendar: failed to save config: {e}")
                ThemedMessageDialog.critical(
                    self, "Error", f"Failed to save calendar settings: {e}"
                )

    def _on_calendar_sign_out(self):
        """Delete the stored OAuth token to sign out of Google."""
        if not self._calendar_config or not self._calendar_config.has_token():
            ThemedMessageDialog.info(
                self, "Not Signed In",
                "No Google Calendar token found — you are not currently signed in."
            )
            return

        if not ThemedMessageDialog.question(
            self, "Sign Out",
            "This will remove your Google Calendar sign-in token. "
            "You will need to sign in again next time you use the calendar. "
            "Continue?"
        ):
            return

        try:
            os.remove(self._calendar_config.token_path)
            self._calendar_sign_out_action.setVisible(False)
            # Clear cached events so the user must sign in again
            self._calendar_raw_events = []
            self._calendar_last_refreshed = None
            self._calendar_date_iso = None
            self.statusBar().showMessage("Signed out of Google Calendar")
            logger.info("Calendar: token deleted — signed out")
        except Exception as e:
            logger.error(f"Calendar: failed to delete token: {e}")
            ThemedMessageDialog.critical(
                self, "Error", f"Failed to delete token: {e}"
            )

    def _set_status(self, text: str, state: str = ""):
        """Update the status bar message with an optional visual state.

        Parameters
        ----------
        text:
            The message to display in the status label.
        state:
            One of ``"info"``, ``"warn"``, ``"error"``, or ``""`` (default /
            neutral).  Controls the subtle background tint and border colour
            defined in the QSS ``status_state`` selectors.
        """
        self._status_msg_label.setText(text)
        self._status_msg_label.setProperty("status_state", state)
        self._status_msg_label.style().unpolish(self._status_msg_label)
        self._status_msg_label.style().polish(self._status_msg_label)
        
    def _show_about(self):
        """Show about dialog with GitHub repository link."""
        github_url = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
        ThemedMessageDialog.about(
            self,
            f"About {APP_NAME}",
            f"<h3>{APP_NAME}</h3>"
            f"<p>Version {APP_VERSION}</p>"
            f"<p>A user-friendly application for recording meeting transcripts "
            f"using macOS accessibility APIs.</p>"
            f"<p>Supports:</p>"
            f"<ul>"
            f"<li>Zoom</li>"
            f"<li>Microsoft Teams</li>"
            f"<li>WebEx</li>"
            f"<li>Slack</li>"
            f"</ul>"
            f'<p>GitHub: <a href="{github_url}">{github_url}</a></p>'
        )
    
    def _set_privacy_mode(self, hidden: bool):
        """Set macOS window sharing type to hide or show in screen recordings."""
        if not _HAS_APPKIT:
            return
        
        try:
            from gui.constants import NSApp
            title = self.windowTitle()
            for ns_window in NSApp().windows():
                if ns_window.title() == title:
                    ns_window.setSharingType_(0 if hidden else 1)
                    break
            
            # Update menu checkmarks
            if hasattr(self, 'privacy_hide_action'):
                self.privacy_hide_action.setChecked(hidden)
            if hasattr(self, 'privacy_show_action'):
                self.privacy_show_action.setChecked(not hidden)
            
            if hidden:
                self.statusBar().showMessage("Window hidden from screen sharing")
                logger.info("Privacy: window hidden from screen sharing")
            else:
                self.statusBar().showMessage("Window visible to screen sharing")
                logger.info("Privacy: window visible to screen sharing")
        except Exception as e:
            logger.error(f"Privacy: failed to set sharing type: {e}")
    
    def _change_privacy_default(self):
        """Prompt the user to choose the default screen sharing privacy setting."""
        current_hidden = True
        if self.config:
            current_hidden = self.config.get("client_settings", {}).get(
                "screen_sharing_hidden", True
            )
        
        items = ["Hidden (default)", "Visible"]
        current_index = 0 if current_hidden else 1
        
        item, ok = QInputDialog.getItem(
            self, "Screen Sharing Privacy Default",
            "Choose the default screen sharing privacy\n"
            "setting when the application starts:",
            items, current_index, False
        )
        if not ok:
            return
        
        new_hidden = item.startswith("Hidden")
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            
            if "client_settings" not in config_data:
                config_data["client_settings"] = {}
            config_data["client_settings"]["screen_sharing_hidden"] = new_hidden
            
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2)
            
            self.config = config_data
            self._set_privacy_mode(new_hidden)
            label = "Hidden" if new_hidden else "Visible"
            self.statusBar().showMessage(f"Privacy default set to: {label}")
            logger.info(f"Privacy default saved: screen_sharing_hidden={new_hidden}")
        except Exception as e:
            ThemedMessageDialog.critical(
                self, "Error",
                f"Failed to save privacy default: {e}"
            )
    
    def _show_log_viewer(self):
        """Open the log viewer window."""
        self.log_viewer = LogViewerDialog(self)
        self.log_viewer.show()
    
    def _show_tool_import(self):
        """Open the Tool Import dialog."""
        tools_dir = self.export_base_dir / "tools"
        tools_dir.mkdir(parents=True, exist_ok=True)
        self._tool_import_dialog = ToolImportDialog(tools_dir, self)
        self._tool_import_dialog.tools_imported.connect(self._scan_tools)
        self._tool_import_dialog.show()
    
    def _show_tool_json_editor(self):
        """Open the tool.json editor for a selected tool."""
        tools_dir = self.export_base_dir / "tools"
        if not tools_dir.exists():
            ThemedMessageDialog.info(self, "No Tools", "No tools directory found.")
            return

        tool_dirs = sorted(
            p for p in tools_dir.iterdir()
            if p.is_dir() and (p / "tool.json").exists()
        )

        if not tool_dirs:
            ThemedMessageDialog.info(
                self, "No Tools",
                "No tools with a tool.json file were found. "
                "Use Tools > Import Tools to install tools first."
            )
            return

        if len(tool_dirs) == 1:
            chosen = tool_dirs[0]
        else:
            names = [d.name for d in tool_dirs]
            name, ok = QInputDialog.getItem(
                self,
                "Select Tool",
                "Choose a tool to edit:",
                names,
                0,
                False,
            )
            if not ok:
                return
            chosen = tools_dir / name

        tool_json_path = chosen / "tool.json"
        self._tool_json_editor = ToolJsonEditorDialog(tool_json_path, self)
        self._tool_json_editor.config_saved.connect(self._scan_tools)
        self._tool_json_editor.show()
    
    def _show_tool_data_file_picker(self):
        """Show a picker for all editable data files across all discovered tools."""
        all_data_files: List[tuple] = []
        for tool_key, tool_def in self._discovered_tools.items():
            tool_dir = Path(tool_def.get("_tool_dir", ""))
            tool_name = tool_def.get("display_name", tool_key)
            for df in tool_def.get("data_files", []):
                file_name = df.get("file", "")
                label = df.get("label", file_name)
                editor_type = df.get("editor", "key_value_grid")
                file_path = tool_dir / file_name
                display = f"{tool_name} — {label}"
                all_data_files.append((display, file_path, editor_type, label, tool_name))

        if not all_data_files:
            ThemedMessageDialog.info(
                self, "No Data Files",
                "No tools with editable data files were found. "
                "Tools can declare editable data files by adding a "
                "\"data_files\" section to their tool.json."
            )
            return

        if len(all_data_files) == 1:
            _, fp, et, lbl, tn = all_data_files[0]
            self._open_data_file_editor(fp, et, lbl, tn)
            return

        names = [item[0] for item in all_data_files]
        name, ok = QInputDialog.getItem(
            self,
            "Edit Data File",
            "Choose a data file to edit:",
            names,
            0,
            False,
        )
        if not ok:
            return
        idx = names.index(name)
        _, fp, et, lbl, tn = all_data_files[idx]
        self._open_data_file_editor(fp, et, lbl, tn)

    def _open_tools_folder(self):
        """Open the tools directory in Finder."""
        tools_dir = self.export_base_dir / "tools"
        tools_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(tools_dir)])

    def _show_source_import(self):
        """Open the Source Import dialog."""
        from gui.source_dialogs import SourceImportDialog
        sources_dir = self.export_base_dir / "sources"
        sources_dir.mkdir(parents=True, exist_ok=True)
        self._source_import_dialog = SourceImportDialog(sources_dir, self)
        self._source_import_dialog.sources_imported.connect(self._scan_sources)
        self._source_import_dialog.show()

    def _show_source_editor(self):
        """Open the Source Editor for a selected source."""
        from gui.source_editor import SourceEditorDialog
        sources_dir = self.export_base_dir / "sources"
        if not sources_dir.exists():
            ThemedMessageDialog.info(self, "No Sources", "No sources directory found.")
            return

        source_dirs = sorted(
            p for p in sources_dir.iterdir()
            if p.is_dir() and (p / "source.json").exists()
        )

        if not source_dirs:
            ThemedMessageDialog.info(
                self, "No Sources",
                "No sources with a source.json file were found. "
                "Use Sources > Import Sources to install sources first."
            )
            return

        if len(source_dirs) == 1:
            chosen = source_dirs[0]
        else:
            names = [d.name for d in source_dirs]
            name, ok = QInputDialog.getItem(
                self,
                "Select Source",
                "Choose a source to edit:",
                names,
                0,
                False,
            )
            if not ok:
                return
            chosen = sources_dir / name

        source_json_path = chosen / "source.json"
        self._source_editor = SourceEditorDialog(source_json_path, self)
        self._source_editor.source_saved.connect(self._scan_sources)
        self._source_editor.show()

    def _show_ax_inspector(self):
        """Open the Accessibility Inspector window."""
        from gui.ax_inspector import AccessibilityInspectorDialog
        self._ax_inspector = AccessibilityInspectorDialog(self)
        self._ax_inspector.show()

    def _open_sources_folder(self):
        """Open the sources directory in Finder."""
        sources_dir = self.export_base_dir / "sources"
        sources_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(sources_dir)])
    
    def _reload_configuration(self):
        """Reload the configuration file."""
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
            
            setup_logging(self.config)
            
            # Sync Log Level menu radio buttons with reloaded config
            saved_level = self.config.get("logging", {}).get("level", "INFO").upper()
            for action in self._log_level_group.actions():
                action.setChecked(action.text() == saved_level)
            
            client_settings = self.config.get("client_settings", {})
            export_dir = client_settings.get("export_directory", "").strip()

            if not export_dir:
                export_dir = self._prompt_for_export_directory()
                if not export_dir:
                    ThemedMessageDialog.warning(
                        self, "Export Directory Required",
                        "No export directory is configured. Some features may not work."
                    )
                    return

            self.export_base_dir = Path(export_dir).expanduser().resolve()
            self.export_base_dir.mkdir(parents=True, exist_ok=True)
            (self.export_base_dir / "tools").mkdir(parents=True, exist_ok=True)
            (self.export_base_dir / "sources").mkdir(parents=True, exist_ok=True)
            
            self._scan_sources()
            self._scan_tools()
            
            logger.info(f"Config: reloaded from {CONFIG_PATH} ({len(self._discovered_sources)} sources)")
            self.statusBar().showMessage("Configuration reloaded")
            
        except json.JSONDecodeError as e:
            ThemedMessageDialog.critical(
                self, "Configuration Error",
                f"Invalid JSON in configuration file: {e}"
            )
        except Exception as e:
            ThemedMessageDialog.critical(
                self, "Configuration Error",
                f"Failed to reload configuration: {e}"
            )
    
    def _prompt_for_export_directory(self) -> Optional[str]:
        """Show the welcome dialog to pick an export directory and persist it to config.

        Called when export_directory is blank (first launch or after reset).
        Returns the chosen directory path string, or None if the user cancelled.
        """
        dlg = WelcomeDialog(self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return None

        chosen_dir = dlg.chosen_directory
        if not chosen_dir:
            return None

        # Persist the choice to the config file
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config_data = json.load(f)

            if "client_settings" not in config_data:
                config_data["client_settings"] = {}
            config_data["client_settings"]["export_directory"] = chosen_dir

            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2)

            # Keep the in-memory config in sync
            if self.config:
                self.config.setdefault("client_settings", {})["export_directory"] = chosen_dir

            logger.info(f"Export directory set to {chosen_dir}")
        except Exception as e:
            logger.error(f"Failed to save export directory to config: {e}")

        return chosen_dir

    def _change_export_directory(self):
        """Let the user pick a new export directory and persist the change."""
        new_dir = QFileDialog.getExistingDirectory(
            self,
            "Choose New Export Directory",
            str(self.export_base_dir),
            QFileDialog.Option.ShowDirsOnly
        )
        if not new_dir:
            return
        
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            
            if "client_settings" not in config_data:
                config_data["client_settings"] = {}
            config_data["client_settings"]["export_directory"] = new_dir
            
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2)
            
            logger.info(f"Export directory changed to {new_dir}")
            
            self._reload_configuration()
            self.statusBar().showMessage(f"Export directory changed to {new_dir}")
            
        except Exception as e:
            ThemedMessageDialog.critical(
                self, "Error",
                f"Failed to update export directory: {e}"
            )
    
    def _set_log_level(self, level_name: str):
        """Change the logging level for the current session (does not change default)."""
        # Reconfigure logging in-place
        if self.config is None:
            self.config = {}
        if "logging" not in self.config:
            self.config["logging"] = {}
        self.config["logging"]["level"] = level_name
        setup_logging(self.config)
        
        if level_name == "NONE":
            self.statusBar().showMessage("Logging disabled for this session")
        else:
            logger.info(f"Log level changed to {level_name}")
            self.statusBar().showMessage(f"Log level set to {level_name}")
    
    def _change_log_level_default(self):
        """Prompt the user to choose the default logging level saved to config."""
        current_level = "INFO"
        if self.config:
            current_level = self.config.get("logging", {}).get("level", "INFO").upper()
        
        items = ["DEBUG", "INFO", "WARNING", "ERROR", "NONE"]
        current_index = items.index(current_level) if current_level in items else 1
        
        item, ok = QInputDialog.getItem(
            self, "Default Log Level",
            "Choose the default logging level used\n"
            "when the application starts:",
            items, current_index, False
        )
        if not ok:
            return
        
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            
            if "logging" not in config_data:
                config_data["logging"] = {}
            config_data["logging"]["level"] = item
            
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2)
            
            self.config = config_data
            setup_logging(self.config)
            
            # Update the radio-button checks in the Log Level submenu
            for action in self._log_level_group.actions():
                action.setChecked(action.text() == item)
            
            if item == "NONE":
                self.statusBar().showMessage("Default log level set to: NONE (disabled)")
            else:
                logger.info(f"Default log level saved: {item}")
                self.statusBar().showMessage(f"Default log level set to: {item}")
        except Exception as e:
            ThemedMessageDialog.critical(
                self, "Error",
                f"Failed to save log level default: {e}"
            )

    def _clear_log_file(self):
        """Clear the log file."""
        if _constants.current_log_file_path is None:
            ThemedMessageDialog.info(self, "Logging Disabled", "File logging is disabled in configuration.")
            return
            
        if not ThemedMessageDialog.question(
            self, "Clear Log File",
            "Are you sure you want to clear the log file?"
        ):
            return
        try:
            if _constants.current_log_file_path.exists():
                with open(_constants.current_log_file_path, 'w', encoding='utf-8') as f:
                    f.write("")
                logger.info("Maintenance: log file cleared")
                self.statusBar().showMessage("Log file cleared")
        except Exception as e:
            ThemedMessageDialog.warning(self, "Error", f"Failed to clear log file: {e}")
    
    def _clear_all_snapshots(self):
        """Remove all .snapshots folders from recordings."""
        recordings_dir = self.export_base_dir / "recordings"
        
        if not recordings_dir.exists():
            ThemedMessageDialog.info(self, "No Recordings", "No recordings folder found.")
            return
        
        snapshots_folders = list(recordings_dir.glob("**/.snapshots"))
        
        if not snapshots_folders:
            ThemedMessageDialog.info(self, "No Snapshots", "No snapshot folders found to clear.")
            return
        
        if not ThemedMessageDialog.question(
            self, "Clear All Snapshots",
            f"This will remove {len(snapshots_folders)} snapshot folder(s) from your recordings. "
            "The merged transcripts (meeting_transcript.txt) will be preserved. "
            "This action cannot be undone. Continue?"
        ):
            return

        removed = 0
        errors = 0
        for folder in snapshots_folders:
            try:
                shutil.rmtree(folder)
                removed += 1
            except Exception as e:
                logger.error(f"Maintenance: failed to remove snapshot folder {folder}: {e}")
                errors += 1
        
        if errors > 0:
            ThemedMessageDialog.warning(
                self, "Partial Success",
                f"Removed {removed} snapshot folder(s). {errors} folder(s) could not be removed."
            )
        else:
            ThemedMessageDialog.info(
                self, "Success",
                f"Removed {removed} snapshot folder(s)."
            )
            
            logger.info(f"Maintenance: cleared {removed} snapshot folders ({errors} errors)")
            self.statusBar().showMessage(f"Cleared {removed} snapshot folders")
    
    def _clear_empty_recordings(self):
        """Remove recording folders that contain no files."""
        recordings_dir = self.export_base_dir / "recordings"
        
        if not recordings_dir.exists():
            ThemedMessageDialog.info(self, "No Recordings", "No recordings folder found.")
            return
        
        empty_folders: List[Path] = []
        for folder in sorted(recordings_dir.glob("**/recording_*")):
            if not folder.is_dir():
                continue
            if self.current_recording_path and folder.resolve() == self.current_recording_path.resolve():
                continue
            has_files = any(f.is_file() for f in folder.rglob("*"))
            if not has_files:
                empty_folders.append(folder)
        
        if not empty_folders:
            ThemedMessageDialog.info(
                self, "No Empty Recordings",
                "No empty recording folders found."
            )
            return
        
        folder_list = ", ".join(f.name for f in empty_folders[:10])
        if len(empty_folders) > 10:
            folder_list += ", ..."
        if not ThemedMessageDialog.question(
            self, "Clear Empty Recordings",
            f"Found {len(empty_folders)} empty recording folder(s): {folder_list}. "
            "These folders contain no files. Remove them?"
        ):
            return

        removed = 0
        errors = 0
        for folder in empty_folders:
            try:
                shutil.rmtree(folder)
                removed += 1
            except Exception as e:
                logger.error(f"Maintenance: failed to remove empty folder {folder}: {e}")
                errors += 1
        
        if errors > 0:
            ThemedMessageDialog.warning(
                self, "Partial Success",
                f"Removed {removed} empty folder(s). {errors} folder(s) could not be removed."
            )
        else:
            ThemedMessageDialog.info(
                self, "Success",
                f"Removed {removed} empty recording folder(s)."
            )
            
            logger.info(f"Maintenance: cleared {removed} empty recording folders ({errors} errors)")
            self.statusBar().showMessage(f"Cleared {removed} empty recording folders")
    
    def _check_for_updates(self):
        """Check GitHub releases for a newer version."""
        self.statusBar().showMessage("Checking for updates...")
        
        if GITHUB_OWNER == "YOUR_GITHUB_USERNAME":
            logger.warning("Update check: skipped (GITHUB_OWNER not configured)")
            ThemedMessageDialog.info(
                self, "Update Check",
                "Update checking is not configured. "
                "Please update GITHUB_OWNER and GITHUB_REPO in version.py "
                "with your GitHub repository information."
            )
            self.statusBar().showMessage("Ready")
            return
        
        url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
        logger.debug(f"Update check: querying {url} (current version: {APP_VERSION})")
        
        try:
            request = urllib.request.Request(
                url,
                headers={"Accept": "application/vnd.github.v3+json", "User-Agent": f"{APP_NAME}/{APP_VERSION}"}
            )
            
            logger.debug("Update check: sending request to GitHub API")
            with urllib.request.urlopen(request, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
            
            latest_version = data.get("tag_name", "").lstrip("v")
            release_url = data.get("html_url", "")
            release_notes = data.get("body", "No release notes available.")
            assets = data.get("assets", [])
            
            logger.debug(f"Update check: latest release={latest_version}, assets={len(assets)}")
            
            current_parts = [int(x) for x in APP_VERSION.split(".")]
            latest_parts = [int(x) for x in latest_version.split(".")]
            
            while len(current_parts) < len(latest_parts):
                current_parts.append(0)
            while len(latest_parts) < len(current_parts):
                latest_parts.append(0)
            
            logger.debug(f"Update check: comparing versions current={current_parts} vs latest={latest_parts}")
            
            if latest_parts > current_parts:
                logger.info(f"Update check: new version available ({latest_version}, current: {APP_VERSION})")
                download_asset = None
                for asset in assets:
                    name = asset.get("name", "").lower()
                    logger.debug(f"Update check: found asset: {name}")
                    if name.endswith(".dmg") or name.endswith(".zip"):
                        download_asset = asset
                        break
                
                notes_preview = release_notes[:500] + ('...' if len(release_notes) > 500 else '')
                msg = (
                    f"A new version is available! "
                    f"Current version: {APP_VERSION}. "
                    f"Latest version: {latest_version}. "
                    f"Release notes: {notes_preview}"
                )
                
                if download_asset:
                    logger.debug(f"Update check: downloadable asset found: {download_asset.get('name')}")
                    if ThemedMessageDialog.question(
                        self, "Update Available",
                        f"{msg} Would you like to download and install the update?"
                    ):
                        self._download_and_install_update(download_asset, latest_version)
                else:
                    logger.debug("Update check: no downloadable asset (.dmg or .zip) found")
                    if ThemedMessageDialog.question(
                        self, "Update Available",
                        f"{msg} Would you like to open the release page in your browser?"
                    ):
                        subprocess.run(["open", release_url])
            else:
                logger.info(f"Update check: already on latest version ({APP_VERSION})")
                ThemedMessageDialog.info(
                    self, "No Updates",
                    f"You're running the latest version ({APP_VERSION})."
                )
            
            self.statusBar().showMessage("Ready")
            
        except urllib.error.HTTPError as e:
            if e.code == 404:
                logger.warning(f"Update check: no releases found (HTTP 404)")
                ThemedMessageDialog.info(
                    self, "No Releases",
                    f"No releases have been published yet. "
                    f"You're running version {APP_VERSION}. "
                    f"Checked: {url}"
                )
            else:
                logger.error(f"Update check: HTTP error {e.code} {e.reason} ({url})")
                ThemedMessageDialog.warning(
                    self, "Update Check Failed",
                    f"HTTP Error {e.code}: {e.reason}. URL: {url}"
                )
            self.statusBar().showMessage("Ready")
        except urllib.error.URLError as e:
            logger.error(f"Update check: connection failed: {e} ({url})")
            ThemedMessageDialog.warning(
                self, "Update Check Failed",
                f"Could not connect to GitHub to check for updates. Error: {e}. URL: {url}"
            )
            self.statusBar().showMessage("Update check failed")
        except Exception as e:
            logger.error(f"Update check: unexpected error: {e} ({url})", exc_info=True)
            ThemedMessageDialog.warning(
                self, "Update Check Failed",
                f"An error occurred while checking for updates. Error: {e}. URL: {url}"
            )
            self.statusBar().showMessage("Update check failed")
    
    def _download_and_install_update(self, asset: dict, version: str):
        """Download and install an update from GitHub releases."""
        download_url = asset.get("browser_download_url")
        filename = asset.get("name")
        
        if not download_url or not filename:
            logger.error("Update download: missing download URL or filename")
            ThemedMessageDialog.warning(self, "Download Failed", "Could not get download URL.")
            return
        
        try:
            self.statusBar().showMessage(f"Downloading {filename}...")
            
            temp_dir = Path(tempfile.gettempdir()) / "TranscriptRecorderUpdate"
            temp_dir.mkdir(exist_ok=True)
            download_path = temp_dir / filename
            
            request = urllib.request.Request(
                download_url,
                headers={"User-Agent": APP_NAME}
            )
            
            with urllib.request.urlopen(request, timeout=60) as response:
                with open(download_path, 'wb') as f:
                    f.write(response.read())
            
            logger.info(f"Update download: saved {filename} to {download_path}")
            
            if filename.endswith(".dmg"):
                self.statusBar().showMessage("Opening installer...")
                subprocess.run(["open", str(download_path)])
                
                ThemedMessageDialog.info(
                    self, "Update Downloaded",
                    "The update has been downloaded and opened. "
                    "Please drag the new version to your Applications folder "
                    "to complete the update, then restart the application."
                )
            elif filename.endswith(".zip"):
                self.statusBar().showMessage("Extracting update...")
                extract_dir = temp_dir / f"TranscriptRecorder-{version}"
                shutil.unpack_archive(str(download_path), str(extract_dir))
                subprocess.run(["open", str(extract_dir)])
                
                ThemedMessageDialog.info(
                    self, "Update Downloaded",
                    "The update has been downloaded and extracted. "
                    "Please move the new application to your Applications folder "
                    "to complete the update, then restart the application."
                )
            
            self.statusBar().showMessage("Update ready to install")
            
        except Exception as e:
            logger.error(f"Update download: failed to download {filename}: {e}", exc_info=True)
            ThemedMessageDialog.warning(
                self, "Download Failed",
                f"Failed to download the update. Error: {e}"
            )
            self.statusBar().showMessage("Update download failed")
        
    def closeEvent(self, event):
        """Handle window close."""
        if self.is_recording:
            if not ThemedMessageDialog.question(
                self,
                "Recording in Progress",
                "Recording is still in progress. Stop and exit?"
            ):
                event.ignore()
                return
            self._on_stop_recording()
            
        if hasattr(self, 'tray_icon'):
            self.tray_icon.hide()
        
        logger.info("Application window closed")
        event.accept()


def main():
    """Application entry point."""
    if sys.platform != "darwin":
        print("This application only runs on macOS.")
        sys.exit(1)

    # Fix stale TLS cert bundles in py2app builds (must run before any
    # HTTPS calls — calendar fetch, update check, etc.)
    from gui.constants import ensure_ssl_certs
    ensure_ssl_certs()

    app = QApplication(sys.argv)
    
    # macOS-specific settings
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("TranscriptRecorder")
    
    # Set app icon
    icon_path = resource_path("appicon.icns")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    
    logger.info(f"Application starting (version {APP_VERSION})")
    
    # Create and show main window
    window = TranscriptRecorderApp()
    if window._closing:
        sys.exit(0)
    window.show()
    
    exit_code = app.exec()
    logger.info(f"Application exiting (code {exit_code})")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
