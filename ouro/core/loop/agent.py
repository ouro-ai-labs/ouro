"""Core agent loop.

A class-based ReAct loop with optional hooks. The loop knows nothing about
memory, BaseTool, verification, or terminal UI — those plug in via
`Hook` and `ToolRegistry` from `protocols.py`.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Callable, Sequence

from ouro.core.llm import LLMMessage, LLMResponse, StopReason, ToolCall, ToolOutput, ToolResult
from ouro.core.llm.reasoning import normalize_reasoning_effort
from ouro.core.log import get_logger

from .context import MessageListContext, RunStatistic
from .message_list import MessageList
from .protocols import (
    ContinueDecision,
    ContinueKind,
    Hook,
    LoopContext,
    NullProgressSink,
    ProgressEvent,
    ProgressSink,
    ToolRegistry,
)
from .rules import RepeatedToolCallRule, Rule

logger = get_logger(__name__)


class Agent:
    """Hooks-based core loop."""

    def __init__(
        self,
        llm: Any,
        tools: ToolRegistry,
        hooks: Sequence[Hook] = (),
        max_iterations: int = 1000,
        max_tokens_per_call: int | None = None,
        progress: ProgressSink | None = None,
        usage_callback: Callable[[dict[str, int]], None] | None = None,
        repeat_tool_call_threshold: int = 3,
        rules: Sequence[Rule] = (),
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.hooks: list[Hook] = list(hooks)
        self.max_iterations = max_iterations
        self.max_tokens_per_call = max_tokens_per_call
        self.progress: ProgressSink = progress or NullProgressSink()
        self._reasoning_effort: str | None = None
        self._usage_callback = usage_callback
        # Warn the model after `repeat_tool_call_threshold` consecutive identical
        # tool-call iterations; <= 0 disables the check. See RepeatedToolCallRule.
        self.repeat_tool_call_threshold = repeat_tool_call_threshold
        # Deterministic per-tool-call rules. The repeated-tool-call breaker is
        # always present (governed by the kwarg above); any caller-supplied
        # rules run after it. A rule blocks a call before dispatch or rewrites
        # its result after; it never stops the loop (max_iterations is the
        # runaway backstop). See `rules.py`.
        self.rules: list[Rule] = [RepeatedToolCallRule(repeat_tool_call_threshold)]
        self.rules.extend(rules)

    def set_reasoning_effort(self, value: str | None) -> None:
        self._reasoning_effort = normalize_reasoning_effort(value)

    def add_hook(self, hook: Hook) -> None:
        self.hooks.append(hook)

    def add_rule(self, rule: Rule) -> None:
        self.rules.append(rule)

    async def run(
        self,
        task: str,
        *,
        context: MessageListContext | None = None,
    ) -> str:
        # ``context`` carries the canonical conversation state across runs
        # (system messages + a mutable detached MessageList).  When None,
        # the loop runs in transient mode with an empty context — useful
        # for unit tests and one-shot uses.
        if context is None:
            context = MessageListContext()
        ctx = RunStatistic(task=task, progress=self.progress, usage_callback=self._usage_callback)
        messages = context.detached
        await self._fanout_async("on_run_start", ctx, messages)

        tool_schemas = self.tools.get_tool_schemas()
        final_answer: str = ""
        for ctx.iteration in range(1, self.max_iterations + 1):
            # Hooks may mutate ``context`` in place here (e.g.
            # ``CompactionHook`` compresses ``context.detached``).
            # The loop continues with whatever state they leave behind.
            await self._fanout_async("on_iteration_start", ctx, context, tool_schemas)
            outgoing = context.build_context()

            async with self.progress.spinner(
                "Analyzing request..." if ctx.iteration == 1 else "Processing results..."
            ):
                call_kwargs: dict[str, Any] = {
                    "messages": outgoing,
                    "tools": tool_schemas,
                    **(
                        {"reasoning_effort": self._reasoning_effort}
                        if self._reasoning_effort is not None
                        else {}
                    ),
                }
                if self.max_tokens_per_call is not None:
                    call_kwargs["max_tokens"] = self.max_tokens_per_call
                if os.environ.get("OURO_DEBUG_LLM_HISTORY"):
                    _log_outgoing_messages(ctx.iteration, outgoing)
                response = await self.llm.call_async(**call_kwargs)
            ctx.stop_reason_last = response.stop_reason
            ctx.add_usage(getattr(response, "usage", None))

            extract_thinking = getattr(self.llm, "extract_thinking", None)
            if extract_thinking is not None:
                thinking = extract_thinking(response)
                if thinking:
                    self.progress.emit(ProgressEvent(kind="thinking", payload={"text": thinking}))

            if response.stop_reason == StopReason.STOP:
                # Persist the assistant's final reply into the loop's
                # canonical history so subsequent turns / verification
                # retries see it.  Memory persistence (disk) is a hook
                # concern; the loop only owns in-memory state.
                messages.append(response.to_message())
                final_answer = self.llm.extract_text(response)
                cont = await self._aggregate_continue(ctx, messages, response, finished=True)
                if cont.kind == ContinueKind.STOP:
                    self.progress.emit(
                        ProgressEvent(kind="final_answer", payload={"text": final_answer})
                    )
                    return final_answer
                if cont.kind == ContinueKind.RETRY:
                    for fb in cont.feedback_messages:
                        messages.append(fb)
                    continue
                continue

            if response.stop_reason == StopReason.TOOL_CALLS:
                if response.content:
                    self.progress.emit(
                        ProgressEvent(
                            kind="assistant_message",
                            payload={"text": response.content},
                        )
                    )

                tool_calls = self.llm.extract_tool_calls(response)
                if not tool_calls:
                    final_answer = self.llm.extract_text(response) or ""
                    return final_answer or "No response generated."

                # Persist the assistant's tool-call message before
                # dispatching, so the tool result messages we append
                # below sit in the correct chronological order.
                messages.append(response.to_message())

                try:
                    # Per-tool-call rules. `before_toolcall` may block a call (its
                    # text becomes the result and the call is skipped); the rest
                    # dispatch, then `after_toolcall` may rewrite each real result.
                    blocked = self._rules_before(ctx, tool_calls)
                    for tc in tool_calls:
                        if tc.id in blocked:
                            self.progress.emit(
                                ProgressEvent(
                                    kind="tool_blocked",
                                    payload={
                                        "name": tc.name,
                                        "arguments": tc.arguments,
                                        "reason": blocked[tc.id],
                                    },
                                )
                            )
                    remaining = [tc for tc in tool_calls if tc.id not in blocked]

                    contents: dict[str, str] = dict(blocked)
                    if remaining:
                        results = await self._dispatch_tools(ctx, remaining)
                        for tc, tr in zip(remaining, results):
                            contents[tc.id] = self._rules_after(ctx, tc, tr)

                    # One tool_result per call, in the model's original order.
                    for tc in tool_calls:
                        messages.append(
                            LLMMessage(
                                role="tool",
                                content=contents[tc.id],
                                tool_call_id=tc.id,
                                name=tc.name,
                            )
                        )
                except Exception:
                    # If anything in the tool-call dispatch path fails
                    # (e.g. a ProgressSink implementation raises), roll
                    # back the assistant message so the conversation
                    # state remains consistent for the next turn.
                    snap = messages.snapshot()
                    if snap and snap[-1].role == "assistant":
                        messages.replace(snap[:-1])
                    raise
                continue

            if response.stop_reason == StopReason.LENGTH:
                # Output was truncated by max_tokens. Any tool_calls in
                # this response are likely to have malformed JSON args
                # (incomplete brackets/quotes), so dispatching them
                # would just produce parse errors and the model would
                # retry with the same truncated output — a silent
                # death-loop. Surface the partial text and stop.
                partial = self.llm.extract_text(response) or ""
                # max_tokens_per_call may be None (default after #177); use %s
                # so the warning still formats cleanly when the cap is set by
                # the provider rather than ouro.
                logger.warning(
                    "Agent.run: LLM response truncated at max_tokens=%s on "
                    "iteration %d. Returning partial answer (%d chars). "
                    "Raise max_tokens_per_call or shorten the prompt.",
                    self.max_tokens_per_call,
                    ctx.iteration,
                    len(partial),
                )
                final_answer = partial or f"[truncated at max_tokens={self.max_tokens_per_call}]"
                self.progress.emit(
                    ProgressEvent(kind="unfinished_answer", payload={"text": final_answer})
                )
                return final_answer

            # Unknown / unexpected stop_reason — terminate instead of
            # silently looping.
            logger.warning(
                "Agent.run: unhandled stop_reason=%r on iteration %d, terminating.",
                response.stop_reason,
                ctx.iteration,
            )
            final_answer = self.llm.extract_text(response) or final_answer
            return final_answer or "No response generated."

        logger.warning("Agent.run reached max_iterations=%d without STOP", self.max_iterations)
        return final_answer

    def _rules_before(
        self,
        ctx: LoopContext,
        tool_calls: list[ToolCall],
    ) -> dict[str, str]:
        """Run every rule's ``before_toolcall`` over each proposed call.

        Returns ``blocked``: a map from ``tool_call_id`` to the text to surface
        in place of dispatching it (messages from multiple rules that block the
        same call are joined). Calls absent from the map dispatch normally.
        """
        blocked: dict[str, list[str]] = {}
        for tc in tool_calls:
            for rule in self.rules:
                fn = getattr(rule, "before_toolcall", None)
                if fn is None:
                    continue
                msg = fn(ctx, tc)
                if msg is not None:
                    blocked.setdefault(tc.id, []).append(msg)
        return {tid: "\n".join(msgs) for tid, msgs in blocked.items()}

    def _rules_after(self, ctx: LoopContext, tool_call: ToolCall, result: ToolResult) -> str:
        """Run every rule's ``after_toolcall`` over a dispatched call's result.

        Each rule may rewrite the content (later rules see earlier rewrites) or
        return ``None`` to leave it unchanged. Returns the final result text.
        """
        content = result.content
        metadata = result.metadata
        for rule in self.rules:
            fn = getattr(rule, "after_toolcall", None)
            if fn is None:
                continue
            current = ToolResult(
                tool_call_id=tool_call.id,
                content=content,
                name=tool_call.name,
                metadata=metadata,
            )
            replacement = fn(ctx, tool_call, current)
            if replacement is not None:
                content = replacement

        # Second pass: rules that need the full metadata (e.g. is_partial_view).
        for rule in self.rules:
            fn = getattr(rule, "after_toolcall_with_metadata", None)
            if fn is None:
                continue
            current = ToolResult(
                tool_call_id=tool_call.id,
                content=content,
                name=tool_call.name,
                metadata=metadata,
            )
            replacement = fn(ctx, tool_call, current)
            if replacement is not None:
                content = replacement

        return content

    async def _dispatch_tools(
        self,
        ctx: RunStatistic,
        tool_calls: list[ToolCall],
    ) -> list[ToolResult]:
        if not tool_calls:
            return []

        results: list[ToolResult | None] = [None] * len(tool_calls)
        for batch in self._build_batches(tool_calls):
            indexed = [(i, tool_calls[i]) for i in batch]
            if len(indexed) == 1:
                i, tc = indexed[0]
                (single,) = await self._exec_sequential(ctx, [tc])
                results[i] = single
            else:
                batch_calls = [tc for _, tc in indexed]
                batch_results = await self._exec_parallel(ctx, batch_calls)
                for (i, _), res in zip(indexed, batch_results):
                    results[i] = res
        return [r for r in results if r is not None]

    def _build_batches(self, tool_calls: list[ToolCall]) -> list[list[int]]:
        """Group tool-call indices into prefix-greedy parallel batches.

        Each call's ``conflict_keys`` describes the resources it touches:
        ``set()`` joins any batch, ``None`` runs alone, non-empty joins the
        current batch only when disjoint with the batch's accumulated keys.
        Order within ``tool_calls`` is preserved across batches.
        """
        batches: list[list[int]] = []
        current: list[int] = []
        current_keys: set[str] = set()

        def flush() -> None:
            nonlocal current, current_keys
            if current:
                batches.append(current)
            current = []
            current_keys = set()

        for i, tc in enumerate(tool_calls):
            keys = self.tools.conflict_keys(tc.name, tc.arguments)
            if keys is None:
                flush()
                batches.append([i])
                continue
            if keys and keys & current_keys:
                flush()
            current.append(i)
            current_keys |= keys
        flush()
        return batches

    async def _exec_sequential(
        self, ctx: RunStatistic, tool_calls: list[ToolCall]
    ) -> list[ToolResult]:
        results: list[ToolResult] = []
        for tc in tool_calls:
            self.progress.emit(
                ProgressEvent(
                    kind="tool_call",
                    payload={"name": tc.name, "arguments": tc.arguments},
                )
            )
            async with self.progress.spinner(f"Executing {tc.name}...", title="Working"):
                output = await self.tools.execute_tool_call(tc.name, tc.arguments)
            self.progress.emit(ProgressEvent(kind="tool_result", payload={"text": output.content}))
            results.append(
                ToolResult(
                    tool_call_id=tc.id,
                    content=output.content,
                    name=tc.name,
                    metadata=output.metadata,
                )
            )
        return results

    async def _exec_parallel(
        self, ctx: RunStatistic, tool_calls: list[ToolCall]
    ) -> list[ToolResult]:
        for tc in tool_calls:
            self.progress.emit(
                ProgressEvent(
                    kind="tool_call",
                    payload={"name": tc.name, "arguments": tc.arguments},
                )
            )

        outputs: list[ToolOutput | None] = [None] * len(tool_calls)

        async def _run(i: int, tc: ToolCall) -> None:
            outputs[i] = await self.tools.execute_tool_call(tc.name, tc.arguments)

        names = ", ".join(tc.name for tc in tool_calls)
        async with self.progress.spinner(
            f"Executing {len(tool_calls)} tools in parallel ({names})...",
            title="Working",
        ), asyncio.TaskGroup() as tg:
            for i, tc in enumerate(tool_calls):
                tg.create_task(_run(i, tc))

        results: list[ToolResult] = []
        for i, tc in enumerate(tool_calls):
            out = outputs[i]
            content = out.content if out is not None else ""
            self.progress.emit(ProgressEvent(kind="tool_result", payload={"text": content}))
            results.append(
                ToolResult(
                    tool_call_id=tc.id,
                    content=content,
                    name=tc.name,
                    metadata=out.metadata if out is not None else None,
                )
            )
        return results

    async def _fanout_async(self, method: str, ctx: LoopContext, *args: Any) -> None:
        for hook in self.hooks:
            fn = getattr(hook, method, None)
            if fn is None:
                continue
            await fn(ctx, *args)

    async def _aggregate_continue(
        self,
        ctx: LoopContext,
        messages: MessageList,
        response: LLMResponse,
        *,
        finished: bool,
    ) -> ContinueDecision:
        decision = ContinueDecision.stop()
        retries: list[LLMMessage] = []
        any_called = False
        for hook in self.hooks:
            fn = getattr(hook, "on_iteration_end", None)
            if fn is None:
                continue
            any_called = True
            d = await fn(ctx, messages, response, finished)
            if d.kind == ContinueKind.STOP:
                return ContinueDecision.stop()
            if d.kind == ContinueKind.RETRY:
                retries.extend(d.feedback_messages)
                decision = ContinueDecision.retry_with_feedback()
        if not any_called:
            return ContinueDecision.stop() if finished else ContinueDecision.cont()
        if retries:
            return ContinueDecision.retry_with_feedback(*retries)
        return decision


def _log_outgoing_messages(iteration: int, messages: list[LLMMessage]) -> None:
    """Dump the outgoing message list for one LLM call.

    Gated by ``OURO_DEBUG_LLM_HISTORY`` env var; called from the loop right
    before ``llm.call_async``. Output goes through the standard logger so
    it lands in ``~/.ouro/logs/`` when ``--verbose`` is set. Each line uses
    the ``LLM_HISTORY`` prefix so it's grep-friendly.
    """
    parts = [f"LLM_HISTORY iter={iteration} count={len(messages)}"]
    for i, m in enumerate(messages):
        role = m.role
        if role == "assistant" and getattr(m, "tool_calls", None):
            ids = []
            for tc in m.tool_calls or []:
                tid = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", "?")
                ids.append(tid or "?")
            content = m.content if isinstance(m.content, str) else ""
            preview = (content or "")[:60].replace("\n", " ")
            parts.append(f"LLM_HISTORY   [{i:03d}] assistant tool_calls={ids} content={preview!r}")
        elif role == "tool":
            tid = getattr(m, "tool_call_id", "?") or "?"
            content_len = len(m.content or "") if isinstance(m.content, str) else 0
            parts.append(f"LLM_HISTORY   [{i:03d}] tool tool_call_id={tid} len={content_len}")
        else:
            content = m.content if isinstance(m.content, str) else "[non-str]"
            preview = (content or "")[:80].replace("\n", " ")
            parts.append(f"LLM_HISTORY   [{i:03d}] {role} preview={preview!r}")
    logger.info("\n".join(parts))
