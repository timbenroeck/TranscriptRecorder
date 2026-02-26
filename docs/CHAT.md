# Meeting Chat

The Meeting Chat tab provides an interactive LLM chat interface within Transcript Recorder. You can ask questions about a meeting transcript and get streaming AI responses, then save, export, and resume conversations.

## Overview

Meeting Chat runs a configurable CLI tool (Cortex, Claude, or any CLI that supports the Anthropic stream-json protocol) in the background to communicate with an LLM. Each message is a one-shot CLI invocation with conversation history embedded in the prompt. Sessions are persisted to JSON files so you can close the app and resume where you left off.

## CLI Backend

### How the CLI Is Invoked

Each time you send a message, the widget spawns a subprocess:

```
<cli_binary> --output-format stream-json [-m <model>] [extra_args...] [-c <connection>] -p "<prompt>"
```

If `model` is blank (empty string), the `-m` flag is omitted entirely and the CLI uses its own default model.

The prompt contains the system prompt (configurable), conversation history (last N messages, configurable via `max_history_messages`), the user's new message, and optionally the meeting transcript.

The subprocess stdout is parsed as newline-delimited JSON (Anthropic stream-json format). Each JSON line may contain `text`, `thinking`, `tool_use`, or `tool_result` content blocks. The widget displays thinking blocks in a collapsible section and text blocks as rendered markdown.

### Configuring the CLI

All chat settings are edited via **Chat > Edit Chat Config...**, which opens a JSON editor for the `chat` section of `config.json`.

| Config Key | Default | Description |
|---|---|---|
| `cli_binary` | `"cortex"` | Executable name on PATH |
| `cli_extra_args` | `[]` | Additional flags passed before `-p` |

### Supported CLIs

| CLI | Binary | Typical Extra Args | Notes |
|---|---|---|---|
| **Snowflake Cortex** | `cortex` | `["--bypass"]` | Uses `-c` for Snowflake connection from `~/.snowflake/connections.toml` |
| **Claude Code** | `claude` | `[]` | Uses the same stream-json output format |

Any CLI that accepts `-p PROMPT --output-format stream-json` (and optionally `-m MODEL`) and emits Anthropic-style JSON can be used.

## System Prompt

The system prompt is the preamble prepended to every prompt sent to the CLI. It is configurable via the `system_prompt` key in the chat config:

```json
"system_prompt": "You are a helpful assistant analyzing a meeting transcript. Respond in well-formatted markdown. Be concise and specific."
```

If set to an empty string, no system prompt is prepended.

## Conversation History

### Prompt Stuffing (Client-Side History)

When you use `-p` (print mode), the CLI performs a stateless, one-shot request. There is **no server-side session** — the CLI does not remember previous messages.

Instead, the app manages history client-side by embedding the last N messages into every prompt:

```
System: You are a helpful assistant analyzing a meeting transcript...

User: What were the key decisions?
Assistant: Based on the transcript, the key decisions were...

User: Can you elaborate on decision #2?
```

This approach is portable across all supported CLIs and does not depend on any server-side session management.

### History Sliding Window

To keep prompts within token limits, only the **last N messages** are included in the prompt, where N is controlled by `max_history_messages` (default: 5). For example, with the default of 5 you get roughly 2-3 user/assistant turns of context. Older messages are still stored in the session JSON but are not sent to the LLM.

Error responses (CLI failures) are excluded from the history window — they are stored in the session for reference but not fed back to the LLM.

### Transcript Context

The meeting transcript is automatically included with the **first message** of a new chat. After that, it is not re-sent on subsequent messages to avoid ballooning the prompt size.

#### Chat History Indicator

The chat history indicator in the input area shows the current transcript context state. The indicator updates automatically when a transcript capture completes (manual or auto). After a message is sent, the indicator reflects the **mode** that was used (full transcript, last N lines, or update), not just a generic "included" label.

