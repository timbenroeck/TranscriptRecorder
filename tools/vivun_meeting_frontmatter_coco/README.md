# Vivun Meeting Frontmatter

Match Obsidian meeting notes to Vivun/CRM SE activity records from Snowflake and enrich the markdown **YAML frontmatter** with account metadata.

> **Important:** This tool adds Vivun data exclusively as YAML frontmatter properties (`vivun_*` keys). It does **not** add inline Obsidian tags like `#vivun/...`, `#sales/...`, or `#snowflake/...` to the `## Tags` section.

## Requirements

* **[Cortex CLI](https://docs.snowflake.com/en/user-guide/cortex-code/cortex-code-cli)** must be installed and available on your PATH.
* A Snowflake connection with access to `sales.se_reporting.dim_se_activity`.

## Parameters

| Flag | Description | Default |
| --- | --- | --- |
| `-b` | Meetings base directory (root of Obsidian Meetings folder) | *required* |
| `-d` | Target month/year (`feb 2026`, `02-2026`, `2026/02`, etc.) | *required* |
| `-s` | Activity SE name to query in Vivun | `Tim Benroeck` |
| `-w` | Snowflake warehouse for queries. If omitted, defaults to `SNOWADHOC_SMALL` in the SKILL. | `SNOWADHOC_SMALL` |
| `-c` | Cortex connection name. If omitted, Cortex uses its default. | `Snowhouse` |

## How It Works

1. **Parses the target date** and locates the corresponding month folder in the Obsidian vault.
2. **Queries Snowflake** for completed SE activities for the specified person and month.
3. **Scans meeting notes** in the month folder, extracting meeting names from the note's `transcript_directory` -> `meeting_details.txt` and `event.json` files.
4. **Matches notes to activities** using two signals:
   - **Meeting name** — `ACTIVITY_DESCRIPTION` vs. meeting name from transcript files (highest weight)
   - **Date + context** — Activity date matches the note filename date, and account/description align with meeting content
5. **Auto-updates only high-confidence matches** — adds all 11 `vivun_*` YAML frontmatter properties.
6. **Generates a match report** (`{YEAR}_{MM}_vivun_matches.md`) listing all confidence levels for manual review of medium/low matches.

## What Gets Added to Frontmatter

For each high-confidence match, all 11 properties are added:

```yaml
vivun_activity_id: "<id>"
vivun_account_id: "<id>"
vivun_account_name: "[[account name]]"
vivun_activity_type: "[[activity type]]"
vivun_geo_name: "[[geo]]"
vivun_region_name: "[[region]]"
vivun_district_name: "[[district]]"
vivun_industry: "[[industry]]"
vivun_segment: "[[segment]]"
vivun_account_se_manager: "[[name]]"
vivun_account_se_director: "[[name]]"
vivun_account_se_vp: "[[name]]"
```

## Configuration

**To customize defaults, edit the `tool.json` file — do not modify the shell script directly.**

The `tool.json` file defines the default values for each parameter. When the tool is run from the app, these defaults are pre-filled in the Parameters table and can be adjusted per-run.

## Usage

### From the App

The tool appears in the Tools panel as **Vivun Meeting Frontmatter**. Fill in the target month/year, verify defaults, and click Run.

### From the Command Line

```bash
# Basic usage
./vivun_meeting_frontmatter_coco.sh -b /Users/tbenroeck/Documents/obsidian_vaults/snowflake/Meetings -d "feb 2026" -s "Tim Benroeck"

# With explicit SE name, warehouse, and connection
./vivun_meeting_frontmatter_coco.sh -b /path/to/Meetings -d "02-2026" -s "Tim Benroeck" -w SNOWADHOC_SMALL -c Snowhouse
```

## Output

- **Updated markdown files** — High-confidence matches get all 11 `vivun_*` frontmatter properties. The `## Tags` section is never modified.
- **Match report** — `{YEAR}_{MM}_vivun_matches.md` saved in the month folder with all match results organized by confidence level.

## Additional Resources

* [Cortex CLI Installation & Setup Guide](https://docs.snowflake.com/en/user-guide/cortex-code/cortex-code-cli)
* [Extensibility and Cortex Skills Overview](https://docs.snowflake.com/en/user-guide/cortex-code/extensibility#extensibility-skills)
