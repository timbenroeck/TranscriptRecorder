# TranscriptRecorder — Style Guide

> **Theme:** Slate & Charcoal  
> **Last updated:** 2026-02-08

This document is the single source of truth for every colour, button class, icon tint, and interactive state used in the TranscriptRecorder UI. When making visual changes, update the corresponding source file **and** this document.

---

## Source Files

| File | Purpose |
|------|---------|
| `gui/styles.py` | All QSS (Qt Style Sheets) — palette variables, widget rules, button classes, status bar tints. |
| `gui/icons.py` | SVG icon registry (`_SVG_SOURCES`), tint colour map (`_TINTS`), and the `IconManager` rendering pipeline. |
| `gui/main_window.py` | Widget construction — assigns `class` properties to buttons, connects signals, sets tooltips. |

---

## 1. Colour Palette

All palette values are defined at the top of `get_application_stylesheet()` in `gui/styles.py`.

### 1.1 Core Palette

| Variable | Dark Mode | Light Mode | Usage |
|----------|-----------|------------|-------|
| `bg_window` | `#1A1A1E` | `#F8F9FA` | Window / app background (Midnight Blue-Gray) |
| `bg_widget` | `#252529` | `#FFFFFF` | Card / widget surface, default button bg (elevated) |
| `text_main` | `#E1E1E6` | `#333333` | Primary text, Action button fill |
| `text_sec` | `#8E8E93` | `#636366` | Secondary text, captions, Action button hover |
| `border` | `#2C2C2C` | `#E0E0E0` | Borders, separators |
| `input_bg` | `#252529` | `#FFFFFF` | Text input background (elevated, matches `bg_widget`) |
| `hover_bg` | `#3A3A3C` | `#F0F0F0` | Default button hover |
| `pressed_bg` | `#2C2C2E` | `#E0E0E0` | Default button pressed |
| `disabled_bg` | `#3A3A3C` | `#E5E5EA` | Disabled button background |
| `disabled_text` | `#636366` | `#8E8E93` | Disabled button text |
| `scrollbar_handle` | `#4D4D4D` | `#C1C1C1` | Scrollbar thumb |

### 1.2 Accent Colours

| Variable | Dark Mode | Light Mode | Usage |
|----------|-----------|------------|-------|
| `accent_blue` | `#7AA2FF` | `#4A67AD` | Primary buttons, selected tabs, focus rings, selection highlight, Action (Ghost Blue) |
| `accent_blue_hover` | `#6690E8` | `#3F5998` | Primary button hover / pressed |
| `accent_blue_subtle` | `rgba(122,162,255,0.1)` | `rgba(74,103,173,0.08)` | Action button bg tint (Ghost Blue) |

### 1.3 Secondary-Action (Solid Neutral) Colours

| Variable | Dark Mode | Light Mode | Usage |
|----------|-----------|------------|-------|
| `secondary_bg` | `#3A3A3C` | `#EEEEF0` | History button resting background |
| `secondary_border` | `#48484A` | `#D1D1D6` | History button border |
| `secondary_bg_hover` | `#4A4A4C` | `#E2E2E7` | History button hover / pressed bg |

### 1.4 Semantic Colours

| Variable | Dark Mode | Light Mode | Usage |
|----------|-----------|------------|-------|
| `capture_green` | `#81C784` | `#388E3C` | Auto-capture toggle OFF (start) border & text |
| `capture_green_subtle` | `rgba(129,199,132,0.05)` | `rgba(56,142,60,0.05)` | Auto-capture OFF hover tint |
| `danger_red` | `#E57373` | `#C62828` | Danger-outline, toggle ON (stop), Reset button |
| `danger_red_subtle` | `rgba(229,115,115,0.1)` | `rgba(198,40,40,0.1)` | Danger hover tint |

### 1.5 Status Bar Tints

Each status state uses a triple: faint background, tinted border, and tinted text.

| State | Dark bg / border / text | Light bg / border / text |
|-------|------------------------|-------------------------|
| **info** | `#1A222F` / `#3A5A8C` / `#A0B0C0` | `#F0F4F8` / `#B0C4DE` / `#4A67AD` |
| **warn** | `#262118` / `#5C4B23` / `#D4B106` | `#FFF9E6` / `#E6C07B` / `#856404` |
| **error** | `#281A1A` / `#633232` / `#E57373` | `#FFF0F0` / `#E8B0B0` / `#A94442` |

