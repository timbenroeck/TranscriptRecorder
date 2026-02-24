# Transcript Recorder

A macOS application that captures meeting transcripts and live captions using the macOS Accessibility API. Supports both automated capture from meeting applications and manual transcript entry.

## Features

- **Manual Recording**: Paste or type transcripts directly — works on first launch with no setup
- **Automated Capture**: Capture live transcripts from Zoom, Microsoft Teams, and more
- **Smart Merging**: Intelligently merges transcript snapshots to avoid duplicates
- **Native macOS UI**: Modern PyQt6 interface with light/dark mode support
- **Meeting Tools**: Run custom scripts (cleanup, summarization, etc.) against your recordings
- **Sources & Tools**: Extensible source-based architecture — download or create your own
- **Meeting Details**: Add meeting name, notes, and timestamps to your recordings
- **Google Calendar** (optional): Populate meeting details from your Google Calendar
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
3. Launch the app and grant Accessibility permissions if needed (see below)

> Releases are code-signed and notarized with Apple, so macOS will not block the app on launch.

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

1. **Prompts for an export directory** — where recordings, sources, and tools will be stored
2. **Copies bundled sources and tools** into the export directory (Zoom, Microsoft Teams, Clean Transcript)
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
            ├── event.json                  # Google Calendar event data (when populated from calendar)
            └── .snapshots/                 # Individual capture snapshots
```

## Sources

Sources define how the app finds and reads transcript content from a specific meeting application. Each source is a folder containing a `source.json` file stored in the `sources/` directory inside your export folder.

> **Full documentation:** See [docs/SOURCES.md](docs/SOURCES.md) for the complete developer guide, including the full `source.json` schema, search path reference, contribution guide, and troubleshooting.

### Bundled Sources

The app ships with sources for **Zoom** and **Microsoft Teams**. These are automatically installed on first launch. Additional sources (Slack, WebEx, etc.) can be downloaded from the Sources menu.

### Source Structure

```
sources/
└── zoom/
    └── source.json
