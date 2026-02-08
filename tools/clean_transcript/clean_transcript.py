#!/usr/bin/env python3
"""
Transcript Cleanup Tool
=======================
Performs a first-pass cleanup of meeting_transcript.txt files by:
  1. Removing filler words (uh, um, hmm, etc.)
  2. Removing "(Unverified)" tags from speaker names
  3. Applying a corrections dictionary (case-insensitive match, case-correct replacement)
  4. Cleaning up repeated/stuttered words
  5. Normalizing whitespace artifacts left by removals
  6. Removing empty lines left after cleanup

By default, the original file is backed up to a .backup/ folder in the same
directory, and the cleaned output overwrites the original file. This ensures
downstream tools (e.g. Summarize Meeting) work with the cleaned transcript
without needing to know a different filename.

Usage:
  python3 clean_transcript.py -t <transcript_file> [--corrections <corrections.json>] [--dry-run] [--no-backup]

Examples:
  # Clean transcript (backs up original to .backup/, overwrites original)
  python3 clean_transcript.py -t /path/to/meeting_transcript.txt

  # Preview changes (dry-run, prints to stdout, no files written)
  python3 clean_transcript.py -t /path/to/meeting_transcript.txt --dry-run

  # Clean without creating a backup (overwrites original directly)
  python3 clean_transcript.py -t /path/to/meeting_transcript.txt --no-backup

  # With custom corrections file
  python3 clean_transcript.py -t /path/to/meeting_transcript.txt --corrections /path/to/corrections.json
"""

import argparse
import json
import os
import re
import shutil
import sys


# ─── Default corrections ────────────────────────────────────────────────────
# These are built into the tool. An external corrections.json will be merged
# on top (external values override defaults for the same key).

DEFAULT_CORRECTIONS = {
    # Intentionally empty — all domain-specific corrections belong in corrections.json.
    # This dict exists so the tool works standalone without a corrections file.
}


# ─── Filler word / noise patterns ────────────────────────────────────────────
# Each pattern is a tuple of (compiled_regex, replacement_string).
# Order matters — more specific patterns should come first.

FILLER_PATTERNS = [
    # --- Filler words with surrounding punctuation / spacing ---

    # "uh" / "um" variants at the START of a sentence or after punctuation
    # e.g. "Uh, so we..." -> "So we..."  /  "Um… And then" -> "And then"
    (re.compile(r'(?<![a-zA-Z])[Uu]h+[,.\s…]*\s*', re.IGNORECASE), ''),
    (re.compile(r'(?<![a-zA-Z])[Uu]mm?[,.\s…]*\s*', re.IGNORECASE), ''),

    # "uh" / "um" in the MIDDLE of a sentence
    # e.g. "I think, uh, we should" -> "I think we should"
    (re.compile(r',?\s*\buh+\b[,.\s…]*', re.IGNORECASE), ' '),
    (re.compile(r',?\s*\bumm?\b[,.\s…]*', re.IGNORECASE), ' '),

    # Thinking sounds: "hmm", "hm"
    (re.compile(r',?\s*\bhmm+\b[,.\s…]*', re.IGNORECASE), ' '),
    (re.compile(r',?\s*\bhm\b[,.\s…]*', re.IGNORECASE), ' '),

    # Acknowledgment sounds: "Mhm", "Mm-hmm", "Mm hmm", "Mmhmm"
    (re.compile(r'\bMm-hmm\b[,.\s…]*', re.IGNORECASE), ''),
    (re.compile(r'\bMm hmm\b[,.\s…]*', re.IGNORECASE), ''),
    (re.compile(r'\bMmhmm\b[,.\s…]*', re.IGNORECASE), ''),
    (re.compile(r'\bMhm\b[,.\s…]*', re.IGNORECASE), ''),
]

# --- Stutter / repeated-word patterns ---
# Words allowed to appear doubled because they are grammatically valid.
# "that that" — "I knew that that would happen"
# "had had"   — "She had had enough" (past perfect)
STUTTER_ALLOWLIST = {'that', 'had', 'do'}

# 3+ repetitions of any word — always a stutter, no allowlist needed
# e.g. "I I I think" -> "I think", "the the the" -> "the"
STUTTER_3PLUS_PATTERN = re.compile(
    r'\b(\w+)(?:[,.\s…]+\1){2,}\b', re.IGNORECASE
)

