"""NestedAgentsMdRule — surface subdirectory AGENTS.md when a file under it is read.

A tool-aware loop rule (implements the core ``Rule`` contract), the lazy
counterpart to the eager startup load in ``ouro.capabilities.context.agents_md``.
The eager load covers the working directory and everything above it; AGENTS.md
files in *subdirectories* of the CWD are surfaced only when the agent actually
reads a file under them.

- ``after_toolcall`` watches ``read_file`` calls. When the read target sits in a
  subdirectory of the CWD, it loads every ``AGENTS.md`` along the path from the
  CWD down to that file's directory (parent-first, nearest last; sibling
  subtrees are never scanned) and **appends** them to the read result as a
  ``<project_instructions>`` block, so the subdirectory's rules land right next
  to the file the model just looked at.

Dedup is per-run: an injected-set records which AGENTS.md were already surfaced
and self-resets when the loop hands the rule a new ``RunStatistic`` (a fresh
object each ``Agent.run``), mirroring ``ReadBeforeWriteRule``. So a subdirectory's
AGENTS.md is injected at most once per run.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from ouro.capabilities.context.agents_md import load_nested_instructions
from ouro.core.log import get_logger

if TYPE_CHECKING:
    from ouro.core.llm import ToolCall, ToolResult
    from ouro.core.loop.protocols import LoopContext

logger = get_logger(__name__)

# Tools that read a specific file at their ``file_path`` argument.
_DEFAULT_READ_TOOLS = frozenset({"read_file"})


class NestedAgentsMdRule:
    """Inject subdirectory AGENTS.md when a file under them is read (see module doc)."""

    name = "nested_agents_md"

    def __init__(
        self,
        *,
        cwd: str | None = None,
        read_tools: frozenset[str] = _DEFAULT_READ_TOOLS,
    ) -> None:
        self._cwd = os.path.abspath(cwd or os.getcwd())
        self._read_tools = read_tools
        # Paths of AGENTS.md already surfaced *this run*.
        self._injected: set[str] = set()
        # Identity of the run context last observed; a new one means a new run.
        self._last_ctx: object | None = None

    def _reset_on_new_run(self, ctx: LoopContext) -> None:
        # ``RunStatistic`` is constructed fresh per ``Agent.run``; a different
        # object identity is the reliable signal that a new run has started.
        if ctx is not self._last_ctx:
            self._injected.clear()
            self._last_ctx = ctx

    def after_toolcall(
        self, ctx: LoopContext, tool_call: ToolCall, tool_result: ToolResult
    ) -> str | None:
        self._reset_on_new_run(ctx)
        if tool_call.name not in self._read_tools:
            return None
        raw = tool_call.arguments.get("file_path")
        if not isinstance(raw, str) or not raw:
            return None
        block = load_nested_instructions(self._cwd, raw, self._injected)
        if not block:
            return None
        logger.info("NestedAgentsMdRule: surfaced subdirectory AGENTS.md for %r", raw)
        return f"{tool_result.content}\n\n{block}"
