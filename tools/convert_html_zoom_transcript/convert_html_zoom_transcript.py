#!/usr/bin/env python3
import argparse
import html as html_module
import re
import sys
from datetime import datetime
from pathlib import Path

ARIA_PATTERN = re.compile(
    r"^(.+?),\s+(?:(\d+) hours )?(?:(\d+) minutes )?(\d+) seconds,\s+(.+)$"
)
LI_ARIA_PATTERN = re.compile(
    r'<li\b[^>]*\baria-label="([^"]+)"',
    re.DOTALL,
)


def looks_like_zoom_html(text: str) -> bool:
    return bool(
        re.search(r'<li\b[^>]*\baria-label=', text)
        and re.search(r'\d+ (hours|minutes|seconds)', text)
    )


def parse_html(raw_html: str) -> list[dict]:
    entries = []
    for m in LI_ARIA_PATTERN.finditer(raw_html):
        aria = html_module.unescape(m.group(1))
        am = ARIA_PATTERN.match(aria)
        if not am:
            continue
        speaker = am.group(1).strip()
        h = int(am.group(2) or 0)
        min_ = int(am.group(3) or 0)
        s = int(am.group(4))
        timestamp = f"{h:02d}:{min_:02d}:{s:02d}"
        text = am.group(5).strip()
        if text:
            entries.append({"speaker": speaker, "timestamp": timestamp, "text": text})
    return entries


def write_transcript(entries: list[dict], path: Path):
    lines = []
    prev_speaker = None
    prev_ts = None
    for e in entries:
        if e["speaker"] != prev_speaker or e["timestamp"] != prev_ts:
            if lines:
                lines.append("")
            lines.append(f"{e['speaker']}  {e['timestamp']}")
            prev_speaker = e["speaker"]
            prev_ts = e["timestamp"]
        lines.append(e["text"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_details_stub(path: Path):
    today = datetime.now().strftime("%m/%d/%Y")
    path.write_text(f"Date/Time: {today}\n\n", encoding="utf-8")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--transcript-file", required=True)
    args = p.parse_args()

    transcript_path = Path(args.transcript_file).expanduser().resolve()

    if not transcript_path.exists():
        print(f"ERROR: File not found: {transcript_path}", file=sys.stderr)
        sys.exit(1)

    raw = transcript_path.read_text(encoding="utf-8")

    if not looks_like_zoom_html(raw):
        print(
            "ERROR: File does not look like Zoom transcript HTML.\n"
            "  Paste the <ul class='transcript-list'> outerHTML into the\n"
            "  Transcript tab and click Save before running this tool.",
            file=sys.stderr,
        )
        sys.exit(1)

    entries = parse_html(raw)

    if not entries:
        print(
            "ERROR: No transcript entries found in the HTML.\n"
            "  Make sure the Audio Transcript tab was selected when you copied.",
            file=sys.stderr,
        )
        sys.exit(1)

    write_transcript(entries, transcript_path)

    details_path = transcript_path.parent / "meeting_details.txt"
    if not details_path.exists():
        write_details_stub(details_path)

    speakers = len(set(e["speaker"] for e in entries))
    print(f"Converted {len(entries)} lines from {speakers} speakers.")
    print(f"Saved: {transcript_path}")
    if not details_path.exists():
        print(f"Created: {details_path}")


if __name__ == "__main__":
    main()
