
---
name: meeting-summarizer
description: "Summarize meeting transcripts into structured markdown with executive summary, personal contributions, and action items. Triggers: summarize meeting, meeting notes, meeting recap."
---

# Meeting Summarizer

## Overview
This skill processes meeting recordings (details + transcript files) and generates a structured markdown summary. When a person's name is provided, it creates personalized summaries with contribution notes for leadership reporting. When no name is provided, it generates a general detailed meeting recap with action items.

## Security Constraints
**CRITICAL: These constraints MUST be followed. Do not deviate.**

### Allowed Read Paths
- `{MEETING_DIR}` (the input meeting_transcript_directory) and its contents
- The skill directory containing this SKILL.md and `attendees.json`

### Allowed Write Paths
- `{MEETINGS_BASE}` (the meetings_base_directory) and its subdirectories only

### Allowed Bash Commands
- `mkdir -p` — creating output directories only within `{MEETINGS_BASE}`
- `cat` — concatenating transcript files only
- `echo` — writing headers to transcript files only

### Prohibited Actions
- NEVER read files outside of `{MEETING_DIR}` or `{MEETINGS_BASE}` or the skill directory
- NEVER write files outside of `{MEETINGS_BASE}`
- NEVER delete, move, or rename any files
- NEVER run destructive commands (`rm`, `mv`, `chmod`, `chown`, etc.)
- NEVER execute arbitrary code or scripts
- NEVER access system directories, home directory root, or sensitive paths

## Headless/Automation Skill
This skill is intended to be called in a headless mode
- **NEVER ask clarifying questions** — make autonomous decisions based on content
- **NEVER prompt for user input** — proceed with best-effort processing or gracefully skip
- **For ambiguous content:** Default to processing the content as-is following the instructions rather than asking for guidance
- **Detection:** Assume headless mode when parameters are provided programmatically in the initial prompt (all 4 parameters present with full paths)

## Input Parameters
The following parameters are expected in the prompt:
- `meeting_transcript_directory` - Path to directory containing meeting files
- `meetings_base_directory` - Base path of the Meetings folder (summaries are organized into date subfolders automatically)
- `summary_for_firstname` - (OPTIONAL) First name of the person the summary is for
- `summary_for_lastname` - (OPTIONAL) Last name of the person the summary is for

## Workflow

### Step 1: Parse Input Parameters
Extract the following from the user prompt:
- `meeting_transcript_directory` → `{MEETING_DIR}`
- `meetings_base_directory` → `{MEETINGS_BASE}` (e.g., `~/Documents/obsidian_vault/Meetings`)
- `summary_for_firstname` → `{FIRST_NAME}` (may be empty/not provided)
- `summary_for_lastname` → `{LAST_NAME}` (may be empty/not provided)
- Full name: `{FIRST_NAME} {LAST_NAME}` → `{FULL_NAME}` (if both provided)
- `{PERSONALIZED}` → TRUE if both firstname and lastname are provided, FALSE otherwise

### Step 2: Read Input Files
The meeting directory should contain:
- `meeting_details.txt` - Meeting metadata (date, attendees, topic)
- `meeting_transcript.txt` - Full meeting transcript

Read both files from `{MEETING_DIR}`:
1. Read `{MEETING_DIR}/meeting_details.txt`
2. Read `{MEETING_DIR}/meeting_transcript.txt`

### Step 2.5: Load Known Attendees for Name Correction
Read the `attendees.json` file from the skill directory to get a list of known team member names that may be mistranscribed by speech-to-text.

**File location:** Same directory as this SKILL.md file (`attendees.json`)

**Purpose:** Use this list during transcript analysis to:
- Correct phonetic misspellings (e.g., "Jim Labaneet" → "Jim Lebonitte", "Fawni" → "Phani Alapaty")
- Identify speakers by partial name matches
- Ensure attendee names in the output use correct spellings

**Usage:** When generating the Attendees table, action items, and person tags, cross-reference names found in the transcript against this list and use the correct spelling from `attendees.json` when a close match is detected.

### Step 3: Extract Meeting Date
- Extract the meeting date/time from the meeting details or {MEETING_DIR} (format: yyyy-mm-dd hh:mm AM/PM)


### Step 4: Generate Meeting Summary and Title
- Derive a brief meeting title (2-5 words) from the content
- Analyze the transcript using the appropriate approach based on whether a name was provided:

