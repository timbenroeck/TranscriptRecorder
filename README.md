# Transcript Recorder

A macOS application that captures meeting transcripts and live captions using the macOS Accessibility API. Supports both automated capture from meeting applications and manual transcript entry.

## Features

- **Manual Recording**: Paste or type transcripts directly — works on first launch with no setup
- **Automated Capture**: Capture live transcripts from Zoom, Microsoft Teams, and more
- **Smart Merging**: Intelligently merges transcript snapshots to avoid duplicates
- **Native macOS UI**: Modern PyQt6 interface with light/dark mode support
- **Meeting Tools**: Run custom scripts (cleanup, summarization, etc.) against your recordings
- **Rules & Tools**: Extensible rule-based architecture — download or create your own
- **Meeting Details**: Add meeting name, notes, and timestamps to your recordings
- **Screen Sharing Privacy**: Hide the app window from screen sharing and recordings
- **Auto-Updates**: Check for and install updates directly from the app

## Requirements

- **macOS 12.0 (Monterey)** or later
- **Python 3.11+** (for running from source)
- **Accessibility Permissions**: Required only for automated capture (not needed for manual recording)

## Installation

### From Release (Recommended)

1. Download the latest `.dmg` file from [Releases](../../releases)
2. Open the DMG and drag "Transcript Recorder" to your Applications folder
3. Follow the steps below to allow the unsigned app and grant required permissions

#### Allowing the Unsigned App

Since Transcript Recorder is not signed with an Apple Developer certificate, macOS will block it on first launch. Follow these steps to allow it:

**Step 1: Dismiss the blocked app warning**

When you first open the app, macOS will display a warning that it cannot verify the developer. Click **Done** to dismiss the dialog.

![Blocked app warning](images/1_blocked_app.png)

**Step 2: Allow the app in System Settings**

Open **System Settings → Privacy & Security**. Scroll down to the Security section where you will see a message about "Transcript Recorder" being blocked. Click **Open Anyway**.

![Allow blocked app in System Settings](images/2_allow_blocked_app.png)

**Step 3: Confirm opening the app**

A confirmation dialog will appear. Click **Open Anyway** to launch the app.

![Confirm open dialog](images/3_confirm_open.png)

#### Granting Accessibility Permissions

Transcript Recorder uses the macOS Accessibility API to read transcript content from meeting applications. If you plan to use automated capture (Zoom, Teams, etc.), you must grant Accessibility access:

1. Open **System Settings → Privacy & Security → Accessibility**
2. Find **Transcript Recorder.app** in the list
3. Toggle the switch to **enable** it

![Accessibility permission setting](images/4_allow_accessibility.png)

> **Note:** Accessibility permissions are **not required** for Manual Recording mode. If you only plan to paste transcripts manually, you can skip this step.

> **Note:** If Transcript Recorder does not appear in the Accessibility list, click the **+** button, navigate to your Applications folder, and add it manually. You may need to restart the app after granting permissions.

## First Launch

On first launch, the application:

1. **Prompts for an export directory** — where recordings, rules, and tools will be stored
2. **Copies bundled rules and tools** into the export directory (Zoom, Microsoft Teams, Clean Transcript)
3. **Selects Manual Recording** by default so the app is immediately usable

No downloads, accessibility permissions, or additional configuration are required to start using the app in manual mode.

## Usage

### Manual Recording

Manual Recording lets you paste or type a transcript directly into the app. This is useful for transcripts you've copied from another source (email, chat, a file, etc.).

