# Meeting Tools — Developer Guide

Transcript Recorder ships with a plugin-style **Meeting Tools** system that lets you run custom scripts against your recordings directly from the GUI. Tools are discovered automatically at startup — no app changes needed to add one.

This guide covers everything you need to create, configure, and troubleshoot tools.

---

## Table of Contents

- [Overview](#overview)
- [Directory Structure](#directory-structure)
- [tool.json Reference](#tooljson-reference)
  - [Top-Level Fields](#top-level-fields)
  - [Parameter Fields](#parameter-fields)
  - [Built-in Parameter Values](#built-in-parameter-values)
  - [Data Files](#data-files)
  - [Refresh on Complete](#refresh-on-complete)
  - [Streaming Fields](#streaming-fields)
- [Script Execution](#script-execution)
  - [Interpreter Selection](#interpreter-selection)
  - [Working Directory](#working-directory)
  - [Environment](#environment)
  - [Blocking vs Streaming Mode](#blocking-vs-streaming-mode)
- [Streaming Output](#streaming-output)
  - [How It Works](#how-it-works)
  - [Built-in Parsers](#built-in-parsers)
  - [Idle Timeout and Auto-Cancel](#idle-timeout-and-auto-cancel)
- [Creating a New Tool](#creating-a-new-tool)
  - [Step-by-Step Walkthrough](#step-by-step-walkthrough)
  - [Minimal Example](#minimal-example)
  - [Streaming Example (Cortex)](#streaming-example-cortex)
- [Bundled Tool: Summarize Meeting](#bundled-tool-summarize-meeting)
- [Bundled Tool: Clean Transcript](#bundled-tool-clean-transcript)
- [Troubleshooting](#troubleshooting)

---

## Overview

The **Meeting Tools** tab in the app provides:

- A **dropdown** listing all discovered tools
- An **editable parameters table** with values pre-filled from defaults or the app's current state
- A **command preview** showing exactly what will be executed
- A **Run** button that executes the script in the background
- A **Cancel** button to terminate a running tool
- An **output area** that displays stdout/stderr (real-time for streaming tools, on-completion otherwise)
- An **elapsed timer** with idle detection for streaming tools

Tools are loaded from the `tools/` directory inside your export folder (by default `~/Documents/transcriptrecorder/tools/`). The app scans every immediate sub-directory for a `tool.json` file (falling back to the first `.json` file alphabetically), validates that the referenced script exists, and populates the dropdown. Reloading the configuration (Maintenance > Reload Configuration) re-scans the tools directory.

---

## Directory Structure

Each tool lives in its own sub-folder:

```
~/Documents/transcriptrecorder/
└── tools/
    └── my_tool/
        ├── tool.json           # Required — tool metadata and parameters
        ├── my_tool.sh          # Required — the script referenced by tool.json
        ├── data/               # Best practice — keep data files in a data/ subfolder
        │   └── corrections.json
        └── README.md           # Optional — documentation
```

You can include any other supporting files in the sub-folder (config files, skill definitions, templates, etc.). Only the JSON + script pair are required. Files declared in the `data_files` section of `tool.json` will be editable from the GUI.

> **Best practice:** Place data files (corrections dictionaries, attendee lists, etc.) in a `data/` subfolder rather than the tool's root directory. The tool scanner looks for `tool.json` first, but falls back to the first `.json` file alphabetically — keeping non-definition JSON files in a subfolder avoids any ambiguity.

---

## tool.json Reference

### Top-Level Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `display_name` | string | **Yes** | — | Name shown in the tool dropdown |
| `description` | string | No | — | Description shown below the dropdown when the tool is selected |
| `script` | string | **Yes** | — | Filename of the script in the same sub-folder |
| `parameters` | array | No | `[]` | Array of parameter definitions (see below) |
| `data_files` | array | No | `[]` | Array of editable data file definitions (see [Data Files](#data-files)) |
| `streaming` | bool | No | `false` | Enable streaming output mode (real-time line-by-line display) |
| `stream_parser` | string | No | `"raw"` | Which built-in parser to use for streaming output |
| `idle_warning_seconds` | int | No | `30` | Seconds of no output before showing a warning in the status bar |
| `idle_kill_seconds` | int | No | `120` | Seconds of no output before auto-cancelling the tool |
| `refresh_on_complete` | array | No | `[]` | UI elements to reload from disk after the tool finishes successfully (see [Refresh on Complete](#refresh-on-complete)) |

### Parameter Fields

Each entry in the `parameters` array describes one command-line argument:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `flag` | string | **Yes** | Command-line flag passed to the script (e.g. `-m`, `--output`) |
| `label` | string | No | Human-readable name shown in the Parameters table |
| `type` | string | No | Parameter type. Use `"boolean"` for flag-only switches (see below) |
| `builtin` | string | No | Auto-fills the value from the app's current state (see below) |
| `default` | string | No | Default value used when `builtin` is not set or not available |
| `required` | bool | No | If `true`, the tool refuses to run when this value is empty |

Parameters appear in an **editable table** in the app. Values pre-filled from `builtin` mappings or `default` values can be modified before clicking Run.

**Boolean parameters:** When `"type": "boolean"` is set, the parameter is treated as a flag-only switch. If the value is truthy (`true`, `1`, `yes` — case-insensitive), the flag is included on the command line with no value (e.g. `--in-place`). If the value is falsy (`false`, `0`, empty), the flag is omitted entirely. This matches the behavior of argparse `store_true` flags and similar CLI conventions.

**Resolution order:** If a parameter has a `builtin` key and the app can resolve it (e.g. a recording is loaded), the built-in value takes precedence. Otherwise the `default` value is used. If neither is available, the cell shows a placeholder.

### Built-in Parameter Values

Parameters with a `"builtin"` key are automatically resolved at run-time from the app's current state. Some builtins require an active recording session; others are always available.

#### Session Builtins (require a loaded recording)

| `builtin` value | Resolves to |
|-----------------|-------------|
| `meeting_directory` | Full path to the current recording folder |
| `meeting_transcript` | Full path to `meeting_transcript.txt` in the recording folder |
| `meeting_details` | Full path to `meeting_details.txt` in the recording folder |
| `export_directory` | Base export directory (e.g. `~/Documents/transcriptrecorder`) |
| `app_name` | Key of the selected meeting application (e.g. `zoom`, `teams`) |

#### Meeting Date Builtins (parsed from the Date/Time field)

These are derived from the **Date/Time** field in the Meeting Details panel. They are available whenever the field contains a parseable date.

| `builtin` value | Format | Example |
|-----------------|--------|---------|
| `meeting_date` | `yyyy-mm-dd` | `2026-02-11` |
| `meeting_date_year_month` | `yyyy-mm` | `2026-02` |
| `meeting_date_year` | `yyyy` | `2026` |
| `meeting_date_month` | `mm` | `02` |
| `meeting_date_month_name` | Full month name | `February` |
| `meeting_date_month_short` | 3-character abbreviation | `Feb` |

#### Meeting Details Builtins (from GUI fields)

| `builtin` value | Resolves to |
|-----------------|-------------|
| `meeting_name` | Text from the **Meeting Name** field |
| `meeting_datetime` | Raw text from the **Date/Time** field (as displayed in the GUI) |

#### Current Date Builtins (always available)

These use the system clock at the moment the tool parameters are populated — no recording required.

| `builtin` value | Format | Example |
|-----------------|--------|---------|
| `current_date` | `yyyy-mm-dd` | `2026-02-11` |
| `current_date_year_month` | `yyyy-mm` | `2026-02` |
| `current_date_year` | `yyyy` | `2026` |
| `current_date_month` | `mm` | `02` |
| `current_date_month_name` | Full month name | `February` |
| `current_date_month_short` | 3-character abbreviation | `Feb` |

#### System Builtins (always available)

| `builtin` value | Resolves to |
|-----------------|-------------|
| `home_directory` | User's home directory (e.g. `/Users/tbenroeck`) |
| `user_name` | System username (e.g. `tbenroeck`) |
| `tools_directory` | Base tools directory (e.g. `~/Documents/transcriptrecorder/tools`) |
| `tool_directory` | The selected tool's own sub-folder |

#### Environment Variable Builtins (`env:`)

Use the `env:` prefix to resolve a parameter from an environment variable. This lets tool authors reference user-specific configuration without hardcoding values or requiring app changes.

**Syntax:** `"builtin": "env:VARIABLE_NAME"`

```json
{
  "flag": "-w",
  "label": "Snowflake Warehouse",
  "builtin": "env:SNOWFLAKE_WAREHOUSE",
  "default": "MY_WAREHOUSE"
}
```

If the environment variable is set, its value is used. If it is not set, the `default` value is used as a fallback (same behavior as other builtins).

Common use cases:
- `env:USER` — system username
- `env:SNOWFLAKE_WAREHOUSE` — Snowflake warehouse from shell profile
- `env:CORTEX_CONNECTION` — default Cortex connection name
- `env:OBSIDIAN_VAULT` — user's Obsidian vault path
- Any custom variable exported in the user's shell profile

### Data Files

Tools can declare editable data files that users can modify directly from the GUI without editing raw JSON. When a tool with `data_files` is selected in the Meeting Tools tab, a collapsible **Data Files** section appears with an **Edit** button for each file. Data files are also accessible from the **Tools > Edit Tool Data Files...** menu.

Each entry in the `data_files` array describes one editable file:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | string | **Yes** | Filename of the data file in the tool's sub-folder |
| `label` | string | No | Human-readable name shown in the GUI (defaults to the filename) |
| `description` | string | No | Tooltip text explaining the file's purpose |
| `editor` | string | **Yes** | Editor type to use (see below) |

#### Editor Types

| `editor` value | Data shape | UI | Use cases |
|----------------|------------|-----|-----------|
| `key_array_grid` | `{ "Key": ["val1", "val2"] }` | Two-column datagrid — Key + comma-separated Values — with Add/Delete Row buttons | Corrections dictionaries, synonym lists, tag mappings |
| `key_value_grid` | `{ "key": "value" }` | Two-column datagrid — Key + Value — with Add/Delete Row buttons | Simple settings, environment variables, name mappings |
| `string_list` | `["item1", "item2"]` | Single-column list with Add/Delete/Move Up/Move Down buttons | Exclusion lists, stop words, allowed names |

All editor types read and write standard JSON files. Changes are saved with pretty-printed formatting.

#### Example

```json
{
  "display_name": "Clean Transcript",
  "script": "clean_transcript.py",
  "parameters": [ ... ],
  "data_files": [
    {
      "file": "data/corrections.json",
      "label": "Corrections Dictionary",
      "description": "Map correct terms to their common mistranscriptions.",
      "editor": "key_array_grid"
    }
  ]
}
```

With this configuration, when the user selects **Clean Transcript** in the Meeting Tools tab, a **Data Files** section appears below Parameters:

```
▶ Data Files
    Corrections Dictionary                    [Edit]
```

Clicking **Edit** opens a datagrid editor where users can add, modify, and delete entries. For the `key_array_grid` editor, the datagrid shows the key (correct term) in the first column and the array values as a comma-separated string in the second column. Both columns are editable inline.

### Refresh on Complete

Tools can request that the app reload specific UI elements from disk after a successful run (exit code 0). This is useful for tools that modify files in the recording directory — for example, a transcript cleanup tool that overwrites `meeting_transcript.txt` can have the cleaned version automatically appear in the Transcript tab.

Add a `"refresh_on_complete"` array to the top level of `tool.json`:

```json
{
  "display_name": "Clean Transcript",
  "script": "clean_transcript.py",
  "refresh_on_complete": ["meeting_transcript"],
  "parameters": [ ... ]
}
```

#### Supported Targets

| Target | What it reloads |
|--------|-----------------|
| `"meeting_transcript"` | Reloads `meeting_transcript.txt` from disk into the Transcript tab. Clears any unsaved in-memory edits. |
| `"meeting_details"` | Reloads `meeting_details.txt` from disk into the Meeting Details fields (name, date/time, notes). |

Multiple targets can be specified: `"refresh_on_complete": ["meeting_transcript", "meeting_details"]`.

The refresh only runs on success (exit code 0). If the tool is cancelled or fails, the UI is left unchanged. The status bar will indicate which elements were refreshed (e.g. "Tool completed: Clean Transcript — refreshed transcript").

### Streaming Fields

These fields only take effect when `"streaming": true` is set.

| Field | Default | Description |
|-------|---------|-------------|
| `stream_parser` | `"raw"` | Parser used to transform raw stdout lines into display text. Available: `"raw"`, `"cortex_json"` |
| `idle_warning_seconds` | `30` | After this many seconds of no stdout output, the status bar shows a warning like "Agent idle for 45s (auto-cancel in 45s)" |
| `idle_kill_seconds` | `120` | After this many seconds of no stdout output, the tool is automatically cancelled |

---

## Script Execution

### Interpreter Selection

The app selects an interpreter based on the script's file extension:

| Extension | Interpreter |
|-----------|-------------|
| `.sh` | The user's default shell (`$SHELL`, typically `/bin/zsh` on macOS) |
| `.bash` | `/bin/bash` |
| `.zsh` | `/bin/zsh` |
| `.py` | The Python interpreter running the app (`sys.executable`) |
| Other | Executed directly (the script's execute bit must be set) |

> **Note:** Since macOS Catalina (2019), the default shell is zsh. Using `.sh` with the user's default shell ensures that tools like `cortex` and other CLIs installed via the user's shell profile are available.

### Working Directory

The script's working directory (`cwd`) is set to the **tool's own sub-folder** — the directory containing `tool.json` and the script. This means relative paths in your script resolve from that directory, which is useful for referencing skill files, templates, or other supporting resources.

### Environment

On macOS, GUI applications inherit a minimal system PATH that often lacks user-specific directories (e.g. `~/.local/bin`, Homebrew paths). The tool runner resolves the user's full PATH by spawning an interactive login shell (`-l -i`) before running the script. This sources both `~/.zprofile` (login config) and `~/.zshrc` (interactive config), so tools like `cortex`, `python3`, and other user-installed CLIs are available without requiring full paths. Unique output markers are used to reliably extract the PATH even when shell frameworks (oh-my-zsh, starship, etc.) produce extra output during initialization.

The child process is spawned with:
- `stdin` closed (`/dev/null`) — prevents tools from hanging waiting for input
- `stdout` and `stderr` piped back to the app
- Its own process session — enables clean cancellation of the entire process tree

### Blocking vs Streaming Mode

| | Blocking (default) | Streaming (`"streaming": true`) |
|---|---|---|
| **How output is read** | All stdout/stderr is collected via `.communicate()` and displayed when the process exits | stdout is read line-by-line and displayed in real-time |
| **UI during execution** | Output area is blank until completion | Output appears incrementally as lines arrive |
| **Idle detection** | None — only the elapsed timer is shown | Active — warns after `idle_warning_seconds`, auto-cancels after `idle_kill_seconds` |
| **Best for** | Quick scripts that complete in seconds | Long-running AI/LLM tools that take minutes |

---

## Streaming Output

### How It Works

When `"streaming": true` is set in `tool.json`:

1. The app spawns the script and reads **stdout line-by-line** in real-time
2. Each line is passed through the configured **parser function** (e.g. `cortex_json`)
3. The parser returns display text (or `null` to skip the line)
4. Display text is immediately appended to the output area in the GUI
5. The app tracks the **timestamp of the last output line** for idle detection
6. When the process exits, stderr and a completion footer are appended

### Built-in Parsers

#### `raw` (default)

Passes every line through as-is with no transformation. Use this for scripts that output plain text.

#### `cortex_json`

Parses the JSON streaming format that Cortex CLI produces when stdout is piped (non-TTY). Extracts human-readable status from each JSON message:

| Cortex JSON content type | Display |
|--------------------------|---------|
| `"type": "text"` | The text content |
| `"type": "thinking"` | `[Thinking] first 120 chars...` |
| `"type": "tool_use", "name": "read"` | `[Reading] /path/to/file` |
| `"type": "tool_use", "name": "write"` | `[Writing] /path/to/file` |
| `"type": "tool_use", "name": "bash"` | `[Running] command...` |
| `"type": "tool_use", "name": "skill"` | `[Skill] skill_name` |
| Other tool_use | `[Tool: name]` |
| `"type": "tool_result"` | `  result: first 200 chars...` |
| Invalid JSON | Falls back to raw line |

Cortex automatically switches to JSON streaming when it detects its stdout is piped (not a terminal). No `--output-format` flag is needed in your shell script.

### Idle Timeout and Auto-Cancel

For streaming tools, the app monitors how long it has been since the last line of output:

- **Warning phase** (`idle_warning_seconds`): The status bar changes to show the idle time and a countdown to auto-cancel. Example: `Running tool... 2m 15s — agent idle for 45s (auto-cancel in 45s)`
- **Kill phase** (`idle_kill_seconds`): The tool is automatically cancelled. The entire process tree (script + all child processes) is terminated via `SIGTERM`, falling back to `SIGKILL` after 3 seconds.

These timeouts protect against tools that hang after completing their work (a known behavior with some CLI tools when their stdout is piped).

---

## Creating a New Tool

### Step-by-Step Walkthrough

1. **Create the sub-folder:**

   ```bash
   mkdir ~/Documents/transcriptrecorder/tools/my_tool
   ```

2. **Write your script** (e.g. `my_tool.sh`):

   ```bash
   #!/bin/zsh
   # my_tool.sh — example tool that processes a meeting recording

   MEETING_DIR=""
   while getopts "m:" opt; do
       case $opt in
           m) MEETING_DIR="$OPTARG" ;;
       esac
   done

   if [ -z "$MEETING_DIR" ]; then
       echo "Error: -m (meeting directory) is required"
       exit 1
   fi

   echo "Processing: $MEETING_DIR"
   # ... your logic here ...
   echo "Done."
   ```

3. **Create `tool.json`:**

   ```json
   {
     "display_name": "My Custom Tool",
     "description": "Does something useful with meeting recordings.",
     "script": "my_tool.sh",
     "parameters": [
       {
         "flag": "-m",
         "label": "Meeting Directory",
         "builtin": "meeting_directory",
         "required": true
       }
     ]
   }
   ```

4. **Optionally add a `README.md`** documenting the tool's purpose, requirements, and usage.

5. **Reload:** Go to Maintenance > Reload Configuration (or restart the app). The tool will appear in the Meeting Tools dropdown.

### Minimal Example

A tool with no parameters that just prints info about the recording:

```json
{
  "display_name": "Recording Info",
  "description": "Show file sizes and line counts for the current recording.",
  "script": "info.sh"
}
```

```bash
#!/bin/zsh
# info.sh — shows recording stats
echo "=== Recording Info ==="
wc -l "$1"/meeting_transcript.txt 2>/dev/null || echo "No transcript found."
wc -l "$1"/meeting_details.txt 2>/dev/null || echo "No details found."
ls -lh "$1"/ 2>/dev/null
```

### Streaming Example (Cortex)

For long-running AI tools that use Cortex CLI:

```json
{
  "display_name": "Summarize Meeting",
  "description": "Generate an AI-powered meeting summary using Cortex.",
  "script": "summarize_meeting.sh",
  "streaming": true,
  "stream_parser": "cortex_json",
  "idle_warning_seconds": 30,
  "idle_kill_seconds": 90,
  "parameters": [
    {
      "flag": "-m",
      "label": "Meeting Directory",
      "builtin": "meeting_directory",
      "required": true
    },
    {
      "flag": "-o",
      "label": "Output Directory",
      "default": "~/Documents/obsidian_vault/Meetings",
      "required": true
    }
  ]
}
```

With `"streaming": true` and `"stream_parser": "cortex_json"`, the output area will show real-time progress like:

```
[Skill] meeting-summarizer
[Reading] /path/to/meeting_details.txt
[Reading] /path/to/meeting_transcript.txt
[Thinking] The user wants me to summarize a meeting...
Let me create the output directories and save the files.
[Writing] /path/to/2025-05-27 Edwards Pre-Call Prep.md
[Writing] /path/to/.transcripts/2025-05-27 Edwards Pre-Call Prep.txt
```

---

## Bundled Tool: Summarize Meeting

Transcript Recorder includes a pre-built **Summarize Meeting** tool that generates AI-powered meeting summaries using [Snowflake Cortex CLI](https://docs.snowflake.com/en/user-guide/cortex-code/cortex-code-cli) and a meeting-summarizer skill.

### Requirements

- **Cortex CLI** installed and on your PATH
- A configured **Snowflake connection** (either the default or specified via the `-c` parameter)

### Parameters

| Flag | Label | Default | Description |
|------|-------|---------|-------------|
| `-m` | Meeting Directory | *(auto-filled)* | Path to the recording folder containing `meeting_details.txt` and `meeting_transcript.txt` |
| `-o` | Output Directory | `~/Documents/obsidian_vault/Meetings` | Base path where summaries are organized into date subfolders (e.g. `2025/05-May/`) |
| `-f` | First Name | `John` | First name for personalized summaries. Omit for a general summary. |
| `-l` | Last Name | `Smith` | Last name for personalized summaries. Omit for a general summary. |
| `-c` | Cortex Connection | `snowflake` | Snowflake connection name. Omit to use the default connection. |

### Output

The tool creates a markdown summary organized by meeting date, and may also create or update attendee CRM notes:

```
~/Documents/obsidian_vault/
├── Meetings/
│   └── 2025/
│       └── 05-May/
│           └── 2025-05-27 Edwards Pre-Call Prep.md       # Markdown summary
└── CRM/
    └── Joseph Cramer (joseph.cramer@snowflake.com).md    # Attendee CRM note
```

**CRM Notes:** When personal or relationship details are shared during a meeting (e.g., family, vacations, hobbies), the skill creates or updates lightweight notes in the `CRM/` folder at the vault root. These serve as a quick-reference cheat sheet before your next conversation with that person. Notes are only created when personal information is actually shared — not for every attendee. The person specified by First Name / Last Name is excluded.

### Customizing Defaults

Edit the `tool.json` file in the tool's directory to change default parameter values. For example, to set your own name and Cortex connection:

```json
{
  "flag": "-f",
  "label": "First Name",
  "default": "YourFirstName",
  "required": false
}
```

Defaults are pre-filled in the Parameters table but can be edited per-run.

---

## Bundled Tool: Clean Transcript

Transcript Recorder includes a **Clean Transcript** tool that performs a first-pass cleanup of `meeting_transcript.txt` files. It removes common transcription artifacts to produce a cleaner transcript for summarization or review.

By default, the original file is backed up to a `.backup/` folder in the recording directory, and the cleaned output overwrites the original `meeting_transcript.txt`. This ensures downstream tools (e.g. Summarize Meeting) work seamlessly with the cleaned transcript without needing to know a different filename.

The tool uses `refresh_on_complete` to automatically reload the cleaned transcript into the Transcript tab after a successful run, so the changes are immediately visible in the UI.

### What It Cleans

| Category | Examples |
|----------|----------|
| Filler words | `uh`, `um`, `umm`, `hmm`, `Mhm`, `Mm-hmm` and variants |
| `(Unverified)` tags | `Tim Benroeck (Unverified)` → `Tim Benroeck` |
| Stuttered/repeated words | `I I think` → `I think`, `like, like` → `like`, `claud. claud` → `claud` (preserves valid doubles like "that that" and "had had") |
| Terminology corrections | `data bricks` → `Databricks` (case-insensitive match, correctly-cased output) |
| Whitespace artifacts | Double spaces, orphaned punctuation, empty lines left by removals |

### Parameters

| Flag | Label | Default | Description |
|------|-------|---------|-------------|
| `-t` | Transcript File | *(auto-filled)* | Path to `meeting_transcript.txt` |
| `-c` | Corrections File | *(auto-loads from tool folder)* | Path to a custom `corrections.json` |
| `--no-backup` | Skip Backup | `false` | If set, skips creating a backup and overwrites the original directly |

### Backup Behavior

When the tool runs, it copies the original transcript to a `.backup/` folder inside the recording directory before overwriting:

```
recording_2025-05-22_13-57/
├── meeting_transcript.txt          ← cleaned version (overwrites original)
└── .backup/
    └── meeting_transcript.txt      ← original pre-cleanup copy
```

The `.backup/` folder uses a dot-prefix so it stays hidden in most file browsers. Use `--no-backup` to skip this step.

### Data Files

The tool includes a **Corrections Dictionary** (`data/corrections.json`) that can be edited from the GUI using the `key_array_grid` editor. The dictionary maps correct terms (keys) to lists of incorrect variants (values). Matching is case-insensitive with word-boundary awareness; the replacement uses the exact casing of the key.

Default entries include common transcription errors for technical terms like `Databricks`, `Power BI`, `PySpark`, `Cosmos DB`, `Iceberg`, and others. Users can add domain-specific corrections through the GUI editor.

### Supported Transcript Formats

The tool handles all transcript formats produced by Transcript Recorder:

- **Teams (browser)** — speaker name on its own line, dialogue on the next
- **Zoom** — speaker name, timestamp, then dialogue lines
- **Manual / Gemini** — `Speaker Name: dialogue text` on a single line

---

## Troubleshooting

### Tool not appearing in the dropdown

- Verify the sub-folder is directly inside `~/Documents/transcriptrecorder/tools/` (not nested deeper)
- Confirm the sub-folder contains a `tool.json` file with valid JSON (the scanner looks for `tool.json` first, then falls back to the first `.json` file alphabetically)
- If you have other `.json` files (corrections, config, etc.), move them into a `data/` subfolder so they aren't mistaken for the tool definition
- Check that `display_name` and `script` keys exist in the JSON
- Check that the script file referenced by `"script"` exists in the same directory
- Try Maintenance > Reload Configuration to re-scan
- Check the log file (View > Log File) for errors like `"invalid JSON"` or `"error loading"`

### Tool fails to run

- **"required parameter has no value"**: A required parameter is empty. Fill it in the Parameters table or start a recording session so built-in values can resolve.
- **"script not found"**: The script file referenced in `tool.json` does not exist. Check the filename and path.
- **Permission denied**: The script may not have its execute bit set. For `.sh`/`.py`/`.zsh` scripts this is handled automatically, but other extensions need `chmod +x`.

### Tool hangs or never completes

- **For non-streaming tools**: The output area stays blank until the process exits. If the tool takes a long time, consider switching to streaming mode.
- **For streaming tools**: Check the status bar for idle warnings. If the tool is idle for longer than `idle_kill_seconds`, it will be auto-cancelled.
- **stdin issues**: Some CLI tools (especially Node.js-based ones like Cortex) hang when stdin is an open pipe. The app sets `stdin` to `/dev/null` to prevent this, but if you run the script manually in a terminal, make sure to handle stdin appropriately.

### Cancel button not working

- The app kills the entire process tree (script + all child processes) when you click Cancel. If the cancel seems stuck, the processes may be in an unkillable state. Check Activity Monitor for orphaned processes.
- The app sends `SIGTERM` first, then `SIGKILL` after 3 seconds if the process doesn't exit.

### Streaming output shows raw JSON

- Make sure `"stream_parser": "cortex_json"` is set in your `tool.json`
- Verify `"streaming": true` is also set — without it, the blocking worker is used and there is no parsing

### Cortex works in terminal but not from the app

- The app resolves your shell's full PATH by spawning an interactive login shell. Check the log for PATH resolution warnings (search for `_get_user_env`).
- If you have PATH modifications in `~/.zshrc` or `~/.zprofile`, they should be picked up automatically. If you use a custom shell config that only runs in certain conditions, the app may not capture those paths.
- Verify your Snowflake connection config is accessible from the app's environment.
- Try running the exact command shown in the output area's "command:" line from your terminal to reproduce.