```

A `source.json` defines:

| Field | Description |
|-------|-------------|
| `display_name` | Name shown in the application dropdown |
| `command_paths` | Paths to detect if the application is running |
| `app_names` | Process names to detect the application (fallback when `command_paths` don't match, e.g. code-sign clones) |
| `transcript_search_paths` | Search paths to locate the transcript UI element |
| `traversal_mode` | `bfs` (breadth-first) or `dfs` (depth-first) search |
| `traversal_roles_to_skip` | Accessibility roles to skip during traversal |
| `serialization_text_element_roles` | Map of roles to attributes for text extraction |
| `serialization_export_depth` | How deep to traverse for text content |
| `monitor_interval_seconds` | Default capture interval |
| `exclude_pattern` | Regex pattern to filter out unwanted text |
| `incremental_export` | When true, only exports new rows since the last capture |

### Managing Sources

- **Sources → Import Sources...** — Download sources from the GitHub repository
- **Sources → Edit Source...** — Open the visual Source Editor for any installed source
- **Sources → Accessibility Inspector** — Interactive rule builder: browse the AX tree, add search steps, configure serialization, and test export live
- **Sources → Set Current as Default** — Set the selected source as the startup default
- **Sources → Open Sources Folder** — Open the sources directory in Finder
- **Sources → Refresh Sources** — Rescan the sources directory

### Adding a New Source

To add support for a new meeting application:

1. Create a new folder in your sources directory (e.g. `sources/my_app/`)
2. Add a `source.json` — use an existing source as a template
3. Use macOS **Accessibility Inspector** to identify the UI element roles and attributes for the transcript
4. Define search paths and steps to locate the transcript element
5. **Sources → Refresh Sources** to pick up the new source

Alternatively, use **Sources → Import Sources...** to download a pre-built source from the repository.

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
  "refresh_on_complete": ["meeting_transcript"],
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
| `refresh_on_complete` | No | `[]` | UI elements to reload after success: `"meeting_transcript"`, `"meeting_details"` |

#### Built-in Parameter Values

Parameters with a `"builtin"` key are automatically resolved at run-time. The full list is documented in [`docs/TOOLS.md`](docs/TOOLS.md#built-in-parameter-values). Summary of categories:

| Category | Example builtins | Availability |
|----------|-----------------|--------------|
| **Session** | `meeting_directory`, `meeting_transcript`, `meeting_details`, `export_directory`, `app_name` | Requires a loaded recording |
| **Meeting Date** | `meeting_date`, `meeting_date_year_month`, `meeting_date_year`, `meeting_date_month`, `meeting_date_month_name`, `meeting_date_month_short` | Requires a Date/Time value |
| **Meeting Details** | `meeting_name`, `meeting_datetime` | Requires Meeting Details fields |
| **Current Date** | `current_date`, `current_date_year_month`, `current_date_year`, `current_date_month`, `current_date_month_name`, `current_date_month_short` | Always available |
| **System** | `home_directory`, `user_name`, `tools_directory`, `tool_directory` | Always available |
| **Environment** | `env:VARIABLE_NAME` | Set if the env var exists |

### Managing Tools

- **Tools → Import Tools...** — Download tools from the GitHub repository
- **Tools → Edit Tool Configuration...** — Edit a tool's `tool.json` in the JSON editor
- **Tools → Edit Tool Data Files...** — Edit a tool's data files (e.g. corrections dictionary)
- **Tools → Open Tools Folder** — Open the tools directory in Finder
- **Tools → Refresh Tools** — Rescan the tools directory

### Streaming Output

For long-running tools (e.g. AI/LLM calls via Cortex), set `"streaming": true` to see output in real-time instead of waiting for the process to complete. The `cortex_json` parser translates Cortex CLI's JSON streaming format into human-readable status lines.

If no output is received for `idle_warning_seconds`, the status bar shows a warning. After `idle_kill_seconds` the tool is auto-cancelled.

## Google Calendar Integration (Optional)

Transcript Recorder can optionally integrate with Google Calendar to populate meeting details (date/time, name, attendees, description) from your calendar events. When configured, a calendar button appears in the Meeting Details button bar — click it to browse events and select one to fill in the meeting fields. Events are pre-fetched in the background on launch so the dialog opens instantly.

### Features

- **Background pre-fetch**: Events are fetched automatically on launch (if previously signed in), so the calendar dialog opens without network delay
- **Event picker dialog**: Shows events with time and name, a clickable date header with calendar date picker, "Last refreshed" status, refresh button, and filter toggles for all-day / declined events
- **Date picker**: Click the date in the dialog header to open a calendar widget and browse events for any day. When opened from a history session, the dialog defaults to that meeting's date
- **Filter conference info**: A toggle at the bottom of the dialog controls whether Zoom/Teams/WebEx boilerplate is stripped from the meeting notes — disable it if the filtering is removing information you want to keep
- **Smart overwrite**: Only prompts to overwrite when meaningful meeting details (name or notes) already exist; skips the prompt if only the date/time is populated
- **Attendee list**: Extracts attendee names and emails from the calendar event for inclusion in meeting notes
- **Clean descriptions**: Strips conferencing boilerplate (join links, meeting IDs, passcodes, phone dial-in blocks) from the event body by default

### Setup

1. **Obtain a Google OAuth client secret**:
   - Create a project at [Google Cloud Console](https://console.cloud.google.com/)
   - Enable the **Google Calendar API**
   - Create an **OAuth 2.0 Client ID** (Desktop application type)
   - Download the `client_secret.json` file
   - Alternatively, use a client secret file provided by your administrator

2. **Configure in the app**:
   - Go to **Integrations > Google Calendar > Configuration**
   - Check **Enable Google Calendar integration**
   - Browse to your `client_secret.json` file
   - Click **Save** — the file is automatically copied to application storage so you can delete the original

3. **Sign in**: The first time you click the calendar button, a browser window will open for Google sign-in. After granting permission, the token is saved locally and subsequent uses will not require re-authentication.

> The Google API libraries are bundled with the app. If running from source, install them with `pip install google-auth google-auth-oauthlib google-api-python-client`.

### Usage

1. Click the **calendar button** in the Meeting Details button bar — the events dialog opens instantly with pre-fetched events
2. Browse events (toggle "Show all-day events" or "Show declined" to see more)
3. Click the **date** in the dialog header to open the date picker and view events for a different day
4. Select an event and click **Select** (or double-click) to populate the meeting details
   - If meaningful meeting details (name or notes) already exist, you are prompted to confirm overwrite
   - The full Google Calendar event is also saved as `event.json` in the recording folder
5. Use the **refresh** button in the dialog header to re-fetch events from Google
6. Toggle **Filter conference info** at the bottom to include or exclude Zoom/Teams/WebEx join links and boilerplate from the notes

> The calendar integration is entirely optional. The source dropdown remains enabled regardless of calendar configuration, so ad-hoc meetings can always be transcribed normally. The calendar menu is under **Integrations > Google Calendar**.

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
    "default_source": "",
    "skipped_update_version": ""
  },
  "google_calendar": {
    "enabled": false,
    "client_secret_path": ""
  }
}
```

