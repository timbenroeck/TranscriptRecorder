
---
name: meeting-summarizer
description: "Summarize meeting transcripts into structured markdown with executive summary, personal contributions, and action items. Triggers: summarize meeting, meeting notes, meeting recap."
---

# Meeting Summarizer

## Overview
This skill processes meeting recordings (details + transcript files) and generates a structured markdown summary. It creates personalized summaries with contribution notes for leadership reporting. It generates a detailed meeting recap with action items.

## Security Constraints
**CRITICAL: These constraints MUST be followed. Do not deviate.**

### Prohibited Actions
- NEVER read files outside of `{MEETING_DIR}`, `{MEETINGS_BASE}`, `{CRM_DIR}`, or the skill directory
- NEVER write files outside of `{MEETINGS_BASE}` or `{CRM_DIR}`
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
- `summary_for_firstname` -  First name of the person the summary is for
- `summary_for_lastname` - Last name of the person the summary is for

## Workflow

### Step 1: Parse Input Parameters
Extract the following from the user prompt:
- `meeting_transcript_directory` → `{MEETING_DIR}`
- `meetings_base_directory` → `{MEETINGS_BASE}` (e.g., `~/Documents/obsidian_vault/Meetings`)
- `summary_for_firstname` → `{FIRST_NAME}` 
- `summary_for_lastname` → `{LAST_NAME}` 
- Full name: `{FIRST_NAME} {LAST_NAME}` → `{FULL_NAME}` (if both provided)

Derived paths:
- `{VAULT_ROOT}` = parent directory of `{MEETINGS_BASE}` (e.g., if `{MEETINGS_BASE}` is `~/Documents/obsidian_vault/Meetings`, then `{VAULT_ROOT}` is `~/Documents/obsidian_vault`)
- `{CRM_DIR}` = `{VAULT_ROOT}/CRM` — used for attendee relationship notes (see Step 8)

### Step 2: Read Input Files
The meeting directory should contain:
- `meeting_details.txt` - Meeting metadata (date, attendees, topic)
- `meeting_transcript.txt` - Full meeting transcript
- `event.json` - Seralized JSON for the Calendar invent (optionanl)

Read all the files from `{MEETING_DIR}`:
1. Read `{MEETING_DIR}/meeting_details.txt`
2. Read `{MEETING_DIR}/meeting_transcript.txt`
3. Optionally read other files for more context

### Step 2.5: Load Known Names for Transcript Correction
Read the `known_names.json` file from the skill directory. This is a curated list of frequently-encountered names that speech-to-text commonly mistranscribes.

**File location:** Same directory as this SKILL.md file (`known_names.json`)

**Purpose:** Correct phonetic misspellings of names in the transcript text. Examples:
- "Jim Labaneet" → "Jim Lebonitte"
- "Fawni" → "Phani Alapaty"
- "Steve Mitchner" → "Steve Mitchener"

**This is NOT the attendee list.** The authoritative attendee names come from `meeting_details.txt` and `meeting_transcript.txt`. `known_names.json` is a secondary fallback for correcting transcript speaker names that don't appear in the calendar attendee list.

### Step 2.6: Name Resolution Priority
When writing ANY name in the output (summary, action items, attendees table, contribution summary), apply this resolution order:

1. **Calendar attendee names (from `meeting_details.txt` or `event.json`)** — These are the **authoritative, correct spellings**. The `{ATTENDEE_NAMES}` extracted in Step 3 are the canonical source of truth. When a transcript speaker matches a calendar attendee, ALWAYS use the calendar spelling with first and last name.
2. **`known_names.json`** — For speakers referenced in the transcript who do NOT match any calendar attendees, check `known_names.json` for a phonetic match and use the corrected spelling from that file.
3. **Transcript as-is** — If a speaker name matches neither source, use the transcript spelling.

**Matching rules:**
- Match by first name, last name, or full name (case-insensitive)
- Allow for common phonetic variations (e.g., transcript says "Fawni Alipati", calendar has "Phani Alapaty")
- When in doubt, prefer the calendar attendee spelling over the transcript spelling

**CRITICAL:** Every name that appears anywhere in the output — frontmatter `attendees`, executive summary, contribution summary, action items, attendees table — MUST use the canonical spelling from this resolution order. Never mix spellings of the same person across sections.