**Meeting Executive Summary:** A concise, high-level overview of the meeting's purpose. 4-6 sentences covering the main topic, key participants, strategic decisions, and outcomes discussed.

---

#### IF {PERSONALIZED} is TRUE (name provided):

**{FIRST_NAME}'s Contribution Summary:** A third-person summary of {FULL_NAME}'s contributions for their weekly activity list. Reference {FIRST_NAME} by name. Max 5 sentences. Focus on their insights, questions, and value-adds.

**{FIRST_NAME} Specific Meeting Recap:** A detailed personal recap for {FULL_NAME} covering:
- Their contributions and observations
- Key understandings from the discussion
- Context needed for follow-up meetings
- Expectations for next steps

**Action Items:**
- Items assigned to {FULL_NAME}: Use `- [ ]` checkbox format
- Items for other assignees: Use `- **Name:** action` format

---

#### IF {PERSONALIZED} is FALSE (no name provided):

**OMIT the Contribution Summary section entirely.**

**Detailed Meeting Recap:** A comprehensive general recap of the meeting covering:
- Key discussion points and decisions made
- Important context and background shared
- Technical or strategic insights discussed
- Open questions and unresolved topics
- Next steps and follow-up items agreed upon
- Timeline and milestone references
- Dependencies or blockers identified

**Action Items:** List ALL action items using simple bullet format:
- {Name}: {Action item description}
- {Name}: {Action item description}

---

**Attendees:** For each meeting participant:
- Name
- Role (derived from context if not explicitly stated - e.g., "Account Executive", "Solutions Architect", "Customer - VP Engineering")
- Brief contribution summary on the call
- Insights for future interactions (communication style, priorities, concerns raised)

**Tags:**
- *Attendee Tags:* Generate a tag for each attendee following Obsidian tag rules:
  - **Only create tags when both first AND last name are known** (skip single-name attendees)
  - Lowercase only
  - Replace spaces with underscores `_`
  - Strip invalid characters (only allow: letters, numbers, underscores, hyphens, forward slashes)
  - Format: `#person/firstname_lastname`
- *Meeting Tags:* Derive topic tags from the transcript content for knowledge graph linking:
  - Company names: `#company/company_name`
  - Technologies: `#tech/technology_name`
  - Topics: `#topic/topic_name`
  - Meeting type: `#meeting/type` (e.g., `#meeting/strategy`, `#meeting/demo`, `#meeting/discovery`)

### Step 5: Determine Output Paths & URI Encoding
Using the meeting date extracted in Step 3, compute the date-based output paths:

