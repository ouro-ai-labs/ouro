"""Smart code editing tool with fuzzy matching and preview capabilities.

This tool provides advanced editing features beyond the basic EditTool:
- Fuzzy matching: Handles whitespace and indentation differences
- Diff preview: Shows before/after comparison
- Auto backup: Creates .bak files before editing (disabled by default in git repos)
- Rollback: Can revert changes if editing fails
"""

import subprocess
from difflib import SequenceMatcher, unified_diff
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import aiofiles
import aiofiles.os

from tools.base import BaseTool


def _is_git_repo(path: Path) -> bool:
    """Check if the given path is inside a git repository."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=path.parent if path.is_file() else path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0 and result.stdout.strip() == "true"
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


class SmartEditTool(BaseTool):
    """Intelligent code editing with fuzzy matching and safety features."""

    def __init__(self):
        self.fuzzy_threshold = 0.8  # Minimum similarity ratio for fuzzy matching

    @property
    def name(self) -> str:
        return "smart_edit"

    @property
    def description(self) -> str:
        return """Intelligent code editing tool with fuzzy matching and preview.

Features:
- Fuzzy matching: Automatically handles whitespace/indentation differences
- Diff preview: Shows exactly what will change
- Auto backup: Creates .bak files before editing (disabled in git repos)
- Rollback: Automatically reverts if editing fails

Modes:
1. diff_replace: Find and replace code with fuzzy matching (MOST COMMON)
   - Handles indentation/whitespace differences automatically
   - Shows diff preview before applying
   - Required: old_code, new_code

2. smart_insert: Insert code relative to an anchor point
   - Find an anchor line and insert before/after it
   - Required: anchor, code, position ('before'/'after')

3. block_edit: Edit a range of lines
   - Replace lines from start_line to end_line
   - Required: start_line, end_line, new_content

Examples:
  # Replace a function with fuzzy matching
  smart_edit(
    file_path="agent/base.py",
    mode="diff_replace",
    old_code="def run(self, task):\\n    # old implementation",
    new_code="def run(self, task):\\n    # new implementation"
  )

  # Insert after a specific line
  smart_edit(
    file_path="config.py",
    mode="smart_insert",
    anchor="class Config:",
    code="    FEATURE_FLAG = True",
    position="after"
  )