| Indicator | Meaning |
|---|---|
| "Chat History: full transcript auto-included on first send" | New chat — the full transcript will be auto-included with the first send |
| "Transcript in msg 1 of 2 (10:30 AM)" | Full transcript was sent and is at position 1 in the 2-message history window |
| "Transcript in msg 1 of 4 (10:30 AM), +15 new lines" | Transcript is in the window and the transcript has grown since inclusion |
| "Transcript not in last 4 msgs" | The transcript-bearing message has scrolled out of the history window |
| "Chat History: full transcript queued" | User chose "Full Transcript"; it will be attached to the next send |
| "Chat History: transcript update queued" | User chose "New Since Last Include"; only new lines will be sent |
| "Chat History: last N lines queued" | User chose "Last N Lines..."; the trailing N lines will be sent |
| "Chat History: no transcript" | User chose "No Transcript"; no transcript will be included |

Hovering over the indicator shows a tooltip with additional detail about the history window size and max configuration.

#### Transcript Button

A "Transcript" dropdown button is always visible in the input area, providing four actions:

- **Full Transcript** — sends the entire current transcript with the next message. Available even on a new chat if you want to explicitly choose full inclusion.
- **New Since Last Include** — sends only the lines added since the transcript was last included. Enabled only when the transcript has grown (line count is higher than the stored snapshot).
- **Last N Lines...** — opens a dialog showing the total number of lines in the transcript and a spinner to choose how many trailing lines to include. Useful when you want a specific amount of recent context without re-sending the full transcript.
- **No Transcript** — opts out of transcript inclusion entirely for the next message. On a new chat, this prevents auto-inclusion so you can ask the LLM a question without meeting context. Also cancels any queued transcript inclusion.

All options except "No Transcript" are available before the first message, letting you choose how much of the transcript to include on the initial send (instead of always auto-including the full transcript). "New Since Last Include" is disabled when there is no previous inclusion to diff against.

An info button (`?`) to the right of the Transcript button opens a scrollable dialog explaining how transcript context works, including auto-inclusion, history window behavior, capture updates, and backups.

#### Transcript Snapshots

Each time the transcript is included (first send or re-include), the app records:

- **Line count** — the number of transcript lines at the time of inclusion, stored as `transcript_line_count` on the message.
- **Timestamp** — the human-readable time of inclusion (e.g. "10:30 AM"), stored as `transcript_included_at`.

These are persisted in the session JSON and used to detect transcript growth and compute diffs.

#### Transcript Backups

A full copy of the transcript is saved to the recording's `.backup/` folder every time it is included:

```
<recording_directory>/.backup/transcript_<session_id>.txt
```

One backup file per session, overwritten on each inclusion. The backup always contains the full transcript regardless of whether "Full" or "New Content Only" was selected for the prompt. This provides a point-in-time reference.

#### Collapsible Transcript in Chat Bubbles

Each user message that includes a transcript shows a collapsible "Transcript" section below the message content, similar to the collapsible "Thinking" section on assistant messages. The toggle label describes the inclusion mode:

- **Full Transcript** — the entire transcript was sent
- **Transcript (last 50 lines)** — only the trailing N lines were sent
- **Transcript Update (new content)** — only new lines since the previous inclusion were sent

Click the toggle to expand/collapse and see the actual transcript text that was sent with that message. When reloading a saved session, the transcript is reconstructed from the backup file using the stored line range. If the backup was overwritten by a later inclusion, a placeholder message is shown instead.

### System Prompt Banner

A collapsible "System Prompt" banner appears at the top of the chat history (above all message bubbles) once the first message is sent or when a session is loaded. It shows the system prompt that was used for the session.

The banner is collapsed by default — click the toggle to expand and see the prompt text. When loading a saved session, the banner shows the system prompt that was stored with the session, which may differ from the current config if the user changed it after the session was created.

### Cortex Session IDs

The Cortex CLI has its own session management (`--continue`, `--resume`), but those features require interactive mode — not `-p` print mode. The app does not use Cortex sessions. All memory is managed by the app's session files.

## Session Persistence

