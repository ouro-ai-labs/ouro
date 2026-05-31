"""Advanced file operation tools inspired by Claude Code."""

import asyncio
import contextlib
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiofiles
import aiofiles.os

from ouro.capabilities.tools.base import BaseTool


class GlobTool(BaseTool):
    """Fast file pattern matching tool."""

    readonly = True

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

    readonly = True

    # Default cap on grep results when head_limit is unspecified.
    # 250 is generous enough for exploratory searches while preventing context bloat.
    # Pass head_limit=0 explicitly for unlimited.
    DEFAULT_HEAD_LIMIT = 250

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

ALWAYS use grep_content for code search tasks. NEVER invoke `grep` or `rg` as a shell command — this tool has correct permissions and ignore patterns configured.
If you just searched for a pattern and got results, do NOT run the exact same search again. Read the matching files or refine your pattern instead.

Output modes:
- files_only: Just list files containing matches (default)
- with_context: Show matching lines with line numbers
- count: Count matches per file

Options:
- file_pattern: Glob pattern to filter files (e.g., '**/*.py', 'src/**/*.js')
- type: File type to search (e.g., 'py', 'js', 'rust') — more efficient than glob for standard types
- exclude_patterns: Glob patterns to exclude (e.g., ['**/*.pyc', 'node_modules/**'])
- context_lines: Show N lines before and after matches (with_context mode)
- multiline: Enable multiline pattern matching
- head_limit: Limit output to first N results (default: 250, 0 = unlimited)
- offset: Skip first N results before applying head_limit (default: 0)

