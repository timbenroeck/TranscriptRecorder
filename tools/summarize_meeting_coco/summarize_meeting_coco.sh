#!/bin/zsh

# Default values
MEETING_DIR=""
OUTPUT_DIR=""
FIRST_NAME=""
LAST_NAME=""
CORTEX_CONNECTION=""

# Model selection - opus for complex instruction following
MODEL="claude-opus-4-5"

usage() {
    echo "Usage: $0 -m <meeting_dir> [-o <output_dir>] [-f <first_name>] [-l <last_name>] [-c <cortex_connection>]"
    echo ""
    echo "Required:"
    echo "  -m    Meeting transcript directory path"
    echo "  -o    Summary output directory"
    echo ""
    echo "Optional:"
    echo "  -f    First name for personalized summary (default: $FIRST_NAME)"
    echo "  -l    Last name for personalized summary (default: $LAST_NAME)"
    echo "  -c    Cortex connection name (e.g. snowflake). If omitted, uses the default connection."
    echo ""
    echo "Example:"
    echo "  $0 -m /Users/tbenroeck/Documents/transcriptrecorder/recordings/recording_2026-02-06_1106_zoom -o /path/to/output"
    echo "  $0 -m /path/to/meeting -f John -l Smith -o /path/to/output"
    echo "  $0 -m /path/to/meeting -c snowflake -o /path/to/output"
    exit 1
}

while getopts "m:o:f:l:c:h" opt; do
    case $opt in
        m) MEETING_DIR="$OPTARG" ;;
        o) OUTPUT_DIR="$OPTARG" ;;
        f) FIRST_NAME="$OPTARG" ;;
        l) LAST_NAME="$OPTARG" ;;
        c) CORTEX_CONNECTION="$OPTARG" ;;
        h) usage ;;
        *) usage ;;
    esac
done

if [ -z "$MEETING_DIR" ]; then
    echo "Error: Meeting directory (-m) is required"
    usage
fi

if [ ! -d "$MEETING_DIR" ]; then
    echo "Error: Directory not found: $MEETING_DIR"
    exit 1
fi

if [ ! -f "$MEETING_DIR/meeting_details.txt" ] || [ ! -f "$MEETING_DIR/meeting_transcript.txt" ]; then
    echo "Error: Directory must contain meeting_details.txt and meeting_transcript.txt"
    exit 1
fi

if [ -z "$OUTPUT_DIR" ]; then
    echo "Error: Output directory (-o) is required"
    usage
fi

if [ ! -d "$OUTPUT_DIR" ]; then
    echo "Error: Directory not found: $OUTPUT_DIR"
    exit 1
fi

# 1. Start with the base prompt (prefix with $meeting-summarizer to force skill activation)
PROMPT="Summarize the meeting using the meeting-summarizer skill. Parameters:
- meeting_transcript_directory: $MEETING_DIR
- meetings_base_directory: $OUTPUT_DIR"

# 2. Conditionally append First Name
if [ -n "$FIRST_NAME" ]; then
    PROMPT="$PROMPT
- summary_for_firstname: $FIRST_NAME"
fi

# 3. Conditionally append Last Name
if [ -n "$LAST_NAME" ]; then
    PROMPT="$PROMPT
- summary_for_lastname: $LAST_NAME"
fi

# Resolve the directory containing this script
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Build cortex command with optional connection flag
# --bypass skips permission prompts for unattended execution
if [ -n "$CORTEX_CONNECTION" ]; then
    echo ""
    echo "============================================"
    echo "cortex --output-format stream-json -m $MODEL -c $CORTEX_CONNECTION  -p '$PROMPT'"
    echo "============================================"
    echo ""
    cortex --output-format stream-json -m "$MODEL" -c "$CORTEX_CONNECTION" -p "$PROMPT"
else
    echo ""
    echo "============================================"
    echo "cortex --output-format stream-json -m $MODEL  -p '$PROMPT'"
    echo "============================================"
    echo ""
    cortex --output-format stream-json -m "$MODEL" -p "$PROMPT"
fi
