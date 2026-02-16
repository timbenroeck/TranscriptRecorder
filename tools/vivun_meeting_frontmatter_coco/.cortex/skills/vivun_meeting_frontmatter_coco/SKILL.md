
---
name: vivun-meeting-frontmatter
description: "Match Obsidian meeting notes to Vivun/CRM SE activity records and enrich YAML frontmatter with account metadata. Triggers: add vivun data, add vivun frontmatter. Supported formats: MM-YYYY, Month YYYY, YYYY/MM."
---

# Vivun Meeting Frontmatter

Match meeting notes in Obsidian to SE activity records from Snowflake and enrich the markdown **exclusively via YAML frontmatter properties**.

## Output Scope — FRONTMATTER ONLY

**CRITICAL: This skill ONLY adds/updates YAML frontmatter properties (the `vivun_*` keys between the `---` fences at the top of each file).**

This skill does **NOT**:
- Add inline Obsidian tags (e.g., `#vivun/...`, `#sales/...`, `#snowflake/...`)
- Modify the `## Tags` section of any note
- Add any content outside of the YAML frontmatter block

All Vivun metadata (activity type, geo, region, district, industry, segment, SE hierarchy) is stored **as frontmatter properties**, never as inline tags. This design keeps Vivun data queryable via Obsidian Dataview while leaving the `## Tags` section for topic/meeting/audience classification only.

## Prerequisites

- Snowflake connection with access to `sales.se_reporting.dim_se_activity`
- Meeting notes in Obsidian vault structure: `{MEETINGS_BASE}/{YEAR}/{MM}-{MonthName}/`

## Security Constraints
**CRITICAL: These constraints MUST be followed. Do not deviate.**

### Prohibited Actions
- NEVER read files outside of `{NOTES_DIR}`, `{MEETINGS_BASE}`, `{TRANSCRIPT_DIRECTORY}`, or the skill directory
- NEVER write files outside of `{NOTES_DIR}`
- NEVER delete, move, or rename any files
- NEVER run destructive commands (`rm`, `mv`, `chmod`, `chown`, etc.)
- NEVER execute arbitrary code or scripts
- NEVER access system directories, home directory root, or sensitive paths
- NEVER add inline Obsidian tags (`#vivun/...`, `#sales/...`, `#snowflake/...`, etc.)
- NEVER modify the `## Tags` section of any note

## Headless/Automation Skill
This skill is intended to be called in a headless mode.
- **NEVER ask clarifying questions** — make autonomous decisions based on content
- **NEVER prompt for user input** — proceed with best-effort processing or gracefully skip
- **For ambiguous content:** Default to processing the content as-is following the instructions rather than asking for guidance
- **Detection:** Assume headless mode when parameters are provided programmatically in the initial prompt (all parameters present)

## Input Parameters
The following parameters are expected in the prompt:
- `meetings_base_directory` — Base path of the Meetings folder (e.g., `/Users/.../Meetings`)
- `target_date` — Month and year to process (any supported format, see Step 1)
- `activity_se_name` — Full name of the SE to query Vivun activities for (e.g., `Tim Benroeck`)
- `snowflake_warehouse` — *(optional)* Snowflake warehouse to use for queries. If provided, execute `USE WAREHOUSE {WAREHOUSE};` before the query. If omitted, default to `SNOWADHOC_SMALL`.

## Workflow

### Step 1: Parse Date from Input

Extract month and year from `target_date`. Supported formats:

| Input Format | Example | Parsed As |
|--------------|---------|-----------|
| MM-YYYY / YYYY-MM | `12-2025` / `2025-12` | Month: 12, Year: 2025 |
| MMM YYYY / Month YYYY | `dec 2025` / `December 2025` | Month: 12, Year: 2025 |
| YYYY/MM / MM/YYYY | `2025/12` / `12/2025` | Month: 12, Year: 2025 |

**Month name mapping:**
```
jan/january=1, feb/february=2, mar/march=3, apr/april=4,
may=5, jun/june=6, jul/july=7, aug/august=8,
sep/september=9, oct/october=10, nov/november=11, dec/december=12
```

### Step 2: Build & Verify Output Paths

Using the date extracted in Step 1, compute the date-based paths:

