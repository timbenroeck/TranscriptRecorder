# Dialog Screens — Style Audit & Recommendations

> **Purpose:** Document the current styling state of every dialog window, identify inconsistencies with the main window's Slate & Charcoal theme, and propose fixes.  
> **Last updated:** 2026-02-08

---

## Source Files

| File | Dialogs Defined |
|------|-----------------|
| `gui/dialogs.py` | LogViewerDialog, SetupDialog, ConfigEditorDialog |
| `gui/tool_dialogs.py` | ToolImportDialog, ToolJsonEditorDialog |
| `gui/data_editors.py` | DataFileEditorDialog (+ BaseDataEditor, KeyArrayGridEditor, KeyValueGridEditor, StringListEditor) |

---

## Common Issues Across All Dialogs

These problems appear in every dialog and should be fixed globally.

### Issue 1: Hardcoded Status Label Colours

Every dialog uses inline `setStyleSheet()` with Apple-era hex colours that do not match the Slate & Charcoal palette:

| Hardcoded Colour | Used For | Slate & Charcoal Equivalent |
|-----------------|----------|----------------------------|
| `#007AFF` | Info / "in progress" text | `accent_blue` (`#7AA2FF` / `#4A67AD`) |
| `#34C759` | Success text | `capture_green` (`#81C784` / `#388E3C`) |
| `#FF3B30` | Error text | `danger_red` (`#E57373` / `#C62828`) |
| `#FF9500` | Warning text | `status_warn_text` (`#D4B106` / `#856404`) |

**Recommendation:** Replace all inline `setStyleSheet("color: #XXXXXX; font-size: 12px;")` calls with a shared helper or themed QSS object names. The main window already has a `_set_status()` pattern. Dialogs should use the same approach — give each dialog's `status_label` an object name (e.g., `dialog_status`) and add QSS rules using a `status_state` dynamic property, mirroring the main window's status bar logic.

### Issue 2: Non-Existent Button Classes

Several buttons reference `class="success"` and `class="danger"`, which were **removed** from the stylesheet during the Slate & Charcoal overhaul. These buttons are currently falling back to the default button style and have **no special visual treatment**.

| Button | Dialog | Current Class | Intended Role |
|--------|--------|---------------|---------------|
| Save | ConfigEditorDialog | `success` (removed) | Confirm / commit action |
| Save | ToolJsonEditorDialog | `success` (removed) | Confirm / commit action |
| Save | DataFileEditorDialog | `success` (removed) | Confirm / commit action |
| Install Selected | ToolImportDialog | `success` (removed) | Confirm / commit action |
| Clear Log | LogViewerDialog | `danger` (removed) | Destructive action |

**Recommendation:** Map these to the existing button hierarchy:

| Old Class | New Class | Rationale |
|-----------|-----------|-----------|
| `success` | `action` | Save/Install are the primary call-to-action on their screen — Ghost Blue makes them prominent and thematically consistent. |
| `danger` | `danger-outline` | "Clear Log" is destructive — use the red outline style already defined for Reset/Cancel. |

### Issue 3: Missing `+ Add Row` / `- Delete Row` Button Styling

The data editor widgets (`KeyArrayGridEditor`, `KeyValueGridEditor`, `StringListEditor`) create `+ Add Row`, `- Delete Row`, `Move Up`, `Move Down` buttons with no class at all. They get the default button style, which is functional but doesn't distinguish adding from deleting.

**Recommendation:**
- `+ Add Row` / `+ Add`: `class="secondary-action"` (Solid Neutral — matches History button; a utility action).
- `- Delete Row` / `- Delete`: `class="danger-outline"` (red outline — consistent with all destructive actions).
- `Move Up` / `Move Down`: Leave as default (neutral utility).

---

## Dialog-by-Dialog Audit

---

### 1. LogViewerDialog

**File:** `gui/dialogs.py` (line 26)  
**Opened from:** Menu > View > View Logs

#### Layout
- Monospace `QTextEdit` (read-only, Menlo 11pt)
- Bottom button row: **Refresh** | **Clear Log** | stretch | **Close**

