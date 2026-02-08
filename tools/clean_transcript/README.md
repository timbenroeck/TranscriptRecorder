# Clean Transcript

First-pass cleanup of meeting transcripts. Removes filler words, `(Unverified)` speaker tags, stuttered/repeated words, and applies terminology corrections using a configurable dictionary.

By default, the original `meeting_transcript.txt` is backed up to a `.backup/` folder in the same directory, and the cleaned output overwrites the original file. This ensures downstream tools (e.g. Summarize Meeting) work seamlessly with the cleaned transcript without needing to know a different filename.

## What It Does

| Cleanup | Example |
| --- | --- |
| Filler words | `uh, um, hmm, Mhm, Mm-hmm` and variants are removed |
| `(Unverified)` tags | `Tim Benroeck (Unverified)` becomes `Tim Benroeck` |
| Combined tags | `Tim Benroeck (Snowflake) (Unverified)` becomes `Tim Benroeck (Snowflake)` |
| Stuttered words | `I I think` → `I think`, `like, like` → `like`, `claud. claud` → `claud` |
| 3+ repetitions | `I I I think` → `I think` (always collapsed, no exceptions) |
| Terminology corrections | `data bricks` becomes `Databricks` (case-insensitive match, correct-case output) |
| Whitespace cleanup | Double spaces, orphaned commas, and empty lines left by removals are normalized |

## Requirements

* Python 3.6+
* No external dependencies (uses only standard library modules: `re`, `json`, `argparse`, `shutil`)

## Supported Transcript Formats

The tool handles all three transcript formats produced by Transcript Recorder:

| Format | Source | Structure |
| --- | --- | --- |
| Teams| Teams in-browser capture | Speaker name on its own line, dialogue on the next line |
| Zoom | Zoom live transcript | Speaker name, timestamp, then dialogue lines |

## Parameters

| Flag | Description | Default |
| --- | --- | --- |
| `-t`, `--transcript` | Path to the `meeting_transcript.txt` file | *required* |
| `-c`, `--corrections` | Path to a `corrections.json` file | Auto-loads `data/corrections.json` next to the script |
| `-d`, `--dry-run` | Print cleaned output to stdout without writing any file | `false` |
| `--no-backup` | Skip creating a backup before overwriting | `false` (backup is created by default) |
| `-s`, `--stats` | Print cleanup statistics to stderr | Shown by default unless `--quiet` |
| `-q`, `--quiet` | Suppress all informational output | `false` |

## Usage

### Clean transcript (default — backup + overwrite)

```bash
python3 clean_transcript.py -t /path/to/meeting_transcript.txt
```

This backs up the original to `.backup/meeting_transcript.txt` in the same directory, then overwrites the original with the cleaned version.

### Preview changes (dry-run)

```bash
python3 clean_transcript.py -t /path/to/meeting_transcript.txt --dry-run
```

Prints cleaned output to stdout without modifying any files.

### Clean without creating a backup

```bash
python3 clean_transcript.py -t /path/to/meeting_transcript.txt --no-backup
```

Overwrites the original file directly without creating a backup.

### Use a custom corrections file

```bash
python3 clean_transcript.py -t /path/to/meeting_transcript.txt --corrections /path/to/corrections.json
```

### Shell wrapper

A convenience shell script is also provided:

```bash
./clean_transcript.sh -t /path/to/meeting_transcript.txt
./clean_transcript.sh -t /path/to/meeting_transcript.txt --no-backup
./clean_transcript.sh -t /path/to/meeting_transcript.txt -c /path/to/corrections.json
```

## Backup Behavior

When the tool runs (without `--dry-run` or `--no-backup`), it creates a `.backup/` folder inside the recording directory and copies the original transcript there before overwriting:

```
recording_2025-05-22_13-57/
├── meeting_transcript.txt          ← cleaned version (overwrites original)
├── meeting_details.txt
└── .backup/
    └── meeting_transcript.txt      ← original pre-cleanup copy
```

The `.backup/` folder uses a dot-prefix so it stays hidden in most file browsers. If you run the tool multiple times, the backup is overwritten with whatever the file contained at the time of the most recent run.

## Stutter Detection

The tool catches repeated words separated by spaces, commas, periods, or ellipses — covering common transcription artifacts like `like, like` and `word. word` in addition to simple `word word` doubles.

**Allowlisted doubles:** The words "that that" and "had had" are preserved when doubled, since they are grammatically valid constructions (e.g. "I knew that that would happen", "She had had enough"). Three or more repetitions of *any* word (including allowlisted ones) are always collapsed — there's no legitimate use of `that that that`.

## Corrections Dictionary

The `data/corrections.json` file maps the **correct term** (key) to a list of **incorrect variants** (values). Matching is case-insensitive with word-boundary awareness; the replacement uses the exact casing of the key.

```json
{
    "Databricks": ["data bricks", "databricks", "DataBricks"],
    "Power BI": ["powerbi", "power bi", "powerby"],
    "PySpark": ["pyspark", "pie spark"],
    "Cosmos DB": ["cosmosdb", "cosmos db", "cosmos database"]
}
```

To add new corrections, simply add entries to `data/corrections.json`. No code changes needed. The corrections dictionary can also be edited from the GUI via **Tools > Edit Tool Data Files**.

### Tips for corrections entries

- **Longer variants are matched first** to avoid partial replacements (e.g., `"cosmos database"` is checked before `"cosmos"`).
- **Word boundaries are enforced**, so a variant like `"ad"` for `"Active Directory"` will only match the standalone word "ad", not "add" or "bad".
- **Case-insensitive matching** means `"databricks"`, `"DataBricks"`, and `"DATABRICKS"` all match and get replaced with the key's casing.

## Cleanup Report

When run without `--quiet`, the tool prints a report to stderr:

```
==================================================
  Transcript Cleanup Report
==================================================
  File: meeting_transcript.txt
  Lines: 1221 -> 1219 (2 removed)
  Characters: 62312 -> 58134 (4178 removed)
  (Unverified) tags removed: 289
  Filler words cleaned: 5
  Stutters cleaned: 102
  Corrections applied: 23 rules loaded
==================================================
```

## Configuration

**To customize defaults when run from the app, edit `tool.json`** — do not modify the Python script directly.

The `tool.json` file defines the tool metadata and parameter defaults for integration with Transcript Recorder's tool runner.