### Data Model

Each recording folder contains:

```
<recording>/
  .backup/
    transcript_20260224_090000.txt   # Transcript snapshot (one per session)
  chats/
    chats.json                       # Manifest of all chat sessions
    sessions/
      20260224_090000.json           # Serialised message history
```

The markdown export (`chat_<id>.md`) is written to `chat_export_directory` if configured, otherwise to `chats/`. Only one copy is created; its full path is tracked in `chats.json`.

### chats.json (Manifest)

The manifest maps session IDs to metadata:

```json
{
  "chats": [
    {
      "id": "20260224_090000",
      "created": "2026-02-24T09:00:00",
      "updated": "2026-02-24T09:15:00",
      "title": "What were the key decisions?",
      "model": "auto",
      "cli_binary": "cortex",
      "assistant_name": "Assistant",
      "message_count": 6,
      "markdown_file": "/Users/.../obsidian/chat_20260224_090000.md",
      "session_file": "sessions/20260224_090000.json",
      "transcript_directory": "/path/to/recording"
    }
  ]
}
```

The `markdown_file` field holds the **full absolute path** to the markdown export. If `chat_export_directory` is configured, the file is written there; otherwise it goes to the recording's `chats/` folder. The field is empty until the chat is explicitly saved (manual or auto-save).

### Session Files

Each session file (`sessions/<id>.json`) stores the full conversation:

```json
{
  "id": "20260224_090000",
  "model": "",
  "connection": "snowflake",
  "assistant_name": "Assistant",
  "cli_binary": "cortex",
  "system_prompt": "You are a helpful assistant analyzing a meeting transcript...",
  "messages": [
    {
      "role": "user",
      "content": "What were the key decisions?",
      "has_transcript": true,
      "transcript_line_count": 142,
      "transcript_included_at": "10:30 AM",
      "transcript_mode": "full",
      "transcript_lines_sent": 142,
      "transcript_start_line": 0,
      "transcript_backup_file": ".backup/transcript_20260224_090000.txt"
    },
    {"role": "assistant", "content": "...", "thinking": "..."}
  ]
}
```

The `system_prompt` field stores the system prompt used for the session so it can be displayed in the system prompt banner when the session is reloaded.

Messages may also include `"is_error": true` for CLI failures — these are stored for reference but excluded from the prompt history. The transcript-related fields are only present on user messages where the transcript was included:

| Field | Description |
|---|---|
| `transcript_line_count` | Total lines in the transcript at the time of inclusion |
| `transcript_included_at` | Human-readable timestamp (e.g. "10:30 AM") |
| `transcript_mode` | `"full"`, `"last_n"`, or `"updates"` |
| `transcript_lines_sent` | Actual number of lines included in the prompt |
| `transcript_start_line` | 0-based start offset into the backup file |
| `transcript_backup_file` | Relative path to the backup file (e.g. `.backup/transcript_<id>.txt`) |

### Session Lifecycle

1. **New Chat** — Selecting "New Chat" from the dropdown clears the UI and resets state.
2. **First Send** — A session ID is generated (timestamp-based), the session file is created, and the manifest is updated.
3. **Each Turn** — After the assistant responds, the session JSON is saved and the manifest is updated.
4. **Save** — The markdown export (with frontmatter) is written. If auto-save is on, this happens after every turn.
5. **Resume** — Selecting a previous chat from the dropdown loads the session JSON, rebuilds the message bubbles, and continues from where you left off.
6. **Delete** — The Delete button (trash icon) removes the session file, markdown export, and manifest entry after confirmation. To start fresh without deleting, select "New Chat" from the dropdown.

## Markdown Export

### Frontmatter

Exported markdown files include YAML frontmatter:

```yaml
---
date: 2026-02-24 09:00 AM
model: auto
assistant_name: Assistant
chat_id: "20260224_090000"
transcript_directory: /path/to/recording
---
```

### Export Directory