#### Current Button Styling

| Button | Label | Current Class | Renders As |
|--------|-------|---------------|------------|
| Refresh | "Refresh" | `primary` | Solid blue — correct |
| Clear Log | "Clear Log" | `danger` (removed!) | Falls back to default grey |
| Close | "Close" | (none) | Default button — correct |

#### Issues
- `class="danger"` no longer exists. Clear Log looks identical to Close.

#### Recommendations
| Button | Suggested Class | Rationale |
|--------|----------------|-----------|
| Refresh | `action` | Demote from `primary`. This is a utility action, not the main CTA. Ghost Blue fits better since this dialog's purpose is *viewing*, not *acting*. |
| Clear Log | `danger-outline` | Destructive action — red outline signals caution. |
| Close | (default) | Keep as neutral dismiss. |

---

### 2. SetupDialog (First-Run)

**File:** `gui/dialogs.py` (line 123)  
**Opened from:** Automatically on first launch when no `config.json` exists

#### Layout
- Header: "Welcome to TranscriptRecorder" (bold 18pt)
- Description paragraph
- **Option A group box:** "Set up a new export directory" with description + button
- **Option B group box:** "Import an existing configuration" with description + button
- Bottom: stretch | **Cancel**

#### Current Button Styling

| Button | Label | Current Class | Renders As |
|--------|-------|---------------|------------|
| Choose Export Directory… | (none) | (default) | Grey button |
| Select config.json… | (none) | (default) | Grey button |
| Cancel | "Cancel" | (none) | Grey button |

#### Issues
- All three buttons look identical — there's no visual hierarchy.
- The header font uses `.AppleSystemUIFont` which may not render consistently.
- Group boxes use the global `QGroupBox` style (transparent bg, no border) which is fine, but the two options are not visually separated from each other.

#### Recommendations
| Button | Suggested Class | Rationale |
|--------|----------------|-----------|
| Choose Export Directory… | `primary` | This is the recommended path for new users — strongest visual weight. |
| Select config.json… | `secondary-action` | Advanced / alternative path — Solid Neutral shows it's clickable but secondary. |
| Cancel | `danger-outline` | Cancelling first-run setup exits the app — this should feel cautious. |

Additional:
- Change header font from `.AppleSystemUIFont` to match the global font stack (`"SF Pro", "SF Compact", "Helvetica Neue", sans-serif`).
- Consider adding a subtle border or divider between the two group boxes for visual separation.

---

### 3. ConfigEditorDialog

**File:** `gui/dialogs.py` (line 274)  
**Opened from:** Menu > Settings > Edit Configuration

#### Layout
- Info label: "Editing: /path/to/config.json" (uses `#secondary_label` — correct)
- Monospace `QTextEdit` (editable, Menlo 11pt)
- Status label (inline-styled)
- Bottom button row: **Reload** | **Download from URL** | **Restore Packaged Config** | stretch | **Save** | **Validate JSON** | **Close**

#### Current Button Styling

| Button | Label | Current Class | Renders As |
|--------|-------|---------------|------------|
| Reload | "Reload" | (none) | Default grey |
| Download from URL | "Download from URL" | (none) | Default grey |
| Restore Packaged Config | "Restore Packaged Config" | (none) | Default grey |
| Save | "Save" | `success` (removed!) | Falls back to default grey |
| Validate JSON | "Validate JSON" | `primary` | Solid blue |
| Close | "Close" | (none) | Default grey |

#### Issues
- 6 buttons in one row — crowded. Difficult to distinguish actions at a glance.
- Save button (`success`) has no special styling — it looks the same as Reload.
- Validate JSON is `primary` (solid blue) but Save is unstyled — the visual hierarchy is backwards.
- Status label uses hardcoded Apple colours.

#### Recommendations
| Button | Suggested Class | Rationale |
|--------|----------------|-----------|
| Reload | (default) | Neutral utility. |
| Download from URL | `secondary-action` | Utility import action — Solid Neutral makes it visible but non-competing. |
| Restore Packaged Config | `danger-outline` | This overwrites the editor content — cautionary action. |
| Save | `action` | This is the primary CTA for this screen — Ghost Blue. |
| Validate JSON | `secondary-action` | Utility check — should not outshine Save. Demote from `primary`. |
| Close | (default) | Neutral dismiss. |