**How to use:** Call `_set_status(text, state)` where `state` is `"info"`, `"warn"`, `"error"`, or `""` (neutral). The method sets the `status_state` dynamic property and triggers QSS repolish.

---

## 2. Button Classes & States

Buttons are styled via the QSS `class` dynamic property. Assign with `btn.setProperty("class", "primary")` in `gui/main_window.py`.

### 2.1 Default Button (no class)

Generic toolbar/dialog buttons.

| State | Background | Text | Border |
|-------|-----------|------|--------|
| Ready | `bg_widget` | `text_main` | 1px `border` |
| Hover | `hover_bg` | — | — |
| Pressed | `pressed_bg` | — | — |
| Disabled | `disabled_bg` | `disabled_text` | none |

### 2.2 `class="primary"` — New Button

Solid accent fill, white text. The main call-to-action.

| State | Background | Text | Border |
|-------|-----------|------|--------|
| Ready | `accent_blue` | white | none |
| Hover | `accent_blue_hover` | white | none |
| Pressed | `accent_blue_hover` | white | none |
| Disabled | `disabled_bg` | `disabled_text` | none |

**Used by:** New button.

### 2.3 `class="secondary-action"` — History Button (Solid Neutral)

Solid neutral background with visible body. Clearly distinct from the Ghost Blue action buttons by its gray tone and thinner border.

| State | Background | Text | Border |
|-------|-----------|------|--------|
| Ready | `secondary_bg` | `text_main` | 1px `secondary_border` |
| Hover | `secondary_bg_hover` | `text_main` | 1px `secondary_border` |
| Pressed | `secondary_bg_hover` | `text_main` | 1px `secondary_border` |
| Disabled | `disabled_bg` | `disabled_text` | none |

**Used by:** History button.

### 2.4 `class="action"` — Capture & Run Buttons (Ghost Blue)

Subtle blue tint with a **2px** blue border and blue text. On hover fills to solid accent blue with white text — vibrant and thematically connected to the app's blue identity. The thicker border and blue colouring make it immediately distinct from the neutral History button.

| State | Background | Text | Border |
|-------|-----------|------|--------|
| Ready | `accent_blue_subtle` | `accent_blue` | 2px `accent_blue` |
| Hover | `accent_blue` | white | 2px `accent_blue` |
| Pressed | `accent_blue_hover` | white | 2px `accent_blue` |
| Disabled | `disabled_bg` | `disabled_text` | none |

**Used by:** Capture button, Run/Cancel toggle (in "Run" state).

### 2.5 `class="toggle_off"` — Auto Capture (Not Recording)

Green outline, transparent background. Signals "ready to start."

| State | Background | Text | Border |
|-------|-----------|------|--------|
| Ready | transparent | `capture_green` | 1.5px `capture_green` |
| Hover | `capture_green_subtle` | `capture_green` | 1.5px `capture_green` |
| Disabled | `disabled_bg` | `disabled_text` | none |

**Used by:** Auto-capture button when recording is OFF.

### 2.6 `class="toggle_on"` — Stop (Recording Active)

Red danger outline, transparent background. Signals "click to stop."

| State | Background | Text | Border |
|-------|-----------|------|--------|
| Ready | transparent | `danger_red` | 1.5px `danger_red` |
| Hover | `danger_red_subtle` | `danger_red` | 1.5px `danger_red` |
| Disabled | `disabled_bg` | `disabled_text` | none |

**Used by:** Auto-capture button when recording is ON.

### 2.7 `class="danger-outline"` — Reset & Cancel

Red outlined button for destructive/caution actions.

| State | Background | Text | Border |
|-------|-----------|------|--------|
| Ready | transparent | `danger_red` | 1px `danger_red` |
| Hover | `danger_red_subtle` | `danger_red` | 1px `danger_red` |
| Pressed | `danger_red_subtle` | `danger_red` | 1px `danger_red` |
| Disabled | `disabled_bg` | `disabled_text` | none |