1. Parse the date to get `{YEAR}`, `{MONTH_NUM}` (zero-padded), and `{MONTH_NAME}`.
2. Build the month folder name: `{MONTH_NUM}-{MONTH_NAME}` (e.g., `12-December`).
3. Compute absolute system paths:
   - `{NOTES_DIR}` = `{MEETINGS_BASE}/{YEAR}/{MONTH_NUM}-{MONTH_NAME}`
   - `{MATCH_REPORT_PATH}` = `{NOTES_DIR}/{YEAR}_{MONTH_NUM}_vivun_matches.md`

**Verify** `{NOTES_DIR}` exists before proceeding. If not found, report error and stop.

### Step 3: Query Vivun Activity Data

Execute SQL in Snowflake to retrieve SE activities for the target period. Use the `activity_se_name` parameter from input — do NOT hardcode any name. Use the `snowflake_warehouse` parameter if provided, otherwise default to the default in their Snowflake connections.json. If none is provided and there is no default an error will be returned from execute_sql skill and you should  report error and stop.

```sql
USE WAREHOUSE {WAREHOUSE}; -- use snowflake_warehouse param, or default

SELECT
    ACTIVITY_ID,
    ACTIVITY_DATE,
    ACTIVITY_TYPE,
    ACTIVITY_DESCRIPTION,
    ACCOUNT_ID,
    ACCOUNT_NAME,
    GEO_NAME,
    REGION_NAME,
    DISTRICT_NAME,
    INDUSTRY,
    SEGMENT,
    ACCOUNT_SE_MANAGER,
    ACCOUNT_SE_DIRECTOR,
    ACCOUNT_SE_VP
FROM sales.se_reporting.dim_se_activity
WHERE activity_se_name = '{ACTIVITY_SE_NAME}'
    AND meeting_status = 'MEETING_STATUS_COMPLETED'
    AND EXTRACT(MONTH FROM activity_date) = {MONTH_NUMBER}
    AND EXTRACT(YEAR FROM activity_date) = {YEAR}
ORDER BY activity_date DESC;
```

Store the results as `{ACTIVITIES}` for matching.

### Step 4: Scan Meeting Notes & Extract Matching Data

1. **List** all `.md` files in `{NOTES_DIR}`.
2. **For each file**, extract:
   - **Date** from filename (format: `YYYY-MM-DD` prefix)
   - **Title** from filename (text after the date)
   - **Existing frontmatter** properties (check for existing `vivun_*` keys — skip files already tagged)
   - **`transcript_directory`** from frontmatter (if present) → `{TRANSCRIPT_DIRECTORY}`
3. **If `{TRANSCRIPT_DIRECTORY}` exists**, read additional matching data from the recording directory:
   - Read `{TRANSCRIPT_DIRECTORY}/meeting_details.txt` → extract the **meeting name/subject** from the first line or `Meeting:` field
   - Read `{TRANSCRIPT_DIRECTORY}/event.json` (if it exists) → extract the **meeting name/subject** from the `summary` or `title` field
   - These meeting names and the date are the **primary matching signal** against `ACTIVITY_DESCRIPTION` and `ACTIVITY_DATE`

### Step 5: Match Notes to Activities

For each note, score potential matches against the `{ACTIVITIES}` list. Matching uses **three signals** combined into a confidence score.

#### Matching Signals

| Signal | Weight | Description |
|--------|--------|-------------|
| **Meeting name and date match** | HIGH | `ACTIVITY_DESCRIPTION` matches the meeting name from `meeting_details.txt` or `event.json`. Compare case-insensitively. Partial/substring matches count but with lower weight than exact matches. |
| **Date and context match** | HIGH | `ACTIVITY_DATE` matches the `YYYY-MM-DD` date from the note filename and Activity Description and Account Name make sense for the match given the context of the executive summary in the meeting notes markdown. |

Auto-update frontmatter (Step 6) for HIGH matches and List in summary report for other possible Medium/Low/No matches. 

**Matching rules:**
- Normalize strings before comparing: lowercase, trim whitespace, collapse multiple spaces
- For meeting name matching, strip common prefixes like "Zoom Meeting - ", "Meeting: ", etc.
- Allow for minor differences: ignore punctuation, articles ("the", "a"), and common filler words
- If a note matches multiple activities, pick the highest confidence match. If tied, prefer the one with a meeting name match.
- Skip files that already have `vivun_activity_id` in their frontmatter (already tagged)

