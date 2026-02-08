"""
Application stylesheet for light and dark mode theming.
"""


def get_application_stylesheet(is_dark: bool, combo_arrow_path: str = "") -> str:
    """Return a single, comprehensive QSS stylesheet for the entire application.
    
    Uses Apple's Semantic Colors to ensure a native macOS look in both
    Light and Dark modes. Applied once on the QApplication so that every
    window, dialog, and popup inherits the theme automatically.
    """
    # --- Palette definition (Slate & Charcoal) ---
    accent_blue = "#7AA2FF" if is_dark else "#4A67AD"
    accent_blue_hover = "#6690E8" if is_dark else "#3F5998"
    accent_blue_subtle = "rgba(122, 162, 255, 0.1)" if is_dark else "rgba(74, 103, 173, 0.08)"
    capture_green = "#81C784" if is_dark else "#388E3C"
    capture_green_subtle = "rgba(129, 199, 132, 0.05)" if is_dark else "rgba(56, 142, 60, 0.05)"
    danger_red = "#E57373" if is_dark else "#C62828"
    danger_red_subtle = "rgba(229, 115, 115, 0.1)" if is_dark else "rgba(198, 40, 40, 0.1)"
    # Status bar tints (double-signal: faint bg + tinted border)
    status_info_bg     = "#1A222F" if is_dark else "#F0F4F8"
    status_info_border = "#3A5A8C" if is_dark else "#B0C4DE"
    status_info_text   = "#A0B0C0" if is_dark else "#4A67AD"
    status_warn_bg     = "#262118" if is_dark else "#FFF9E6"
    status_warn_border = "#5C4B23" if is_dark else "#E6C07B"
    status_warn_text   = "#D4B106" if is_dark else "#856404"
    status_error_bg     = "#281A1A" if is_dark else "#FFF0F0"
    status_error_border = "#633232" if is_dark else "#E8B0B0"
    status_error_text   = "#E57373" if is_dark else "#A94442"
    # Solid Neutral — secondary-action (History) button
    secondary_bg       = "#3A3A3C" if is_dark else "#EEEEF0"
    secondary_border   = "#48484A" if is_dark else "#D1D1D6"
    secondary_bg_hover = "#4A4A4C" if is_dark else "#E2E2E7"
    bg_window = "#1A1A1E" if is_dark else "#F8F9FA"
    bg_widget = "#252529" if is_dark else "#FFFFFF"
    text_main = "#E1E1E6" if is_dark else "#333333"
    text_sec  = "#8E8E93" if is_dark else "#636366"
    border    = "#2C2C2C" if is_dark else "#E0E0E0"
    input_bg  = "#252529" if is_dark else "#FFFFFF"
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
            padding: 4px 10px;
            background-color: transparent;
        }}
        QLabel#status_msg[status_state="info"] {{
            background-color: {status_info_bg};
            border-color: {status_info_border};
            color: {status_info_text};
        }}
        QLabel#status_msg[status_state="warn"] {{
            background-color: {status_warn_bg};
            border-color: {status_warn_border};
            color: {status_warn_text};
        }}
        QLabel#status_msg[status_state="error"] {{
            background-color: {status_error_bg};
            border-color: {status_error_border};
            color: {status_error_text};
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

        /* ========== Tool Panel Elements ========== */

        /* Tool description text — uses secondary colour for readability */
        QLabel#tool_description {{
            color: {text_sec};
            font-size: 13px;
            padding: 2px 0;
        }}

        /* Collapsible section toggle buttons (Parameters, Data Files) */
        QPushButton#section_toggle {{
            text-align: left;
            font-weight: 600;
            padding: 2px 0;
            color: {text_main};
            background: transparent;
            border: none;
        }}
        QPushButton#section_toggle:hover {{
            color: {accent_blue};
        }}

        /* Expanded collapsible panels (Params table wrapper, Data Files list, Command preview) */
        QWidget#collapsible_panel, QFrame#collapsible_panel {{
            background-color: {bg_widget};
            border: 1px solid {border};
            border-radius: 6px;
        }}

        /* Child rows inside collapsible panels — transparent so parent bg shows through */
        QWidget#panel_row {{
            background-color: transparent;
        }}

        /* Params table — elevated surface with themed borders */
        QTableWidget#tool_params_table {{
            background-color: {bg_widget};
            border: 1px solid {border};
            border-radius: 6px;
            gridline-color: {border};
        }}
        QTableWidget#tool_params_table QHeaderView::section {{
            background-color: {hover_bg};
            color: {text_sec};
            border: none;
            border-bottom: 1px solid {border};
            padding: 4px 6px;
            font-weight: 600;
        }}

        /* ========== Inputs & Text Areas ========== */
        QLineEdit, QTextEdit, QPlainTextEdit {{
            background-color: {input_bg};
            color: {text_main};
            border: 1px solid {border};
            border-radius: 6px;
            padding: 6px;
            selection-background-color: {accent_blue};
            selection-color: white;
        }}
        QLineEdit:focus, QTextEdit:focus {{
            border-color: {accent_blue};
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
            border-color: {accent_blue};
        }}
        QComboBox::drop-down {{
            border: none;
            width: 20px;
        }}
        QComboBox::down-arrow {{
            image: url({combo_arrow_path});
            width: 12px;
            height: 12px;
            margin-right: 6px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {bg_widget};
            color: {text_main};
            selection-background-color: {accent_blue};
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

        /* ========== Tab Bar Styling (underline) ========== */
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
            background: transparent;
            border: 0;
            left: 0;
        }}
        QTabBar {{
            background: transparent;
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
            padding: 8px 14px;
            margin-right: 8px;
            border: none;
            border-bottom: 3px solid transparent;
        }}
        QTabBar::tab:selected {{
            background: transparent;
            color: {accent_blue};
            border-bottom: 3px solid {accent_blue};
            font-weight: 500;
        }}
        QTabBar::tab:hover:!selected {{
            background: transparent;
            color: {text_main};
        }}
        QTabBar::tab:disabled {{
            background: transparent;
            color: {disabled_text};
            border: none;
            border-bottom: 3px solid transparent;
        }}
        QTabBar::tab:selected:disabled {{
            background: transparent;
            color: {disabled_text};
            border: none;
            border-bottom: 3px solid {disabled_bg};
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

        /* Primary Button — solid accent fill, white text */
        QPushButton[class="primary"] {{
            background-color: {accent_blue};
            color: white;
            border: none;
        }}
        QPushButton[class="primary"]:hover {{
            background-color: {accent_blue_hover};
        }}
        QPushButton[class="primary"]:pressed {{
            background-color: {accent_blue_hover};
        }}

        /* Secondary-Action Button — Solid Neutral (visible body, subtle hover darken) */
        QPushButton[class="secondary-action"] {{
            background-color: {secondary_bg};
            color: {text_main};
            border: 1px solid {secondary_border};
        }}
        QPushButton[class="secondary-action"]:hover {{
            background-color: {secondary_bg_hover};
        }}
        QPushButton[class="secondary-action"]:pressed {{
            background-color: {secondary_bg_hover};
        }}

        /* Action Button — Ghost Blue (subtle blue tint, blue border & text; solid blue on hover) */
        QPushButton[class="action"] {{
            background-color: {accent_blue_subtle};
            color: {accent_blue};
            border: 2px solid {accent_blue};
            font-weight: 600;
        }}
        QPushButton[class="action"]:hover {{
            background-color: {accent_blue};
            color: white;
        }}
        QPushButton[class="action"]:pressed {{
            background-color: {accent_blue_hover};
            color: white;
        }}

        /* Auto-Capture Toggle — OFF / Start (green outline) */
        QPushButton[class="toggle_off"] {{
            background-color: transparent;
            color: {capture_green};
            border: 1.5px solid {capture_green};
        }}
        QPushButton[class="toggle_off"]:hover {{
            background-color: {capture_green_subtle};
        }}

        /* Auto-Capture Toggle — ON / Stop (red danger outline) */
        QPushButton[class="toggle_on"] {{
            background-color: transparent;
            color: {danger_red};
            border: 1.5px solid {danger_red};
        }}
        QPushButton[class="toggle_on"]:hover {{
            background-color: {danger_red_subtle};
        }}

        /* Danger Outline Button — red outlined, transparent bg */
        QPushButton[class="danger-outline"] {{
            background-color: transparent;
            color: {danger_red};
            border: 1px solid {danger_red};
        }}
        QPushButton[class="danger-outline"]:hover {{
            background-color: {danger_red_subtle};
        }}
        QPushButton[class="danger-outline"]:pressed {{
            background-color: {danger_red_subtle};
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
