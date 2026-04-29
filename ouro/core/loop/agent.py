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

from .message_list import MessageList
from .protocols import (
    CompactionDecision,
    ContinueDecision,
    ContinueKind,
    Hook,
    LoopContext,
    NullProgressSink,
    ProgressSink,
    ToolRegistry,
)

logger = get_logger(__name__)


class _RunContext:
    """Mutable run state. Exposed to hooks via the LoopContext Protocol view."""

    def __init__(self, task: str, progress: ProgressSink) -> None:
        self.task = task
        self.iteration = 0
        self.usage_total: dict[str, int] = {}
        self.stop_reason_last: str | None = None
        self.progress = progress

    def add_usage(self, usage: dict[str, int] | None) -> None:
        if not usage:
            return
        for k, v in usage.items():
            if isinstance(v, int):
                self.usage_total[k] = self.usage_total.get(k, 0) + v


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

    async def run(self, task: str) -> str:
        ctx = _RunContext(task=task, progress=self.progress)
        messages = MessageList()
        await self._fanout_async("on_run_start", ctx, messages)

        tool_schemas = self.tools.get_tool_schemas()
        final_answer: str = ""
        try:
            for ctx.iteration in range(1, self.max_iterations + 1):
                decision = await self._first_non_none_async("on_compact_check", ctx, messages)
                if decision is not None:
                    await self._do_compaction(ctx, messages, tool_schemas, decision)
                    continue

                outgoing = await self._build_outgoing(ctx, messages, tool_schemas)

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
                response = await self._chain_response("after_call", ctx, messages, response)
                ctx.stop_reason_last = response.stop_reason
                ctx.add_usage(getattr(response, "usage", None))

                extract_thinking = getattr(self.llm, "extract_thinking", None)
                if extract_thinking is not None:
                    thinking = extract_thinking(response)
                    if thinking:
                        self.progress.thinking(thinking)

                if response.stop_reason == StopReason.STOP:
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

                    tool_results = await self._dispatch_tools(ctx, tool_calls)
                    await self._fanout_async(
                        "on_tool_results", ctx, messages, tool_calls, tool_results
                    )
                    continue

            logger.warning("Agent.run reached max_iterations=%d without STOP", self.max_iterations)
            return final_answer
        finally:
            await self._fanout_async("on_run_end", ctx, messages, final_answer)

    async def _build_outgoing(
        self,
        ctx: LoopContext,
        messages: MessageList,
        tool_schemas: list[dict[str, Any]],
    ) -> list[LLMMessage]:
        outgoing = messages.snapshot()
        any_called = False
        for hook in self.hooks:
            fn = getattr(hook, "before_call", None)
            if fn is None:
                continue
            any_called = True
            outgoing = await fn(ctx, messages, tool_schemas)
        return outgoing if any_called else messages.snapshot()

    async def _do_compaction(
        self,
        ctx: _RunContext,
        messages: MessageList,
        tool_schemas: list[dict[str, Any]],
        decision: CompactionDecision,
    ) -> None:
        fork = MessageList(messages.snapshot())
        fork.append(decision.compaction_prompt)
        outgoing = await self._build_outgoing(ctx, fork, tool_schemas)
        async with self.progress.spinner("Compressing memory...", title="Working"):
            response = await self.llm.call_async(
                messages=outgoing,
                tools=tool_schemas,
                max_tokens=self.max_tokens_per_call,
            )
        summary = self.llm.extract_text(response)
        usage = getattr(response, "usage", None) or {}
        result = decision.on_summary(summary, usage, messages)
        if asyncio.iscoroutine(result):
            await result
        ctx.add_usage(usage)

    async def _dispatch_tools(
        self,
        ctx: _RunContext,
        tool_calls: list[ToolCall],
    ) -> list[ToolResult]:
        rewritten: list[ToolCall] = [
            await self._chain_tool_call("before_tool", ctx, tc) for tc in tool_calls
        ]
        all_readonly = len(rewritten) > 1 and all(
            self.tools.is_tool_readonly(tc.name) for tc in rewritten
        )
        if all_readonly:
            return await self._exec_parallel(ctx, rewritten)
        return await self._exec_sequential(ctx, rewritten)

    async def _exec_sequential(
        self, ctx: _RunContext, tool_calls: list[ToolCall]
    ) -> list[ToolResult]:
        results: list[ToolResult] = []
        for tc in tool_calls:
            self.progress.tool_call(tc.name, tc.arguments)
            async with self.progress.spinner(f"Executing {tc.name}...", title="Working"):
                output = await self.tools.execute_tool_call(tc.name, tc.arguments)
            self.progress.tool_result(output)
            tr = ToolResult(tool_call_id=tc.id, content=output, name=tc.name)
            tr = await self._chain_tool_result("after_tool", ctx, tc, tr)
            results.append(tr)
        return results

    async def _exec_parallel(
        self, ctx: _RunContext, tool_calls: list[ToolCall]
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
            tr = ToolResult(tool_call_id=tc.id, content=output, name=tc.name)
            tr = await self._chain_tool_result("after_tool", ctx, tc, tr)
            results.append(tr)
        return results

    async def _chain_response(
        self,
        method: str,
        ctx: LoopContext,
        messages: MessageList,
        response: LLMResponse,
    ) -> LLMResponse:
        out = response
        for hook in self.hooks:
            fn = getattr(hook, method, None)
            if fn is None:
                continue
            out = await fn(ctx, messages, out)
        return out

    async def _chain_tool_call(
        self,
        method: str,
        ctx: LoopContext,
        tool_call: ToolCall,
    ) -> ToolCall:
        out = tool_call
        for hook in self.hooks:
            fn = getattr(hook, method, None)
            if fn is None:
                continue
            out = await fn(ctx, out)
        return out

    async def _chain_tool_result(
        self,
        method: str,
        ctx: LoopContext,
        tool_call: ToolCall,
        result: ToolResult,
    ) -> ToolResult:
        out = result
        for hook in self.hooks:
            fn = getattr(hook, method, None)
            if fn is None:
                continue
            out = await fn(ctx, tool_call, out)
        return out

    async def _first_non_none_async(self, method: str, ctx: LoopContext, *args: Any) -> Any:
        for hook in self.hooks:
            fn = getattr(hook, method, None)
            if fn is None:
                continue
            result = await fn(ctx, *args)
            if result is not None:
                return result
        return None

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