### Step 3: Extract Meeting Date and Attendees
- Extract the meeting date/time from the meeting details or {MEETING_DIR} (format: yyyy-mm-dd hh:mm AM/PM)
- Extract attendees email from the `Attendees (N):` section in `meeting_details.txt` or `event.json`. Each line is formatted as:
  `- Name (email@domain.com) [optional status]`

**Attendee Cleaning Rules:**
1. **Filter conference rooms/resources:** Remove any entry where the name contains `[ZOOM Room]` (case-insensitive), starts with a City-Country-Floor pattern like `Bellevue-US-2-`, `Toronto-Canada-32-`, or `New York-US-`, or starts with `MPK-`.
2. **Strip bracket suffixes from names:** Remove trailing `[...], (...)` patterns from names. These are organizational codes from email systems that should NOT appear in the summary.  Examples:
   - `Sorg, Donald [EMR/ENT/IT/STL]` → `Sorg, Donald`
   - `CJ Gonzalez [C]` → `CJ Gonzalez`
   - `Prakash, Santosh [CTR]` → `Prakash, Santosh`
   - `Tim Benroeck (Snowflake)` → `Tim Benroeck` 
3. **Preserve emails as-is** — no cleaning needed for email addresses.
4. **Normalize and Sanitize Characters** - De-accent (Optional but recommended): Convert unicode characters to their closest ASCII equivalent (e.g., Paweł → Pawel, Mitrús → Mitrus). This prevents "duplicate" person notes caused by slight spelling variations.

Remove YAML-breaking characters: Strip any characters that interfere with Obsidian’s link or property syntax: #, ^, |, *, \, and double quotes " from within the name string.

Normalize Spaces: Replace all non-breaking spaces (\xa0 or &nbsp;) and tabs with a single standard ASCII space. Trim leading and trailing whitespace.

Handle Parentheses/Brackets: Since names will be wrapped in [[ ]] and emails in ( ), ensure the name itself does not contain unclosed brackets or parens that might confuse the parser.

**CRITICAL:** Do not infer attandee name and email from meeting_transcript.txt context for the frontmater properties.

### Step 4: Generate Meeting Summary and Title
- Derive a brief meeting title (2-5 words) from the content
- Generate the Meeting Summary using the following markdown template

**Meeting Executive Summary:** A concise, high-level overview of the meeting's purpose. 4-6 sentences covering the main topic, key participants, strategic decisions, and outcomes discussed.

**{FIRST_NAME}'s Contribution Summary:** A third-person summary of {FULL_NAME}'s contributions for their weekly activity summary or leadership. Reference {FIRST_NAME} by name. Max 5 sentences. {FIRST_NAME}'s leadership knows {FIRST_NAME}'s role and background and that does not need to be summarized. Focus on {FIRST_NAME}'s contribution and value in the meeting.

**{FIRST_NAME} Specific Meeting Recap:** A detailed personal recap for {FULL_NAME} covering:
- Their insights and observations made durning the meeting
- Key understandings from the discussion
- Context needed for follow-up meetings
- Expectations for next steps

**Action Items:**
- Items assigned to {FULL_NAME}: Use `- [ ]` checkbox format
- Items for other assignees: Use `- **Name:** action` format

**Attendees:** For each meeting participant:
- Name
- Role (derived from context if not explicitly stated - e.g., "Account Executive", "Solutions Architect", "Customer - VP Engineering")
- Brief contribution summary on the call
- Insights for future interactions (communication style, priorities, concerns raised)

**Inferred attendees:** For the Attendees section for the SUMMARY the Name's can be inferred from the meeting_transcript. 

- *Meeting Tags:* - For knowledge graph linking
  - Topics: `#topic/topic_name` - Derive 3-5 of the major topic tags from the transcript content for  (e.g., `#topic/streaming`, `#topic/ingestion`, `#topic/cost_optimization`, `#topic/data_engineering`, `#topic/ai_ml`, etc)
  - Meeting Type(s): Derive 1-2 `#meeting/meeting_type` (e.g., `#meeting/strategy`, `#meeting/thought_leadership`, `#meeting/discovery`, `#meeting/interopability`, `#meeting/one_on_one`, `#meeting/team_sync`, `#meeting/customer_prep`, `#meeting/debrief`)
  - Audience Type: `#audience/audience_type` (e.g., `#audience/internal`, `#audience/customer`, `#audience/partner`)
  - (optional) Sensitivity Flag(s): `sensitivity/sensitivity_type` (e.g. `sensitivity/compensation`, `sensitivity/feedback`, `sensitivity/venting`)


