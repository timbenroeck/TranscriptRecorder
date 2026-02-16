#!/bin/bash

# Default values
MEETINGS_BASE=""
TARGET_DATE=""
SE_NAME=""
CORTEX_CONNECTION=""
WAREHOUSE=""

# Model selection - opus for complex instruction following
MODEL="claude-opus-4-5"

usage() {
    echo "Usage: $0 -b <meetings_base_dir> -d <target_date> -s <se_name> [-w <warehouse>] [-c <cortex_connection>]"
    echo ""
    echo "Required:"
    echo "  -b    Meetings base directory (e.g., /Users/.../obsidian_vaults/snowflake/Meetings)"
    echo "  -d    Target month/year (e.g., '02-2026', 'feb 2026', '2026/02')"
    echo "  -s    Activity SE name to match in Vivun"
    echo ""
    echo "Optional:"
    echo "  -w    Snowflake warehouse to use for queries (e.g. SNOWADHOC_SMALL). If omitted, uses the warehouse in the SKILL."
    echo "  -c    Cortex connection name (e.g. Snowhouse). If omitted, uses the default connection."
    echo ""
    echo "Example:"
    echo "  $0 -b /Users/tbenroeck/Documents/obsidian_vaults/snowflake/Meetings -d 'feb 2026' -s 'Tim Benroeck'"
    echo "  $0 -b /Users/tbenroeck/Documents/obsidian_vaults/snowflake/Meetings -d '02-2026' -s 'Tim Benroeck' -w SNOWADHOC_SMALL"
    echo "  $0 -b /path/to/meetings -d '2026/02' -s 'Tim Benroeck' -c Snowhouse"
    exit 1
}

while getopts "b:d:s:w:c:h" opt; do
    case $opt in
        b) MEETINGS_BASE="$OPTARG" ;;
        d) TARGET_DATE="$OPTARG" ;;
        s) SE_NAME="$OPTARG" ;;
        w) WAREHOUSE="$OPTARG" ;;
        c) CORTEX_CONNECTION="$OPTARG" ;;
        h) usage ;;
        *) usage ;;
    esac
done

if [ -z "$MEETINGS_BASE" ]; then
    echo "Error: Meetings base directory (-b) is required"
    usage
fi

if [ ! -d "$MEETINGS_BASE" ]; then
    echo "Error: Directory not found: $MEETINGS_BASE"
    exit 1
fi

if [ -z "$TARGET_DATE" ]; then
    echo "Error: Target date (-d) is required"
    usage
fi
if [ -z "$SE_NAME" ]; then
    echo "Error: SE Name (-s) is required"
    usage
fi

# Build the prompt with the vivun_meeting_frontmatter_coco skill trigger
PROMPT="Add vivun frontmatter to meetings using the vivun_meeting_frontmatter_coco skill. Parameters:
- meetings_base_directory: $MEETINGS_BASE
- target_date: $TARGET_DATE
- activity_se_name: $SE_NAME"

# Conditionally append warehouse
if [ -n "$WAREHOUSE" ]; then
    PROMPT="$PROMPT
- snowflake_warehouse: $WAREHOUSE"
fi

# Resolve the directory containing this script
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Build cortex command with optional connection flag
# --bypass skips permission prompts for unattended execution
if [ -n "$CORTEX_CONNECTION" ]; then
    echo ""
    echo "============================================"
    echo "cortex --bypass --output-format stream-json -m $MODEL -c $CORTEX_CONNECTION -p '$PROMPT'"
    echo "============================================"
    echo ""
    cortex --bypass --output-format stream-json -m "$MODEL" -c "$CORTEX_CONNECTION" -p "$PROMPT"
else
    echo ""
    echo "============================================"
    echo "cortex --bypass --output-format stream-json -m $MODEL -p '$PROMPT'"
    echo "============================================"
    echo ""
    cortex --bypass --output-format stream-json -m "$MODEL" -p "$PROMPT"
fi
