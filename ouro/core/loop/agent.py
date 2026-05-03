"""Core agent loop.

A class-based ReAct loop with optional hooks. The loop knows nothing about
memory, BaseTool, verification, or terminal UI — those plug in via
`Hook` and `ToolRegistry` from `protocols.py`.
"""

from __future__ import annotations

import asyncio
from typing import Any, Sequence

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
        max_tokens_per_call: int = 4096,
        progress: ProgressSink | None = None,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.hooks: list[Hook] = list(hooks)
        self.max_iterations = max_iterations
        self.max_tokens_per_call = max_tokens_per_call
        self.progress: ProgressSink = progress or NullProgressSink()
        self._reasoning_effort: str | None = None

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
        ctx = RunStatistic(task=task, progress=self.progress)
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
                response = await self.llm.call_async(
                    messages=outgoing,
                    tools=tool_schemas,
                    max_tokens=self.max_tokens_per_call,
                    **(
                        {"reasoning_effort": self._reasoning_effort}
                        if self._reasoning_effort is not None
                        else {}
                    ),
                )
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
                logger.warning(
                    "Agent.run: LLM response truncated at max_tokens=%d on "
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

    async def _dispatch_tools(
        self,
        ctx: RunStatistic,
        tool_calls: list[ToolCall],
    ) -> list[ToolResult]:
        all_readonly = len(tool_calls) > 1 and all(
            self.tools.is_tool_readonly(tc.name) for tc in tool_calls
        )
        if all_readonly:
            return await self._exec_parallel(ctx, tool_calls)
        return await self._exec_sequential(ctx, tool_calls)

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