| Setting | Description |
|---------|-------------|
| `logging.level` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`, or `NONE` |
| `logging.log_to_file` | Write logs to a rotating file |
| `logging.log_file_name` | Log filename inside the `.logs` directory |
| `client_settings.export_directory` | Where recordings, sources, and tools are stored |
| `client_settings.default_source` | Source key selected on startup (e.g. `zoom`, `manual`) |
| `client_settings.skipped_update_version` | Version string the user chose to skip (e.g. `1.5.0`); cleared on download |
| `google_calendar.enabled` | Enable/disable the Google Calendar integration |
| `google_calendar.client_secret_path` | Path to your Google OAuth `client_secret.json` file |

You can change the log level from **Maintenance → Log Level** without editing the file. Use **Maintenance → Change Export Directory...** to move your export location. Use **Calendar → Setup Google Calendar** to set up Google Calendar integration.

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

### Sources

| Menu Item | Description |
|-----------|-------------|
| **Import Sources...** | Download sources from the GitHub repository |
| **Edit Source...** | Open the visual Source Editor for an installed source |
| **Accessibility Inspector** | Interactive AX tree browser with step builder and test export |
| **Set Current as Default** | Save the selected source as the startup default |
| **Clear Default** | Remove the default source setting (falls back to Manual Recording) |
| **Open Sources Folder** | Open the sources directory in Finder |
| **Refresh Sources** | Rescan the sources directory for new or updated sources |

### Calendar

| Menu Item | Description |
|-----------|-------------|
| **Setup Google Calendar** | Set up Google Calendar integration (client secret path, enable/disable) |
| **Sign Out** | Remove the stored Google OAuth token to sign out |

### Maintenance

| Menu Item | Description |
|-----------|-------------|
| **Change Export Directory...** | Move the export location (recordings, sources, tools) |
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
| **WebEx** | Available | Download via Sources → Import Sources |
| **Slack** | Available | Download via Sources → Import Sources |

## Troubleshooting

### "Accessibility permission required"

See [Granting Accessibility Permissions](#granting-accessibility-permissions) above for detailed instructions with screenshots.

1. Open **System Settings** → **Privacy & Security** → **Accessibility**
2. Click the **+** button and add Transcript Recorder
3. Ensure the toggle is enabled
4. Restart the application

> This only applies to automated capture sources. Manual Recording does not require accessibility permissions.

### Transcript not capturing

- Ensure captions/transcripts are **enabled** in your meeting application
- Make sure the transcript **window is visible** (not minimized)
- Try clicking **"Capture"** to test manual capture
- Check the **log file** (View → Log File) for error details

> **Note:** Some Electron apps (Teams, Slack, etc.) lazily build their accessibility tree and may not expose sub-elements until prompted. Transcript Recorder automatically "pokes" each application before searching by setting `AXManualAccessibility` and reading the window tree. Check the log for `AX poke` entries to confirm this ran.

### Application not detected

- Verify the meeting app is **running**
- Check that the `command_paths` in the source match your installation
- Some apps (like Teams) may run from different paths depending on how they were installed
- On macOS, some apps use **code-sign clones** that run from a temporary path (e.g. `/private/var/folders/...`) instead of `/Applications/`. If `command_paths` don't match, add `app_names` with the process name (visible in the **Accessibility Inspector** process list)
- Use **Sources → Edit Source...** to update the command paths or app names

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

### Utility Scripts

The `scripts/` folder contains maintenance and migration utilities:

| Script | Description |
|--------|-------------|
| `backfill_calendar_events.py` | Match existing recordings to Google Calendar events and enrich them with event data, meeting details, and corrected timestamps. Supports `--dry-run` for preview. |
| `backfill_attendees_frontmatter.py` | Backfill attendees from `meeting_details.txt` into Obsidian summary frontmatter. Writes `attendees` (wikilinks) and `attendee_emails` (plain emails) as separate YAML lists. Strips org-code bracket suffixes and filters conference room entries. Supports `--dry-run`. |
| `migrate_attendees_split.py` | One-time migration to convert the old combined `"[[Name]] (email)"` attendee format into the split `attendees` + `attendee_emails` format. |
| `migrate_recordings.py` | Migrate old-format recordings into the `YYYY/MM` directory structure |
| `batch_clean_and_summarize.sh` | Walk a directory tree, find recording folders, and run tools on each. Supports per-tool flags (`--clean`, `--summarize`, `--tag`, `--all`), `--dry-run`, `--force`, `--min-bytes`, and vivun tagger options (`--tag-date`, `--tag-se-name`). Defaults to `--clean --summarize` when no tool flags are given. |
| `changelog-commit.py` | Commit helper for the Cursor changelog. Lists pending change entries, lets you commit them individually or in groups, and tracks committed entries with their git hashes. Run with no args to see pending changes, `commit` to interactively select entries, `log` to see committed history, or `show <id>` for full details. |

```bash
# Preview what the calendar backfill would do
.venv/bin/python scripts/backfill_calendar_events.py --dry-run --verbose

