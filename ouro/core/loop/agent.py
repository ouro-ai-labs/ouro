"""Core agent loop.

A class-based ReAct loop with optional hooks. The loop knows nothing about
memory, BaseTool, verification, or terminal UI — those plug in via
`Hook` and `ToolRegistry` from `protocols.py`.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Sequence

from ouro.core.llm import (
    LLMMessage,
    LLMResponse,
    StopReason,
    ToolCall,
    ToolResult,
)
from ouro.core.llm.reasoning import normalize_reasoning_effort
from ouro.core.log import get_logger

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
        self.usage_total: Dict[str, int] = {}
        self.stop_reason_last: Optional[str] = None
        self.progress = progress

    def add_usage(self, usage: Optional[Dict[str, int]]) -> None:
        if not usage:
            return
        for k, v in usage.items():
            if isinstance(v, int):
                self.usage_total[k] = self.usage_total.get(k, 0) + v


class Agent:
    """Hooks-based core loop.

    No knowledge of MemoryManager, BaseTool, Verifier, or Config. Memory,
    compaction, and verification plug in as hooks; the tool layer
    plugs in via `ToolRegistry`.
    """

    def __init__(
        self,
        llm: Any,  # LiteLLMAdapter (avoid hard dep for testability)
        tools: ToolRegistry,
        hooks: Sequence[Hook] = (),
        max_iterations: int = 1000,
        max_tokens_per_call: int = 4096,
        progress: Optional[ProgressSink] = None,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.hooks: List[Hook] = list(hooks)
        self.max_iterations = max_iterations
        self.max_tokens_per_call = max_tokens_per_call
        self.progress: ProgressSink = progress or NullProgressSink()
        self._reasoning_effort: Optional[str] = None

    # ---- caller-facing knobs -------------------------------------------------

    def set_reasoning_effort(self, value: Optional[str]) -> None:
        self._reasoning_effort = normalize_reasoning_effort(value)

    def add_hook(self, hook: Hook) -> None:
        self.hooks.append(hook)

    # ---- main entry ----------------------------------------------------------

    async def run(
        self,
        task: str,
        *,
        initial_messages: Optional[List[LLMMessage]] = None,
    ) -> str:
        ctx = _RunContext(task=task, progress=self.progress)
        messages: List[LLMMessage] = list(initial_messages or [])

        messages = await self._chain_async(
            "on_run_start", ctx, messages, default=messages
        )

        tool_schemas = self.tools.get_tool_schemas()

        final_answer: str = ""
        try:
            for ctx.iteration in range(1, self.max_iterations + 1):
                # 1) Compaction fork (cache-safe). Hook decides; loop calls LLM.
                decision = await self._first_non_none_async(
                    "on_compact_check", ctx, messages
                )
                if decision is not None:
                    await self._do_compaction(ctx, messages, tool_schemas, decision)
                    continue

                # 2) Build outgoing messages via before_call chain.
                outgoing = await self._chain_async(
                    "before_call", ctx, messages, tool_schemas, default=messages
                )

                # 3) LLM call.
                async with self.progress.spinner(
                    "Analyzing request..." if ctx.iteration == 1
                    else "Processing results..."
                ):
                    response = await self.llm.call_async(
                        messages=outgoing,
                        tools=tool_schemas,
                        max_tokens=self.max_tokens_per_call,
                        **({"reasoning_effort": self._reasoning_effort}
                           if self._reasoning_effort is not None else {}),
                    )
                response = await self._chain_async(
                    "after_call", ctx, response, default=response
                )
                ctx.stop_reason_last = response.stop_reason
                ctx.add_usage(getattr(response, "usage", None))

                # Append assistant message to local list (memoryless mode needs it;
                # memory hook keeps its own copy via after_call → memory.add_message).
                messages.append(response.to_message())

                # Surface thinking (provider-specific helper) via progress sink.
                extract_thinking = getattr(self.llm, "extract_thinking", None)
                if extract_thinking is not None:
                    thinking = extract_thinking(response)
                    if thinking:
                        self.progress.thinking(thinking)

                # 4) STOP path.
                if response.stop_reason == StopReason.STOP:
                    final_answer = self.llm.extract_text(response)
                    cont = await self._aggregate_continue(ctx, response, finished=True)
                    if cont.kind == ContinueKind.STOP:
                        self.progress.final_answer(final_answer)
                        return final_answer
                    if cont.kind == ContinueKind.RETRY:
                        for fb in cont.feedback_messages:
                            messages.append(fb)
                        continue
                    # CONTINUE: fall through to next iteration with current messages.
                    continue

                # 5) TOOL_CALLS path.
                if response.stop_reason == StopReason.TOOL_CALLS:
                    if response.content:
                        self.progress.assistant_message(response.content)

                    tool_calls = self.llm.extract_tool_calls(response)
                    if not tool_calls:
                        # No tool calls present despite stop_reason — treat as final.
                        final_answer = self.llm.extract_text(response) or ""
                        return final_answer or "No response generated."

                    tool_results = await self._dispatch_tools(ctx, tool_calls)

                    # Format & append tool result messages.
                    formatted = self.llm.format_tool_results(tool_results)
                    if isinstance(formatted, list):
                        messages.extend(formatted)
                    else:
                        messages.append(formatted)

            # Hit max_iterations.
            logger.warning(
                "Agent.run reached max_iterations=%d without STOP", self.max_iterations
            )
            return final_answer
        finally:
            await self._fanout_async("on_run_end", ctx, final_answer)

    # ---- compaction fork -----------------------------------------------------

    async def _do_compaction(
        self,
        ctx: _RunContext,
        messages: List[LLMMessage],
        tool_schemas: List[Dict[str, Any]],
        decision: CompactionDecision,
    ) -> None:
        fork = list(messages) + [decision.compaction_prompt]
        # Run before_call so memory hooks can substitute compressed prefix etc.
        outgoing = await self._chain_async(
            "before_call", ctx, fork, tool_schemas, default=fork
        )
        async with self.progress.spinner("Compressing memory...", title="Working"):
            response = await self.llm.call_async(
                messages=outgoing,
                tools=tool_schemas,
                max_tokens=self.max_tokens_per_call,
            )
        summary = self.llm.extract_text(response)
        usage = getattr(response, "usage", None) or {}
        result = decision.on_summary(summary, usage)
        if asyncio.iscoroutine(result):
            await result
        ctx.add_usage(usage)

    # ---- tool dispatch -------------------------------------------------------

    async def _dispatch_tools(
        self,
        ctx: _RunContext,
        tool_calls: List[ToolCall],
    ) -> List[ToolResult]:
        # Hook chain rewrites each call before execution.
        rewritten: List[ToolCall] = []
        for tc in tool_calls:
            rewritten.append(
                await self._chain_async("before_tool", ctx, tc, default=tc)
            )

        all_readonly = len(rewritten) > 1 and all(
            self.tools.is_tool_readonly(tc.name) for tc in rewritten
        )
        if all_readonly:
            return await self._exec_parallel(ctx, rewritten)
        return await self._exec_sequential(ctx, rewritten)

    async def _exec_sequential(
        self, ctx: _RunContext, tool_calls: List[ToolCall]
    ) -> List[ToolResult]:
        results: List[ToolResult] = []
        for tc in tool_calls:
            self.progress.tool_call(tc.name, tc.arguments)
            async with self.progress.spinner(
                f"Executing {tc.name}...", title="Working"
            ):
                output = await self.tools.execute_tool_call(tc.name, tc.arguments)
            self.progress.tool_result(output)
            tr = ToolResult(tool_call_id=tc.id, content=output, name=tc.name)
            tr = await self._chain_async("after_tool", ctx, tc, tr, default=tr)
            results.append(tr)
        return results

    async def _exec_parallel(
        self, ctx: _RunContext, tool_calls: List[ToolCall]
    ) -> List[ToolResult]:
        for tc in tool_calls:
            self.progress.tool_call(tc.name, tc.arguments)

        outputs: List[Optional[str]] = [None] * len(tool_calls)

        async def _run(i: int, tc: ToolCall) -> None:
            outputs[i] = await self.tools.execute_tool_call(tc.name, tc.arguments)

        names = ", ".join(tc.name for tc in tool_calls)
        async with self.progress.spinner(
            f"Executing {len(tool_calls)} tools in parallel ({names})...",
            title="Working",
        ):
            async with asyncio.TaskGroup() as tg:
                for i, tc in enumerate(tool_calls):
                    tg.create_task(_run(i, tc))

        results: List[ToolResult] = []
        for i, tc in enumerate(tool_calls):
            output = outputs[i] or ""
            self.progress.tool_result(output)
            tr = ToolResult(tool_call_id=tc.id, content=output, name=tc.name)
            tr = await self._chain_async("after_tool", ctx, tc, tr, default=tr)
            results.append(tr)
        return results

    # ---- hook plumbing -------------------------------------------------------

    async def _chain_async(
        self,
        method: str,
        ctx: LoopContext,
        value: Any,
        *extra: Any,
        default: Any = None,
    ) -> Any:
        """Call hooks[i].method(ctx, value, *extra) in order, threading the return.

        Hooks that don't define `method` are skipped. If no hooks define it,
        returns `default` (defaults to `value`).
        """
        out = value
        any_called = False
        for hook in self.hooks:
            fn = getattr(hook, method, None)
            if fn is None:
                continue
            any_called = True
            out = await fn(ctx, out, *extra)
        if not any_called:
            return default if default is not None else value
        return out

    async def _first_non_none_async(
        self, method: str, ctx: LoopContext, *args: Any
    ) -> Any:
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
        response: LLMResponse,
        *,
        finished: bool,
    ) -> ContinueDecision:
        """STOP > RETRY > CONTINUE; multiple RETRYs concatenate feedback."""
        decision = ContinueDecision.stop()  # default: terminate when finished
        retries: List[LLMMessage] = []
        any_called = False
        for hook in self.hooks:
            fn = getattr(hook, "on_iteration_end", None)
            if fn is None:
                continue
            any_called = True
            d = await fn(ctx, response, finished)
            if d.kind == ContinueKind.STOP:
                return ContinueDecision.stop()
            if d.kind == ContinueKind.RETRY:
                retries.extend(d.feedback_messages)
                decision = ContinueDecision.retry_with_feedback()  # placeholder
        if not any_called:
            return ContinueDecision.stop() if finished else ContinueDecision.cont()
        if retries:
            return ContinueDecision.retry_with_feedback(*retries)
        return decision