# Double-word stutter — matches words separated by whitespace and/or punctuation
# e.g. "I I think" -> "I think", "like, like" -> "like", "claud. claud" -> "claud"
STUTTER_PATTERN = re.compile(
    r'\b(\w+)[,.\s…]+\1\b', re.IGNORECASE
)

# --- (Unverified) removal from speaker names ---
# Matches " (Unverified)" anywhere, typically on speaker-name lines
UNVERIFIED_PATTERN = re.compile(r'\s*\(Unverified\)', re.IGNORECASE)

# --- Excessive ellipsis normalization (Zoom transcripts) ---
# Collapse "… " or "... " sequences that appear as pauses
# We keep a single one when between words, remove when trailing
TRAILING_ELLIPSIS = re.compile(r'\s*…\s*$')
LEADING_ELLIPSIS = re.compile(r'^\s*…\s*')

# --- Cleanup artifacts ---
MULTI_SPACE = re.compile(r'  +')              # collapse multiple spaces
SPACE_BEFORE_PUNCT = re.compile(r'\s+([,.])')  # remove space before comma/period
LEADING_COMMA = re.compile(r'^\s*,\s*')        # line starting with comma after removal
TRAILING_SPACE = re.compile(r'\s+$')           # trailing whitespace


def load_corrections(path: str) -> dict:
    """Load corrections JSON. Keys = correct form, values = list of incorrect variants."""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def build_corrections_regex(corrections: dict) -> list:
    """
    Build a list of (compiled_regex, replacement) from the corrections dict.
    Each incorrect variant becomes a case-insensitive whole-word regex,
    and the replacement is the correctly-cased key.

    Longer patterns are matched first to avoid partial replacements.
    """
    pairs = []
    for correct, variants in corrections.items():
        for variant in variants:
            # Use word boundaries to avoid partial matches.
            # re.escape handles any special regex chars in the variant.
            pattern = re.compile(r'\b' + re.escape(variant) + r'\b', re.IGNORECASE)
            pairs.append((pattern, correct, len(variant)))

    # Sort by variant length descending so longer matches win
    pairs.sort(key=lambda x: x[2], reverse=True)
    return [(p, r) for p, r, _ in pairs]


def is_speaker_line(line: str, prev_line: str) -> bool:
    """
    Heuristic to detect if a line is a speaker name line in the transcript.
    Speaker lines are typically:
      - Just a name (no colon, short)
      - A name with (Unverified) / (Company)
      - In the Gemini/manual format: "Name: text"
    """
    # If line contains a colon followed by text, it's "Speaker: dialogue" format
    if ':' in line:
        parts = line.split(':', 1)
        # If the part before the colon looks like a name (no digits, reasonable length)
        name_part = parts[0].strip()
        if len(name_part) < 80 and not any(c.isdigit() for c in name_part):
            return True

    # Lines that are just a name (Teams browser format) — short, no period, no question mark
    stripped = line.strip()
    if (stripped and
            len(stripped) < 80 and
            not stripped.endswith('.') and
            not stripped.endswith('?') and
            not stripped.endswith('!') and
            not any(c.isdigit() for c in stripped) and
            stripped[0].isupper()):
        # Additional heuristic: if next/prev line looks like dialogue, this is a name
        return True

    return False


def _stutter_replace(match: re.Match) -> str:
    """Replace a doubled word with a single instance, unless it's in the allowlist."""
    word = match.group(1)
    if word.lower() in STUTTER_ALLOWLIST:
        return match.group(0)  # keep the original text
    return word


def clean_dialogue_text(text: str) -> str:
    """Apply filler removal and stutter cleanup to dialogue text."""
    # Apply filler removal
    for pattern, replacement in FILLER_PATTERNS:
        text = pattern.sub(replacement, text)

    # Collapse 3+ repetitions unconditionally (no allowlist — never legitimate)
    text = STUTTER_3PLUS_PATTERN.sub(r'\1', text)

    # Collapse double-word stutters, respecting the allowlist
    # Apply multiple times to catch residual pairs after 3+ collapse
    for _ in range(3):
        new_text = STUTTER_PATTERN.sub(_stutter_replace, text)
        if new_text == text:
            break
        text = new_text

    return text


