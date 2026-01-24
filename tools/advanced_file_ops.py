"""Advanced file operation tools inspired by Claude Code."""

import asyncio
import contextlib
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiofiles
import aiofiles.os

from tools.base import BaseTool


class GlobTool(BaseTool):
    """Fast file pattern matching tool."""

    @property
    def name(self) -> str:
        return "glob_files"

    @property
    def description(self) -> str:
        return """Fast file pattern matching tool.

Use this to find files by patterns like:
- "**/*.py" - all Python files recursively
- "src/**/*.js" - JavaScript files in src/
- "*.txt" - text files in current directory

Much faster than reading directories recursively.
Returns sorted list of matching file paths."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "pattern": {
                "type": "string",
                "description": "Glob pattern to match files (e.g., '**/*.py', 'src/**/*.js')",
            },
            "path": {
                "type": "string",
                "description": "Base directory to search in (default: current directory)",
            },
        }

    async def execute(self, pattern: str, path: str = ".") -> str:
        """Find files matching glob pattern."""
        try:
            base_path = Path(path)
            if not await aiofiles.os.path.exists(str(base_path)):
                return f"Error: Path does not exist: {path}"

            matches = await asyncio.to_thread(lambda: sorted(base_path.glob(pattern)))
            if not matches:
                return f"No files found matching pattern: {pattern} in {path}"

            # Limit to 100 results to avoid overwhelming output
            if len(matches) > 100:
                result_lines = [str(m) for m in matches[:100]]
                result_lines.append(f"\n... and {len(matches) - 100} more files")
                return "\n".join(result_lines)

            return "\n".join(str(m) for m in matches)
        except Exception as e:
            return f"Error executing glob: {str(e)}"


class GrepTool(BaseTool):
    """Search file contents using regex patterns."""

    def __init__(self):
        """Initialize GrepTool, checking for ripgrep availability."""
        self._rg_path = shutil.which("rg")
        self._has_ripgrep = self._rg_path is not None

    @property
    def name(self) -> str:
        return "grep_content"

    @property
    def description(self) -> str:
        return """Search file contents using regex patterns.

Output modes:
- files_only: Just list files containing matches (default)
- with_context: Show matching lines with line numbers
- count: Count matches per file

Options:
- file_pattern: Glob pattern to filter files (e.g., '**/*.py', 'src/**/*.js')
- exclude_patterns: Glob patterns to exclude (e.g., ['**/*.pyc', 'node_modules/**'])
- context_lines: Show N lines before and after matches (with_context mode)
- multiline: Enable multiline pattern matching

