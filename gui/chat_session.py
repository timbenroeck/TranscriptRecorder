"""
Chat session persistence — manages chats.json manifest and session JSON files.

Each recording's ``chats/`` folder may contain:

    chats/
      chats.json              # manifest of all sessions for this recording
      sessions/
        <id>.json             # serialized message history per session
      chat_<id>.md            # markdown export

History is entirely client-managed.  Each CLI call uses ``-p`` (one-shot
print mode) with no server-side session.  The prompt is built by embedding
the last N messages into the prompt text.  The session JSON enables
reloading a previous chat and continuing it.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from gui.constants import logger


@dataclass
class ChatMessage:
    """Serialisable representation of a single chat message."""
    role: str
    content: str
    thinking: str = ""
    has_transcript: bool = False
    is_error: bool = False
    transcript_line_count: int = 0
    transcript_included_at: str = ""
    transcript_mode: str = ""
    transcript_lines_sent: int = 0
    transcript_start_line: int = 0
    transcript_backup_file: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"role": self.role, "content": self.content}
        if self.thinking:
            d["thinking"] = self.thinking
        if self.has_transcript:
            d["has_transcript"] = True
        if self.is_error:
            d["is_error"] = True
        if self.transcript_line_count:
            d["transcript_line_count"] = self.transcript_line_count
        if self.transcript_included_at:
            d["transcript_included_at"] = self.transcript_included_at
        if self.transcript_mode:
            d["transcript_mode"] = self.transcript_mode
        if self.transcript_lines_sent:
            d["transcript_lines_sent"] = self.transcript_lines_sent
        if self.transcript_start_line:
            d["transcript_start_line"] = self.transcript_start_line
        if self.transcript_backup_file:
            d["transcript_backup_file"] = self.transcript_backup_file
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ChatMessage":
        return cls(
            role=d.get("role", "user"),
            content=d.get("content", ""),
            thinking=d.get("thinking", ""),
            has_transcript=d.get("has_transcript", False),
            is_error=d.get("is_error", False),
            transcript_line_count=d.get("transcript_line_count", 0),
            transcript_included_at=d.get("transcript_included_at", ""),
            transcript_mode=d.get("transcript_mode", ""),
            transcript_lines_sent=d.get("transcript_lines_sent", 0),
            transcript_start_line=d.get("transcript_start_line", 0),
            transcript_backup_file=d.get("transcript_backup_file", ""),
        )


@dataclass
class ChatSessionMeta:
    """Metadata stored in chats.json for one chat session."""
    id: str
    created: str
    updated: str
    title: str = ""
    model: str = "claude-opus-4-5"
    cli_binary: str = "cortex"
    assistant_name: str = "Assistant"
    message_count: int = 0
    markdown_file: str = ""
    session_file: str = ""
    transcript_directory: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ChatSessionMeta":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class SessionData:
    """Full serialised session including messages."""
    id: str
    model: str = "claude-opus-4-5"
    connection: str = ""
    assistant_name: str = "Assistant"
    cli_binary: str = "cortex"
    system_prompt: str = ""
    messages: List[ChatMessage] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "id": self.id,
            "model": self.model,
            "connection": self.connection,
            "assistant_name": self.assistant_name,
            "cli_binary": self.cli_binary,
            "messages": [m.to_dict() for m in self.messages],
        }
        if self.system_prompt:
            d["system_prompt"] = self.system_prompt
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SessionData":
        msgs = [ChatMessage.from_dict(m) for m in d.get("messages", [])]
        return cls(
            id=d.get("id", ""),
            model=d.get("model", "claude-opus-4-5"),
            connection=d.get("connection", ""),
            assistant_name=d.get("assistant_name", "Assistant"),
            cli_binary=d.get("cli_binary", "cortex"),
            system_prompt=d.get("system_prompt", ""),
            messages=msgs,
        )


class ChatSessionManager:
    """Manages ``chats.json`` manifest and ``sessions/*.json`` files."""

    @staticmethod
    def _chats_dir(recording_path: Path) -> Path:
        return recording_path / "chats"

    @staticmethod
    def _manifest_path(recording_path: Path) -> Path:
        return recording_path / "chats" / "chats.json"

    @staticmethod
    def _sessions_dir(recording_path: Path) -> Path:
        return recording_path / "chats" / "sessions"

    # -- manifest I/O --

    @classmethod
    def list_sessions(cls, recording_path: Path) -> List[ChatSessionMeta]:
        """Return all session metadata from chats.json, newest first."""
        manifest = cls._manifest_path(recording_path)
        if not manifest.exists():
            return []
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            entries = [ChatSessionMeta.from_dict(c) for c in data.get("chats", [])]
            entries.sort(key=lambda e: e.created, reverse=True)
            return entries
        except Exception as e:
            logger.warning(f"ChatSessionManager: failed to read manifest: {e}")
            return []

    @classmethod
    def update_manifest(cls, recording_path: Path,
                        meta: ChatSessionMeta) -> None:
        """Insert or update a session entry in chats.json."""
        chats_dir = cls._chats_dir(recording_path)
        chats_dir.mkdir(parents=True, exist_ok=True)
        manifest = cls._manifest_path(recording_path)

        entries: List[Dict[str, Any]] = []
        if manifest.exists():
            try:
                entries = json.loads(
                    manifest.read_text(encoding="utf-8")
                ).get("chats", [])
            except Exception:
                entries = []

        updated = False
        for i, entry in enumerate(entries):
            if entry.get("id") == meta.id:
                entries[i] = meta.to_dict()
                updated = True
                break
        if not updated:
            entries.append(meta.to_dict())

        manifest.write_text(
            json.dumps({"chats": entries}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # -- session file I/O --

    @classmethod
    def save_session(cls, recording_path: Path,
                     session: SessionData) -> Path:
        """Write a session's messages to ``sessions/<id>.json``."""
        sessions_dir = cls._sessions_dir(recording_path)
        sessions_dir.mkdir(parents=True, exist_ok=True)
        filepath = sessions_dir / f"{session.id}.json"
        filepath.write_text(
            json.dumps(session.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return filepath

    @classmethod
    def load_session(cls, recording_path: Path,
                     session_id: str) -> Optional[SessionData]:
        """Load a session from ``sessions/<id>.json``."""
        filepath = cls._sessions_dir(recording_path) / f"{session_id}.json"
        if not filepath.exists():
            return None
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            return SessionData.from_dict(data)
        except Exception as e:
            logger.warning(f"ChatSessionManager: failed to load session "
                           f"{session_id}: {e}")
            return None

    @classmethod
    def delete_session(cls, recording_path: Path, session_id: str) -> None:
        """Delete a session's JSON file, markdown export, and manifest entry."""
        session_file = cls._sessions_dir(recording_path) / f"{session_id}.json"
        if session_file.exists():
            session_file.unlink()
            logger.info(f"ChatSessionManager: deleted session file {session_file}")

        manifest = cls._manifest_path(recording_path)
        md_path: Optional[str] = None
        if manifest.exists():
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
                entries = data.get("chats", [])
                for e in entries:
                    if e.get("id") == session_id:
                        md_path = e.get("markdown_file", "")
                        break
                entries = [e for e in entries if e.get("id") != session_id]
                manifest.write_text(
                    json.dumps({"chats": entries}, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            except Exception as e:
                logger.warning(f"ChatSessionManager: failed to update manifest "
                               f"after delete: {e}")

        if md_path:
            md_file = Path(md_path)
            if md_file.exists():
                md_file.unlink()
                logger.info(f"ChatSessionManager: deleted markdown {md_file}")

    @classmethod
    def generate_id(cls) -> str:
        """Generate a timestamp-based session ID."""
        return datetime.now().strftime("%Y%m%d_%H%M%S")