IMPORTANT:
- Always use fuzzy_match=True (default) for code to handle formatting
- Set dry_run=True first to preview changes
- Backup is disabled by default in git repos (use create_backup=True to force)"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "file_path": {"type": "string", "description": "Path to the file to edit"},
            "mode": {
                "type": "string",
                "description": "Edit mode: diff_replace, smart_insert, or block_edit",
                "enum": ["diff_replace", "smart_insert", "block_edit"],
            },
            "old_code": {
                "type": "string",
                "description": "Code to find and replace (diff_replace mode). Can be approximate - fuzzy matching will find it.",
            },
            "new_code": {"type": "string", "description": "New code to insert (diff_replace mode)"},
            "anchor": {
                "type": "string",
                "description": "Anchor line to insert relative to (smart_insert mode)",
            },
            "code": {"type": "string", "description": "Code to insert (smart_insert mode)"},
            "position": {
                "type": "string",
                "description": "Where to insert: 'before' or 'after' anchor (smart_insert mode)",
                "enum": ["before", "after"],
            },
            "start_line": {
                "type": "integer",
                "description": "Starting line number (block_edit mode, 1-indexed)",
            },
            "end_line": {
                "type": "integer",
                "description": "Ending line number (block_edit mode, 1-indexed, inclusive)",
            },
            "fuzzy_match": {
                "type": "boolean",
                "description": "Enable fuzzy matching for whitespace differences (default: true)",
            },
            "dry_run": {
                "type": "boolean",
                "description": "Preview changes without applying (default: false)",
            },
            "create_backup": {
                "type": "boolean",
                "description": "Create .bak backup file (default: false in git repos, true otherwise)",
            },
            "show_diff": {
                "type": "boolean",
                "description": "Show diff preview even when not dry_run (default: true)",
            },
        }

    async def execute(
        self,
        file_path: str,
        mode: str,
        old_code: str = "",
        new_code: str = "",
        anchor: str = "",
        code: str = "",
        position: str = "after",
        start_line: int = 0,
        end_line: int = 0,
        fuzzy_match: bool = True,
        dry_run: bool = False,
        create_backup: Optional[bool] = None,
        show_diff: bool = True,
        **kwargs,
    ) -> str:
        """Execute smart edit operation."""
        try:
            path = Path(file_path)

            # Validation
            if not await aiofiles.os.path.exists(str(path)):
                return f"Error: File does not exist: {file_path}"

            # Determine create_backup default: False in git repos, True otherwise
            if create_backup is None:
                create_backup = not _is_git_repo(path)

            # Read original content
            async with aiofiles.open(path, encoding="utf-8") as f:
                original_content = await f.read()

            # Execute the appropriate edit mode
            if mode == "diff_replace":
                result = await self._diff_replace(
                    path,
                    original_content,
                    old_code,
                    new_code,
                    fuzzy_match,
                    dry_run,
                    create_backup,
                    show_diff,
                )
            elif mode == "smart_insert":
                result = await self._smart_insert(
                    path,
                    original_content,
                    anchor,
                    code,
                    position,
                    dry_run,
                    create_backup,
                    show_diff,
                )
            elif mode == "block_edit":
                result = await self._block_edit(
                    path,
                    original_content,
                    start_line,
                    end_line,
                    new_code,
                    dry_run,
                    create_backup,
                    show_diff,
                )
            else:
                return f"Error: Unknown mode '{mode}'. Supported: diff_replace, smart_insert, block_edit"

            return result

        except Exception as e:
            return f"Error executing smart_edit: {str(e)}"

    async def _diff_replace(
        self,
        path: Path,
        original_content: str,
        old_code: str,
        new_code: str,
        fuzzy_match: bool,
        dry_run: bool,
        create_backup: bool,
        show_diff: bool,
    ) -> str:
        """Replace code with fuzzy matching."""
        if not old_code:
            return "Error: old_code parameter is required for diff_replace mode"

        # Try exact match first
        similarity = 1.0  # Default for exact match
        if old_code in original_content:
            match_start = original_content.find(old_code)
            match_end = match_start + len(old_code)
        elif fuzzy_match:
            # Try fuzzy matching
            match_result = self._fuzzy_find(old_code, original_content)
            if match_result is None:
                return f"Error: Could not find code block (even with fuzzy matching).\n\nSearched for:\n{old_code[:200]}..."
            match_start, match_end, similarity = match_result

            # Show what was actually matched if similarity is not perfect
            if similarity < 0.99:
                matched_text = original_content[match_start:match_end]
                info = f"\n[Fuzzy match found with {similarity:.1%} similarity]\nMatched text:\n{matched_text[:200]}...\n"
            else:
                info = ""
        else:
            return f"Error: Exact match not found and fuzzy_match is disabled.\n\nSearched for:\n{old_code[:200]}..."

        # Create new content with replacement
        new_content = original_content[:match_start] + new_code + original_content[match_end:]

        # Generate diff for preview
        diff = self._generate_diff(original_content, new_content, str(path), context_lines=3)

        # Show diff if requested
        output_parts = []
        if show_diff or dry_run:
            if similarity < 0.99 and fuzzy_match:
                output_parts.append(info)
            output_parts.append(f"Diff preview:\n{diff}\n")

        # Dry run - don't actually modify
        if dry_run:
            output_parts.append("[DRY RUN] No changes made to file.")
            return "\n".join(output_parts)

        # Create backup if requested
        backup_path = None
        if create_backup:
            backup_path = await self._create_backup(path)
            output_parts.append(f"Created backup: {backup_path}")

        # Apply changes
        try:
            async with aiofiles.open(path, "w", encoding="utf-8") as f:
                await f.write(new_content)
            output_parts.append(f"Successfully edited {path}")
            return "\n".join(output_parts)
        except Exception as e:
            # Rollback if writing failed
            if create_backup and backup_path and await aiofiles.os.path.exists(str(backup_path)):
                await self._copy_file(backup_path, path)
                output_parts.append(f"Edit failed, restored from backup: {e}")
            else:
                output_parts.append(f"Edit failed: {e}")
            return "\n".join(output_parts)

    async def _smart_insert(
        self,
        path: Path,
        original_content: str,
        anchor: str,
        code: str,
        position: str,
        dry_run: bool,
        create_backup: bool,
        show_diff: bool,
    ) -> str:
        """Insert code relative to an anchor line."""
        if not anchor:
            return "Error: anchor parameter is required for smart_insert mode"
        if not code:
            return "Error: code parameter is required for smart_insert mode"

        lines = original_content.splitlines(keepends=True)

        # Find anchor line
        anchor_idx = None
        for i, line in enumerate(lines):
            if anchor in line:
                anchor_idx = i
                break

        if anchor_idx is None:
            return f"Error: Anchor line not found: {anchor}"

        # Ensure code ends with newline
        if not code.endswith("\n"):
            code += "\n"

        # Insert at appropriate position
        if position == "before":
            lines.insert(anchor_idx, code)
        else:  # after
            lines.insert(anchor_idx + 1, code)

        new_content = "".join(lines)

        # Generate and show diff
        output_parts = []
        if show_diff or dry_run:
            diff = self._generate_diff(original_content, new_content, str(path))
            output_parts.append(f"Diff preview:\n{diff}\n")

        if dry_run:
            output_parts.append("[DRY RUN] No changes made to file.")
            return "\n".join(output_parts)

        # Create backup and apply
        backup_path = None
        if create_backup:
            backup_path = await self._create_backup(path)
            output_parts.append(f"Created backup: {backup_path}")

        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write(new_content)
        output_parts.append(f"Successfully inserted code {position} anchor in {path}")
        return "\n".join(output_parts)

    async def _block_edit(
        self,
        path: Path,
        original_content: str,
        start_line: int,
        end_line: int,
        new_content_block: str,
        dry_run: bool,
        create_backup: bool,
        show_diff: bool,
    ) -> str:
        """Edit a block of lines."""
        if start_line <= 0 or end_line <= 0:
            return "Error: line numbers must be positive (1-indexed)"
        if start_line > end_line:
            return "Error: start_line must be <= end_line"

        lines = original_content.splitlines(keepends=True)

        if start_line > len(lines) or end_line > len(lines):
            return f"Error: line range {start_line}-{end_line} exceeds file length {len(lines)}"

        # Ensure new content ends with newline
        if not new_content_block.endswith("\n"):
            new_content_block += "\n"

        # Replace the block
        new_lines = lines[: start_line - 1] + [new_content_block] + lines[end_line:]
        new_content = "".join(new_lines)

        # Generate and show diff
        output_parts = []
        if show_diff or dry_run:
            diff = self._generate_diff(original_content, new_content, str(path))
            output_parts.append(f"Diff preview:\n{diff}\n")

        if dry_run:
            output_parts.append("[DRY RUN] No changes made to file.")
            return "\n".join(output_parts)

        # Create backup and apply
        backup_path = None
        if create_backup:
            backup_path = await self._create_backup(path)
            output_parts.append(f"Created backup: {backup_path}")

        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write(new_content)
        output_parts.append(f"Successfully edited lines {start_line}-{end_line} in {path}")
        return "\n".join(output_parts)

    def _fuzzy_find(self, target: str, text: str) -> Optional[Tuple[int, int, float]]:
        """
        Find target in text using fuzzy matching.

        Returns: (start_pos, end_pos, similarity_ratio) or None if not found
        """
        # Normalize whitespace for matching
        target_normalized = self._normalize_whitespace(target)

        # Sliding window approach
        target_lines = target.splitlines()
        text_lines = text.splitlines()

        best_match = None
        best_ratio = 0

        # Try different window sizes around target length
        for window_size in range(len(target_lines), len(target_lines) + 5):
            if window_size > len(text_lines):
                break

            for i in range(len(text_lines) - window_size + 1):
                window = text_lines[i : i + window_size]
                window_text = "\n".join(window)
                window_normalized = self._normalize_whitespace(window_text)

                # Calculate similarity
                ratio = SequenceMatcher(None, target_normalized, window_normalized).ratio()

                if ratio > best_ratio and ratio >= self.fuzzy_threshold:
                    # Found better match - calculate actual character positions
                    char_start = len("\n".join(text_lines[:i]))
                    if i > 0:
                        char_start += 1  # Account for newline
                    char_end = char_start + len(window_text)

                    best_match = (char_start, char_end, ratio)
                    best_ratio = ratio

        return best_match

    def _normalize_whitespace(self, text: str) -> str:
        """Normalize whitespace for fuzzy matching."""
        # Replace multiple spaces/tabs with single space
        # Keep line structure but normalize indentation
        lines = []
        for line in text.splitlines():
            # Strip leading/trailing whitespace but keep structure
            normalized = " ".join(line.split())
            lines.append(normalized)
        return "\n".join(lines)

    def _generate_diff(
        self, old_content: str, new_content: str, filename: str, context_lines: int = 3
    ) -> str:
        """Generate unified diff between old and new content."""
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)

        diff_lines = unified_diff(
            old_lines,
            new_lines,
            fromfile=f"{filename} (original)",
            tofile=f"{filename} (modified)",
            lineterm="",
            n=context_lines,
        )

        return "".join(diff_lines)

    async def _create_backup(self, path: Path) -> Path:
        """Create a backup file with .bak extension."""
        backup_path = path.with_suffix(path.suffix + ".bak")
        await self._copy_file(path, backup_path)
        return backup_path

    async def _copy_file(self, source: Path, destination: Path) -> None:
        """Copy a file using async IO."""
        async with aiofiles.open(source, "rb") as src, aiofiles.open(destination, "wb") as dst:
            while True:
                chunk = await src.read(1024 * 1024)
                if not chunk:
                    break
                await dst.write(chunk)
