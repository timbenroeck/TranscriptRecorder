#!/usr/bin/env python3
"""Migrate old recordings into the new YYYY/MM directory structure,
normalizing folder names to recording_YYYY-MM-DD_HHMM format."""

import os
import re
import shutil
import sys
from pathlib import Path

DRY_RUN = "--dry-run" in sys.argv

SRC = Path.home() / "Documents" / "transcriptrecorder_old" / "recordings"
DST = Path.home() / "Documents" / "TranscriptRecorder" / "recordings"

if not SRC.exists():
    print(f"ERROR: Source directory does not exist: {SRC}")
    sys.exit(1)

stats = {"ok": 0, "collision": 0, "no_time": 0, "skipped": 0}

for entry in sorted(SRC.iterdir()):
    if not entry.is_dir() or not entry.name.startswith("recording_"):
        continue

    name = entry.name

    # Extract the date: recording_YYYY-MM-DD_<rest>
    m = re.match(r"recording_(\d{4})-(\d{2})-(\d{2})_(.*)", name)
    if not m:
        print(f"  SKIP (no date match): {name}")
        stats["skipped"] += 1
        continue

    year, month, day, rest = m.groups()

    # Try to extract HHMM from rest. Handles:
    #   "1130"                   -> 11, 30
    #   "11-37"                  -> 11, 37
    #   "1000-18"  (HHMM-SS)    -> 10, 00  (drop seconds)
    #   "08-01_westcon"          -> 08, 01  (drop suffix)
    #   "1659_zoom"              -> 16, 59  (drop suffix)
    #   "1430 CircleK - ..."     -> 14, 30  (drop text after space)
    time_match = re.match(r"(\d{2})-?(\d{2})(?:-\d{2})?(?:[_ ].*)?$", rest)

    if time_match:
        hh, mm = time_match.groups()
        new_name = f"recording_{year}-{month}-{day}_{hh}{mm}"
    else:
        # No recognizable time (e.g. "PSP", "Snowflake_FIS") — keep original
        new_name = name
        stats["no_time"] += 1
        print(f"  NOTE (no time, keeping name): {name}")

    dst_dir = DST / year / month
    dst_path = dst_dir / new_name

    # Handle name collisions by appending _2, _3, etc.
    if dst_path.exists():
        i = 2
        while (dst_dir / f"{new_name}_{i}").exists():
            i += 1
        dst_path = dst_dir / f"{new_name}_{i}"
        stats["collision"] += 1
        print(f"  COLLISION: {name} -> {year}/{month}/{dst_path.name}")

    if DRY_RUN:
        print(f"  [DRY] {name} -> {year}/{month}/{dst_path.name}")
    else:
        dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(entry, dst_path)
        print(f"  OK: {name} -> {year}/{month}/{dst_path.name}")

    stats["ok"] += 1

print(f"\nDone! Migrated: {stats['ok']}, Collisions: {stats['collision']}, "
      f"No time (kept name): {stats['no_time']}, Skipped: {stats['skipped']}")
if DRY_RUN:
    print("(This was a dry run — no files were copied.)")
