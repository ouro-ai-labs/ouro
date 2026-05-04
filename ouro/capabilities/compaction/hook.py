"""CompactionHook — adapts CompactionManager into the core loop's Hook protocol.

The hook owns the full compaction pipeline: detect-need → run a
cache-safe LLM call to produce a summary → apply that summary to the
loop's detached message list in place.  The core loop knows nothing
about compaction; it just gives every hook a chance to pre-empt the
iteration via ``on_iteration_start``.
"""

from __future__ import annotations

from typing import Any

from ouro.core.log import get_logger
from ouro.core.loop import MessageListContext
from ouro.core.loop.protocols import LoopContext

from .manager import CompactionManager

logger = get_logger(__name__)


class CompactionHook:
    """Wires a CompactionManager into the core agent loop.

    Structurally satisfies the ``core.loop.Hook`` Protocol via the
    single ``on_iteration_start`` method.  We deliberately *don't*
    inherit from ``Hook``: Protocol method bodies are ``...`` which
    at runtime resolves to ``return None``.  Inheriting would supply
    no-op stubs for every lifecycle method, and ``before_call``'s
    ``None`` return would clobber upstream hooks' transformations in
    the ``_build_outgoing`` chain.
    """

    def __init__(
        self,
        compaction: CompactionManager,
        *,
        max_tokens: int = 4096,
    ) -> None:
        self.compaction = compaction
        # Token budget for the compaction LLM call (the summary
        # response).  Mirrors ``Agent.max_tokens_per_call`` so the
        # summary has room to express itself.
        self.max_tokens = max_tokens

    async def on_iteration_start(
        self,
        ctx: LoopContext,
        context: MessageListContext,
        tools: list[dict[str, Any]],
    ) -> None:
        snap = context.detached.snapshot()
        if not snap:
            return
        tokens = self.compaction.estimate_tokens(snap)
        should, _reason = self.compaction.should_compress(tokens)
        if not should:
            return

        # Cache-safe fork: system + current detached + the compaction
        # prompt.  Reusing the live system prefix keeps the prompt
        # cache hot for both the compaction call and the regular LLM
        # call the loop will issue right after we return.
        compaction_prompt = await self.compaction.build_compaction_prompt(snap, tokens)
        fork_messages = list(context.system_messages) + snap + [compaction_prompt]

        async with ctx.progress.spinner("Compressing memory...", title="Working"):
            response = await self.compaction.llm.call_async(
                messages=fork_messages,
                tools=tools,
                max_tokens=self.max_tokens,
            )

        summary = self.compaction.llm.extract_text(response)
        usage = getattr(response, "usage", None) or {}
        compressed = self.compaction.apply_compression(summary, snap, usage)
        context.detached.replace(compressed)
        ctx.add_usage(usage)
