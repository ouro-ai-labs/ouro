"""Sandbox-backed variants of the standard builtin tools."""

from __future__ import annotations

import os
from typing import Any

from ouro.core.sandbox import SandboxExecResult, SandboxSession

from ..base import BaseTool
from .advanced_file_ops import GlobTool, GrepTool
from .file_ops import FileReadTool, FileWriteTool
from .shell import ShellTool
from .smart_edit import SmartEditTool


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
            f"Error: Tool output (~{estimated_tokens} tokens) exceeds maximum "
            f"allowed ({tool.MAX_TOKENS}). Use pagination, grep, or redirect output to a file."
        )
    return output


def _default_cwd(session: SandboxSession) -> str | None:
    profile = getattr(session, "profile", None)
    working_dir = getattr(profile, "working_dir", None)
    return str(working_dir) if working_dir else None


class SandboxShellTool(ShellTool):
    """Standard shell tool backed by a sandbox session."""

    def __init__(self, session: SandboxSession, attribution_enabled: bool = True):
        super().__init__(attribution_enabled=attribution_enabled)
        self.session = session

    async def execute(self, command: str, timeout: float = 120.0, **kwargs: Any) -> str:
        try:
            result = await self.session.exec(
                command,
                cwd=kwargs.get("cwd") or _default_cwd(self.session),
                timeout=timeout,
            )
            return _check_output_size(self, _format_exec_result(result))
        except Exception as e:
            return f"Error executing sandbox command: {e}"


class SandboxReadFileTool(FileReadTool):
    """Standard read_file tool backed by a sandbox session."""

    def __init__(self, session: SandboxSession):
        self.session = session

    async def execute(self, file_path: str, offset: int = 0, limit: int | None = None) -> str:
        try:
            content = await self.session.read_file(file_path, offset=offset, limit=limit)
            return _check_output_size(self, content)
        except Exception as e:
            return f"Error reading sandbox file: {e}"


class SandboxWriteFileTool(FileWriteTool):
    """Standard write_file tool backed by a sandbox session."""

    def __init__(self, session: SandboxSession):
        self.session = session

    def conflict_keys(self, **kwargs: Any) -> set[str] | None:
        file_path = kwargs.get("file_path")
        if not isinstance(file_path, str) or not file_path:
            return None
        return {f"sandbox:{self.session.id}:{os.path.normpath(file_path)}"}

    async def execute(self, file_path: str, content: str) -> str:
        try:
            await self.session.write_file(file_path, content)
            return f"Successfully wrote to {file_path}"
        except Exception as e:
            return f"Error writing sandbox file: {e}"


class SandboxGlobTool(GlobTool):
    """Standard glob_files tool backed by a sandbox session."""

    def __init__(self, session: SandboxSession):
        self.session = session

    async def execute(self, pattern: str, path: str = ".") -> str:
        try:
            matches = await self.session.glob(pattern, path=path)
            if not matches:
                return f"No files found matching pattern: {pattern} in {path}"
            if len(matches) > 100:
                return "\n".join(matches[:100] + [f"\n... and {len(matches) - 100} more files"])
            return "\n".join(matches)
        except Exception as e:
            return f"Error executing glob: {e}"