def clean_line(line: str, corrections_regex: list, is_name_line: bool) -> str:
    """Apply all cleanup transformations to a single line."""

    # Handle "Speaker: dialogue" format — split, clean name & dialogue separately
    if is_name_line and ':' in line:
        colon_idx = line.index(':')
        name_part = line[:colon_idx]
        dialogue_part = line[colon_idx + 1:]

        # Clean (Unverified) from speaker name
        name_part = UNVERIFIED_PATTERN.sub('', name_part)

        # Clean fillers/stutters from the dialogue portion
        dialogue_part = clean_dialogue_text(dialogue_part)

        # Apply corrections to dialogue portion
        for pattern, replacement in corrections_regex:
            dialogue_part = pattern.sub(replacement, dialogue_part)

        # Normalize whitespace in dialogue
        dialogue_part = MULTI_SPACE.sub(' ', dialogue_part)
        dialogue_part = SPACE_BEFORE_PUNCT.sub(r'\1', dialogue_part)
        dialogue_part = TRAILING_SPACE.sub('', dialogue_part)

        # Recapitalize first letter of dialogue after cleanup
        dialogue_stripped = dialogue_part.lstrip()
        if dialogue_stripped:
            leading_space = dialogue_part[:len(dialogue_part) - len(dialogue_stripped)]
            dialogue_part = leading_space + dialogue_stripped[0].upper() + dialogue_stripped[1:] if len(dialogue_stripped) > 1 else leading_space + dialogue_stripped.upper()

        line = name_part + ':' + dialogue_part
    elif is_name_line:
        # Pure name line (no colon) — just remove (Unverified)
        line = UNVERIFIED_PATTERN.sub('', line)
    else:
        # Pure dialogue line (no speaker prefix)
        line = clean_dialogue_text(line)

        # Capitalize first letter after cleanup (if we stripped a leading filler)
        if line:
            line = line[0].upper() + line[1:] if len(line) > 1 else line.upper()

    # Apply corrections (to entire line for non-split lines)
    if not (is_name_line and ':' in line):
        for pattern, replacement in corrections_regex:
            line = pattern.sub(replacement, line)

    # Final whitespace normalization
    line = MULTI_SPACE.sub(' ', line)
    line = SPACE_BEFORE_PUNCT.sub(r'\1', line)
    line = LEADING_COMMA.sub('', line)
    line = TRAILING_SPACE.sub('', line)

    return line


def is_timestamp_line(line: str) -> bool:
    """Check if a line is a timestamp (e.g., '08:37:47' or '00:01:00')."""
    return bool(re.match(r'^\d{2}:\d{2}(:\d{2})?\s*$', line.strip()))


def is_empty_noise_line(line: str) -> bool:
    """Check if a cleaned line is now empty or just punctuation/whitespace."""
    stripped = line.strip()
    return stripped == '' or stripped in {'.', ',', '…', '...', '-', '—'}


def clean_transcript(text: str, corrections_regex: list) -> str:
    """Clean an entire transcript text."""
    lines = text.split('\n')
    cleaned_lines = []
    prev_line = ''

    for i, line in enumerate(lines):
        # Skip empty lines (preserve structure)
        if not line.strip():
            cleaned_lines.append(line)
            prev_line = line
            continue

        # Don't modify timestamp lines
        if is_timestamp_line(line):
            cleaned_lines.append(line)
            prev_line = line
            continue

        # Determine if this is a speaker name line
        # Look at context: the previous line and the current line
        is_name = is_speaker_line(line, prev_line)

        # Clean the line
        cleaned = clean_line(line, corrections_regex, is_name)

        # If the line became empty/noise after cleaning, skip it
        if is_empty_noise_line(cleaned) and not is_name:
            prev_line = line
            continue

        cleaned_lines.append(cleaned)
        prev_line = line

    # Remove consecutive duplicate empty lines
    result = []
    prev_empty = False
    for line in cleaned_lines:
        is_empty = not line.strip()
        if is_empty and prev_empty:
            continue
        result.append(line)
        prev_empty = is_empty

    return '\n'.join(result)


def compute_stats(original: str, cleaned: str) -> dict:
    """Compute statistics about what was changed."""
    orig_lines = original.split('\n')
    clean_lines = cleaned.split('\n')

    unverified_count = len(re.findall(r'\(Unverified\)', original, re.IGNORECASE))

    # Count filler words in original
    filler_count = 0
    for pattern, _ in FILLER_PATTERNS:
        filler_count += len(pattern.findall(original))

    # Count stutters (doubles + 3+ repetitions)
    stutter_count = (len(STUTTER_PATTERN.findall(original))
                     + len(STUTTER_3PLUS_PATTERN.findall(original)))

    return {
        'original_lines': len(orig_lines),
        'cleaned_lines': len(clean_lines),
        'lines_removed': len(orig_lines) - len(clean_lines),
        'unverified_removed': unverified_count,
        'fillers_found': filler_count,
        'stutters_found': stutter_count,
        'original_chars': len(original),
        'cleaned_chars': len(cleaned),
        'chars_removed': len(original) - len(cleaned),
    }