# Run the backfill for real
.venv/bin/python scripts/backfill_calendar_events.py --verbose

# Backfill attendees into Obsidian summaries
.venv/bin/python scripts/backfill_attendees_frontmatter.py --dry-run --verbose
.venv/bin/python scripts/backfill_attendees_frontmatter.py --verbose
```

### Building the App Bundle

```bash
# Local source build (uses SourceBuild bundle ID to avoid permission conflicts)
./scripts/build_local.sh

# Build, auto-sign, and auto-launch (no prompts)
./scripts/build_local.sh --sign

# Build with interactive launch loop (re-launch without rebuilding)
./scripts/build_local.sh --loop

# Build, auto-sign, auto-launch, and keep the launch loop open
./scripts/build_local.sh --sign --loop

# Full clean rebuild (prompts for SourceBuild or Release)
./scripts/full_rebuild_local.sh

# Quick release rebuild (reuses existing .venv from full_rebuild_local.sh)
./scripts/build_release_local.sh
```

#### Build Types

`full_rebuild_local.sh` prompts you to choose a build type:

| Type | What it produces | When to use |
|------|-----------------|-------------|
| **SourceBuild** | `Transcript Recorder SourceBuild.app` with a separate bundle ID | Day-to-day development — won't conflict with your installed release copy |
| **Release** | Signed `.app` + signed `.dmg` with optional notarization | Validating the full release pipeline locally before pushing a tag |

The **Release** build mirrors the GitHub Actions workflow exactly: build, sign .app, create DMG, sign DMG, and optionally notarize via Apple's notary service.

#### Notarization Prerequisites

To notarize locally, store your Apple credentials in the Keychain once:

```bash
xcrun notarytool store-credentials "TranscriptRecorder" \
  --apple-id "your-apple-id@example.com" \
  --team-id "YOUR_TEAM_ID" \
  --password "<app-specific-password>"
```

Generate an app-specific password at [appleid.apple.com](https://appleid.apple.com) under Sign-In and Security.

### Bundle Manifest

The `bundle.json` file at the repo root controls which sources and tools are shipped inside the built `.app`:

```json
{
  "sources": ["zoom", "msteams"],
  "tools": ["clean_transcript"]
}
```

Only explicitly listed items are included in the app bundle. Other sources and tools in the repo (e.g. `slack`, `webex`, `summarize_meeting_coco`, `vivun_meeting_frontmatter_coco`) remain available for download via the Import menus but are not shipped with the app.

## License

MIT License - See LICENSE file for details.

## Acknowledgments

- Built with [PyQt6](https://www.riverbankcomputing.com/software/pyqt/)
- Uses [pyobjc](https://pyobjc.readthedocs.io/) for macOS Accessibility API access
- App icon generated with [Icon Kitchen](https://icon.kitchen/) by Roman Nurik
- UI icons from [Lucide](https://lucide.dev/) (ISC License)