class SandboxGrepTool(GrepTool):
    """Standard grep_content tool backed by a sandbox session."""

    def __init__(self, session: SandboxSession):
        # Intentionally do not call GrepTool.__init__(): sandbox grep is handled
        # by the provider/session, not host ripgrep discovery.
        self.session = session

    async def execute(
        self,
        pattern: str,
        path: str = ".",
        mode: str = "files_only",
        case_sensitive: bool = True,
        file_pattern: str | None = None,
        type: str | None = None,
        exclude_patterns: list[str] | None = None,
        context_lines: int = 0,
        multiline: bool = False,
        head_limit: int | None = None,
        offset: int = 0,
        **kwargs: Any,
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
            return f"Error executing grep: {e}"


class SandboxSmartEditTool(SmartEditTool):
    """Standard smart_edit tool backed by a sandbox session."""

    def __init__(self, session: SandboxSession):
        super().__init__()
        self.session = session

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
        create_backup: bool | None = None,
        show_diff: bool = True,
        **kwargs: Any,
    ) -> str:
        try:
            original = await self.session.read_file(file_path)
            if mode == "diff_replace":
                return await self._diff_replace_sandbox(
                    file_path,
                    original,
                    old_code,
                    new_code,
                    fuzzy_match,
                    dry_run,
                    bool(create_backup),
                    show_diff,
                )
            if mode == "smart_insert":
                return await self._smart_insert_sandbox(
                    file_path,
                    original,
                    anchor,
                    code,
                    position,
                    dry_run,
                    bool(create_backup),
                    show_diff,
                )
            if mode == "block_edit":
                return await self._block_edit_sandbox(
                    file_path,
                    original,
                    start_line,
                    end_line,
                    new_code,
                    dry_run,
                    bool(create_backup),
                    show_diff,
                )
            return (
                f"Error: Unknown mode '{mode}'. Supported: diff_replace, smart_insert, block_edit"
            )
        except Exception as e:
            return f"Error executing smart_edit: {e}"

    async def _diff_replace_sandbox(
        self,
        path: str,
        original: str,
        old_code: str,
        new_code: str,
        fuzzy_match: bool,
        dry_run: bool,
        create_backup: bool,
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
                return (
                    "Error: Could not find code block (even with fuzzy matching).\n\n"
                    f"Searched for:\n{old_code[:200]}..."
                )
            start, end, similarity = found
            if similarity < 0.99:
                info = (
                    f"\n[Fuzzy match found with {similarity:.1%} similarity]\n"
                    f"Matched text:\n{original[start:end][:200]}...\n"
                )
        else:
            return (
                "Error: Exact match not found and fuzzy_match is disabled.\n\n"
                f"Searched for:\n{old_code[:200]}..."
            )
        new_content = original[:start] + new_code + original[end:]
        return await self._maybe_write_sandbox(
            path,
            original,
            new_content,
            dry_run,
            create_backup,
            show_diff,
            info,
            f"Successfully edited {path}",
        )

    async def _smart_insert_sandbox(
        self,
        path: str,
        original: str,
        anchor: str,
        code: str,
        position: str,
        dry_run: bool,
        create_backup: bool,
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
        return await self._maybe_write_sandbox(
            path,
            original,
            "".join(lines),
            dry_run,
            create_backup,
            show_diff,
            "",
            f"Successfully inserted code {position} anchor in {path}",
        )

    async def _block_edit_sandbox(
        self,
        path: str,
        original: str,
        start_line: int,
        end_line: int,
        new_block: str,
        dry_run: bool,
        create_backup: bool,
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
        return await self._maybe_write_sandbox(
            path,
            original,
            new_content,
            dry_run,
            create_backup,
            show_diff,
            "",
            f"Successfully edited lines {start_line}-{end_line} in {path}",
        )

    async def _maybe_write_sandbox(
        self,
        path: str,
        original: str,
        new_content: str,
        dry_run: bool,
        create_backup: bool,
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
            parts.append("[DRY RUN] No changes made to file.")
            return "\n".join(parts)
        if create_backup:
            backup_path = f"{path}.bak"
            await self.session.write_file(backup_path, original)
            parts.append(f"Created backup: {backup_path}")
        await self.session.write_file(path, new_content)
        parts.append(success)
        return "\n".join(parts)


def create_sandbox_tools(session: SandboxSession) -> list[BaseTool]:
    """Create standard-named tools backed by a sandbox session."""

    return [
        SandboxReadFileTool(session),
        SandboxWriteFileTool(session),
        SandboxShellTool(session),
        SandboxGlobTool(session),
        SandboxGrepTool(session),
        SandboxSmartEditTool(session),
    ]