By default, markdown is saved to the recording's `chats/` folder. If `chat_export_directory` is configured, the markdown is written there instead (e.g. an Obsidian vault). Only one copy is created. The session JSON and manifest always remain with the recording.

## Chat Logging

When `chat_logging` is enabled, verbose diagnostic output is written to the **main application log** (`gui_client.log`) at DEBUG level. This includes:

- The full CLI command, model, and connection
- The complete prompt text with embedded history
- The exit code, thinking text, response text, and any stderr output

To see this output, set `logging.level` to `"DEBUG"` in `config.json` and open the log from **Maintenance > Open Logs**.

When `chat_logging` is disabled (default), only summary-level INFO messages are logged (e.g. "Chat: sending prompt to cortex, model=auto").

## Configuration Reference

All settings live under the `chat` key in `config.json`. Edit them via **Chat > Edit Chat Config...** which opens a JSON editor.

```json
{
  "chat": {
    "system_prompt": "You are a helpful assistant analyzing a meeting transcript. Respond in well-formatted markdown. Be concise and specific.",
    "cli_binary": "cortex",
    "cli_extra_args": [],
    "cortex_connection": "",
    "model": "",
    "assistant_name": "Cortex",
    "chat_export_directory": "",
    "auto_save": false,
    "chat_logging": false,
    "max_history_messages": 5,
    "prompts": [
      {
        "label": "Summarize Technical Details",
        "text": "Can you summarize the technical details in this meeting"
      }
    ]
  }
}
```

| Key | Type | Default | Description |
|---|---|---|---|
| `system_prompt` | string | *(see above)* | System preamble prepended to every prompt |
| `cli_binary` | string | `"cortex"` | CLI executable name |
| `cli_extra_args` | string[] | `[]` | Additional CLI flags |
| `cortex_connection` | string | `""` | Connection name passed via `-c` (blank = default) |
| `model` | string | `""` | LLM model identifier (blank = CLI default, shown as "auto") |
| `assistant_name` | string | `"Cortex"` | Display name in bubbles and exports |
| `chat_export_directory` | string | `""` | Directory for markdown export (blank = recording's `chats/` folder) |
| `auto_save` | boolean | `false` | Auto-save markdown after each response |
| `chat_logging` | boolean | `false` | Emit verbose chat diagnostics to the main app log |
| `max_history_messages` | integer | `5` | Number of recent messages included in each prompt |
| `prompts` | array | *(see below)* | Pre-defined prompts shown in the Prompts dropdown |

Each entry in `prompts` is an object with `label` (display text in the dropdown) and `text` (the prompt inserted into the input field when selected).

## UI Layout

### Header

```
[ Chat selector (dropdown) ▼ ]  [Save][Delete][Copy][Folder]
```

The dropdown shows "New Chat" plus previous sessions from `chats.json` for the current recording.

### Chat Area

The chat area contains, in order from top to bottom:

1. **System Prompt Banner** (collapsible) — appears after the first message is sent or when a session is loaded. Shows the system prompt used for the session.
2. **Message Bubbles** — user messages (blue tint) and assistant messages (neutral). Each assistant bubble has a collapsible "Thinking" section. Each user bubble that included a transcript has a collapsible "Transcript" section showing the actual text that was sent.

### Input Area

```
[Prompts v]       Transcript in msg 1 of 2 (10:30 AM), +5 new lines  [Transcript ▾] [?]
[ Type your message...                                                            ] [Send]
```

The Prompts dropdown, chat history indicator, Transcript dropdown, and info button share a row above the text input. Selecting a prompt from the dropdown populates the input field (it does not send automatically). The Transcript button is always visible with consistent text; its menu actions are enabled/disabled based on state. The info button (`?`) opens a scrollable dialog explaining transcript context behavior.

### Button Bar

| Icon | Action |
|---|---|
| Save (disk) | Save chat to markdown with frontmatter |
| Trash | Delete the current chat session (with confirmation) |
| Copy | Copy entire conversation to clipboard |
| Folder | Open the chats directory in Finder |
