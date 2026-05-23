"""memory_block_edit — edit named long-term memory blocks.

Single tool with an ``operation`` argument (``replace`` / ``append`` / ``read``)
instead of three sibling tools. Fewer schema tokens on every turn, and the LLM
only needs to remember one name. Strict blocks (``user``, ``project``) raise
``BlockBudgetExceeded`` on overflow — the tool surfaces the error verbatim so
the LLM can trim and retry.
"""

from __future__ import annotations

from typing import Any

from ouro.capabilities.memory.blocks import (
    BlockBudgetExceeded,
    MemoryBlockManager,
)

from ..base import BaseTool


class MemoryBlockEditTool(BaseTool):
    """Edit or read named long-term memory blocks."""

    def __init__(self, manager: MemoryBlockManager) -> None:
        self._manager = manager

    @property
    def name(self) -> str:
        return "memory_block_edit"

    @property
    def description(self) -> str:
        return (
            "Edit or read your long-term memory blocks (user / project / scratch). "
            "Use this to remember durable facts across sessions instead of "
            "re-deriving them. `operation` is 'read', 'replace', or 'append'."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "block": {
                "type": "string",
                "description": "Block name: 'user', 'project', or 'scratch'.",
            },
            "operation": {
                "type": "string",
                "enum": ["read", "replace", "append"],
                "description": (
                    "'read' returns current contents; 'replace' swaps `old` for "
                    "`content` (or replaces the whole block if `old` is empty); "
                    "'append' adds `content` at the end."
                ),
            },
            "content": {
                "type": "string",
                "description": "New text to write. Required for replace/append.",
                "default": "",
            },
            "old": {
                "type": "string",
                "description": (
                    "Exact existing text to replace. Required for replace when "
                    "doing a targeted edit; omit for a full-block overwrite."
                ),
                "default": "",
            },
        }

    def conflict_keys(self, **kwargs: Any) -> set[str] | None:
        # Each block is its own resource; concurrent edits to different blocks are fine.
        op = kwargs.get("operation", "")
        block = kwargs.get("block", "")
        if op == "read":
            return set()
        return {f"memory_block:{block}"} if block else None

    async def execute(
        self,
        block: str = "",
        operation: str = "",
        content: str = "",
        old: str = "",
    ) -> str:
        block = (block or "").strip()
        op = (operation or "").strip().lower()
        if not block:
            return "Error: `block` is required (e.g. 'user', 'project', 'scratch')."
        if op not in {"read", "replace", "append"}:
            return f"Error: unknown operation {operation!r}. Use 'read', 'replace', or 'append'."

        if op == "read":
            body = await self._manager.read(block)
            if not body.strip():
                return f"Block {block!r} is empty."
            return f"--- {block} ---\n{body}"

        if not content:
            return f"Error: `content` is required for operation={op!r}."

        try:
            if op == "replace":
                result = await self._manager.replace(block, old, content)
            else:
                result = await self._manager.append(block, content)
        except BlockBudgetExceeded as e:
            return f"Error: {e}"
        except ValueError as e:
            return f"Error: {e}"

        return (
            f"Block {result.name!r} updated: {result.tokens} tokens "
            f"(budget {self._manager.block_budgets.get(result.name, 0)})."
        )