Examples:
- Find functions: pattern="def\\s+\\w+", file_pattern="**/*.py"
- Search imports: pattern="^import\\s+", file_pattern="src/**/*.py"
- Find TODOs: pattern="TODO|FIXME", exclude_patterns=["tests/**"]
- Count prints: pattern="print\\(", mode="count"
- With context: pattern="ERROR", mode="with_context", context_lines=2"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "pattern": {"type": "string", "description": "Regex pattern to search for"},
            "path": {
                "type": "string",
                "description": "Directory to search in (default: current directory)",
            },
            "mode": {
                "type": "string",
                "description": "Output mode: files_only, with_context, or count (default: files_only)",
            },
            "case_sensitive": {
                "type": "boolean",
                "description": "Whether search is case sensitive (default: true)",
            },
            "file_pattern": {
                "type": "string",
                "description": "Optional glob pattern to filter files before content search (e.g., '**/*.py', 'src/**/*.js')",
            },
            "exclude_patterns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of glob patterns to exclude (e.g., ['**/*.pyc', 'node_modules/**'])",
            },
            "max_matches_per_file": {
                "type": "integer",
                "description": "Maximum matches to show per file in with_context mode (default: 5)",
            },
            "context_lines": {
                "type": "integer",
                "description": "Number of lines to show before and after each match (default: 0)",
            },
            "multiline": {
                "type": "boolean",
                "description": "Enable multiline pattern matching (default: false)",
            },
            "max_count": {
                "type": "integer",
                "description": "Maximum total number of results to return (default: 50)",
            },
        }

    async def execute(
        self,
        pattern: str,
        path: str = ".",
        mode: str = "files_only",
        case_sensitive: bool = True,
        file_pattern: str = None,
        exclude_patterns: list = None,
        max_matches_per_file: int = 5,
        context_lines: int = 0,
        multiline: bool = False,
        max_count: int = 50,
        **kwargs,
    ) -> str:
        """Search for pattern in files with optional file filtering."""
        base_path = Path(path)
        if not await aiofiles.os.path.exists(str(base_path)):
            return f"Error: Path does not exist: {path}"

        # Use ripgrep if available
        if self._has_ripgrep:
            return await self._execute_ripgrep(
                pattern=pattern,
                path=path,
                mode=mode,
                case_sensitive=case_sensitive,
                file_pattern=file_pattern,
                exclude_patterns=exclude_patterns,
                max_matches_per_file=max_matches_per_file,
                context_lines=context_lines,
                multiline=multiline,
                max_count=max_count,
            )
        else:
            return await self._execute_python_fallback(
                pattern=pattern,
                path=path,
                mode=mode,
                case_sensitive=case_sensitive,
                file_pattern=file_pattern,
                exclude_patterns=exclude_patterns,
                max_matches_per_file=max_matches_per_file,
                max_count=max_count,
            )

    async def _execute_ripgrep(
        self,
        pattern: str,
        path: str,
        mode: str,
        case_sensitive: bool,
        file_pattern: Optional[str],
        exclude_patterns: Optional[List[str]],
        max_matches_per_file: int,
        context_lines: int,
        multiline: bool,
        max_count: int,
    ) -> str:
        """Execute search using ripgrep."""
        cmd = [self._rg_path]

        # Output mode
        if mode == "files_only":
            cmd.append("-l")  # --files-with-matches
        elif mode == "count":
            cmd.append("-c")  # --count
        else:  # with_context
            cmd.append("-n")  # --line-number
            if context_lines > 0:
                cmd.extend(["-C", str(context_lines)])

        # Case sensitivity
        if not case_sensitive:
            cmd.append("-i")

        # Multiline mode
        if multiline:
            cmd.append("-U")  # --multiline

        # File type filtering via glob
        if file_pattern:
            cmd.extend(["-g", file_pattern])

        # Exclude patterns
        default_excludes = [
            ".git/",
            "node_modules/",
            "__pycache__/",
            "*.pyc",
            ".venv/",
            "venv/",
            "target/",
            "build/",
        ]
        excludes = exclude_patterns if exclude_patterns is not None else default_excludes
        for exclude in excludes:
            cmd.extend(["-g", f"!{exclude}"])

        # Max results per file (only for with_context mode)
        if mode == "with_context":
            cmd.extend(["-m", str(max_matches_per_file)])

        # Include hidden files but exclude .git
        cmd.append("--hidden")

        # Pattern and path
        cmd.extend(["--", pattern, path])

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
            except asyncio.TimeoutError:
                process.kill()
                await process.communicate()
                return "Error: Search timed out after 30 seconds"

            output = stdout.decode(errors="ignore")
            error_output = stderr.decode(errors="ignore")
            if not output and process.returncode == 1:
                return f"No matches found for pattern '{pattern}'"
            elif process.returncode not in (0, 1):
                if error_output:
                    return f"Error executing ripgrep: {error_output.strip()}"
                return f"No matches found for pattern '{pattern}'"

            # Limit output size
            lines = output.strip().split("\n") if output.strip() else []
            if len(lines) > max_count:
                lines = lines[:max_count]
                lines.append(f"\n... (truncated, showing first {max_count} results)")

            output = "\n".join(lines)

            # Check output size
            estimated_tokens = len(output) // self.CHARS_PER_TOKEN
            if estimated_tokens > self.MAX_TOKENS:
                max_chars = self.MAX_TOKENS * self.CHARS_PER_TOKEN
                output = output[:max_chars]
                output += f"\n... (output truncated to ~{self.MAX_TOKENS} tokens)"

            return output

        except Exception as e:
            return f"Error executing ripgrep: {str(e)}"

    async def _execute_python_fallback(
        self,
        pattern: str,
        path: str,
        mode: str,
        case_sensitive: bool,
        file_pattern: Optional[str],
        exclude_patterns: Optional[List[str]],
        max_matches_per_file: int,
        max_count: int,
    ) -> str:
        """Execute search using Python regex (fallback when ripgrep not available)."""
        try:
            flags = 0 if case_sensitive else re.IGNORECASE
            regex = re.compile(pattern, flags)
        except re.error as e:
            return f"Error: Invalid regex pattern: {str(e)}"

        try:
            base_path = Path(path)

            # Default exclusions if not specified
            default_excludes = [
                "*.pyc",
                "*.so",
                "*.dylib",
                "*.dll",
                "*.exe",
                "*.bin",
                "*.jpg",
                "*.png",
                "*.gif",
                "*.pdf",
                "*.zip",
                "*.tar",
                "*.gz",
            ]

            # Determine files to search
            if file_pattern:
                try:
                    files_to_search = await asyncio.to_thread(
                        lambda: [f for f in base_path.glob(file_pattern) if f.is_file()]
                    )
                except Exception as e:
                    return f"Error with file_pattern '{file_pattern}': {str(e)}"
            else:
                files_to_search = await asyncio.to_thread(
                    lambda: [f for f in base_path.rglob("*") if f.is_file()]
                )

            # Filter out excluded patterns
            excludes = exclude_patterns if exclude_patterns is not None else default_excludes

            # Pre-compute set of excluded files
            excluded_files = set()
            for exclude_pattern in excludes:
                with contextlib.suppress(Exception):
                    glob_matches = await asyncio.to_thread(
                        lambda exclude_pattern=exclude_pattern: list(
                            base_path.glob(exclude_pattern)
                        )
                    )
                    rglob_matches = await asyncio.to_thread(
                        lambda exclude_pattern=exclude_pattern: list(
                            base_path.rglob(exclude_pattern)
                        )
                    )
                    excluded_files.update(glob_matches)
                    excluded_files.update(rglob_matches)

            # Also exclude common directories
            exclude_dirs = {
                ".git",
                "node_modules",
                "__pycache__",
                ".venv",
                "venv",
                "target",
                "build",
            }

            # Filter files
            filtered_files = []
            for file_path in files_to_search:
                if file_path in excluded_files:
                    continue
                # Check for excluded directories
                skip = False
                for part in file_path.parts:
                    if part in exclude_dirs:
                        skip = True
                        break
                if not skip:
                    filtered_files.append(file_path)

            results = []
            files_searched = 0

            for file_path in filtered_files:
                files_searched += 1

                try:
                    async with aiofiles.open(file_path, encoding="utf-8") as f:
                        content = await f.read()
                    matches = list(regex.finditer(content))

                    if not matches:
                        continue

                    if mode == "files_only":
                        results.append(str(file_path))
                    elif mode == "count":
                        results.append(f"{file_path}: {len(matches)} matches")
                    elif mode == "with_context":
                        lines = content.splitlines()
                        for match in matches[:max_matches_per_file]:
                            line_no = content[: match.start()].count("\n") + 1
                            if line_no <= len(lines):
                                results.append(f"{file_path}:{line_no}: {lines[line_no-1].strip()}")
                except (UnicodeDecodeError, PermissionError):
                    continue

                if len(results) >= max_count:
                    break

            if not results:
                return (
                    f"No matches found for pattern '{pattern}' in {files_searched} files searched"
                )

            output = "\n".join(results)

            # Check output size
            estimated_tokens = len(output) // self.CHARS_PER_TOKEN
            if estimated_tokens > self.MAX_TOKENS:
                return (
                    f"Error: Grep output (~{estimated_tokens} tokens) exceeds "
                    f"maximum allowed ({self.MAX_TOKENS}). Please use more specific "
                    f"file_pattern or pattern to narrow results."
                )

            return output
        except Exception as e:
            return f"Error executing grep: {str(e)}"