1. **Select "Manual Recording"** from the dropdown (it's the default)
2. **Click "New"** to start a new session
3. **Paste or type** your transcript into the text area — it auto-saves as you type
4. Use **Meeting Tools** to run cleanup or other tools against your transcript

> In manual mode the Capture and Auto Capture buttons are disabled since there is nothing to capture from the accessibility tree.

### Automated Capture

For live meeting transcript capture:

1. **Select** your meeting application from the dropdown (e.g. Zoom, Microsoft Teams)
2. **Grant Accessibility Permissions** if prompted (System Settings → Privacy & Security → Accessibility)
3. **Click "New"** to start a new session
4. **Join your meeting** and enable captions/transcripts in the meeting app
5. **Click "Capture"** for a single snapshot, or **"Auto Capture"** for continuous recording

### Recording Workflow

1. **New**: Creates a new recording session with a timestamped folder
2. **Capture**: Takes a single snapshot of the current transcript
3. **Auto Capture**: Continuously captures at the configured interval (default: 30 seconds)
4. **Meeting Details**: Add a meeting name, notes, and adjust the date/time
5. **History**: Load and review a previous recording

### Output Files

Recordings are saved under your export directory in a date-based structure:

```
recordings/
└── 2025/
    └── 02/
        └── recording_2025-02-08_1430_zoom/
            ├── meeting_transcript.txt      # Merged transcript
            ├── meeting_details.txt         # Meeting metadata
            └── .snapshots/                 # Individual capture snapshots
```

## Rules

Rules define how the app finds and reads transcript content from a specific meeting application. Each rule is a folder containing a `rule.json` file stored in the `rules/` directory inside your export folder.

### Bundled Rules

The app ships with rules for **Zoom** and **Microsoft Teams**. These are automatically installed on first launch. Additional rules (Slack, WebEx, etc.) can be downloaded from the Rules menu.

### Rule Structure

```
rules/
└── zoom/
    └── rule.json
```

A `rule.json` defines:

| Field | Description |
|-------|-------------|
| `display_name` | Name shown in the application dropdown |
| `command_paths` | Paths to detect if the application is running |
| `rules_to_find_transcript_table` | Search paths to locate the transcript UI element |
| `traversal_mode` | `bfs` (breadth-first) or `dfs` (depth-first) search |
| `traversal_roles_to_skip` | Accessibility roles to skip during traversal |
| `serialization_text_element_roles` | Map of roles to attributes for text extraction |
| `serialization_export_depth` | How deep to traverse for text content |
| `monitor_interval_seconds` | Default capture interval |
| `exclude_pattern` | Regex pattern to filter out unwanted text |
| `incremental_export` | When true, only exports new rows since the last capture |

### Managing Rules

- **Rules → Import Rules...** — Download rules from the GitHub repository
- **Rules → Edit Rule...** — Open the visual Rule Editor for any installed rule
- **Rules → Set Current as Default** — Set the selected rule as the startup default
- **Rules → Open Rules Folder** — Open the rules directory in Finder
- **Rules → Refresh Rules** — Rescan the rules directory

### Adding a New Rule

To add support for a new meeting application:

1. Create a new folder in your rules directory (e.g. `rules/my_app/`)
2. Add a `rule.json` — use an existing rule as a template
3. Use macOS **Accessibility Inspector** to identify the UI element roles and attributes for the transcript
4. Define search paths and steps to locate the transcript element
5. **Rules → Refresh Rules** to pick up the new rule

Alternatively, use **Rules → Import Rules...** to download a pre-built rule from the repository.

## Meeting Tools

The **Meeting Tools** tab lets you run custom scripts against your recordings directly from the app. Tools are stored in the `tools/` directory inside your export folder.

> **Full documentation:** See [docs/TOOLS.md](docs/TOOLS.md) for the complete developer guide, including the full `tool.json` schema, streaming output, parser reference, and troubleshooting.

### Bundled Tools

The app ships with the **Clean Transcript** tool, which performs first-pass cleanup of meeting transcripts (removes filler words, stutters, and applies terminology corrections). It is automatically installed on first launch.

Additional tools can be downloaded via **Tools → Import Tools...**.

### Tool Structure

Each tool lives in its own sub-folder with a JSON definition and a script:

```
tools/
└── clean_transcript/
    ├── tool.json               # Tool metadata and parameter definitions
    ├── clean_transcript.py     # The script that gets executed
    ├── data/
    │   └── corrections.json    # Editable data file for corrections
    └── README.md               # Optional documentation
```

### tool.json

```json
{
  "display_name": "Clean Transcript",
  "description": "First-pass cleanup of meeting transcripts.",
  "script": "clean_transcript.py",
  "streaming": false,
  "parameters": [
    {
      "flag": "-t",
      "label": "Transcript File",
      "builtin": "meeting_transcript",
      "required": true
    }
  ],
  "data_files": [
    {
      "file": "data/corrections.json",
      "label": "Corrections Dictionary",
      "editor": "key_array_grid"
    }
  ]
}
```

#### Top-Level Fields

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `display_name` | Yes | — | Name shown in the tool dropdown |
| `description` | No | — | Shown below the dropdown when the tool is selected |
| `script` | Yes | — | Filename of the script in the same sub-folder |
| `parameters` | No | `[]` | Array of parameter definitions |
| `streaming` | No | `false` | Enable real-time streaming output |
| `stream_parser` | No | `"raw"` | Parser for streaming lines (`"raw"` or `"cortex_json"`) |
| `idle_warning_seconds` | No | `30` | Seconds of no output before showing a warning |
| `idle_kill_seconds` | No | `120` | Seconds of no output before auto-cancelling |
| `data_files` | No | `[]` | Editable data files with in-app editors |

#### Built-in Parameter Values

Parameters with a `"builtin"` key are automatically resolved at run-time:

| `builtin` value | Resolves to |
|-----------------|-------------|
| `meeting_directory` | Full path to the current recording folder |
| `meeting_transcript` | Full path to `meeting_transcript.txt` |
| `meeting_details` | Full path to `meeting_details.txt` |
| `export_directory` | Base export directory |
| `app_name` | Key of the selected rule (e.g. `zoom`, `msteams`, `manual`) |

### Managing Tools

- **Tools → Import Tools...** — Download tools from the GitHub repository
- **Tools → Edit Tool Configuration...** — Edit a tool's `tool.json` in the JSON editor
- **Tools → Edit Tool Data Files...** — Edit a tool's data files (e.g. corrections dictionary)
- **Tools → Open Tools Folder** — Open the tools directory in Finder
- **Tools → Refresh Tools** — Rescan the tools directory

### Streaming Output

For long-running tools (e.g. AI/LLM calls via Cortex), set `"streaming": true` to see output in real-time instead of waiting for the process to complete. The `cortex_json` parser translates Cortex CLI's JSON streaming format into human-readable status lines.

If no output is received for `idle_warning_seconds`, the status bar shows a warning. After `idle_kill_seconds` the tool is auto-cancelled.

## Configuration

The application configuration is stored at `~/Library/Application Support/TranscriptRecorder/config.json`. On first launch, a default config is copied from the app bundle.

```json
{
  "logging": {
    "level": "INFO",
    "log_to_file": true,
    "log_file_name": "gui_client.log"
  },
  "client_settings": {
    "export_directory": "",
    "default_rule": ""
  }
}
```

| Setting | Description |
|---------|-------------|
| `logging.level` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`, or `NONE` |
| `logging.log_to_file` | Write logs to a rotating file |
| `logging.log_file_name` | Log filename inside the `.logs` directory |
| `client_settings.export_directory` | Where recordings, rules, and tools are stored |
| `client_settings.default_rule` | Rule key selected on startup (e.g. `zoom`, `manual`) |

You can change the log level from **Maintenance → Log Level** without editing the file. Use **Maintenance → Change Export Directory...** to move your export location.

## Menu Reference

### File

| Menu Item | Shortcut | Description |
|-----------|----------|-------------|
| **New** | `Cmd+N` | Creates a new recording session |
| **Reset** | `Cmd+R` | Stops any active capture and resets the session |
| **Open Export Folder** | `Cmd+O` | Opens the base export directory in Finder |

### Edit

| Menu Item | Shortcut | Description |
|-----------|----------|-------------|
| **Copy Transcript** | `Cmd+C` | Copies the transcript text to the clipboard |

### View

| Menu Item | Shortcut | Description |
|-----------|----------|-------------|
| **Appearance** | | Switch between **System**, **Light**, and **Dark** themes |
| **Screen Sharing Privacy** | | Show or hide the app from screen sharing and recordings |
| **Log File...** | `Cmd+L` | Opens the log viewer window |

### Tools

| Menu Item | Description |
|-----------|-------------|
| **Import Tools...** | Download tools from the GitHub repository |
| **Edit Tool Configuration...** | Edit a tool's JSON definition |
| **Edit Tool Data Files...** | Edit a tool's data files in a visual editor |
| **Open Tools Folder** | Open the tools directory in Finder |
| **Refresh Tools** | Rescan the tools directory for new or updated tools |

### Rules

| Menu Item | Description |
|-----------|-------------|
| **Import Rules...** | Download rules from the GitHub repository |
| **Edit Rule...** | Open the visual Rule Editor for an installed rule |
| **Set Current as Default** | Save the selected rule as the startup default |
| **Clear Default** | Remove the default rule setting (falls back to Manual Recording) |
| **Open Rules Folder** | Open the rules directory in Finder |
| **Refresh Rules** | Rescan the rules directory for new or updated rules |

### Maintenance

| Menu Item | Description |
|-----------|-------------|
| **Change Export Directory...** | Move the export location (recordings, rules, tools) |
| **Log Level** | Set the runtime log level; **Change Default...** persists it to config |
| **Clear Log File** | Clears the application log file |
| **Clear All Snapshots** | Removes `.snapshots` folders from past recordings while preserving merged transcripts |
| **Clear Empty Recordings** | Removes recording folders that contain no files |
| **Check Permissions** | Verifies that macOS Accessibility permissions are granted |
| **Check for Updates...** | Queries GitHub releases for a newer version |

## Supported Applications

| Application | Status | Notes |
|-------------|--------|-------|
| **Manual Recording** | Built-in | Paste or type transcripts — no permissions needed |
| **Zoom** | Bundled | Works with transcript window and in-meeting captions |
| **Microsoft Teams** | Bundled | Works with Live Captions feature |
| **WebEx** | Available | Download via Rules → Import Rules |
| **Slack** | Available | Download via Rules → Import Rules |

## Troubleshooting

### "Accessibility permission required"

See [Granting Accessibility Permissions](#granting-accessibility-permissions) above for detailed instructions with screenshots.

1. Open **System Settings** → **Privacy & Security** → **Accessibility**
2. Click the **+** button and add Transcript Recorder
3. Ensure the toggle is enabled
4. Restart the application

> This only applies to automated capture rules. Manual Recording does not require accessibility permissions.

### Transcript not capturing

- Ensure captions/transcripts are **enabled** in your meeting application
- Make sure the transcript **window is visible** (not minimized)
- Try clicking **"Capture"** to test manual capture
- Check the **log file** (View → Log File) for error details

### Application not detected

- Verify the meeting app is **running**
- Check that the `command_paths` in the rule match your installation
- Some apps (like Teams) may run from different paths depending on how they were installed
- Use **Rules → Edit Rule...** to update the command paths

### Tools not appearing

- Ensure the tool folder contains both the script file and a valid `tool.json`
- Use **Tools → Refresh Tools** to rescan
- Check the log file for JSON parsing errors

## Building from Source

### Development

```bash
# Clone the repository
git clone <repo-url>
cd TranscriptRecorder

# Install dependencies
pip install -r requirements.txt

# Run without building
python gui_app.py
```

### Building the App Bundle

```bash
# Local source build (uses SourceBuild bundle ID to avoid permission conflicts)
./scripts/build_local.sh

# Full clean rebuild
./scripts/full_rebuild_local.sh
```

### Bundle Manifest

The `bundle.json` file at the repo root controls which rules and tools are shipped inside the built `.app`:

```json
{
  "rules": ["zoom", "msteams"],
  "tools": ["clean_transcript"]
}
```

Only explicitly listed items are included in the app bundle. Other rules and tools in the repo (e.g. `slack`, `webex`, `summarize_meeting_coco`) remain available for download via the Import menus but are not shipped with the app.

## License

MIT License - See LICENSE file for details.

## Acknowledgments

- Built with [PyQt6](https://www.riverbankcomputing.com/software/pyqt/)
- Uses [pyobjc](https://pyobjc.readthedocs.io/) for macOS Accessibility API access
- App icon generated with [Icon Kitchen](https://icon.kitchen/) by Roman Nurik
- UI icons from [Lucide](https://lucide.dev/) (ISC License)
