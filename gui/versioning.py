"""
Hash-based versioning and backup utilities for rules and tools.

Hashes are computed **only by CI** (see .github/workflows/hash-definitions.yml).
The client never computes hashes -- it only reads and compares the .sha256
sibling files that CI commits alongside each rule.json / tool.json.
"""
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def read_stored_hash(json_path: Path) -> Optional[str]:
    """Read the CI-authored ``.sha256`` sibling file for a JSON definition.

    For example, given ``rules/zoom/rule.json`` this reads
    ``rules/zoom/rule.json.sha256``.

    Returns:
        The hash string (stripped), or ``None`` if the file is missing
        or unreadable.
    """
    hash_path = json_path.parent / f"{json_path.name}.sha256"
    try:
        if hash_path.exists():
            return hash_path.read_text(encoding="utf-8").strip()
    except Exception as e:
        logger.debug(f"versioning: could not read {hash_path}: {e}")
    return None


def is_update_available(local_hash: Optional[str], remote_hash: str) -> bool:
    """Compare a local hash against a remote hash.

    Returns ``True`` when the remote hash differs from the local hash,
    meaning the upstream definition has changed since the user last
    installed or updated.
    """
    if local_hash is None:
        # No local hash means we can't determine -- treat as no update
        return False
    return local_hash.strip() != remote_hash.strip()


def backup_json_file(json_path: Path, max_backups: int = 3) -> Optional[Path]:
    """Create a timestamped backup of a JSON file, keeping at most *max_backups*.

    Generalised from ``_backup_tool_json`` in ``tool_dialogs.py``.

    Returns:
        The ``Path`` of the new backup file, or ``None`` if the source
        file does not exist.
    """
    if not json_path.exists():
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = json_path.parent / f"{json_path.name}.bak.{timestamp}"
    shutil.copy2(json_path, backup_path)
    logger.info(f"versioning: backed up {json_path} -> {backup_path.name}")

    # Prune old backups (keep newest max_backups)
    pattern = f"{json_path.name}.bak.*"
    backups = sorted(
        json_path.parent.glob(pattern),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in backups[max_backups:]:
        try:
            old.unlink()
            logger.debug(f"versioning: pruned old backup {old.name}")
        except OSError:
            pass

    return backup_path


def backup_data_files(
    json_path: Path, data_files: list, max_backups: int = 3
) -> list:
    """Back up data files declared alongside a JSON definition.

    *data_files* is a list of dicts, each with a ``"file"`` key containing
    a relative path from the JSON file's parent directory.  This matches
    the ``data_files`` array in ``tool.json`` / ``rule.json``.

    Returns:
        A list of backup ``Path`` objects that were created.
    """
    created: list = []
    base_dir = json_path.parent
    for entry in data_files:
        rel = entry.get("file", "")
        if not rel:
            continue
        data_path = base_dir / rel
        if data_path.exists():
            bp = backup_json_file(data_path, max_backups=max_backups)
            if bp:
                created.append(bp)
    return created