**Used by:** Reset button, Run/Cancel toggle (in "Cancel" / "Cancelling…" state).

---

## 3. Run/Cancel Toggle Button

The tool panel uses a **single button** (`run_tool_btn`) that toggles between Run and Cancel states. This avoids layout shift from a second button appearing/disappearing.

| Mode | Label | Class | Enabled | Width |
|------|-------|-------|---------|-------|
| Idle | "Run" | `action` | Yes (if tool+session) | Fixed 100px |
| Running | "Cancel" | `danger-outline` | Yes | Fixed 100px |
| Cancelling | "Cancelling…" | `danger-outline` | No | Fixed 100px |

The elapsed timer label sits to the right with a fixed 52px width, always present in the layout (empty text when idle) to prevent the combo box from jumping.

**Dispatcher:** `_on_run_cancel_toggle()` checks `self._tool_runner is not None` and routes to `_on_run_tool()` or `_on_cancel_tool()`.

**Style swap:** After changing text, call `setProperty("class", ...)` followed by `style().unpolish()` / `style().polish()` to trigger QSS re-evaluation.

---

## 4. Tool Panel Elements

### 4.1 Tool Description (`QLabel#tool_description`)

Displays the selected tool's description text below the separator.

| Mode | Text Colour | Font Size | Padding |
|------|------------|-----------|---------|
| Dark | `text_sec` (`#8E8E93`) | 13px | 2px 0 |
| Light | `text_sec` (`#636366`) | 13px | 2px 0 |

**File:** Styled in `gui/styles.py` via `QLabel#tool_description`. Object name set in `gui/main_window.py`.

### 4.2 Section Toggles (`QPushButton#section_toggle`)

Flat buttons that expand/collapse the Parameters and Data Files sections.

| State | Background | Text | Border |
|-------|-----------|------|--------|
| Ready | transparent | `text_main` | none |
| Hover | transparent | `accent_blue` | none |

**Used by:** "▶ Parameters" and "▶ Data Files" toggle buttons.

### 4.3 Collapsible Panels (`QWidget#collapsible_panel`, `QFrame#collapsible_panel`)

The expanded content areas for Parameters (command preview) and Data Files. They use an elevated surface to differentiate them from the window background.

| Property | Dark Mode | Light Mode |
|----------|-----------|------------|
| Background | `bg_widget` (`#252529`) | `bg_widget` (`#FFFFFF`) |
| Border | 1px `border` (`#2C2C2C`) | 1px `border` (`#E0E0E0`) |
| Border radius | 6px | 6px |

**Used by:** Command preview frame, Data Files widget.

**Important:** Child `QWidget` rows inside a collapsible panel are given `objectName("panel_row")` and styled with `background-color: transparent` so they don't paint over the parent's elevated `bg_widget` surface with the default `bg_window` colour.

### 4.4 Parameters Table (`QTableWidget#tool_params_table`)

The params table uses the elevated surface for its body and a subtly different header row.

| Part | Dark Mode | Light Mode |
|------|-----------|------------|
| Body bg | `bg_widget` (`#252529`) | `bg_widget` (`#FFFFFF`) |
| Body border | 1px `border`, 6px radius | 1px `border`, 6px radius |
| Gridlines | `border` | `border` |
| Header bg | `hover_bg` (`#3A3A3C`) | `hover_bg` (`#F0F0F0`) |
| Header text | `text_sec` | `text_sec` |
| Header border | bottom 1px `border` | bottom 1px `border` |

---

## 5. Tab Bar

Tabs use a minimal underline style instead of pill backgrounds.

| State | Background | Text | Bottom Border |
|-------|-----------|------|---------------|
| Unselected | transparent | `text_sec` | 3px transparent |
| Selected | transparent | `accent_blue` | 3px `accent_blue` |
| Hover (unselected) | transparent | `text_main` | — |
| Disabled | transparent | `disabled_text` | 3px transparent |
| Selected + Disabled | transparent | `disabled_text` | 3px `disabled_bg` |

---

## 6. Inputs & Combo Boxes

### Text Inputs (`QLineEdit`, `QTextEdit`, `QPlainTextEdit`)

