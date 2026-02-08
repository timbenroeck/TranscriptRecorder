"""
Application stylesheet for light and dark mode theming.
"""


def get_application_stylesheet(is_dark: bool) -> str:
    """Return a single, comprehensive QSS stylesheet for the entire application.
    
    Uses Apple's Semantic Colors to ensure a native macOS look in both
    Light and Dark modes. Applied once on the QApplication so that every
    window, dialog, and popup inherits the theme automatically.
    """
    # --- Palette definition ---
    bg_window = "#1E1E1E" if is_dark else "#F5F5F7"
    bg_widget = "#2D2D2D" if is_dark else "#FFFFFF"
    text_main = "#FFFFFF" if is_dark else "#1D1D1F"
    text_sec  = "#98989D" if is_dark else "#86868B"
    border    = "#3D3D3D" if is_dark else "#D2D2D7"
    input_bg  = "#1A1A1A" if is_dark else "#FFFFFF"
    hover_bg  = "#3A3A3C" if is_dark else "#F0F0F0"
    pressed_bg    = "#2C2C2E" if is_dark else "#E0E0E0"
    disabled_bg   = "#3A3A3C" if is_dark else "#E5E5EA"
    disabled_text = "#636366" if is_dark else "#8E8E93"
    scrollbar_handle = "#4D4D4D" if is_dark else "#C1C1C1"

    return f"""
        /* ========== Global Defaults ========== */
        QWidget {{
            background-color: {bg_window};
            color: {text_main};
            font-family: "SF Pro", "SF Compact", "Helvetica Neue", sans-serif;
            font-size: 13px;
        }}

        QMainWindow {{
            background-color: {bg_window};
        }}

        QLabel {{
            background-color: transparent;
        }}

        /* Horizontal separator lines */
        QFrame[frameShape="4"] {{
            color: {border};
        }}

        /* Secondary label (info / caption text) */
        QLabel#secondary_label {{
            color: {text_sec};
            font-size: 11px;
        }}

        QStatusBar {{
            background-color: {bg_window};
            color: {text_sec};
            padding: 0px;
        }}

        /* Bordered status message in the centre of the status bar */
        QLabel#status_msg {{
            color: {text_sec};
            font-size: 11px;
            border: 1px solid {border};
            border-radius: 4px;
            padding: 2px 8px;
        }}

        QGroupBox {{
            background-color: transparent;
            border: none;
            margin-top: 20px;
            padding-top: 4px;
            font-weight: 600;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 0 4px;
            top: 4px;
        }}

        /* ========== Inputs & Text Areas ========== */
        QLineEdit, QTextEdit, QPlainTextEdit {{
            background-color: {input_bg};
            color: {text_main};
            border: 1px solid {border};
            border-radius: 6px;
            padding: 6px;
            selection-background-color: #007AFF;
            selection-color: white;
        }}
        QLineEdit:focus, QTextEdit:focus {{
            border-color: #007AFF;
        }}

        QComboBox {{
            background-color: {bg_widget};
            color: {text_main};
            border: 1px solid {border};
            border-radius: 6px;
            padding: 5px 10px;
            min-height: 20px;
        }}
        QComboBox:hover {{
            border-color: #007AFF;
        }}
        QComboBox::drop-down {{
            border: none;
            width: 20px;
        }}
        QComboBox::down-arrow {{
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-top: 6px solid {text_sec};
            margin-right: 8px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {bg_widget};
            color: {text_main};
            selection-background-color: #007AFF;
            selection-color: white;
        }}

        /* ========== Modern macOS Scrollbars ========== */
        QScrollBar:vertical {{
            border: none;
            background: transparent;
            width: 8px;
            margin: 0px;
        }}
        QScrollBar::handle:vertical {{
            background: {scrollbar_handle};
            min-height: 20px;
            border-radius: 4px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {text_sec};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: transparent;
        }}

        QScrollBar:horizontal {{
            border: none;
            background: transparent;
            height: 8px;
            margin: 0px;
        }}
        QScrollBar::handle:horizontal {{
            background: {scrollbar_handle};
            min-width: 20px;
            border-radius: 4px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: {text_sec};
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0px;
        }}
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
            background: transparent;
        }}

        /* ========== Tab Bar Styling ========== */
        QTabWidget {{
            background: {bg_window};
            border: 0;
            padding: 0;
            margin: 0;
        }}
        QTabWidget::pane {{
            background: {bg_window};
            border: 0;
            border-top: 1px solid {border};
            padding: 0;
            margin: 0;
            top: 0;
        }}
        QTabWidget::tab-bar {{
            background: {bg_window};
            border: 0;
            left: 0;
        }}
        QTabBar {{
            background: {bg_window};
            border: 0;
            qproperty-drawBase: 0;
        }}
        QTabBar::scroller {{
            width: 0;
        }}
        QTabBar::tear {{
            width: 0;
            border: 0;
        }}
        QTabBar::tab {{
            background: transparent;
            color: {text_sec};
            padding: 6px 14px;
            margin-right: 8px;
            margin-bottom: 4px;
            border: 1px solid {border};
            border-radius: 6px;
        }}
        QTabBar::tab:selected {{
            background-color: #007AFF;
            color: white;
            border-color: #007AFF;
            font-weight: 500;
        }}
        QTabBar::tab:hover:!selected {{
            background: {hover_bg};
            color: {text_main};
        }}
        QTabBar::tab:disabled {{
            background: transparent;
            color: {disabled_text};
            border: 1px solid {disabled_bg};
        }}
        QTabBar::tab:selected:disabled {{
            background: {disabled_bg};
            color: {disabled_text};
            border: 1px solid {disabled_bg};
            font-weight: 500;
        }}

        /* ========== BUTTON STATES ========== */

        /* Default (Secondary) Button */
        QPushButton {{
            background-color: {bg_widget};
            border: 1px solid {border};
            border-radius: 6px;
            padding: 6px 14px;
            font-weight: 500;
        }}
        QPushButton:hover {{
            background-color: {hover_bg};
        }}
        QPushButton:pressed {{
            background-color: {pressed_bg};
        }}

        /* Primary Blue Button */
        QPushButton[class="primary"] {{
            background-color: #007AFF;
            color: white;
            border: none;
        }}
        QPushButton[class="primary"]:hover {{
            background-color: #0A84FF;
        }}
        QPushButton[class="primary"]:pressed {{
            background-color: #0062CC;
        }}

        /* Success Green Button */
        QPushButton[class="success"] {{
            background-color: #34C759;
            color: white;
            border: none;
        }}
        QPushButton[class="success"]:hover {{
            background-color: #30D158;
        }}
        QPushButton[class="success"]:pressed {{
            background-color: #248A3D;
        }}

        /* Danger Red Button */
        QPushButton[class="danger"] {{
            background-color: #FF3B30;
            color: white;
            border: none;
        }}
        QPushButton[class="danger"]:hover {{
            background-color: #FF453A;
        }}
        QPushButton[class="danger"]:pressed {{
            background-color: #C93028;
        }}

        /* Pink Button */
        QPushButton[class="pink"] {{
            background-color: #FF2D55;
            color: white;
            border: none;
        }}
        QPushButton[class="pink"]:hover {{
            background-color: #FF375F;
        }}
        QPushButton[class="pink"]:pressed {{
            background-color: #D12549;
        }}

        /* Round Time Buttons — side-by-side beside date/time */
        QPushButton#time_btn {{
            border-radius: 6px;
            padding: 2px;
            min-width: 0px;
            min-height: 0px;
        }}

        /* Disabled State for all buttons */
        QPushButton:disabled {{
            background-color: {disabled_bg};
            color: {disabled_text};
            border: none;
        }}
    """
