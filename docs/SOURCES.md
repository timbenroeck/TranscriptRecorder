# Sources — Developer Guide

Transcript Recorder uses a plugin-style **Sources** system to capture live transcripts from meeting applications. Each source defines how the app finds and reads transcript content from a specific application using the macOS Accessibility API. Sources are discovered automatically at startup — no app changes needed to add one.

This guide covers everything you need to understand, create, and contribute sources.

---

## Table of Contents

- [Overview](#overview)
- [How Sources Work](#how-sources-work)
- [Directory Structure](#directory-structure)
- [source.json Reference](#sourcejson-reference)
  - [Top-Level Fields](#top-level-fields)
  - [Transcript Search Paths](#transcript-search-paths)
  - [Search Steps](#search-steps)
  - [Step Matching Criteria](#step-matching-criteria)
  - [Serialization Fields](#serialization-fields)
- [Built-in Manual Recording](#built-in-manual-recording)
- [Bundled Sources](#bundled-sources)
- [Creating a New Source](#creating-a-new-source)
  - [Step-by-Step Walkthrough](#step-by-step-walkthrough)
  - [Using the Accessibility Inspector](#using-the-accessibility-inspector)
  - [Tips for Building Search Paths](#tips-for-building-search-paths)
  - [Minimal Example](#minimal-example)
  - [Full Example (Zoom)](#full-example-zoom)
- [Managing Sources in the App](#managing-sources-in-the-app)
- [Contributing a Source](#contributing-a-source)
  - [Repository Structure](#repository-structure)
  - [Contribution Checklist](#contribution-checklist)
  - [Bundle Manifest](#bundle-manifest)
  - [CI / GitHub Actions](#ci--github-actions)
  - [Reserved Names](#reserved-names)
- [Troubleshooting](#troubleshooting)

---

## Overview

When you select a source from the dropdown (e.g. Zoom, Microsoft Teams) and start a recording session, the app:

1. **Detects** whether the meeting application is running by checking `command_paths`
2. **Walks** the application's accessibility tree using the `transcript_search_paths` to locate the transcript UI element
3. **Serializes** the text content from the found element using `serialization_text_element_roles`
4. **Merges** captured snapshots into a clean `meeting_transcript.txt` file

Sources are loaded from the `sources/` directory inside your export folder (by default `~/Documents/TranscriptRecorder/sources/`). The app scans every immediate sub-directory for a `source.json` file, validates its structure, and populates the dropdown.

---

## How Sources Work

The macOS Accessibility API exposes every application's UI as a tree of elements, each with a role (e.g. `AXWindow`, `AXTable`, `AXStaticText`), attributes (title, description, value), and children. Meeting applications render their transcript/caption content somewhere in this tree.

A source tells Transcript Recorder **where** to look in that tree and **how** to extract text from what it finds. The search is defined as a sequence of **paths**, each containing **steps** that progressively narrow down to the transcript element:

```
Application Process
    └─ AXWindow (title contains "Transcript")      ← Step 1: find the window
        └─ AXTable (description contains "list")    ← Step 2: find the table
            └─ AXStaticText                          ← Serialization: extract text
```

Multiple paths can be defined for the same application. The app tries each path in order and uses the first one that successfully locates the transcript element. This is useful when an application has different UI layouts depending on window configuration (e.g. Zoom's separate transcript window vs. in-meeting captions panel).

---

## Directory Structure

Each source lives in its own sub-folder:

```
~/Documents/TranscriptRecorder/
└── sources/
    └── zoom/
        ├── source.json             # Required — source definition
        └── source.json.sha256      # Auto-generated hash (CI creates this)
```

The folder name (e.g. `zoom`, `msteams`) is the **source key** — a unique identifier used in configuration and logs. It should be lowercase, use underscores for spaces, and match the application it targets.

---

## source.json Reference

### Top-Level Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `display_name` | string | **Yes** | — | Name shown in the application dropdown |
| `command_paths` | array | **Yes** | — | Filesystem paths to the application's executable. Used to detect if the app is running. |
| `transcript_search_paths` | array | **Yes** | — | Ordered list of search paths to locate the transcript element (see below) |
| `traversal_mode` | string | No | `"bfs"` | Tree search strategy: `"bfs"` (breadth-first) or `"dfs"` (depth-first) |
| `traversal_roles_to_skip` | array | No | `[]` | AX roles to skip during tree traversal (e.g. `"AXButton"`, `"AXImage"`) |
| `serialization_text_element_roles` | object | No | `{}` | Map of AX role to attribute name for text extraction (see [Serialization Fields](#serialization-fields)) |
| `serialization_export_depth` | int | No | `10` | How many levels deep to traverse when serializing text content |
| `serialization_save_json` | bool | No | `false` | Save the raw accessibility tree as JSON for debugging |
| `monitor_interval_seconds` | int | No | `30` | Default capture interval in seconds for auto-capture |
| `exclude_pattern` | string | No | — | Regex pattern to filter out unwanted text lines during serialization |
| `incremental_export` | bool | No | `false` | When true, only exports new rows since the last capture |

### Transcript Search Paths

The `transcript_search_paths` array is the core of a source definition. Each entry is a **path** — a named sequence of steps that the app executes in order to locate the transcript element.

```json
"transcript_search_paths": [
  {
    "path_name": "Transcript Window Path",
    "steps": [ ... ]
  },
  {
    "path_name": "Main Meeting Window Path",
    "steps": [ ... ]
  }
]
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `path_name` | string | No | Human-readable label for this path (used in logs and the Source Editor) |
| `steps` | array | **Yes** | Ordered list of search steps |

Paths are tried **in order**. The first path whose steps all succeed is used. If all paths fail, the capture attempt reports that the transcript element was not found.

### Search Steps

Each step in a path narrows the search by finding elements that match specified criteria within a limited depth from the current position.

```json
{
  "role": "AXWindow",
  "title_contains": "Transcript",
  "search_scope": {
    "levels_deep": 1
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `role` | string | No | AX role the element must have (e.g. `AXWindow`, `AXTable`, `AXGroup`) |
| `search_scope` | object | No | Search depth configuration |
| `search_scope.levels_deep` | int | No | How many levels deep to search from the current position (default: `1`) |
| `index` | int | No | If multiple elements match, select the one at this index (0-based) |

Plus one or more **matching criteria** (see below).

### Step Matching Criteria

Each step can use one or more of these criteria to identify the target element. All specified criteria must match (AND logic).

| Criterion | Type | Description |
|-----------|------|-------------|
| `role` | string | Exact match on the element's AX role |
| `title` | string | Exact match on the element's `AXTitle` attribute |
| `title_contains` | string | Substring match on `AXTitle` |
| `title_matches_one_of` | array | `AXTitle` must equal one of the provided strings |
| `description` | string | Exact match on the element's `AXDescription` attribute |
| `description_contains` | string | Substring match on `AXDescription` |

**Example — Match a window whose title contains "Transcript":**

```json
{
  "role": "AXWindow",
  "title_contains": "Transcript",
  "search_scope": { "levels_deep": 1 }
}
```

**Example — Match a window with one of several possible titles:**

```json
{
  "role": "AXWindow",
  "title_matches_one_of": ["Transcript", "Captions"],
  "search_scope": { "levels_deep": 1 }
}
```

### Serialization Fields

Once the transcript element is located, the app traverses its children to extract text content.

| Field | Description |
|-------|-------------|
| `serialization_text_element_roles` | A JSON object mapping AX role names to the attribute that holds the text. For example, `{"AXStaticText": "AXValue"}` means "for every `AXStaticText` element, read its `AXValue` attribute." |
| `serialization_export_depth` | How deep to traverse below the found transcript element when extracting text. Set this high enough to reach all text nodes, but not so high that unrelated content is captured. |
| `serialization_save_json` | When `true`, the full accessibility tree below the transcript element is saved as a JSON file in the `.snapshots` directory. Useful for debugging but generates large files. |

**Common serialization patterns:**

```json
// Zoom — text is in AXTextArea and AXStaticText elements
"serialization_text_element_roles": {
  "AXTextArea": "AXValue",
  "AXStaticText": "AXValue"
}

// Microsoft Teams — text is in AXStaticText and AXCell elements
"serialization_text_element_roles": {
  "AXStaticText": "AXValue",
  "AXCell": "AXDescription"
}
```

---

## Built-in Manual Recording

The app includes a built-in **Manual Recording** source that is always available, even with no sources installed. It allows the user to paste or type a transcript directly — no accessibility permissions or meeting application required.

Manual Recording is a virtual source (it does not exist as a `source.json` on disk) and uses the reserved key `manual`. You cannot create a source directory named `manual`.

---

## Bundled Sources

The app ships with sources for **Zoom** and **Microsoft Teams** baked into the application bundle. These are automatically copied into the user's `sources/` directory on first launch (existing sources are never overwritten).

Additional sources (Slack, WebEx, etc.) are available in the repository and can be downloaded via **Sources > Import Sources...** in the app.

Which sources are bundled with the app is controlled by the `bundle.json` manifest at the repository root:

```json
{
  "sources": ["zoom", "msteams"],
  "tools": ["clean_transcript"]
}
```

Only sources explicitly listed in the `"sources"` array are included in the built `.app`. See [Bundle Manifest](#bundle-manifest) for details.

---

## Creating a New Source

### Step-by-Step Walkthrough

1. **Identify the transcript UI element.** Open the meeting application, start a call with captions/transcripts enabled, and use the macOS **Accessibility Inspector** (built into Xcode) or Transcript Recorder's built-in **Accessibility Inspector** (Sources > Accessibility Inspector) to explore the accessibility tree.

2. **Map the path.** Starting from the application root, note the chain of elements that leads to the transcript content. Record each element's role, title or description, and how many levels deep it sits relative to its parent.

3. **Create the source folder:**

   ```bash
   mkdir ~/Documents/TranscriptRecorder/sources/my_app
   ```

4. **Write `source.json`:**

   ```json
   {
     "display_name": "My Meeting App",
     "command_paths": [
       "/Applications/My Meeting App.app/Contents/MacOS/MyMeetingApp"
     ],
     "transcript_search_paths": [
       {
         "path_name": "Primary Path",
         "steps": [
           {
             "role": "AXWindow",
             "title_contains": "Captions",
             "search_scope": { "levels_deep": 1 }
           },
           {
             "role": "AXList",
             "search_scope": { "levels_deep": 5 }
           }
         ]
       }
     ],
     "serialization_text_element_roles": {
       "AXStaticText": "AXValue"
     },
     "serialization_export_depth": 10,
     "monitor_interval_seconds": 30
   }
   ```

5. **Test.** In the app, go to **Sources > Refresh Sources** to pick up the new source. Select it from the dropdown, start a meeting with captions enabled, and click **Capture** to verify it finds the transcript.

6. **Iterate.** If capture fails, check the log file (View > Log File) for details on which search paths were attempted and where they failed. Adjust `search_scope.levels_deep`, matching criteria, or `serialization_export_depth` as needed.

### Using the Accessibility Inspector

Transcript Recorder includes a built-in **Accessibility Inspector** (Sources > Accessibility Inspector) that helps you build `transcript_search_paths` without needing Xcode:

1. **Select a running application** from the dropdown.
2. **Browse the accessibility tree** — expand nodes to find the transcript element.
3. **Click a node** to auto-generate a minimal search path that targets it.
4. **Copy the generated JSON** and paste it into your `source.json`.

The inspector also supports filtering by role and searching for elements containing specific text, which is useful for large accessibility trees.

### Tips for Building Search Paths

- **Start specific, fall back to broad.** Define your most targeted path first (e.g. matching a specific window title), then add broader fallback paths.

- **Use `title_contains` or `description_contains`** instead of exact matches when possible. Applications may localize or change exact titles across versions.

- **Use `title_matches_one_of`** when an application uses different window titles depending on state (e.g. `["Transcript", "Captions"]`).

- **Keep `levels_deep` as small as possible.** Searching too deep is slower and may match unintended elements. Start with `1` and increase until the element is found.

- **Use `traversal_roles_to_skip`** to exclude irrelevant branches. Skipping `AXButton` and `AXImage` roles is common and significantly speeds up traversal.

- **Choose `bfs` vs `dfs`** based on the tree structure. Breadth-first (`bfs`) is better when the target is close to the root. Depth-first (`dfs`) is better when the target is deeply nested under a specific branch (like Teams' Live Captions).

- **Enable `serialization_save_json`** temporarily to inspect exactly what the app captures. The JSON files in `.snapshots/` show the full tree below the matched element.

- **Define multiple paths** for the same app if it has different UI layouts (e.g. Zoom's separate transcript window vs. in-meeting panel).

### Minimal Example

A source that captures from a hypothetical app with a simple accessibility tree:

```json
{
  "display_name": "Simple Captions App",
  "command_paths": ["/Applications/SimpleCaptions.app/Contents/MacOS/SimpleCaptions"],
  "transcript_search_paths": [
    {
      "path_name": "Main Window",
      "steps": [
        {
          "role": "AXList",
          "search_scope": { "levels_deep": 5 }
        }
      ]
    }
  ],
  "serialization_text_element_roles": {
    "AXStaticText": "AXValue"
  },
  "serialization_export_depth": 5
}
```

### Full Example (Zoom)

The bundled Zoom source demonstrates multiple search paths and a skip list:

```json
{
  "display_name": "Zoom",
  "command_paths": [
    "/Applications/zoom.us.app/Contents/MacOS/zoom.us"
  ],
  "transcript_search_paths": [
    {
      "path_name": "Transcript Window Path",
      "steps": [
        {
          "role": "AXWindow",
          "title_matches_one_of": ["Transcript"],
          "search_scope": { "levels_deep": 1 }
        },
        {
          "role": "AXTable",
          "description_contains": "Transcript list",
          "search_scope": { "levels_deep": 3 }
        }
      ]
    },
    {
      "path_name": "Main Meeting Window Path",
      "steps": [
        {
          "role": "AXTable",
          "description_contains": "Transcript list",
          "search_scope": { "levels_deep": 4 }
        }
      ]
    }
  ],
  "traversal_roles_to_skip": ["AXButton"],
  "traversal_mode": "bfs",
  "incremental_export": true,
  "serialization_text_element_roles": {
    "AXTextArea": "AXValue",
    "AXStaticText": "AXValue"
  },
  "serialization_export_depth": 5,
  "serialization_save_json": false,
  "monitor_interval_seconds": 30
}
```

Path 1 targets Zoom's **separate Transcript window** (a standalone window titled "Transcript"). Path 2 targets the **in-meeting transcript panel** (the table embedded directly in the meeting window). This ensures capture works regardless of how the user has Zoom configured.

---

## Managing Sources in the App

| Menu Item | Description |
|-----------|-------------|
| **Sources > Import Sources...** | Download sources from the GitHub repository |
| **Sources > Edit Source...** | Open the visual Source Editor for any installed source |
| **Sources > Accessibility Inspector** | Launch the interactive AX tree browser for building search paths |
| **Sources > Set Current as Default** | Save the selected source as the startup default |
| **Sources > Clear Default** | Remove the default source setting (falls back to Manual Recording) |
| **Sources > Open Sources Folder** | Open the sources directory in Finder |
| **Sources > Refresh Sources** | Rescan the sources directory for new or updated sources |

The **Source Editor** (Sources > Edit Source) provides a form-based GUI for editing `source.json` files. It has three tabs:

- **General** — Display name, command paths, monitor interval, traversal mode, roles to skip
- **Serialization** — Export depth, save JSON toggle, text element roles
- **Transcript Search Paths** — Visual builder for search paths and steps with add/remove controls

---

## Contributing a Source

### Repository Structure

Sources in the repository live under the `sources/` directory at the repo root:

```
TranscriptRecorder/
├── sources/
│   ├── zoom/
│   │   ├── source.json
│   │   └── source.json.sha256
│   ├── msteams/
│   │   ├── source.json
│   │   └── source.json.sha256
│   ├── slack/
│   │   ├── source.json
│   │   └── source.json.sha256
│   └── webex/
│       ├── source.json
│       └── source.json.sha256
├── bundle.json
└── ...
```

### Contribution Checklist

When contributing a new source or updating an existing one:

1. **Create a sub-directory** under `sources/` named after the application (lowercase, underscores for spaces).

2. **Add a `source.json`** with all required fields:
   - `display_name` — clear, recognizable name
   - `command_paths` — at least one path; include common installation locations
   - `transcript_search_paths` — at least one path with at least one step

3. **Test thoroughly:**
   - Verify the source detects the running application
   - Verify capture finds the transcript element in different window configurations
   - Test with auto-capture over several minutes to confirm stability
   - Check the log file for warnings about search path failures

4. **Do not include a `.sha256` file.** The CI pipeline ([hash-definitions.yml](#ci--github-actions)) automatically generates and commits `source.json.sha256` after your PR is merged.

5. **Do not modify `bundle.json`** unless your source is intended to ship with the app. Most contributed sources should be available for download via Import but not bundled.

6. **Open a pull request** with a clear description of:
   - Which meeting application the source targets
   - Which transcript/caption feature it captures from
   - Any known limitations (e.g. requires a specific app version, only works with certain UI configurations)

### Bundle Manifest

The `bundle.json` file at the repository root controls which sources and tools are **shipped inside the built `.app`**:

```json
{
  "sources": ["zoom", "msteams"],
  "tools": ["clean_transcript"]
}
```

- Only items listed here are copied into the application bundle during the `py2app` build.
- Items **not** in `bundle.json` remain in the repository and are available for users to download via **Sources > Import Sources** or **Tools > Import Tools**.
- Adding a source to `bundle.json` means it will be installed automatically on first launch for every user.

**When to add a source to the bundle:**

- The application is widely used (e.g. Zoom, Teams)
- The source has been well-tested across multiple macOS versions
- The command paths are stable across application updates

**When to leave it out of the bundle:**

- The source targets a niche or enterprise-only application
- It's newly contributed and needs more real-world testing
- The application frequently changes its UI structure, requiring frequent source updates

### CI / GitHub Actions

Two GitHub Actions workflows validate and manage sources:

#### `hash-definitions.yml` — Automatic Hashing

Triggered on pushes to `main` that modify `sources/**/source.json` or `tools/**/tool.json`. Computes SHA-256 hashes and commits `.sha256` sidecar files. These hashes are used by the app's import system to detect whether a locally installed source has been modified by the user.

**You do not need to create or update `.sha256` files manually.** The CI pipeline handles this automatically.

#### `validate-repo.yml` — Structure Validation

Triggered on pushes and pull requests that modify `sources/`, `tools/`, or `bundle.json`. Checks:

- **Reserved names** — Ensures no `sources/manual/` directory exists (reserved for the built-in Manual Recording source)
- **Bundle integrity** — Verifies every entry in `bundle.json` has a corresponding directory in the repository

### Reserved Names

The following source directory names are reserved and cannot be used:

| Name | Reason |
|------|--------|
| `manual` | Used by the built-in Manual Recording source |

The CI validation workflow will block any PR that creates a `sources/manual/` directory.

---

## Troubleshooting

### Source not appearing in the dropdown

- Verify the sub-folder is directly inside `~/Documents/TranscriptRecorder/sources/` (not nested deeper)
- Confirm the sub-folder contains a `source.json` file with valid JSON
- Check that `display_name` exists and is not empty
- Try **Sources > Refresh Sources** to re-scan
- Check the log file (View > Log File) for errors like `"invalid JSON"` or `"missing 'display_name'"`

### Application not detected

- Verify the meeting app is **running**
- Check that the `command_paths` in the source match your installation. Some apps install to different locations depending on how they were installed (App Store vs. direct download, managed browsers, etc.)
- Use **Sources > Edit Source** to view and update the command paths
- Check Activity Monitor to find the actual executable path of the running application

### Transcript not capturing

- Ensure captions/transcripts are **enabled** in your meeting application
- Make sure the transcript **window is visible** (not minimized or hidden behind other windows)
- Try clicking **Capture** to test a single manual capture
- Check the log file for messages like:
  - `"no 'transcript_search_paths' in config"` — the `source.json` is missing search paths
  - `"all search paths exhausted"` — none of the defined paths found the transcript element
  - `"transcript element not found"` — the search ran but no matching element was located

### Search path not finding the element

- **Increase `levels_deep`** — the element may be deeper in the tree than expected
- **Enable `serialization_save_json`** temporarily and run a capture. Inspect the saved JSON to understand the actual tree structure.
- **Use the Accessibility Inspector** (Sources > Accessibility Inspector) to browse the live tree and verify element roles, titles, and descriptions
- **Try a broader match** — use `description_contains` instead of an exact match, or remove the `role` constraint
- **Add a fallback path** — define a second search path with different criteria

### Capture returns empty or garbled text

- Check `serialization_text_element_roles` — you may be reading the wrong attribute. Try `"AXValue"` vs. `"AXDescription"` vs. `"AXTitle"`.
- Increase `serialization_export_depth` — text nodes may be deeper than the current depth allows
- Add an `exclude_pattern` regex to filter out unwanted content (e.g. timestamps, UI labels)
- Check `traversal_roles_to_skip` — you may be skipping roles that contain the text content

### Import fails

- Verify you have an internet connection
- The Import dialog fetches from the GitHub API. If you're behind a corporate proxy, the request may be blocked.
- Check the log file for the specific HTTP error code and URL