| State | Background | Border | Selection |
|-------|-----------|--------|-----------|
| Normal | `input_bg` | 1px `border` | `accent_blue` bg, white text |
| Focused | `input_bg` | 1px `accent_blue` | — |

### Combo Box (`QComboBox`)

| State | Background | Border | Arrow |
|-------|-----------|--------|-------|
| Normal | `bg_widget` | 1px `border` | `chevron_down` SVG (secondary tint, 12px) |
| Hover | `bg_widget` | 1px `accent_blue` | — |
| Dropdown list | `bg_widget` | — | Selection: `accent_blue` bg, white text |

The combo box arrow is rendered as a Retina-quality PNG via `IconManager.render_to_file()` and referenced in QSS with `image: url(...)`.

### Popup Positioning (`DropDownComboBox`)

The main window uses a `DropDownComboBox` subclass (defined in `gui/main_window.py`) instead of a plain `QComboBox`. On macOS, Qt's default combo box popup aligns the currently selected item with the widget, which causes a "drop-up" effect when items near the end of the list are selected. `DropDownComboBox` overrides `showPopup()` to anchor the popup's top edge to the widget's bottom edge so the list always drops **down**.

Use `DropDownComboBox` for any combo box in the main window where consistent downward popup placement is desired.

---

## 7. Status Bar

The status message label (`QLabel#status_msg`) supports four visual states via the `status_state` dynamic property.

| State | Visual | When Used |
|-------|--------|-----------|
| `""` (default) | Neutral — transparent bg, `border` border, `text_sec` text | "Ready" |
| `"info"` | Cool blue tint — faint blue bg + blue border + blue text | "Recording ready", "Captured", "Auto capturing…", "Loaded previous meeting" |
| `"warn"` | Warm amber tint — faint gold bg + gold border + gold text | "Stopped" |
| `"error"` | Soft rose tint — faint red bg + red border + red text | "Capture failed", "Error" |

See **Section 1.5** for exact hex values.

---

## 8. Icon System

All icons are Lucide SVGs stored in the `_SVG_SOURCES` dictionary in `gui/icons.py`.

### 7.1 Available Icons

| Key | Description | Used By |
|-----|-------------|---------|
| `maximize` | Expand arrows (outward) | Maximize window button |
| `minimize` | Shrink arrows (inward) | Restore window button |
| `shrink` | Four-corner shrink | — (available) |
| `expand` | Four-corner expand | — (available) |
| `chevrons_up` | Double chevron up | Compact view button (expanded state) |
| `chevrons_down` | Double chevron down | Compact view button (compacted state) |
| `chevron_down` | Single chevron down | Combo box dropdown arrow |
| `arrow_up` | Upload/house arrow up | Time round-up button |
| `arrow_down` | Download/house arrow down | Time round-down button |
| `copy` | Clipboard copy | Copy transcript, Copy tool output |
| `download` | Download arrow | Save tool output |
| `save` | Floppy disk | Save meeting details |
| `folder_open` | Open folder | Open meeting folder |
| `refresh` | Circular arrows | Reload transcript |
| `calendar` | Calendar page | Calendar toolbar button |
| `calendar_sync` | Calendar with sync arrows | Calendar events dialog refresh button |
| `search` | Magnifying glass | Accessibility Inspector filter fields |
| `scan_eye` | Scanning eye in viewfinder | Accessibility Inspector window |

### 7.2 Tint System

Icons are dynamically tinted at render time. The `_TINTS` dictionary in `gui/icons.py` maps tint names to hex colours per theme mode.

| Tint | Dark Mode | Light Mode | Usage |
|------|-----------|------------|-------|
| `default` | `#E1E1E6` | `#333333` | Most UI icons (matches `text_main`) |
| `primary` | `#7AA2FF` | `#4A67AD` | Accent-coloured icons |
| `secondary` | `#8E8E93` | `#636366` | Muted icons (combo arrow, etc.) |
| `success` | `#81C784` | `#388E3C` | Success/capture indicators |
| `danger` | `#E57373` | `#C62828` | Error/stop indicators |

### 7.3 How Tinting Works

