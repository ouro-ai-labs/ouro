"""MemoryHook — adapts MemoryManager into the core loop's Hook protocol.

This hook owns persistence, compaction-decision logic, and the substitution
of compressed-context messages on every LLM call. It does not call into the
LLM directly during compaction — the loop performs the cache-safe fork call
itself, then hands the summary back via `CompactionDecision.on_summary`.
"""

from __future__ import annotations

from typing import Any

from ouro.core.llm import LLMMessage, LLMResponse, ToolCall, ToolResult
from ouro.core.log import get_logger
from ouro.core.loop.protocols import (
    CompactionDecision,
    LoopContext,
)

from .manager import MemoryManager

logger = get_logger(__name__)


class MemoryHook:
    """Wires a MemoryManager into the core agent loop.

    Lifecycle:
    - before_call: substitute messages with `memory.get_context_for_llm()`.
    - after_call: persist the assistant response (with usage).
    - after_tool: persist the tool result message.
    - on_compact_check: ask memory whether compression is needed; if yes,
      hand back a CompactionDecision so the loop runs the cache-safe fork
      call and we apply the summary on its return.

    NOTE: Adding the user task message is the *caller's* responsibility (the
    `ComposedAgent` wrapper does this so it can handle multimodal images).
    Memory is incrementally persisted after every add_message — no explicit
    flush is required at run end.
    """

    def __init__(self, memory: MemoryManager) -> None:
        self.memory = memory

    # ---- lifecycle ------------------------------------------------------

    async def before_call(
        self,
        ctx: LoopContext,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]],
    ) -> list[LLMMessage]:
        # Tool schemas drive token accounting for compaction triggers.
        self.memory.set_tool_schemas(tools)
        return self.memory.get_context_for_llm()

    async def after_call(self, ctx: LoopContext, response: LLMResponse) -> LLMResponse:
        usage = getattr(response, "usage", None)
        await self.memory.add_message(response.to_message(), usage=usage)
        if self.memory.was_compressed_last_iteration:
            logger.debug(
                "Memory compressed: saved %s tokens",
                self.memory.last_compression_savings,
            )
        return response

    async def after_tool(
        self,
        ctx: LoopContext,
        tool_call: ToolCall,
        result: ToolResult,
    ) -> ToolResult:
        # MemoryManager stores tool result messages in the OpenAI shape.
        await self.memory.add_message(
            LLMMessage(
                role="tool",
                content=result.content,
                tool_call_id=tool_call.id,
                name=tool_call.name,
            )
        )
        return result

    # ---- specialty ------------------------------------------------------

    async def on_compact_check(
        self, ctx: LoopContext, messages: list[LLMMessage]
    ) -> CompactionDecision | None:
        if not self.memory.needs_compression():
            return None
        prompt = await self.memory.get_compaction_prompt()

        async def _on_summary(summary: str, usage: dict[str, int]) -> None:
            self.memory.apply_compression(summary, usage=usage)

        return CompactionDecision(compaction_prompt=prompt, on_summary=_on_summary)