### Step 6: Update Markdown (High-Confidence Matches Only)

**CRITICAL: Only update files with HIGH confidence matches. All other matches are reported in the summary only.**

#### 6. Add/Update YAML Frontmatter

**CRITICAL: Follow these formatting rules strictly for Obsidian compatibility.**

1. **Indentation:** Use ONLY two standard ASCII spaces (`0x20`) for indentation. No tabs.
2. **Naming:** All keys must be **lowercase** and prefixed with `vivun_`.
3. **Value Formatting:**
   - Convert all values to **lowercase**.
   - Wrap IDs in double quotes to prevent numerical parsing errors (e.g., `"12345"`).
   - Wrap wikilinks in double quotes outside the brackets: `"[[value]]"`.
4. **Placement:** Insert these properties immediately after the `date:` property (preserving any other existing metadata).
5. **Completeness:** ALL 11 properties listed below MUST be added together. Do NOT add a partial set (e.g., only ID/account/name). If any column value is NULL or empty in the query results, still add the key with an empty string value.

**Properties to add (all 11 are required for every match):**

```yaml
vivun_activity_id: "<ACTIVITY_ID>"
vivun_account_id: "<ACCOUNT_ID>"
vivun_account_name: "[[<account_name>]]"
vivun_activity_type: "[[<activity_type>]]"
vivun_geo_name: "[[<geo_name>]]"
vivun_region_name: "[[<region_name>]]"
vivun_district_name: "[[<district_name>]]"
vivun_industry: "[[<industry>]]"
vivun_segment: "[[<segment>]]"
vivun_account_se_manager: "[[<account_se_manager>]]"
vivun_account_se_director: "[[<account_se_director>]]"
vivun_account_se_vp: "[[<account_se_vp>]]"
```

#### What NOT to Do

**CRITICAL: Do NOT add Vivun/Sales/Snowflake metadata as inline Obsidian tags.**

The following are WRONG and must NEVER be generated:
```markdown
## Tags
#vivun/technical_overview_deep_dive #vivun/0013100001nlqgzaae #sales/amsexpansion #snowflake/mike_wies   ← WRONG
```

The correct approach is YAML frontmatter ONLY:
```yaml
vivun_activity_type: "[[technical overview / deep dive]]"
vivun_account_id: "0013100001nlqgzaae"
vivun_geo_name: "[[amsexpansion]]"
vivun_account_se_manager: "[[mike wies]]"
```

Do NOT touch the `## Tags` section at all. Leave it exactly as-is.

**Example output in context:**

```yaml
---
date: 2025-12-01 02:31 PM
vivun_activity_id: "a1b2c3d4e5f6"
vivun_account_id: "0011a00000v9abc"
vivun_account_name: "[[frostfit computing solutions]]"
vivun_activity_type: "[[technical deep dive]]"
vivun_geo_name: "[[north america]]"
vivun_region_name: "[[us west]]"
vivun_district_name: "[[pacific northwest]]"
vivun_industry: "[[software & services]]"
vivun_segment: "[[enterprise]]"
vivun_account_se_manager: "[[jane doe]]"
vivun_account_se_director: "[[john smith]]"
vivun_account_se_vp: "[[alex johnson]]"
transcript_directory: /path/to/recording
attendees:
  - "[[Person A (a@example.com)]]"
attendees_email_domains:
  - "[[snowflake.com]]"
---
```

**The `## Tags` section below the frontmatter is NOT modified by this skill.** It retains whatever `#topic/...`, `#meeting/...`, and `#audience/...` tags were already present.

### Step 7: Generate or Merge Match Report

Save a match report to `{MATCH_REPORT_PATH}` (`{NOTES_DIR}/{YEAR}_{MONTH_NUM}_vivun_matches.md`).

#### 7a. Check for Existing Report

Before writing, check if `{MATCH_REPORT_PATH}` already exists.

- **If it does NOT exist:** Create a new report using the template below.
- **If it DOES exist:** Read the existing report and merge this run's results into it (see [Merge Rules](#7b-merge-rules-for-re-runs) below).

#### 7b. Merge Rules for Re-Runs

When `{MATCH_REPORT_PATH}` already exists, merge the current run's results into the existing report:

