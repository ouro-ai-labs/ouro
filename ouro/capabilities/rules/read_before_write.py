"""ReadBeforeWriteRule — block blind overwrites of files the agent hasn't read.

A tool-aware loop rule (implements the core ``Rule`` contract). It guards
against the model issuing ``write_file`` / ``smart_edit`` on an *existing* file
it never looked at this session — a common way to clobber content the model is
only guessing about.

- ``after_toolcall`` records the ``file_path`` of every read (``read_file``) and
  every successful write/edit (writing a file means the agent now knows its
  contents), keyed by absolute path.
- ``before_toolcall`` blocks a write/edit when the target file **exists on disk**
  but is not in the recorded set, returning a message telling the model to read
  it first. Creating a brand-new file (path does not exist) is allowed, as is
  re-editing a file already read or written this session.

State is per-run: it self-resets when the loop hands the rule a new
``RunStatistic`` context (a fresh object each ``Agent.run``), so reads from one
session never authorize writes in the next.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from ouro.core.log import get_logger

if TYPE_CHECKING:
    from ouro.core.llm import ToolCall, ToolResult
    from ouro.core.loop.protocols import LoopContext

logger = get_logger(__name__)

# Tools that mutate the file at their ``file_path`` argument.
_DEFAULT_WRITE_TOOLS = frozenset({"write_file", "smart_edit"})
# Tools that read a specific file at their ``file_path`` argument.
_DEFAULT_READ_TOOLS = frozenset({"read_file"})


class ReadBeforeWriteRule:
    """Require a file to be read before it is overwritten/edited (see module doc)."""

    name = "read_before_write"

    def __init__(
        self,
        *,
        write_tools: frozenset[str] = _DEFAULT_WRITE_TOOLS,
        read_tools: frozenset[str] = _DEFAULT_READ_TOOLS,
    ) -> None:
        self._write_tools = write_tools
        self._read_tools = read_tools
        # Absolute paths the agent has read or written *this run*.
        # A path maps to True only when the file was read in full (no offset/limit).
        self._seen: set[str] = set()
        # Absolute paths that were read with offset/limit or returned partial content.
        self._partial: set[str] = set()
        # Identity of the run context last observed; a new one means a new run.
        self._last_ctx: object | None = None

    def _reset_on_new_run(self, ctx: LoopContext) -> None:
        # ``RunStatistic`` is constructed fresh per ``Agent.run``; a different
        # object identity is the reliable signal that a new run has started.
        if ctx is not self._last_ctx:
            self._seen.clear()
            self._partial.clear()
            self._last_ctx = ctx

    @staticmethod
    def _abs_path(tool_call: ToolCall) -> str | None:
        raw = tool_call.arguments.get("file_path")
        if not isinstance(raw, str) or not raw:
            return None
        return os.path.abspath(raw)

    def before_toolcall(self, ctx: LoopContext, tool_call: ToolCall) -> str | None:
        self._reset_on_new_run(ctx)
        if tool_call.name not in self._write_tools:
            return None
        path = self._abs_path(tool_call)
        if path is None or path in self._seen:
            return None
        # Creating a new file is fine; only guard overwrites of existing content.
        if not os.path.exists(path):
            return None
        # The file was read, but only partially (offset/limit or truncated).
        # Force a full read before allowing edits.
        if path in self._partial:
            logger.warning(
                "ReadBeforeWriteRule: blocked %s on partial-read file %r",
                tool_call.name,
                tool_call.arguments.get("file_path"),
            )
            return (
                f"[ouro] Refusing to run {tool_call.name} on "
                f"{tool_call.arguments.get('file_path')!r}: you only read a "
                "partial view of this file earlier (offset/limit or truncated). "
                "Call read_file without pagination to load the full contents, "
                "then retry your change."
            )
        logger.warning(
            "ReadBeforeWriteRule: blocked %s on unread existing file %r",
            tool_call.name,
            tool_call.arguments.get("file_path"),
        )
        return (
            f"[ouro] Refusing to run {tool_call.name} on "
            f"{tool_call.arguments.get('file_path')!r}: it exists but you have not "
            "read it this session, so an edit would be based on guessed contents. "
            "Call read_file on it first, then retry your change."
        )

    @staticmethod
    def _is_partial_read(tool_call: ToolCall, tool_result: ToolResult) -> bool:
        """Detect whether a read_file call returned partial/truncated content.

        Heuristics:
        - offset > 0 or limit is set → pagination
        - result contains '[Lines X-Y of Z]' header → paginated
        - result mentions 'too large' or 'Showing code structure instead' → truncated
        """
        if tool_call.name != "read_file":
            return False
        args = tool_call.arguments
        if args.get("offset", 0) > 0 or args.get("limit") is not None:
            return True
        content = tool_result.content or ""
        return (
            content.startswith("[Lines ")
            or "too large" in content
            or "Showing code structure instead" in content
        )

    def after_toolcall(
        self, ctx: LoopContext, tool_call: ToolCall, tool_result: ToolResult
    ) -> str | None:
        # A read makes a file known; a dispatched write/edit means we now know
        # its post-write contents. Either way, record it. Never rewrites results.
        self._reset_on_new_run(ctx)
        if tool_call.name in self._read_tools or tool_call.name in self._write_tools:
            path = self._abs_path(tool_call)
            if path is not None:
                if self._is_partial_read(tool_call, tool_result):
                    self._partial.add(path)
                else:
                    self._seen.add(path)
        return None
