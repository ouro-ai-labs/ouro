"""Multi-turn message-list invariants for ``core.loop.Agent``.

Pins down that the loop never silently drops messages: across multiple
sequential ``Agent.run(...)`` invocations sharing one ``MessageListContext``,
every assistant tool_call has its matching tool result in the detached
list, history grows monotonically, and the LLM sees the full prior
context on every iteration.

A "messages lost" regression — e.g. a hook clobbering ``context.detached``
or an accidental slice in the LLM call path — would surface here as
either an orphan tool_call_id or a shrinking history between iterations.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from ouro.capabilities.tools.base import BaseTool
from ouro.capabilities.tools.executor import ToolExecutor
from ouro.core.llm import LLMMessage, LLMResponse, StopReason, ToolCall
from ouro.core.loop import Agent, MessageListContext, NullProgressSink

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class ReadFileStub(BaseTool):
    readonly = True

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "stub"

    @property
    def parameters(self):
        return {}

    async def execute(self, **kwargs) -> str:
        return f"[lines for offset={kwargs.get('offset')} limit={kwargs.get('limit')}]"


@dataclass
class ScriptedLLM:
    """Replays a fixed sequence of ``LLMResponse`` objects, recording every
    messages-list it was called with so tests can introspect what the LLM
    saw at each iteration."""

    responses: list[LLMResponse]
    seen_messages: list[list[LLMMessage]] = field(default_factory=list)
    _idx: int = 0

    async def call_async(self, messages, tools=None, max_tokens=None, **kwargs):
        self.seen_messages.append(list(messages))
        resp = self.responses[self._idx]
        self._idx += 1
        return resp

    def extract_tool_calls(self, response: LLMResponse) -> list[ToolCall]:
        if not response.tool_calls:
            return []
        out = []
        for tc in response.tool_calls:
            fn = tc["function"]
            args_raw = fn["arguments"]
            args = json.loads(args_raw) if args_raw else {}
            out.append(ToolCall(id=tc["id"], name=fn["name"], arguments=args))
        return out

    def extract_text(self, response: LLMResponse) -> str:
        return response.content or ""


def _tool_call_block(call_id: str, name: str, args: dict) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def _tool_call_response(call_id: str, args: dict, name: str = "read_file") -> LLMResponse:
    return LLMResponse(
        content=None,
        tool_calls=[_tool_call_block(call_id, name, args)],
        stop_reason=StopReason.TOOL_CALLS,
    )


def _final_response(text: str) -> LLMResponse:
    return LLMResponse(content=text, tool_calls=None, stop_reason=StopReason.STOP)


def _all_tool_call_ids(messages: list[LLMMessage]) -> list[str]:
    ids = []
    for m in messages:
        if m.role == "assistant" and m.tool_calls:
            for tc in m.tool_calls:
                tid = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                if tid:
                    ids.append(tid)
    return ids


def _all_tool_result_ids(messages: list[LLMMessage]) -> list[str]:
    return [m.tool_call_id for m in messages if m.role == "tool" and m.tool_call_id]


def _make_agent(llm: ScriptedLLM) -> Agent:
    return Agent(
        llm=llm,
        tools=ToolExecutor([ReadFileStub()]),
        hooks=(),
        progress=NullProgressSink(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_three_user_turns_preserve_every_tool_call_id():
    """Mirrors the 2026-05-08 session shape: 3 sequential user turns, each
    issuing one tool_call. The detached list must end with all three pairs
    intact and the LLM must see all earlier pairs on every later call."""
    llm = ScriptedLLM(
        responses=[
            _tool_call_response("tc1", {"offset": 0, "limit": 30}),
            _final_response("turn 1 done"),
            _tool_call_response("tc2", {"offset": 100, "limit": 30}),
            _final_response("turn 2 done"),
            _tool_call_response("tc3", {"offset": 200, "limit": 30}),
            _final_response("turn 3 done"),
        ]
    )
    agent = _make_agent(llm)
    ctx = MessageListContext()

    for i, prompt in enumerate(["t1", "t2", "t3"], start=1):
        ctx.detached.append(LLMMessage(role="user", content=prompt))
        result = await agent.run(prompt, context=ctx)
        assert result == f"turn {i} done"

    msgs = ctx.detached.snapshot()
    assert _all_tool_call_ids(msgs) == ["tc1", "tc2", "tc3"]
    assert _all_tool_result_ids(msgs) == ["tc1", "tc2", "tc3"]
    # 3 user + 3 assistant{tool_calls} + 3 tool result + 3 assistant{final}
    assert len(msgs) == 12

    # Last LLM call (final assistant of turn 3) must have seen every prior
    # tool_call_id and result. This is the property a "messages lost" bug
    # would violate.
    last_seen = llm.seen_messages[-1]
    assert _all_tool_call_ids(last_seen) == ["tc1", "tc2", "tc3"]
    assert _all_tool_result_ids(last_seen) == ["tc1", "tc2", "tc3"]


async def test_history_grows_monotonically_across_iterations():
    """No LLM call ever sees fewer messages than the previous one within a
    single ``Agent.run`` or across consecutive runs sharing a context."""
    llm = ScriptedLLM(
        responses=[
            _tool_call_response("a", {"offset": 0, "limit": 10}),
            _tool_call_response("b", {"offset": 50, "limit": 10}),
            _final_response("first done"),
            _tool_call_response("c", {"offset": 100, "limit": 10}),
            _final_response("second done"),
        ]
    )
    agent = _make_agent(llm)
    ctx = MessageListContext()

    ctx.detached.append(LLMMessage(role="user", content="u1"))
    await agent.run("u1", context=ctx)
    ctx.detached.append(LLMMessage(role="user", content="u2"))
    await agent.run("u2", context=ctx)

    sizes = [len(m) for m in llm.seen_messages]
    assert sizes == sorted(sizes), f"history shrunk: {sizes}"
    # And the very last call must see every tool_call_id ever issued.
    last_seen = llm.seen_messages[-1]
    assert set(_all_tool_call_ids(last_seen)) == {"a", "b", "c"}
    assert set(_all_tool_result_ids(last_seen)) == {"a", "b", "c"}


async def test_iteration_n_sees_iterations_1_to_n_minus_1():
    """Within a single turn with multiple sequential tool calls, iteration N
    must see iterations 1..N-1 outputs. Catches the regression where a
    pre-call hook would replace ``detached`` with a stale snapshot."""
    llm = ScriptedLLM(
        responses=[
            _tool_call_response("a", {"offset": 0, "limit": 10}),
            _tool_call_response("b", {"offset": 50, "limit": 10}),
            _tool_call_response("c", {"offset": 100, "limit": 10}),
            _final_response("done"),
        ]
    )
    agent = _make_agent(llm)
    ctx = MessageListContext()
    ctx.detached.append(LLMMessage(role="user", content="task"))
    await agent.run("task", context=ctx)

    # Iteration 1: only the user message, no tool calls yet.
    assert _all_tool_call_ids(llm.seen_messages[0]) == []
    # Iteration 2: must see 'a' and its result.
    assert _all_tool_call_ids(llm.seen_messages[1]) == ["a"]
    assert _all_tool_result_ids(llm.seen_messages[1]) == ["a"]
    # Iteration 3: a + b.
    assert _all_tool_call_ids(llm.seen_messages[2]) == ["a", "b"]
    assert _all_tool_result_ids(llm.seen_messages[2]) == ["a", "b"]
    # Iteration 4 (final reply): a + b + c.
    assert _all_tool_call_ids(llm.seen_messages[3]) == ["a", "b", "c"]
    assert _all_tool_result_ids(llm.seen_messages[3]) == ["a", "b", "c"]


async def test_no_orphan_tool_call_or_result_at_run_end():
    """Every assistant.tool_calls[i].id has exactly one matching role=tool
    message in detached after the run ends — no orphans either way."""
    llm = ScriptedLLM(
        responses=[
            _tool_call_response("x1", {"offset": 0, "limit": 5}),
            _tool_call_response("x2", {"offset": 10, "limit": 5}),
            _final_response("ok"),
        ]
    )
    agent = _make_agent(llm)
    ctx = MessageListContext()
    ctx.detached.append(LLMMessage(role="user", content="t"))
    await agent.run("t", context=ctx)

    msgs = ctx.detached.snapshot()
    call_ids = _all_tool_call_ids(msgs)
    result_ids = _all_tool_result_ids(msgs)
    assert call_ids == result_ids, f"call/result mismatch: calls={call_ids} results={result_ids}"
    # And no duplicates — same id never appears twice on either side.
    assert len(set(call_ids)) == len(call_ids)
    assert len(set(result_ids)) == len(result_ids)