def main():
    parser = argparse.ArgumentParser(
        description='Clean up meeting transcripts by removing fillers, (Unverified) tags, '
                    'and applying corrections.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        '-t', '--transcript',
        required=True,
        help='Path to meeting_transcript.txt file'
    )
    parser.add_argument(
        '--corrections', '-c',
        help='Path to corrections.json (key=correct, value=list of incorrect variants)',
        default=None
    )
    parser.add_argument(
        '--dry-run', '-d',
        action='store_true',
        help='Print cleaned output to stdout without writing any file'
    )
    parser.add_argument(
        '--no-backup',
        action='store_true',
        help='Skip creating a backup before overwriting (default: backs up to .backup/)'
    )
    parser.add_argument(
        '--stats', '-s',
        action='store_true',
        help='Print cleanup statistics to stderr'
    )
    parser.add_argument(
        '--quiet', '-q',
        action='store_true',
        help='Suppress informational output'
    )

    args = parser.parse_args()

    # Validate input
    if not os.path.isfile(args.transcript):
        print(f"Error: File not found: {args.transcript}", file=sys.stderr)
        sys.exit(1)

    # Load corrections
    corrections = dict(DEFAULT_CORRECTIONS)
    if args.corrections:
        if not os.path.isfile(args.corrections):
            print(f"Error: Corrections file not found: {args.corrections}", file=sys.stderr)
            sys.exit(1)
        external = load_corrections(args.corrections)
        corrections.update(external)
    else:
        # Look for corrections.json next to this script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        default_corrections_path = os.path.join(script_dir, 'data', 'corrections.json')
        if os.path.isfile(default_corrections_path):
            external = load_corrections(default_corrections_path)
            corrections.update(external)
            if not args.quiet:
                print(f"Loaded corrections from: {default_corrections_path}", file=sys.stderr)

    corrections_regex = build_corrections_regex(corrections)

    # Read transcript
    with open(args.transcript, 'r', encoding='utf-8') as f:
        original = f.read()

    # Clean
    cleaned = clean_transcript(original, corrections_regex)

    # Stats
    if args.stats or not args.quiet:
        stats = compute_stats(original, cleaned)
        print(f"\n{'='*50}", file=sys.stderr)
        print(f"  Transcript Cleanup Report", file=sys.stderr)
        print(f"{'='*50}", file=sys.stderr)
        print(f"  File: {args.transcript}", file=sys.stderr)
        print(f"  Lines: {stats['original_lines']} -> {stats['cleaned_lines']} ({stats['lines_removed']} removed)", file=sys.stderr)
        print(f"  Characters: {stats['original_chars']} -> {stats['cleaned_chars']} ({stats['chars_removed']} removed)", file=sys.stderr)
        print(f"  (Unverified) tags removed: {stats['unverified_removed']}", file=sys.stderr)
        print(f"  Filler words cleaned: {stats['fillers_found']}", file=sys.stderr)
        print(f"  Stutters cleaned: {stats['stutters_found']}", file=sys.stderr)
        print(f"  Corrections applied: {len(corrections)} rules loaded", file=sys.stderr)
        print(f"{'='*50}\n", file=sys.stderr)

    # Output
    if args.dry_run:
        print(cleaned)
    else:
        # Back up the original before overwriting (unless --no-backup)
        if not args.no_backup:
            from datetime import datetime as _dt
            transcript_dir = os.path.dirname(os.path.abspath(args.transcript))
            backup_dir = os.path.join(transcript_dir, '.backup')
            os.makedirs(backup_dir, exist_ok=True)
            base, ext = os.path.splitext(os.path.basename(args.transcript))
            timestamp = _dt.now().strftime('%Y%m%d_%H%M%S')
            backup_path = os.path.join(backup_dir, f"{base}_{timestamp}{ext}")
            shutil.copy2(args.transcript, backup_path)
            if not args.quiet:
                print(f"Backup saved: {backup_path}", file=sys.stderr)

        # Overwrite the original file with cleaned content
        with open(args.transcript, 'w', encoding='utf-8') as f:
            f.write(cleaned)
        if not args.quiet:
            print(f"Cleaned: {args.transcript}", file=sys.stderr)


if __name__ == '__main__':
    main()