Examples:
- Find functions: pattern="def\\s+\\w+", file_pattern="**/*.py"
- Search imports: pattern="^import\\s+", type="py"
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
            "type": {
                "type": "string",
                "description": "File type to search (e.g., 'py', 'js', 'rust') — more efficient than glob for standard types",
            },
            "exclude_patterns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of glob patterns to exclude (e.g., ['**/*.pyc', 'node_modules/**'])",
            },
            "context_lines": {
                "type": "integer",
                "description": "Number of lines to show before and after each match (default: 0)",
            },
            "multiline": {
                "type": "boolean",
                "description": "Enable multiline pattern matching (default: false)",
            },
            "head_limit": {
                "type": "integer",
                "description": "Limit output to first N results (default: 250, 0 = unlimited)",
            },
            "offset": {
                "type": "integer",
                "description": "Skip first N results before applying head_limit (default: 0)",
            },
        }

    async def execute(
        self,
        pattern: str,
        path: str = ".",
        mode: str = "files_only",
        case_sensitive: bool = True,
        file_pattern: str = None,
        type: str = None,
        exclude_patterns: list = None,
        context_lines: int = 0,
        multiline: bool = False,
        head_limit: int = None,
        offset: int = 0,
        **kwargs,
    ) -> str:
        """Search for pattern in files with optional file filtering."""
        base_path = Path(path)
        if not await aiofiles.os.path.exists(str(base_path)):
            return f"Error: Path does not exist: {path}"

        # Normalize head_limit: None -> DEFAULT_HEAD_LIMIT, 0 -> unlimited
        effective_head_limit = head_limit if head_limit is not None else self.DEFAULT_HEAD_LIMIT

        # Use ripgrep if available
        if self._has_ripgrep:
            return await self._execute_ripgrep(
                pattern=pattern,
                path=path,
                mode=mode,
                case_sensitive=case_sensitive,
                file_pattern=file_pattern,
                type=type,
                exclude_patterns=exclude_patterns,
                context_lines=context_lines,
                multiline=multiline,
                head_limit=effective_head_limit,
                offset=offset,
            )
        else:
            return await self._execute_python_fallback(
                pattern=pattern,
                path=path,
                mode=mode,
                case_sensitive=case_sensitive,
                file_pattern=file_pattern,
                type=type,
                exclude_patterns=exclude_patterns,
                context_lines=context_lines,
                multiline=multiline,
                head_limit=effective_head_limit,
                offset=offset,
            )

    def _apply_head_limit(
        self,
        items: list[str],
        head_limit: int,
        offset: int = 0,
    ) -> tuple[list[str], bool]:
        """Apply head_limit and offset to result items.

        Returns (sliced_items, was_truncated).
        """
        # Explicit 0 = unlimited escape hatch
        if head_limit == 0:
            return items[offset:], False

        sliced = items[offset : offset + head_limit]
        was_truncated = len(items) - offset > head_limit
        return sliced, was_truncated

    def _format_pagination_hint(
        self,
        mode: str,
        shown: int,
        total: int,
        was_truncated: bool,
        head_limit: int,
        offset: int,
    ) -> str:
        """Build a clear pagination / completion hint."""
        if mode == "files_only":
            noun = "file" if total == 1 else "files"
            if was_truncated:
                return f"Found {total} {noun} (showing {shown}, use offset={offset + head_limit} to see more)"
            return f"Found {total} {noun}"

        if mode == "count":
            noun = "file" if total == 1 else "files"
            if was_truncated:
                return f"Found {total} {noun} with matches (showing {shown}, use offset={offset + head_limit} to see more)"
            return f"Found {total} {noun} with matches"

        # with_context mode
        noun = "line" if total == 1 else "lines"
        if was_truncated:
            return f"Found {total} matching {noun} (showing {shown}, use offset={offset + head_limit} to see more)"
        return f"Found {total} matching {noun}"

    async def _execute_ripgrep(
        self,
        pattern: str,
        path: str,
        mode: str,
        case_sensitive: bool,
        file_pattern: Optional[str],
        type: Optional[str],
        exclude_patterns: Optional[List[str]],
        context_lines: int,
        multiline: bool,
        head_limit: int,
        offset: int,
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
            cmd.append("--heading")  # group matches by file, print path once
            if context_lines > 0:
                cmd.extend(["-C", str(context_lines)])

        # Case sensitivity
        if not case_sensitive:
            cmd.append("-i")

        # Multiline mode
        if multiline:
            cmd.append("-U")  # --multiline

        # File type filtering
        if type:
            cmd.extend(["--type", type])

        # File pattern filtering via glob
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

            # Split into lines and apply head_limit/offset
            lines = output.strip().split("\n") if output.strip() else []
            total_lines = len(lines)
            sliced_lines, was_truncated = self._apply_head_limit(lines, head_limit, offset)

            # Build pagination hint
            hint = self._format_pagination_hint(
                mode, len(sliced_lines), total_lines, was_truncated, head_limit, offset
            )

            result = hint + "\n" + "\n".join(sliced_lines) if sliced_lines else hint

            # Check output size
            estimated_tokens = len(result) // self.CHARS_PER_TOKEN
            if estimated_tokens > self.MAX_TOKENS:
                max_chars = self.MAX_TOKENS * self.CHARS_PER_TOKEN
                result = result[:max_chars]
                result += f"\n... (output truncated to ~{self.MAX_TOKENS} tokens)"

            return result

        except Exception as e:
            return f"Error executing ripgrep: {str(e)}"

    async def _execute_python_fallback(
        self,
        pattern: str,
        path: str,
        mode: str,
        case_sensitive: bool,
        file_pattern: Optional[str],
        type: Optional[str],
        exclude_patterns: Optional[List[str]],
        context_lines: int,
        multiline: bool,
        head_limit: int,
        offset: int,
    ) -> str:
        """Execute search using Python regex (fallback when ripgrep not available)."""
        try:
            flags = 0 if case_sensitive else re.IGNORECASE
            if multiline:
                flags |= re.DOTALL
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

            # Collect all results first, then apply head_limit/offset
            all_results = []
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
                        all_results.append(str(file_path))
                    elif mode == "count":
                        all_results.append(f"{file_path}: {len(matches)} matches")
                    elif mode == "with_context":
                        lines = content.splitlines()
                        for match in matches:
                            line_no = content[: match.start()].count("\n") + 1
                            if line_no <= len(lines):
                                all_results.append(
                                    f"{file_path}:{line_no}: {lines[line_no-1].strip()}"
                                )
                except (UnicodeDecodeError, PermissionError):
                    continue

            total_results = len(all_results)
            sliced_results, was_truncated = self._apply_head_limit(all_results, head_limit, offset)

            # Build pagination hint
            hint = self._format_pagination_hint(
                mode, len(sliced_results), total_results, was_truncated, head_limit, offset
            )

            if not sliced_results:
                if total_results == 0:
                    return f"No matches found for pattern '{pattern}' in {files_searched} files searched"
                return hint

            result = hint + "\n" + "\n".join(sliced_results)

            # Check output size
            estimated_tokens = len(result) // self.CHARS_PER_TOKEN
            if estimated_tokens > self.MAX_TOKENS:
                return (
                    f"Error: Grep output (~{estimated_tokens} tokens) exceeds "
                    f"maximum allowed ({self.MAX_TOKENS}). Please use more specific "
                    f"file_pattern or pattern to narrow results."
                )

            return result
        except Exception as e:
            return f"Error executing grep: {str(e)}"