1. Parse the meeting date to get `{YEAR}`, `{MONTH_NUM}` (zero-padded), and `{MONTH_NAME}`.
2. Build the month folder name: `{MONTH_NUM}-{MONTH_NAME}` (e.g., `05-May`).
3. Compute absolute system paths:
   - `{OUTPUT_DIR}` = `{MEETINGS_BASE}/{YEAR}/{MONTH_NUM}-{MONTH_NAME}`
   - `{TRANSCRIPTS_DIR}` = `{OUTPUT_DIR}/.transcripts`
   - `{BASE_NAME}` = `{yyyy-mm-dd} {Brief Meeting Title}` (Ensure no special characters like `/`, `:`, or `\`)
   - `{SUMMARY_PATH}` = `{OUTPUT_DIR}/{BASE_NAME}.md`
   - `{TRANSCRIPT_PATH}` = `{TRANSCRIPTS_DIR}/{BASE_NAME}.txt`
4. **Generate Encoded Link:**
   - Create `{TRANSCRIPT_URI}` by taking the absolute path `{TRANSCRIPT_PATH}`.
   - Prepend with `file://`.
   - **Important:** Only encode spaces as `%20`. Do NOT encode periods (`.`) — they are valid in file URIs and encoding them breaks links (e.g., `/.transcripts/` should remain as-is, not `/%2Etranscripts/`).
   - Example: `file:///Users/name/Vault/.transcripts/File%20Name.txt`

Example:
- Meeting date: 2026-02-06 → `{MEETINGS_BASE}/2026/02-February/`
- Summary: `{MEETINGS_BASE}/2026/02-February/2026-02-06 Contoso Services Strategy Brief.md`
- Transcript: `{MEETINGS_BASE}/2026/02-February/.transcripts/2026-02-06 Contoso Services Strategy Brief.txt`

### Step 6: Generate Output Markdown
Create the markdown file using the following template structure. Ensure all placeholders in curly brackets are replaced with generated content.

#### Template

```markdown
---
date: {extracted date in yyyy-mm-dd hh:mm AM/PM format}
---

## Meeting Executive Summary

{Generated executive summary}

---


## {FIRST_NAME}'s Contribution Summary (when {PERSONALIZED} is TRUE)

{Generated third-person contribution summary for leadership reporting}

---

## {FIRST_NAME} Specific Meeting Recap (when {PERSONALIZED} is TRUE)

{Generated detailed personal recap}

---

## Action Items

### Assigned to {FIRST_NAME}: (when {PERSONALIZED} is TRUE)

- [ ] {Action item 1}
- [ ] {Action item 2}

### Other Assignees: (when {PERSONALIZED} is TRUE OMIT header when FALSE)

- **{Name}:** {Action item}
- **{Name}:** {Action item}

---

## Attendees

| Name | Role | Contribution | Insights |
|------|------|--------------|----------|
| {Name} | {Role - derived if not stated} | {Brief contribution on call} | {Notes for future interactions} |
| {Name} | {Role} | {Contribution} | {Insights} |

---

## Tags

### Attendee Tags
#person/firstname_lastname #person/firstname_lastname

### Meeting Tags
#company/company_name #tech/snowflake #topic/data_strategy #meeting/strategy

## Resources
> [!info] ****Transcript Text File****
> [View Full Transcript]({TRANSCRIPT_URL})

```

### Step 7: Save Output Summary
Save the generated markdown to `{SUMMARY_PATH}`:
```
{OUTPUT_DIR}/{yyyy-mm-dd} {Brief Meeting Title}.md
```

Where:
- `{OUTPUT_DIR}` is the date-based folder computed in Step 5
- `yyyy-mm-dd` is the meeting date
- `{Brief Meeting Title}` is derived from meeting details/transcript (2-5 words, descriptive)

### Step 8: Create Merged Transcript File
Create a merged transcript file at `{TRANSCRIPT_PATH}` using a **single bash command** to concatenate the source files. Do NOT re-read the files — use shell concatenation:

```bash
echo "---- meeting_details ----" > "{TRANSCRIPT_PATH}" && cat "{MEETING_DIR}/meeting_details.txt" >> "{TRANSCRIPT_PATH}" && echo -e "\n---- meeting_transcript ----" >> "{TRANSCRIPT_PATH}" && cat "{MEETING_DIR}/meeting_transcript.txt" >> "{TRANSCRIPT_PATH}"
```

This avoids re-reading files into context and directly copies them to the destination.

### Step 9: Final Output to User
After completing all steps, output ONLY the following to the user:

1. A brief 1-2 sentence description of what was processed
2. The file paths where outputs were saved

**Example output:**
```
Meeting summary complete.

**Summary saved to:** `/Users/.../2025-05-28 Microsoft Positioning QBR.md`

**Transcript saved to:** `/Users/.../2025-05-28 Microsoft Positioning QBR.txt`
```

**DO NOT:**
- Include the meeting summary content in the response
- Provide a recap of the meeting
- Ask follow-up questions
- Offer to make modifications

## Examples

### Example Input (Personalized)
```
Summarize the meeting. Parameters:
- meeting_transcript_directory: /Users/tbenroeck/Documents/transcriptrecorder/recordings/recording_2026-02-06_1106_zoom
- meetings_base_directory: /Users/tbenroeck/Documents/obsidian_vaults/snowflake/Meetings
- summary_for_firstname: Tim
- summary_for_lastname: Benroeck
```

### Example Input (General - no name)
```
Summarize the meeting. Parameters:
- meeting_transcript_directory: /Users/tbenroeck/Documents/transcriptrecorder/recordings/recording_2026-02-06_1106_zoom
- meetings_base_directory: /Users/tbenroeck/Documents/obsidian_vaults/snowflake/Meetings
```

### Example Output Files
- Summary saved to: `~/Documents/obsidian_vaults/snowflake/Meetings/2026/02-February/2026-02-06 Contoso Services Strategy Brief.md`
- Transcript saved to: `~/Documents/obsidian_vaults/snowflake/Meetings/2026/02-February/.transcripts/2026-02-06 Contoso Services Strategy Brief.txt`

## When to Apply
- User asks to "summarize a meeting"
- User provides meeting parameters including `meeting_transcript_directory`
- User references the transcriptrecorder recordings directory