Additional:
- Replace all `status_label.setStyleSheet(...)` calls with a `dialog_status` object name + `status_state` property approach matching the main window.

---

### 4. ToolImportDialog

**File:** `gui/tool_dialogs.py` (line 45)  
**Opened from:** Menu > Tools > Import Tools from GitHub

#### Layout
- URL input row: label + `QLineEdit` + **Fetch** button
- Info label (uses `#secondary_label` — correct)
- `QTableWidget` with columns: Install (checkbox) | Tool Name | Status
- Status label (inline-styled)
- Bottom button row: **Select All** | **Deselect All** | stretch | **Install Selected** | **Close**

#### Current Button Styling

| Button | Label | Current Class | Renders As |
|--------|-------|---------------|------------|
| Fetch | "Fetch" | `primary` | Solid blue — correct |
| Select All | "Select All" | (none) | Default grey |
| Deselect All | "Deselect All" | (none) | Default grey |
| Install Selected | "Install Selected" | `success` (removed!) | Falls back to default grey |
| Close | "Close" | (none) | Default grey |

#### Issues
- Install Selected (`success`) is unstyled — it's the most important button on this screen.
- Status label uses hardcoded Apple colours.

#### Recommendations
| Button | Suggested Class | Rationale |
|--------|----------------|-----------|
| Fetch | `action` | Demote from `primary` to Ghost Blue. Fetching is a step in the workflow, not the final action. |
| Select All | (default) | Neutral utility. |
| Deselect All | (default) | Neutral utility. |
| Install Selected | `primary` | This is the final commit action — strongest visual weight. Promote to solid blue. |
| Close | (default) | Neutral dismiss. |

---

### 5. ToolJsonEditorDialog

**File:** `gui/tool_dialogs.py` (line 321)  
**Opened from:** Menu > Tools > Edit Tool Configuration

#### Layout
- Info label: "Editing: /path/to/tool.json" (uses `#secondary_label` — correct)
- Monospace `QTextEdit` (editable, Menlo 11pt)
- Status label (inline-styled)
- Bottom button row: **Reload** | stretch | **Save** | **Validate JSON** | **Close**

#### Current Button Styling

| Button | Label | Current Class | Renders As |
|--------|-------|---------------|------------|
| Reload | "Reload" | (none) | Default grey |
| Save | "Save" | `success` (removed!) | Falls back to default grey |
| Validate JSON | "Validate JSON" | `primary` | Solid blue |
| Close | "Close" | (none) | Default grey |

#### Issues
- Same as ConfigEditorDialog: Save is unstyled, Validate outshines Save.
- Status label uses hardcoded Apple colours.

#### Recommendations
| Button | Suggested Class | Rationale |
|--------|----------------|-----------|
| Reload | (default) | Neutral utility. |
| Save | `action` | Primary CTA — Ghost Blue. |
| Validate JSON | `secondary-action` | Utility check — Solid Neutral. |
| Close | (default) | Neutral dismiss. |

---

### 6. DataFileEditorDialog

**File:** `gui/data_editors.py` (line 415)  
**Opened from:** Tool panel > Data Files > Edit button, or Menu > Tools > Edit Tool Data Files

#### Layout
- Info label: "Editing: /path/to/data.json" (uses `#secondary_label` — correct)
- Structured editor widget (table-based — one of three editor types)
- Status label (inline-styled)
- Bottom button row: **Reload** | stretch | **Save** | **Close**

#### Current Button Styling

| Button | Label | Current Class | Renders As |
|--------|-------|---------------|------------|
| Reload | "Reload" | (none) | Default grey |
| Save | "Save" | `success` (removed!) | Falls back to default grey |
| Close | "Close" | (none) | Default grey |

#### Issues
- Save is unstyled.
- Status label uses hardcoded Apple colours.
- The embedded editor widgets (KeyArrayGridEditor, etc.) have `+ Add Row` and `- Delete Row` buttons with no class.

