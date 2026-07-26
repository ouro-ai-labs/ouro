"""Tools that operate inside the configured sandbox."""

from __future__ import annotations

import os
from difflib import SequenceMatcher, unified_diff
from typing import Any

from ouro.core.sandbox import SandboxExecResult, SandboxSession

from ..base import BaseTool


def _format_exec_result(result: SandboxExecResult) -> str:
    output = result.stdout or ""
    if result.stderr:
        output = output + result.stderr if not output else output + result.stderr
    if result.timed_out:
        return output + ("\n" if output else "") + "Error: Sandbox command timed out"
    if result.exit_code != 0:
        output = f"{output}\n[exit {result.exit_code}]" if output else f"[exit {result.exit_code}]"
    return output or "Sandbox command executed successfully (no output)"


def _check_output_size(tool: BaseTool, output: str) -> str:
    estimated_tokens = len(output) // tool.CHARS_PER_TOKEN
    if estimated_tokens > tool.MAX_TOKENS:
        return (
            f"Error: Sandbox tool output (~{estimated_tokens} tokens) exceeds maximum "
            f"allowed ({tool.MAX_TOKENS}). Use pagination, grep, or redirect output to a file."
        )
    return output


class SandboxShellTool(BaseTool):
    """Execute shell commands inside the configured sandbox."""

    def __init__(self, session: SandboxSession):
        self.session = session

    @property
    def name(self) -> str:
        return "sandbox_shell"

    @property
    def description(self) -> str:
        return (
            "Execute shell commands inside the configured sandbox, not on the host. "
            "Returns stdout/stderr. Commands that exceed the timeout are killed or return an error."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "command": {"type": "string", "description": "Shell command to execute in the sandbox"},
            "timeout": {"type": "number", "description": "Timeout in seconds", "default": 120.0},
            "cwd": {
                "type": "string",
                "description": "Working directory inside the sandbox (default: sandbox profile working_dir)",
                "default": None,
            },
        }

    async def execute(self, command: str, timeout: float = 120.0, cwd: str | None = None) -> str:
        try:
            result = await self.session.exec(command, cwd=cwd, timeout=timeout)
            return _check_output_size(self, _format_exec_result(result))
        except Exception as e:
            return f"Error executing sandbox command: {e}"


class SandboxReadFileTool(BaseTool):
    """Read files inside the sandbox."""

    readonly = True

    def __init__(self, session: SandboxSession):
        self.session = session

    @property
    def name(self) -> str:
        return "sandbox_read_file"

    @property
    def description(self) -> str:
        return (
            "Read contents of a file inside the configured sandbox, not on the host. "
            "For large files, use offset and limit parameters."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "file_path": {"type": "string", "description": "Path inside the sandbox to read"},
            "offset": {
                "type": "integer",
                "description": "Line number to start from (0-indexed)",
                "default": 0,
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to read",
                "default": None,
            },
        }

    async def execute(self, file_path: str, offset: int = 0, limit: int | None = None) -> str:
        try:
            content = await self.session.read_file(file_path, offset=offset, limit=limit)
            return _check_output_size(self, content)
        except Exception as e:
            return f"Error reading sandbox file: {e}"


class SandboxWriteFileTool(BaseTool):
    """Write files inside the sandbox."""

    def __init__(self, session: SandboxSession):
        self.session = session

    @property
    def name(self) -> str:
        return "sandbox_write_file"

    @property
    def description(self) -> str:
        return "Write content to a file inside the configured sandbox, not on the host."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "file_path": {"type": "string", "description": "Path inside the sandbox to write"},
            "content": {"type": "string", "description": "Content to write"},
        }

    def conflict_keys(self, **kwargs: Any) -> set[str] | None:
        file_path = kwargs.get("file_path")
        if not isinstance(file_path, str) or not file_path:
            return None
        return {f"sandbox:{self.session.id}:{os.path.normpath(file_path)}"}

    async def execute(self, file_path: str, content: str) -> str:
        try:
            await self.session.write_file(file_path, content)
            return f"Successfully wrote sandbox file {file_path}"
        except Exception as e:
            return f"Error writing sandbox file: {e}"


class SandboxGlobTool(BaseTool):
    """Glob files inside the sandbox."""

    readonly = True

    def __init__(self, session: SandboxSession):
        self.session = session

    @property
    def name(self) -> str:
        return "sandbox_glob_files"

    @property
    def description(self) -> str:
        return "Fast file pattern matching inside the configured sandbox, not on the host."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "pattern": {"type": "string", "description": "Glob pattern to match files"},
            "path": {
                "type": "string",
                "description": "Base directory inside sandbox",
                "default": ".",
            },
        }

    async def execute(self, pattern: str, path: str = ".") -> str:
        try:
            matches = await self.session.glob(pattern, path=path)
            if not matches:
                return f"No sandbox files found matching pattern: {pattern} in {path}"
            if len(matches) > 100:
                return "\n".join(matches[:100] + [f"\n... and {len(matches) - 100} more files"])
            return "\n".join(matches)
        except Exception as e:
            return f"Error executing sandbox glob: {e}"


