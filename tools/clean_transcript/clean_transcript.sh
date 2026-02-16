#!/bin/zsh

# Default values
TRANSCRIPT_FILE=""
CORRECTIONS_FILE=""
NO_BACKUP=false

usage() {
    echo "Usage: $0 -t <transcript_file> [-c <corrections.json>] [--no-backup]"
    echo ""
    echo "Required:"
    echo "  -t    Path to meeting_transcript.txt file"
    echo ""
    echo "Optional:"
    echo "  -c    Path to corrections.json (default: uses data/corrections.json next to script)"
    echo "  --no-backup  Skip creating a backup before overwriting"
    echo ""
    echo "By default, the original file is backed up to a .backup/ folder in the"
    echo "same directory, then the cleaned output overwrites the original file."
    echo ""
    echo "Example:"
    echo "  $0 -t /path/to/recording/meeting_transcript.txt"
    echo "  $0 -t /path/to/recording/meeting_transcript.txt --no-backup"
    echo "  $0 -t /path/to/recording/meeting_transcript.txt -c /path/to/corrections.json"
    exit 1
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -t) TRANSCRIPT_FILE="$2"; shift 2 ;;
        -c) CORRECTIONS_FILE="$2"; shift 2 ;;
        --no-backup) NO_BACKUP=true; shift ;;
        -h|--help) usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

if [ -z "$TRANSCRIPT_FILE" ]; then
    echo "Error: Transcript file (-t) is required"
    usage
fi

if [ ! -f "$TRANSCRIPT_FILE" ]; then
    echo "Error: File not found: $TRANSCRIPT_FILE"
    exit 1
fi

# Resolve the directory containing this script
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Build command
CMD="python3 \"$SCRIPT_DIR/clean_transcript.py\" -t \"$TRANSCRIPT_FILE\""

if [ -n "$CORRECTIONS_FILE" ]; then
    CMD="$CMD --corrections \"$CORRECTIONS_FILE\""
fi

if [ "$NO_BACKUP" = true ]; then
    CMD="$CMD --no-backup"
fi

# Run
eval $CMD
