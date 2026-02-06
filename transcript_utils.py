"""
Utility functions for transcript processing.
"""
import difflib
import logging
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


def smart_merge(
    file1_path: str,
    file2_path: str,
    output_path: str,
    min_match_length: int = 5
) -> Tuple[bool, Optional[List[str]], int]:
    """
    Merges two transcript files using difflib with intelligent overlap detection.
    
    This function compares two transcript files and merges them, detecting overlapping
    content to avoid duplicates. It's useful for combining sequential transcript exports
    where there may be some overlap between captures.
    
    Args:
        file1_path: Path to the first (older) transcript file
        file2_path: Path to the second (newer) transcript file  
        output_path: Path where the merged transcript should be written
        min_match_length: Minimum number of matching lines to consider as meaningful overlap
        
    Returns:
        Tuple of (success: bool, merged_lines: Optional[List[str]], overlap_count: int)
        - success: True if merge completed successfully
        - merged_lines: List of merged lines if successful, None if failed
        - overlap_count: Number of lines that were identified as overlapping
    """
    try:
        with open(file1_path, 'r', encoding='utf-8') as f1:
            lines1 = f1.readlines()
        with open(file2_path, 'r', encoding='utf-8') as f2:
            lines2 = f2.readlines()

        logger.debug(f"smart_merge file1: {file1_path} ({len(lines1)} lines)")
        logger.debug(f"smart_merge file2: {file2_path} ({len(lines2)} lines)")

        merged_lines: List[str] = []
        overlap_count = 0

        matcher = difflib.SequenceMatcher(None, lines1, lines2)
        opcodes = matcher.get_opcodes()

        # Check for meaningful overlap
        found_meaningful_overlap = any(
            tag == 'equal' and (i2 - i1) >= min_match_length
            for tag, i1, i2, j1, j2 in opcodes
        )
        logger.debug(f"smart_merge Found meaningful overlap? {'YES' if found_meaningful_overlap else 'NO'}")

        if not found_meaningful_overlap:
            logger.debug("smart_merge No meaningful overlap — falling back to appending file1 + file2.")
            merged_lines.extend(lines1)
            merged_lines.extend(lines2)
        else:
            for tag, i1, i2, j1, j2 in opcodes:
                block_length = (i2 - i1)
                if tag == 'equal' and block_length >= min_match_length:
                    overlap_count += block_length
                    merged_lines.extend(lines2[j1:j2])
                elif tag == 'equal':
                    merged_lines.extend(lines2[j1:j2])
                elif tag in ('replace', 'insert'):
                    merged_lines.extend(lines2[j1:j2])
                elif tag == 'delete':
                    merged_lines.extend(lines1[i1:i2])

        with open(output_path, 'w', encoding='utf-8') as out:
            out.writelines(merged_lines)

        return True, merged_lines, overlap_count

    except Exception as e:
        logger.error(f"Error during smart_merge: {e}", exc_info=True)
        return False, None, 0


def merge_transcript_files(
    transcript_paths: List[str],
    output_path: str,
    min_match_length: int = 5
) -> Tuple[bool, Optional[str]]:
    """
    Merges multiple transcript files in sequence into a single output file.
    
    Args:
        transcript_paths: List of paths to transcript files in chronological order
        output_path: Path for the final merged output
        min_match_length: Minimum matching lines for overlap detection
        
    Returns:
        Tuple of (success: bool, output_path_or_error: Optional[str])
    """
    if not transcript_paths:
        return False, "No transcript files provided"
    
    if len(transcript_paths) == 1:
        # Just copy the single file
        try:
            with open(transcript_paths[0], 'r', encoding='utf-8') as f:
                content = f.read()
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True, output_path
        except Exception as e:
            return False, str(e)
    
    # Start with first file
    current_merged = transcript_paths[0]
    temp_output = output_path
    
    for i, next_file in enumerate(transcript_paths[1:], start=1):
        # For intermediate merges, use temp naming
        if i < len(transcript_paths) - 1:
            temp_output = f"{output_path}.temp"
        else:
            temp_output = output_path
            
        success, _, _ = smart_merge(
            current_merged,
            next_file,
            temp_output,
            min_match_length
        )
        
        if not success:
            return False, f"Failed to merge file {i}"
        
        current_merged = temp_output
    
    # Clean up temp file if it exists
    temp_path = Path(f"{output_path}.temp")
    if temp_path.exists():
        temp_path.unlink()
    
    return True, output_path


def get_transcript_text(file_path: str) -> Optional[str]:
    """
    Reads and returns the contents of a transcript file.
    
    Args:
        file_path: Path to the transcript file
        
    Returns:
        File contents as string, or None if reading failed
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        logger.error(f"Error reading transcript file {file_path}: {e}")
        return None
