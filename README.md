# Transcript Recorder

A macOS application that captures meeting transcripts and live captions using the macOS Accessibility API. Designed for users who want to save and review meeting transcripts from popular video conferencing applications.

## Features

- **Multi-Application Support**: Works with Zoom, Microsoft Teams, WebEx, and Slack
- **Real-Time Capture**: Automatically captures transcript updates at configurable intervals
- **Smart Merging**: Intelligently merges transcript snippets to avoid duplicates
- **Native macOS UI**: Modern PyQt6 interface with light/dark mode support
- **Meeting Details**: Add meeting name, notes, and timestamps to your recordings
- **Auto-Updates**: Check for and install updates directly from the app
- **Configurable**: JSON-based configuration for each meeting application

## Requirements

- **macOS 12.0 (Monterey)** or later
- **Python 3.11+** (for running from source)
- **Accessibility Permissions**: The app requires accessibility access to read transcript content

## Installation

### From Release (Recommended)

1. Download the latest `.dmg` file from [Releases](../../releases)
2. Open the DMG and drag "Transcript Recorder" to your Applications folder
3. On first launch, grant Accessibility permissions when prompted

### From Source

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/tr_v3.git
cd tr_v3

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the application
python gui_app.py
```

### Building the App Bundle

```bash
# Install py2app
pip install py2app

# Build the application
python setup_py2app.py py2app

# The app will be in dist/Transcript Recorder.app
```

## Usage

### Quick Start

1. **Launch** Transcript Recorder
2. **Grant Accessibility Permissions** when prompted (System Settings → Privacy & Security → Accessibility)
3. **Select** your meeting application from the dropdown
4. **Click "New Recording"** to start a new session
5. **Join your meeting** and enable captions/transcripts in the meeting app
6. **Click "Capture Now"** for manual capture, or **"Start Auto Capture"** for continuous recording

### Recording Workflow

1. **New Recording**: Creates a new recording session with a timestamped folder
2. **Capture Now**: Takes a single snapshot of the current transcript
3. **Start Auto Capture**: Continuously captures at the configured interval (default: 30 seconds)
4. **Meeting Details**: Add a meeting name, notes, and adjust the date/time

### Output Files

Recordings are saved to `~/Documents/transcriptrecorder/recordings/`:

```
recordings/
└── recording_20240115_143022_Zoom/
    ├── meeting_transcript.txt      # Merged transcript
    ├── meeting_details.txt         # Meeting metadata
    └── .snapshots/                 # Individual capture snapshots
        ├── snapshot_001.txt
        ├── snapshot_002.txt
        └── snapshots_index.json
```

## Configuration

The application is configured via `config.json` located at `~/Documents/transcriptrecorder/config.json`.

### Logging Settings

```json
{
  "logging": {
    "level": "INFO",           // DEBUG, INFO, WARNING, ERROR, CRITICAL
    "log_to_file": true,       // Write logs to file
    "log_file_name": "tr_client.log"
  }
}
```

### Application Settings

Each meeting application has its own configuration block:

```json
{
  "application_settings": {
    "zoom": {
      "display_name": "Zoom",
      "command_paths": ["/Applications/zoom.us.app/Contents/MacOS/zoom.us"],
      "rules_to_find_transcript_table": [...],
      "monitor_interval_seconds": 30
    }
  }
}
```

### Configuration Options

| Option | Description |
|--------|-------------|
| `display_name` | Name shown in the application dropdown |
| `command_paths` | Paths to detect if the application is running |
| `rules_to_find_transcript_table` | Rules to locate the transcript UI element |
| `traversal_mode` | `bfs` (breadth-first) or `dfs` (depth-first) search |
| `traversal_roles_to_skip` | Accessibility roles to skip during traversal |
| `serialization_text_element_roles` | Map of roles to attributes for text extraction |
| `serialization_export_depth` | How deep to traverse for text content |
| `monitor_interval_seconds` | Default capture interval |
| `exclude_pattern` | Regex pattern to filter out unwanted text |

### Adding a New Application

To add support for a new meeting application:

1. Open the config editor (View → Edit Configuration or `Cmd+Shift+,`)
2. Add a new entry under `application_settings`
3. Use macOS Accessibility Inspector to identify:
   - The application's command path
   - UI element roles and attributes for the transcript
4. Define rules to locate the transcript element
5. Save and reload configuration

## Supported Applications

| Application | Status | Notes |
|-------------|--------|-------|
| **Zoom** | ✅ Supported | Works with transcript window and in-meeting captions |
| **Microsoft Teams** | ✅ Supported | Works with Live Captions feature |
| **WebEx** | ✅ Supported | Works with Captions window |
| **Slack** | ✅ Supported | Works with Huddle transcripts |

## Menu Options

### File Menu
- **New Recording** (`Cmd+N`): Start a new recording session
- **Reset** (`Cmd+R`): Reset the current session
- **Open Export Folder** (`Cmd+O`): Open the recordings folder

### View Menu
- **Appearance**: Switch between Light, Dark, or System theme
- **Log File** (`Cmd+L`): View application logs
- **Edit Configuration** (`Cmd+Shift+,`): Edit the config file

### Maintenance Menu
- **Reload Configuration**: Reload config without restarting
- **Clear Log File**: Clear the log file
- **Clear All Snapshots**: Remove snapshot folders from all recordings

### Help Menu
- **About**: Version and app information
- **Check Permissions**: Verify accessibility permissions
- **Check for Updates**: Check for new versions on GitHub

## Troubleshooting

### "Accessibility permission required"

1. Open **System Settings** → **Privacy & Security** → **Accessibility**
2. Click the **+** button and add Transcript Recorder
3. Ensure the checkbox is enabled
4. Restart the application

### Transcript not capturing

- Ensure captions/transcripts are **enabled** in your meeting application
- Make sure the transcript **window is visible** (not minimized)
- Try clicking **"Capture Now"** to test manual capture
- Check the **log file** (View → Log File) for error details

### Application not detected

- Verify the meeting app is **running**
- Check that the `command_paths` in config.json match your installation
- Some apps (like Teams) may run from different paths depending on how they were installed

## Development

### Project Structure

```
tr_v3/
├── gui_app.py              # Main GUI application
├── transcript_recorder.py  # Core recording logic
├── transcript_utils.py     # Transcript merging utilities
├── version.py              # Version information
├── config.json             # Default configuration
├── setup_py2app.py         # py2app build script
├── bump_version.py         # Version management script
├── requirements.txt        # Python dependencies
└── .github/
    └── workflows/
        └── build-release.yml  # GitHub Actions workflow
```

### Running Tests

```bash
# Run the TUI version (for debugging)
python tui_app.py

# Run the GUI version
python gui_app.py
```

### Creating a Release

See [RELEASE.md](RELEASE.md) for detailed release instructions.

```bash
# Bump version
python bump_version.py patch

# Commit and tag
git add version.py
git commit -m "Bump version to X.Y.Z"
git tag vX.Y.Z
git push origin main --tags
```

## License

MIT License - See LICENSE file for details.

## Acknowledgments

- Built with [PyQt6](https://www.riverbankcomputing.com/software/pyqt/)
- Uses [pyobjc](https://pyobjc.readthedocs.io/) for macOS Accessibility API access