class EditTool(BaseTool):
    """Edit files surgically without reading entire contents."""

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return """Edit files surgically without reading entire contents.

Operations:
- replace: Find and replace text exactly (old_text and new_text required)
- append: Add to end of file (text required)
- insert_at_line: Insert text at specific line number (line_number and text required)

More efficient than reading full file, modifying, and writing back.

IMPORTANT: Use this for small, targeted edits to save tokens."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "file_path": {"type": "string", "description": "Path to the file to edit"},
            "operation": {
                "type": "string",
                "description": "Operation to perform: replace, append, or insert_at_line",
            },
            "old_text": {
                "type": "string",
                "description": "Text to find and replace (for replace operation)",
            },
            "new_text": {
                "type": "string",
                "description": "New text to insert (for replace operation)",
            },
            "text": {
                "type": "string",
                "description": "Text to add (for append or insert_at_line operations)",
            },
            "line_number": {
                "type": "integer",
                "description": "Line number to insert at (for insert_at_line operation, 1-indexed)",
            },
        }

    async def execute(
        self,
        file_path: str,
        operation: str,
        old_text: str = "",
        new_text: str = "",
        text: str = "",
        line_number: int = 0,
        **kwargs,
    ) -> str:
        """Perform surgical file edit."""
        try:
            path = Path(file_path)

            if not await aiofiles.os.path.exists(str(path)):
                return f"Error: File does not exist: {file_path}"

            if operation == "replace":
                if not old_text:
                    return "Error: old_text parameter is required for replace operation"

                async with aiofiles.open(file_path, encoding="utf-8") as f:
                    content = await f.read()

                if old_text not in content:
                    return f"Error: Text not found in {file_path}"

                # Replace only the first occurrence
                content = content.replace(old_text, new_text, 1)
                async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
                    await f.write(content)
                return f"Successfully replaced text in {file_path}"

            elif operation == "append":
                if not text:
                    return "Error: text parameter is required for append operation"

                async with aiofiles.open(file_path, "a", encoding="utf-8") as f:
                    await f.write(text)
                return f"Successfully appended to {file_path}"

            elif operation == "insert_at_line":
                if not text:
                    return "Error: text parameter is required for insert_at_line operation"
                if line_number <= 0:
                    return "Error: line_number must be positive (1-indexed)"

                async with aiofiles.open(file_path, encoding="utf-8") as f:
                    content = await f.read()
                lines = content.splitlines(keepends=True)

                # Insert at the specified line (1-indexed)
                if line_number > len(lines) + 1:
                    return f"Error: line_number {line_number} is beyond file length {len(lines)}"

                # Ensure text ends with newline if inserting in middle
                insert_text = text if text.endswith("\n") else text + "\n"
                lines.insert(line_number - 1, insert_text)

                async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
                    await f.write("".join(lines))
                return f"Successfully inserted text at line {line_number} in {file_path}"

            else:
                return f"Error: Unknown operation '{operation}'. Supported: replace, append, insert_at_line"

        except Exception as e:
            return f"Error executing edit: {str(e)}"