#### Recommendations
| Button | Suggested Class | Rationale |
|--------|----------------|-----------|
| Reload | (default) | Neutral utility. |
| Save | `action` | Primary CTA — Ghost Blue. |
| Close | (default) | Neutral dismiss. |
| + Add Row / + Add | `secondary-action` | Constructive utility. |
| - Delete Row / - Delete | `danger-outline` | Destructive action. |
| Move Up / Move Down | (default) | Neutral utility. |

---

## Summary: Recommended Button Class Mapping

This table shows the complete proposed mapping across all dialogs.

| Dialog | Button | Current | Proposed |
|--------|--------|---------|----------|
| **LogViewer** | Refresh | `primary` | `action` |
| | Clear Log | `danger` (broken) | `danger-outline` |
| | Close | default | default |
| **Setup** | Choose Export Directory… | default | `primary` |
| | Select config.json… | default | `secondary-action` |
| | Cancel | default | `danger-outline` |
| **ConfigEditor** | Reload | default | default |
| | Download from URL | default | `secondary-action` |
| | Restore Packaged Config | default | `danger-outline` |
| | Save | `success` (broken) | `action` |
| | Validate JSON | `primary` | `secondary-action` |
| | Close | default | default |
| **ToolImport** | Fetch | `primary` | `action` |
| | Select All | default | default |
| | Deselect All | default | default |
| | Install Selected | `success` (broken) | `primary` |
| | Close | default | default |
| **ToolJsonEditor** | Reload | default | default |
| | Save | `success` (broken) | `action` |
| | Validate JSON | `primary` | `secondary-action` |
| | Close | default | default |
| **DataFileEditor** | Reload | default | default |
| | Save | `success` (broken) | `action` |
| | Close | default | default |
| **Data Editors** | + Add Row | default | `secondary-action` |
| | - Delete Row | default | `danger-outline` |
| | Move Up / Move Down | default | default |

---

## Status Label Refactoring

All six dialogs use the same pattern for status feedback:

```python
self.status_label.setStyleSheet("color: #34C759; font-size: 12px;")  # success
self.status_label.setStyleSheet("color: #FF3B30; font-size: 12px;")  # error
self.status_label.setStyleSheet("color: #FF9500; font-size: 12px;")  # warning
self.status_label.setStyleSheet("color: #007AFF; font-size: 12px;")  # info
```

**Recommendation:** Give every dialog's status label `setObjectName("dialog_status")` and add QSS rules to `gui/styles.py`:

```python
QLabel#dialog_status {
    font-size: 12px;
    color: {text_sec};
    background-color: transparent;
}
QLabel#dialog_status[status_state="info"] {
    color: {accent_blue};
}
QLabel#dialog_status[status_state="success"] {
    color: {capture_green};
}
QLabel#dialog_status[status_state="warn"] {
    color: {status_warn_text};
}
QLabel#dialog_status[status_state="error"] {
    color: {danger_red};
}
```

Then replace every `setStyleSheet(...)` call with:

```python
self.status_label.setText("✓ Saved")
self.status_label.setProperty("status_state", "success")
self.status_label.style().unpolish(self.status_label)
self.status_label.style().polish(self.status_label)
```

This ensures all status colours are theme-aware and consistent across light/dark modes.

---

## Visual Hierarchy Principle

Across all dialogs, the button hierarchy should follow this priority:

| Priority | Class | When to Use | Example |
|----------|-------|-------------|---------|
| 1 (highest) | `primary` | Final commit / irreversible action | Install Selected, Choose Export Directory |
| 2 | `action` | Primary CTA for the current screen | Save, Fetch, Refresh (LogViewer) |
| 3 | `secondary-action` | Utility / alternative actions | Validate JSON, Download from URL, + Add Row |
| 4 (lowest) | default | Neutral dismiss / navigation | Close, Select All, Move Up/Down |
| Caution | `danger-outline` | Destructive / cautionary actions | Clear Log, Restore Packaged Config, - Delete Row, Cancel (Setup) |