class SandboxGrepTool(BaseTool):
    """Grep files inside the sandbox."""

    readonly = True

    def __init__(self, session: SandboxSession):
        self.session = session

    @property
    def name(self) -> str:
        return "sandbox_grep_content"

    @property
    def description(self) -> str:
        return (
            "Search file contents inside the configured sandbox, not on the host. "
            "Use this for code/content search in sandbox files."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "pattern": {"type": "string", "description": "Regex pattern to search for"},
            "path": {"type": "string", "description": "Directory inside sandbox", "default": "."},
            "mode": {
                "type": "string",
                "description": "files_only, with_context, or count",
                "default": "files_only",
            },
            "case_sensitive": {
                "type": "boolean",
                "description": "Case sensitive search",
                "default": True,
            },
            "file_pattern": {
                "type": "string",
                "description": "Optional glob filter",
                "default": None,
            },
            "context_lines": {"type": "integer", "description": "Context lines", "default": 0},
            "head_limit": {
                "type": "integer",
                "description": "Limit results; 0 = unlimited",
                "default": 250,
            },
            "offset": {"type": "integer", "description": "Skip first N results", "default": 0},
        }

    async def execute(
        self,
        pattern: str,
        path: str = ".",
        mode: str = "files_only",
        case_sensitive: bool = True,
        file_pattern: str | None = None,
        context_lines: int = 0,
        head_limit: int | None = 250,
        offset: int = 0,
        **kwargs,
    ) -> str:
        try:
            output = await self.session.grep(
                pattern,
                path=path,
                mode=mode,
                case_sensitive=case_sensitive,
                file_pattern=file_pattern,
                context_lines=context_lines,
                head_limit=head_limit,
                offset=offset,
            )
            return _check_output_size(self, output)
        except Exception as e:
            return f"Error executing sandbox grep: {e}"