1. Each SVG in `_SVG_SOURCES` uses `stroke="currentColor"` as its stroke colour.
2. When `IconManager.get_icon(name, is_dark, tint, size)` is called, the `_tinted_svg()` method replaces `stroke="currentColor"` with the resolved hex colour from `_TINTS[tint][is_dark]`.
3. The tinted SVG string is fed to `QSvgRenderer` and painted onto a `QPixmap` sized at `size × devicePixelRatio` for Retina sharpness.
4. Results are cached by `(name, is_dark, tint, size)`. Call `IconManager.refresh()` after a theme toggle to flush the cache.

### 7.4 Rendering Pipeline

```
SVG source string
    ↓  _tinted_svg() — replace stroke="currentColor" with hex
Tinted SVG string
    ↓  QSvgRenderer
    ↓  QPainter → QPixmap (physical = size × devicePixelRatio)
    ↓  setDevicePixelRatio(dpr)
QIcon (for buttons)  or  PNG file (for QSS image: url)
```

**For QSS usage** (e.g. combo box arrow): `render_to_file()` saves the pixmap as a PNG to `/tmp/TranscriptRecorder_icons/` and returns the path. The path is passed into `get_application_stylesheet(is_dark, combo_arrow_path=...)`.

### 7.5 Adding a New Icon

1. Find the SVG on [lucide.dev](https://lucide.dev/icons/).
2. Copy the `<svg>` element and add it to `_SVG_SOURCES` in `gui/icons.py`, using the same format (single-line string, `stroke="currentColor"`).
3. Use it via `IconManager.get_icon("your_key", is_dark=..., tint="default", size=24)`.

---

## 9. Window Sizes

| Mode | Size | Min Size |
|------|------|----------|
| Default (launch) | 600 × 450 | 350 × 300 |
| Maximized | 960 × 720 | 350 × 300 |
| Compact | `minimumSizeHint()` (both axes) | 0 × 0 (temporarily) |

Compact mode hides the tab section and separator, relaxes minimum constraints, then resizes to the tightest fit. Expanding restores the previous size and re-applies `350 × 300` minimums.

---

## 10. Button Label & Tooltip Reference

All labels follow the **Minimalist Verb** pattern. Tooltips start with a verb.

| Button | Label | Tooltip | Class |
|--------|-------|---------|-------|
| New | "New" | "Create a new meeting recording" | `primary` |
| Reset | "Reset" | "Clear the current meeting recording" | `danger-outline` |
| History | "History" | "Open a previous meeting and transcript" | `secondary-action` |
| Capture | "Capture" | "Capture a single transcript snapshot" | `action` |
| Auto Capture | "Auto Capture" | "Start continuous transcript capture" | `toggle_off` |
| Stop | "Stop (Xs)" | "Stop continuous transcript capture" | `toggle_on` |
| Run | "Run" | — | `action` |
| Cancel | "Cancel" | — | `danger-outline` |

**Terminology:** Use "Meeting" for the data structure, "Transcript" for the text output, "Recording" for the session lifecycle.

---

## 11. Scrollbars

Styled as thin, macOS-native overlays.

| Part | Normal | Hover |
|------|--------|-------|
| Track | transparent | transparent |
| Handle (vertical) | `scrollbar_handle`, min-height 20px, radius 4px | `text_sec` |
| Handle (horizontal) | `scrollbar_handle`, min-width 20px, radius 4px | `text_sec` |
| Arrows / paging | Hidden (0px) | — |

---

## 12. Making Changes

### Changing a colour

1. Update the variable in `gui/styles.py` (palette section, lines 13–41).
2. If the colour is also an icon tint, update `_TINTS` in `gui/icons.py` (lines 38–60).
3. Update this document.

### Adding a new button class

1. Add the QSS rules in `gui/styles.py` under the `BUTTON STATES` section.
2. In `gui/main_window.py`, call `btn.setProperty("class", "your-class")`.
3. If the button changes state at runtime, call `style().unpolish(btn)` then `style().polish(btn)` after `setProperty`.
4. Document the class in **Section 2** of this guide.

### Adding a new status state

1. Add palette variables (`status_*`) in `gui/styles.py`.
2. Add the `QLabel#status_msg[status_state="..."]` QSS rule.
3. Use via `self._set_status("message", "your_state")` in `gui/main_window.py`.
4. Document in **Section 1.5** and **Section 7**.