**Audience Mapping:**
- **Internal:** All attendees share the user's email domain or are recognized colleagues in context.
- **Customer:** Attendees have multiple emaili domains and the discussion context is supporting sales/support/archtiecture conversations to support customers.
- **Partner:** ttendees have multiple emaili domains and the discussion context is with parnters around co-selling, system integration for shared customer uses, etc.
- **Personal:** Content is mostly non-professional.

**Sensitivity Mapping:**
Scan for "Sensitive Pillars." If detected, add the tag and a "Review" flag to frontmatter.
- **Compensation:** Salary, bonuses, equity, promotions.
- **Feedback:** Performance reviews, negative feedback, PIPs.
- **Personal:** Medical info, family emergencies, legal disputes.
- **Venting:** Discussions involving workplace venting, critical talk regarding leadership or colleagues, "water cooler" gossip, or internal office politics.

### Step 5: Determine Output Paths & URI Encoding
Using the meeting date extracted in Step 3, compute the date-based output paths:

1. Parse the meeting date to get `{YEAR}`, `{MONTH_NUM}` (zero-padded), and `{MONTH_NAME}`.
2. Build the month folder name: `{MONTH_NUM}-{MONTH_NAME}` (e.g., `05-May`).
3. Compute absolute system paths:
   - `{OUTPUT_DIR}` = `{MEETINGS_BASE}/{YEAR}/{MONTH_NUM}-{MONTH_NAME}`
   - `{BASE_NAME}` = `{yyyy-mm-dd} {Brief Meeting Title}` (Ensure no special characters like `/`, `:`, or `\`)
   - `{SUMMARY_PATH}` = `{OUTPUT_DIR}/{BASE_NAME}.md`

Example:
- Meeting date: 2026-02-06 → `{MEETINGS_BASE}/2026/02-February/`
- Summary: `{MEETINGS_BASE}/2026/02-February/2026-02-06 Contoso Services Strategy Brief.md`

### Step 6: Generate Output Markdown
Create the markdown file using the following template structure. Ensure all placeholders in curly brackets are replaced with generated content.

#### YAML Frontmatter Rules
Here is the updated set of rules for your Skill, incorporating the logic for the distinct email domains while maintaining your strict formatting requirements.

**CRITICAL: Follow these formatting rules exactly for the YAML frontmatter block.**

1. **Indentation:** Use ONLY standard ASCII spaces (hex `0x20`) for indentation. NEVER use non-breaking spaces, tabs, or any other whitespace character. Indent each YAML list item with exactly **two standard spaces** followed by a dash and a space (` -`).
2. **`attendees` property:** A YAML list of Obsidian wikilinks. Each item MUST be wrapped in double quotes and brackets `[[Name (email_address)]]`. Extract only the Name and Email; do not include status (e.g., "accepted") or roles (e.g., "organizer"). These must of been specified in the `meeting_details.txt` or `event.json`.
3. **`attendees_email_domains` property:** A YAML list of Obsidian wikilinks. Extract the domain (the portion after the `@` symbol) from every attendee email. This list MUST contain only **distinct** (unique) domains, wrapped in double quotes and brackets `[[domain.com]]`.
4. **`transcript_directory` property:** The absolute path to `{MEETING_DIR}` as a plain string.
5. **Closing `---`:** The closing frontmatter delimiter MUST be on its own line, with a newline character before it. Never append it to the last property value.

**Summary Markdown Template**

---
date: {extracted date in yyyy-mm-dd hh:mm AM/PM format}
transcript_directory: {MEETING_DIR}
attendees:
  - "[[{ATTENDEE_NAME_1} ({ATTENDEE_EMAIL_1})]]"
  - "[[{ATTENDEE_NAME_2} ({ATTENDEE_EMAIL_2})]]"
  - "[[{ATTENDEE_NAME_N} ({ATTENDEE_EMAIL_N})]]"
attendees_email_domains:
  - "[[{DISTINCT_DOMAIN_1}]]"
  - "[[{DISTINCT_DOMAIN_2}]]"
  - "[[{DISTINCT_DOMAIN_N}]]"
---

## Meeting Executive Summary Summary
{Generated Executive Summary from step 4}

## {FIRST_NAME}'s Contribution Summary
{Generated Contribution Summary from step 4}

## {FIRST_NAME} Specific Meeting Recap
{Generated Meeting Recap from step 4}

## Action Items

### Assigned to {FIRST_NAME}: 

- [ ] {Action item 1}
- [ ] {Action item 2}

### Other Assignees: 

- **{Name}:** {Action item}
- **{Name}:** {Action item}


## Attendees

| Name | Role | Contribution | Insights |
|------|------|--------------|----------|
| {Name} | {Role - derived if not stated} | {Brief contribution on call} | {Notes for future interactions} |
| {Name} | {Role} | {Contribution} | {Insights} |


## Tags
#topic/topic_name #meeting/meeting_topic #audience/audience_topic #sensitivity/sensitivity_type

> [!info] **Transcript Access**
> * **Folder:** `$= "[" + "Open Folder" + "](file://" + encodeURI(dv.current().transcript_directory) + ")"`
> * **File:** `$= "[" + "View Transcript" + "](file://" + encodeURI(dv.current().transcript_directory + "/meeting_transcript.txt") + ")"`

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

### Step 8: Attendee CRM Notes

After saving the meeting summary, scan the transcript for personal and relationship details shared by or about each attendee, and maintain lightweight CRM-style notes in the vault.  Do this only for attendees listed in the attendees frontmatter. 

**CRM Directory:** `{CRM_DIR}` (derived in Step 1)

Create the `{CRM_DIR}` directory if it does not already exist.

#### Scope

- Process every attendee from the `{ATTENDEE_NAMES}` list (Step 3) **except** `{FULL_NAME}` (the person the summary is written for). Never create a CRM note for `{FULL_NAME}`.
- If **no** personal information was shared by or about an attendee in this meeting, skip them entirely — do not create or update a note.

#### What to Extract

Scan the transcript for casual, personal, or relationship details such as:

- Partner / spouse name
- Children's or family members' names
- Pets
- Where they live or are relocating to
- Upcoming or recent vacations / trips
- Hobbies, interests, or side projects
- Fun facts or personal anecdotes
- Recent life events (new home, wedding, marathon, etc.)

Keep each fact to a single concise bullet — enough to jog your memory before the next conversation, not a full biography.

#### File Naming

Use the same `Name (email)` format as the attendee wikilinks:

```
{CRM_DIR}/{ATTENDEE_NAME} ({ATTENDEE_EMAIL}).md
```

Example: `{CRM_DIR}/Joseph Cramer (joseph.cramer@snowflake.com).md`

Apply the same name-cleaning and character-sanitization rules from Step 3 to the filename.  The file name should represent the Obsidian wikilink destination for the attendee. 

#### Create vs Update Logic

1. **Check** if `{CRM_DIR}/{ATTENDEE_NAME} ({ATTENDEE_EMAIL}).md` exists.
2. **If it does NOT exist** — create the file using the template below.
3. **If it DOES exist** — read the file, merge new facts into the `## Personal Notes` section (skip duplicates or facts already captured), append a new entry to the `## Interaction Log`, and update the `last_updated` frontmatter field. Preserve all existing content.
4. Add the date when adding the personal note. 

#### CRM Note Template (new file)

```
---
name: {ATTENDEE_NAME}
email: {ATTENDEE_EMAIL}
last_updated: {MEETING_DATE yyyy-mm-dd}
---

# {ATTENDEE_NAME}

## Personal Notes
- {fact 1} (yyyy-mm-dd)
- {fact 2} (yyyy-mm-dd)

## Interaction Log
- **{MEETING_DATE yyyy-mm-dd}** — {one-sentence context of what was shared}
```

#### Update Rules

- Add new bullet points to **Personal Notes**; do not duplicate facts already present.
- Append a new line to **Interaction Log** with the meeting date and a brief note of what new info came up.
- Update `last_updated` in the frontmatter to the current meeting's date.
- Keep the tone casual and brief — this is a quick-reference cheat sheet, not meeting minutes.

### Step 9: Final Output to User
After completing all steps, output ONLY the following to the user:

1. A brief 1-2 sentence description of what was processed
2. The file paths where outputs were saved
3. If any CRM notes were created or updated in Step 8, list the file paths

**Example output:**
```
Meeting summary complete.

**Summary saved to:** `/Users/.../2025-05-28 Microsoft Positioning QBR.md`

**CRM notes updated:**
- Created: `/Users/.../CRM/Joseph Cramer (joseph.cramer@snowflake.com).md`
- Updated: `/Users/.../CRM/Sarah Chen (sarah.chen@contoso.com).md`
```

If no personal information was found for any attendees, omit the CRM notes section from the output.

**DO NOT:**
- Include the meeting summary content in the response
- Provide a recap of the meeting
- Ask follow-up questions
- Offer to make modifications