1. **Read the existing report** to understand what was previously recorded.
2. **Rebuild each section** using the current run's data as the source of truth for match states:
   - A note that was previously "High Confidence" or "Medium Confidence" but now has `vivun_activity_id` in its frontmatter → move it to **Already Tagged (Skipped)**.
   - A note that was previously "Unmatched" or "Low Confidence" but now has a HIGH match → add it to **High Confidence** (it was auto-updated this run).
   - A note that was previously "Medium Confidence" and is still medium → keep it in **Medium Confidence**.
   - New notes that didn't exist in the previous report → add them to the appropriate section.
   - Activities that were previously "Unmatched" but now matched a note → remove them from **Unmatched Activities**.
3. **Append a new entry to the Run History** section at the bottom of the report with the current run's timestamp and counts.
4. **Update the header** `Last updated:` timestamp and cumulative totals.

**Key principle:** The match sections (High/Medium/Low/Unmatched/Already Tagged) always reflect the **current cumulative state** — they are not append-only logs. The **Run History** section at the bottom is the append-only log that tracks what happened in each individual run.

#### Report Template

```markdown
# Vivun Activity Matching Report
**Period:** {MONTH_NAME} {YEAR}
**SE:** {ACTIVITY_SE_NAME}
**Last updated:** {CURRENT_TIMESTAMP}
**Notes scanned:** {TOTAL_NOTES}
**Activities found:** {TOTAL_ACTIVITIES}

## High Confidence — Auto-Updated
| Note | Activity Description | Account | Matched On | Run |
|------|---------------------|---------|------------|-----|
| {filename} | {ACTIVITY_DESCRIPTION} | {ACCOUNT_NAME} | meeting name + date | {RUN_TIMESTAMP} |

## Medium Confidence — Manual Review Recommended
| Note | Activity Description | Account | Signals |
|------|---------------------|---------|---------|
| {filename} | {ACTIVITY_DESCRIPTION} | {ACCOUNT_NAME} | date + account name |

## Low Confidence — Possible Matches
| Note | Activity Description | Account | Signal |
|------|---------------------|---------|--------|
| {filename} | {ACTIVITY_DESCRIPTION} | {ACCOUNT_NAME} | date only |

## Unmatched Notes
- {filename}

## Unmatched Activities
| Activity Date | Description | Account |
|--------------|-------------|---------|
| {ACTIVITY_DATE} | {ACTIVITY_DESCRIPTION} | {ACCOUNT_NAME} |

## Already Tagged (Skipped)
- {filename} (vivun_activity_id: {existing_id})

---

## Run History
| Run | Timestamp | Notes Scanned | Activities | High | Medium | Low | Unmatched Notes | Already Tagged |
|-----|-----------|---------------|------------|------|--------|-----|-----------------|----------------|
| 1 | {TIMESTAMP} | {N} | {N} | {N} | {N} | {N} | {N} | {N} |
```

#### Merge Example

**Run 1** (initial): 20 notes scanned, 15 activities. 10 high, 3 medium, 2 unmatched notes, 5 already tagged.

**Run 2** (re-run after cleanup): 20 notes scanned, 15 activities. The 10 previously high-confidence notes now have `vivun_activity_id` so they move to "Already Tagged". 2 of the 3 medium notes now match as high. 1 unmatched note now matches.

The merged report after Run 2 would show:
- **High Confidence:** 3 new auto-updates this run
- **Medium Confidence:** 1 remaining from before
- **Unmatched Notes:** 1 remaining
- **Already Tagged:** 15 total (10 from run 1 + 5 originally tagged)
- **Run History:** 2 rows showing both runs

### Step 8: Final Output to User

After completing all steps, output ONLY the following:

1. A brief 1-2 sentence summary of what was processed
2. Counts: notes scanned, high-confidence updates made, medium/low matches for review
3. The file path to the match report

**Example output:**
```
Vivun tagging complete for February 2026.

- 23 notes scanned, 18 activities found
- 14 high-confidence matches auto-updated
- 4 medium-confidence matches listed for review
- 5 notes unmatched

**Match report:** `/Users/.../Meetings/2026/02-February/2026_02_vivun_matches.md`
```

**DO NOT:**
- Include the full match report in the response
- Ask follow-up questions
- Offer to make modifications
