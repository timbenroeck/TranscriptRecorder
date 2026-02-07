# Summarize Meeting

Generate an AI-powered meeting summary using Cortex and the meeting-summarizer skill.

## Requirements

* **[Cortex CLI](https://docs.snowflake.com/en/user-guide/cortex-code/cortex-code-cli)** must be installed and available on your PATH.
* The `meeting-summarizer` skill must be installed. For more information on how skills work, see **[Understanding Cortex Skills](https://docs.snowflake.com/en/user-guide/cortex-code/extensibility#extensibility-skills)**.
* A default Snowflake connection configuration must exist, or use the `-c` parameter to specify one.

## Parameters

| Flag | Description | Default |
| --- | --- | --- |
| `-m` | Meeting transcript directory (auto-filled by the app) | *required* |
| `-o` | Output directory for the summary |  |
| `-f` | First name for personalized summary |  |
| `-l` | Last name for personalized summary |  |
| `-c` | Cortex connection name (e.g. `snowflake`). If omitted, Cortex uses its default connection. |  |

## Configuration

**To customize defaults, edit the `tool.json` file — do not modify the shell script directly.**

The `tool.json` file defines the default values for each parameter. When the tool is run from the app, these defaults are pre-filled in the Parameters table and can be adjusted per-run. For example, to always use a specific Cortex connection, set the `default` value for the `-c` parameter in `tool.json`:

```json
{
  "flag": "-c",
  "label": "Cortex Connection",
  "default": "snowflake",
  "required": false
}
```

## Usage

The tool expects the meeting directory to contain both `meeting_details.txt` and `meeting_transcript.txt`. These are created automatically by Transcript Recorder during a recording session.

When run from the app, the `-m` flag is auto-filled with the current recording directory. All other parameters use their defaults from `tool.json` but can be edited in the Parameters table before clicking Run.

## Additional Resources

* [Cortex CLI Installation & Setup Guide](https://docs.snowflake.com/en/user-guide/cortex-code/cortex-code-cli)
* [Extensibility and Cortex Skills Overview](https://docs.snowflake.com/en/user-guide/cortex-code/extensibility#extensibility-skills)
