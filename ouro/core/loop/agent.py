"""Core agent loop.

A class-based ReAct loop with optional hooks. The loop knows nothing about
memory, BaseTool, verification, or terminal UI — those plug in via
`Hook` and `ToolRegistry` from `protocols.py`.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Callable, Literal, NamedTuple, Sequence

from ouro.core.llm import LLMMessage, LLMResponse, StopReason, ToolCall, ToolResult
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
    ProgressSink,
    ToolRegistry,
)

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
        repeat_tool_call_max: int = 5,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.hooks: list[Hook] = list(hooks)
        self.max_iterations = max_iterations
        self.max_tokens_per_call = max_tokens_per_call
        self.progress: ProgressSink = progress or NullProgressSink()
        self._reasoning_effort: str | None = None
        self._usage_callback = usage_callback
        # Soft intercept at `repeat_tool_call_threshold` consecutive identical
        # tool-call iterations; hard terminate at `repeat_tool_call_max`.
        # Setting threshold <= 0 disables the circuit breaker entirely.
        self.repeat_tool_call_threshold = repeat_tool_call_threshold
        self.repeat_tool_call_max = repeat_tool_call_max

    def set_reasoning_effort(self, value: str | None) -> None:
        self._reasoning_effort = normalize_reasoning_effort(value)

    def add_hook(self, hook: Hook) -> None:
        self.hooks.append(hook)

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
        # Per-run state for the repeated-tool-call circuit breaker. Tracks the
        # last iteration's tool-call signature and how many iterations in a
        # row have emitted the same signature. See `_tool_call_iter_signature`.
        last_iter_sig: tuple[tuple[str, str], ...] | None = None
        repeat_count: int = 0
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
                    self.progress.thinking(thinking)

            if response.stop_reason == StopReason.STOP:
                # Persist the assistant's final reply into the loop's
                # canonical history so subsequent turns / verification
                # retries see it.  Memory persistence (disk) is a hook
                # concern; the loop only owns in-memory state.
                messages.append(response.to_message())
                final_answer = self.llm.extract_text(response)
                cont = await self._aggregate_continue(ctx, messages, response, finished=True)
                if cont.kind == ContinueKind.STOP:
                    self.progress.final_answer(final_answer)
                    return final_answer
                if cont.kind == ContinueKind.RETRY:
                    for fb in cont.feedback_messages:
                        messages.append(fb)
                    continue
                continue

            if response.stop_reason == StopReason.TOOL_CALLS:
                if response.content:
                    self.progress.assistant_message(response.content)

                tool_calls = self.llm.extract_tool_calls(response)
                if not tool_calls:
                    final_answer = self.llm.extract_text(response) or ""
                    return final_answer or "No response generated."

                # Persist the assistant's tool-call message before
                # dispatching, so the tool result messages we append
                # below sit in the correct chronological order.
                messages.append(response.to_message())

                guard = self._apply_repeated_tool_call_guard(
                    tool_calls=tool_calls,
                    messages=messages,
                    last_iter_sig=last_iter_sig,
                    repeat_count=repeat_count,
                    iteration=ctx.iteration,
                )
                last_iter_sig = guard.last_iter_sig
                repeat_count = guard.repeat_count
                if guard.action == "halted":
                    final_answer = guard.final_answer or ""
                    self.progress.unfinished_answer(final_answer)
                    return final_answer
                if guard.action == "intercepted":
                    continue

                tool_results = await self._dispatch_tools(ctx, tool_calls)
                for tc, tr in zip(tool_calls, tool_results):
                    messages.append(
                        LLMMessage(
                            role="tool",
                            content=tr.content,
                            tool_call_id=tc.id,
                            name=tc.name,
                        )
                    )
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
                self.progress.unfinished_answer(final_answer)
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

    def _apply_repeated_tool_call_guard(
        self,
        *,
        tool_calls: list[ToolCall],
        messages: MessageList,
        last_iter_sig: tuple[tuple[str, str], ...] | None,
        repeat_count: int,
        iteration: int,
    ) -> _RepeatGuardOutcome:
        """Track consecutive identical tool_call iterations and intercept loops.

        Compaction summaries can re-inject pathological tool-call patterns as
        if they were task state, so when the model emits the same
        ``(name, arguments)`` iteration N times in a row we either synthesize
        a "stop repeating" tool_result (soft intercept) or terminate the run
        (hard stop).  This method updates ``messages`` in place with the
        synthesized tool_results when intercepting; the caller routes on
        ``outcome.action``.
        """
        iter_sig = _tool_call_iter_signature(tool_calls)
        if last_iter_sig is not None and iter_sig == last_iter_sig:
            new_repeat_count = repeat_count + 1
        else:
            new_repeat_count = 1

        if self.repeat_tool_call_threshold <= 0:
            return _RepeatGuardOutcome("dispatch", iter_sig, new_repeat_count, None)

        if new_repeat_count >= self.repeat_tool_call_max:
            for tc in tool_calls:
                messages.append(
                    LLMMessage(
                        role="tool",
                        content=(
                            f"[ouro] Same tool_call(s) repeated {new_repeat_count} "
                            "times consecutively with no progress. Terminating "
                            "to prevent runaway loop."
                        ),
                        tool_call_id=tc.id,
                        name=tc.name,
                    )
                )
            logger.warning(
                "Agent.run: hard-stopping after %d consecutive identical "
                "tool_call iterations on iteration %d (names=%s)",
                new_repeat_count,
                iteration,
                [tc.name for tc in tool_calls],
            )
            final_answer = (
                "[ouro] Halted: the model repeated the same tool call "
                f"{new_repeat_count} times without progress "
                f"({[tc.name for tc in tool_calls]}). Please rephrase your "
                "request or restart the session."
            )
            return _RepeatGuardOutcome("halted", iter_sig, new_repeat_count, final_answer)

        if new_repeat_count >= self.repeat_tool_call_threshold:
            feedback = (
                f"[ouro] This exact tool_call has now been issued {new_repeat_count} "
                "times consecutively. The result has not changed. Stop repeating: "
                "either choose a different action, ask the user for clarification, "
                "or finish the task."
            )
            for tc in tool_calls:
                messages.append(
                    LLMMessage(
                        role="tool",
                        content=feedback,
                        tool_call_id=tc.id,
                        name=tc.name,
                    )
                )
            logger.warning(
                "Agent.run: intercepted %d-times-repeated tool_call(s) on "
                "iteration %d (names=%s)",
                new_repeat_count,
                iteration,
                [tc.name for tc in tool_calls],
            )
            return _RepeatGuardOutcome("intercepted", iter_sig, new_repeat_count, None)

        return _RepeatGuardOutcome("dispatch", iter_sig, new_repeat_count, None)

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
            self.progress.tool_call(tc.name, tc.arguments)
            async with self.progress.spinner(f"Executing {tc.name}...", title="Working"):
                output = await self.tools.execute_tool_call(tc.name, tc.arguments)
            self.progress.tool_result(output)
            results.append(ToolResult(tool_call_id=tc.id, content=output, name=tc.name))
        return results

    async def _exec_parallel(
        self, ctx: RunStatistic, tool_calls: list[ToolCall]
    ) -> list[ToolResult]:
        for tc in tool_calls:
            self.progress.tool_call(tc.name, tc.arguments)

        outputs: list[str | None] = [None] * len(tool_calls)

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
            output = outputs[i] or ""
            self.progress.tool_result(output)
            results.append(ToolResult(tool_call_id=tc.id, content=output, name=tc.name))
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


class _RepeatGuardOutcome(NamedTuple):
    """Result of one iteration's repeated-tool-call check.

    ``action`` routes the caller:
    - ``"dispatch"``: not a repeat (or breaker disabled); run the tools normally.
    - ``"intercepted"``: synthesized tool_results already appended; ``continue``.
    - ``"halted"``: synthesized tool_results already appended; return ``final_answer``.
    """

    action: Literal["dispatch", "intercepted", "halted"]
    last_iter_sig: tuple[tuple[str, str], ...]
    repeat_count: int
    final_answer: str | None


def _tool_call_iter_signature(
    tool_calls: list[ToolCall],
) -> tuple[tuple[str, str], ...]:
    """Build a deterministic fingerprint for one iteration's tool_calls.

    Used by the repeated-tool-call circuit breaker to detect when the model
    is emitting the exact same (name, arguments) batch iteration after
    iteration. Arguments are serialized with ``sort_keys=True`` so key order
    is normalized; non-JSON-safe values fall back to ``str(...)`` so the
    helper never raises on exotic argument types.
    """
    sigs: list[tuple[str, str]] = []
    for tc in tool_calls:
        try:
            args_repr = json.dumps(tc.arguments, sort_keys=True, default=str)
        except (TypeError, ValueError):
            args_repr = repr(tc.arguments)
        sigs.append((tc.name, args_repr))
    return tuple(sigs)


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