class SandboxSmartEditTool(BaseTool):
    """Smart edit for files inside the sandbox."""

    def __init__(self, session: SandboxSession):
        self.session = session
        self.fuzzy_threshold = 0.8

    @property
    def name(self) -> str:
        return "sandbox_smart_edit"

    @property
    def description(self) -> str:
        return (
            "Intelligent code editing inside the configured sandbox, not on the host. "
            "Supports diff_replace, smart_insert, and block_edit with diff preview."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "file_path": {"type": "string", "description": "Path inside sandbox to edit"},
            "mode": {"type": "string", "description": "diff_replace, smart_insert, or block_edit"},
            "old_code": {"type": "string", "description": "Code to replace", "default": ""},
            "new_code": {"type": "string", "description": "New code", "default": ""},
            "anchor": {"type": "string", "description": "Anchor for smart_insert", "default": ""},
            "code": {"type": "string", "description": "Code to insert", "default": ""},
            "position": {"type": "string", "description": "before or after", "default": "after"},
            "start_line": {
                "type": "integer",
                "description": "Start line for block_edit",
                "default": 0,
            },
            "end_line": {"type": "integer", "description": "End line for block_edit", "default": 0},
            "fuzzy_match": {
                "type": "boolean",
                "description": "Enable fuzzy matching",
                "default": True,
            },
            "dry_run": {
                "type": "boolean",
                "description": "Preview without writing",
                "default": False,
            },
            "show_diff": {"type": "boolean", "description": "Show diff preview", "default": True},
        }

    def conflict_keys(self, **kwargs: Any) -> set[str] | None:
        file_path = kwargs.get("file_path")
        if not isinstance(file_path, str) or not file_path:
            return None
        return {f"sandbox:{self.session.id}:{os.path.normpath(file_path)}"}

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
        show_diff: bool = True,
        **kwargs,
    ) -> str:
        try:
            original = await self.session.read_file(file_path)
            if mode == "diff_replace":
                return await self._diff_replace(
                    file_path, original, old_code, new_code, fuzzy_match, dry_run, show_diff
                )
            if mode == "smart_insert":
                return await self._smart_insert(
                    file_path, original, anchor, code, position, dry_run, show_diff
                )
            if mode == "block_edit":
                return await self._block_edit(
                    file_path, original, start_line, end_line, new_code, dry_run, show_diff
                )
            return (
                f"Error: Unknown mode '{mode}'. Supported: diff_replace, smart_insert, block_edit"
            )
        except Exception as e:
            return f"Error executing sandbox_smart_edit: {e}"

    async def _diff_replace(
        self,
        path: str,
        original: str,
        old_code: str,
        new_code: str,
        fuzzy_match: bool,
        dry_run: bool,
        show_diff: bool,
    ) -> str:
        if not old_code:
            return "Error: old_code parameter is required for diff_replace mode"
        similarity = 1.0
        info = ""
        if old_code in original:
            start = original.find(old_code)
            end = start + len(old_code)
        elif fuzzy_match:
            found = self._fuzzy_find(old_code, original)
            if found is None:
                return f"Error: Could not find code block (even with fuzzy matching).\n\nSearched for:\n{old_code[:200]}..."
            start, end, similarity = found
            if similarity < 0.99:
                info = f"\n[Fuzzy match found with {similarity:.1%} similarity]\nMatched text:\n{original[start:end][:200]}...\n"
        else:
            return f"Error: Exact match not found and fuzzy_match is disabled.\n\nSearched for:\n{old_code[:200]}..."
        new_content = original[:start] + new_code + original[end:]
        return await self._maybe_write(
            path,
            original,
            new_content,
            dry_run,
            show_diff,
            info,
            f"Successfully edited sandbox file {path}",
        )

    async def _smart_insert(
        self,
        path: str,
        original: str,
        anchor: str,
        code: str,
        position: str,
        dry_run: bool,
        show_diff: bool,
    ) -> str:
        if not anchor:
            return "Error: anchor parameter is required for smart_insert mode"
        if not code:
            return "Error: code parameter is required for smart_insert mode"
        lines = original.splitlines(keepends=True)
        idx = next((i for i, line in enumerate(lines) if anchor in line), None)
        if idx is None:
            return f"Error: Anchor line not found: {anchor}"
        if not code.endswith("\n"):
            code += "\n"
        lines.insert(idx if position == "before" else idx + 1, code)
        return await self._maybe_write(
            path,
            original,
            "".join(lines),
            dry_run,
            show_diff,
            "",
            f"Successfully inserted code {position} anchor in sandbox file {path}",
        )

    async def _block_edit(
        self,
        path: str,
        original: str,
        start_line: int,
        end_line: int,
        new_block: str,
        dry_run: bool,
        show_diff: bool,
    ) -> str:
        if start_line <= 0 or end_line <= 0:
            return "Error: line numbers must be positive (1-indexed)"
        if start_line > end_line:
            return "Error: start_line must be <= end_line"
        lines = original.splitlines(keepends=True)
        if start_line > len(lines) or end_line > len(lines):
            return f"Error: line range {start_line}-{end_line} exceeds file length {len(lines)}"
        if not new_block.endswith("\n"):
            new_block += "\n"
        new_content = "".join(lines[: start_line - 1] + [new_block] + lines[end_line:])
        return await self._maybe_write(
            path,
            original,
            new_content,
            dry_run,
            show_diff,
            "",
            f"Successfully edited sandbox lines {start_line}-{end_line} in {path}",
        )

    async def _maybe_write(
        self,
        path: str,
        original: str,
        new_content: str,
        dry_run: bool,
        show_diff: bool,
        info: str,
        success: str,
    ) -> str:
        parts = []
        if show_diff or dry_run:
            if info:
                parts.append(info)
            parts.append(f"Diff preview:\n{self._generate_diff(original, new_content, path)}\n")
        if dry_run:
            parts.append("[DRY RUN] No changes made to sandbox file.")
            return "\n".join(parts)
        await self.session.write_file(path, new_content)
        parts.append(success)
        return "\n".join(parts)

    def _fuzzy_find(self, target: str, text: str) -> tuple[int, int, float] | None:
        target_norm = self._normalize_whitespace(target)
        target_lines = target.splitlines()
        text_lines = text.splitlines()
        best = None
        best_ratio = 0.0
        for window_size in range(len(target_lines), len(target_lines) + 5):
            if window_size > len(text_lines):
                break
            for i in range(len(text_lines) - window_size + 1):
                window = text_lines[i : i + window_size]
                window_text = "\n".join(window)
                ratio = SequenceMatcher(
                    None, target_norm, self._normalize_whitespace(window_text)
                ).ratio()
                if ratio > best_ratio and ratio >= self.fuzzy_threshold:
                    char_start = len("\n".join(text_lines[:i]))
                    if i > 0:
                        char_start += 1
                    best = (char_start, char_start + len(window_text), ratio)
                    best_ratio = ratio
        return best

    def _normalize_whitespace(self, text: str) -> str:
        return "\n".join(" ".join(line.split()) for line in text.splitlines())

    def _generate_diff(self, old: str, new: str, filename: str) -> str:
        return "".join(
            unified_diff(
                old.splitlines(keepends=True),
                new.splitlines(keepends=True),
                fromfile=f"{filename} (sandbox original)",
                tofile=f"{filename} (sandbox modified)",
                lineterm="",
                n=3,
            )
        )


def create_sandbox_tools(session: SandboxSession) -> list[BaseTool]:
    """Create the default sandbox toolset for a session."""

    return [
        SandboxShellTool(session),
        SandboxReadFileTool(session),
        SandboxWriteFileTool(session),
        SandboxGlobTool(session),
        SandboxGrepTool(session),
        SandboxSmartEditTool(session),
    ]
