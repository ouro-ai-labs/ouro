"""Tests for the steering mechanism (RFC 016).

Covers:
- SteeringQueues: enqueue, drain (``all`` mode), overflow cap, run-state flag.
- ``_drain_steering_into_memory``: inject as role=user messages.
- ``_execute_tools_sequential`` skip semantics: remaining tools get
  ``[Skipped due to user steering]`` with matching tool_call_id; no UI
  tool-call or tool-result is printed for skipped entries.
- ``LoopAgent.run`` flips ``steering.is_running`` via try/finally, including
  on exceptions.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.steering import DEFAULT_QUEUE_CAP, SteeringQueues
from llm import LLMMessage, ToolCall, ToolResult

# --------------------------------------------------------------------------- #
# SteeringQueues — pure unit tests
# --------------------------------------------------------------------------- #


def test_steering_enqueue_and_drain_preserves_order():
    q = SteeringQueues()
    q.steer("first")
    q.steer("second")
    q.steer("third")
    assert q.pending_steering() == 3
    assert q.drain_steering() == ["first", "second", "third"]
    assert q.pending_steering() == 0


def test_follow_up_enqueue_and_drain_preserves_order():
    q = SteeringQueues()
    q.follow_up("a")
    q.follow_up("b")
    assert q.drain_follow_up() == ["a", "b"]
    assert q.pending_follow_up() == 0


def test_drain_steering_empty_returns_empty_list():
    q = SteeringQueues()
    assert q.drain_steering() == []
    assert q.drain_follow_up() == []


def test_whitespace_only_messages_are_ignored():
    q = SteeringQueues()
    q.steer("   ")
    q.steer("\n\t")
    q.steer("")
    q.follow_up("   ")
    assert q.pending_counts() == (0, 0)


def test_steering_trims_whitespace_around_text():
    q = SteeringQueues()
    q.steer("  hello  ")
    assert q.drain_steering() == ["hello"]


def test_steering_and_follow_up_are_independent():
    q = SteeringQueues()
    q.steer("s1")
    q.follow_up("f1")
    assert q.pending_counts() == (1, 1)
    assert q.drain_steering() == ["s1"]
    # follow-up still pending after draining steering
    assert q.pending_follow_up() == 1
    assert q.drain_follow_up() == ["f1"]


def test_queue_overflow_drops_oldest_with_warning(caplog):
    q = SteeringQueues(cap=3)
    with caplog.at_level(logging.WARNING, logger="agent.steering"):
        q.steer("a")
        q.steer("b")
        q.steer("c")
        q.steer("d")  # overflow — drops "a"

    assert q.drain_steering() == ["b", "c", "d"]
    # Warning log emitted referencing the dropped item
    assert any("dropped oldest" in rec.message for rec in caplog.records)


def test_follow_up_overflow_drops_oldest():
    q = SteeringQueues(cap=2)
    q.follow_up("a")
    q.follow_up("b")
    q.follow_up("c")  # overflow
    assert q.drain_follow_up() == ["b", "c"]


def test_default_cap_is_32():
    q = SteeringQueues()
    for i in range(DEFAULT_QUEUE_CAP + 5):
        q.steer(f"msg-{i}")
    drained = q.drain_steering()
    assert len(drained) == DEFAULT_QUEUE_CAP
    # Oldest 5 dropped; newest kept
    assert drained[0] == "msg-5"
    assert drained[-1] == f"msg-{DEFAULT_QUEUE_CAP + 4}"


def test_run_state_flags():
    q = SteeringQueues()
    assert q.is_running() is False
    q._mark_running()
    assert q.is_running() is True
    q._mark_idle()
    assert q.is_running() is False


def test_snapshot_returns_contents_and_run_state():
    q = SteeringQueues()
    q.steer("s")
    q.follow_up("f")
    q._mark_running()
    snap = q.snapshot()
    assert snap == {
        "is_running": True,
        "steering": ["s"],
        "follow_up": ["f"],
    }
    # Mutating the snapshot does not affect the queue.
    snap["steering"].append("x")
    assert q.pending_steering() == 1


# --------------------------------------------------------------------------- #
# Helpers for agent integration tests (mirrors test_parallel_tools.py)
# --------------------------------------------------------------------------- #


def _make_mock_agent():
    """Minimal BaseAgent subclass bypassing __init__; just enough for
    _execute_tools_sequential and _drain_steering_into_memory."""
    from agent.base import BaseAgent
    from agent.tool_executor import ToolExecutor

    class _ConcreteAgent(BaseAgent):
        async def run(self, task: str) -> str:
            raise NotImplementedError

    agent = object.__new__(_ConcreteAgent)
    agent.tool_executor = MagicMock(spec=ToolExecutor)
    agent.tool_executor.execute_tool_call = AsyncMock(return_value="real-result")
    agent.steering = SteeringQueues()
    agent.memory = MagicMock()
    agent.memory.add_message = AsyncMock()
    return agent


def _tc(name: str, call_id: str) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments={})


# --------------------------------------------------------------------------- #
# _drain_steering_into_memory
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_drain_injects_all_messages_as_user_turns_to_memory():
    agent = _make_mock_agent()
    agent.steering.steer("one")
    agent.steering.steer("two")
    agent.steering.steer("three")

    injected = await agent._drain_steering_into_memory([], use_memory=True, save_to_memory=True)

    assert injected == 3
    # All three messages appended to memory in order as role=user
    calls = agent.memory.add_message.await_args_list
    assert len(calls) == 3
    roles_and_contents = [(c.args[0].role, c.args[0].content) for c in calls]
    assert roles_and_contents == [
        ("user", "one"),
        ("user", "two"),
        ("user", "three"),
    ]
    # Queue drained.
    assert agent.steering.pending_steering() == 0


@pytest.mark.asyncio
async def test_drain_uses_messages_list_when_save_to_memory_is_false():
    agent = _make_mock_agent()
    agent.steering.steer("hi")
    local_msgs: list[LLMMessage] = []

    injected = await agent._drain_steering_into_memory(
        local_msgs, use_memory=True, save_to_memory=False
    )

    assert injected == 1
    assert [m.role for m in local_msgs] == ["user"]
    assert local_msgs[0].content == "hi"
    agent.memory.add_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_drain_is_noop_when_use_memory_is_false():
    """Mini-loops (use_memory=False) don't accept steering."""
    agent = _make_mock_agent()
    agent.steering.steer("should-not-inject")
    local: list[LLMMessage] = []

    injected = await agent._drain_steering_into_memory(
        local, use_memory=False, save_to_memory=False
    )

    assert injected == 0
    assert local == []
    # Message still pending (not drained).
    assert agent.steering.pending_steering() == 1


@pytest.mark.asyncio
async def test_drain_empty_queue_returns_zero():
    agent = _make_mock_agent()
    injected = await agent._drain_steering_into_memory([], use_memory=True, save_to_memory=True)
    assert injected == 0
    agent.memory.add_message.assert_not_awaited()


# --------------------------------------------------------------------------- #
# _execute_tools_sequential — skip semantics
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@patch("agent.base.terminal_ui")
async def test_sequential_no_steering_executes_all_tools(mock_tui):
    agent = _make_mock_agent()
    tcs = [_tc("a", "id-a"), _tc("b", "id-b")]

    results = await agent._execute_tools_sequential(tcs)

    assert [r.tool_call_id for r in results] == ["id-a", "id-b"]
    assert [r.content for r in results] == ["real-result", "real-result"]
    # Both tools actually executed.
    assert agent.tool_executor.execute_tool_call.await_count == 2


@pytest.mark.asyncio
@patch("agent.base.terminal_ui")
async def test_steering_before_batch_skips_all_tools(mock_tui):
    """If steering is pending before we enter the loop, skip every tool."""
    agent = _make_mock_agent()
    agent.steering.steer("wait, do X instead")

    tcs = [_tc("a", "id-a"), _tc("b", "id-b"), _tc("c", "id-c")]
    results = await agent._execute_tools_sequential(tcs)

    # Every tool_call has a matching result (invariant).
    assert [r.tool_call_id for r in results] == ["id-a", "id-b", "id-c"]
    assert [r.content for r in results] == [
        "[Skipped due to user steering]",
        "[Skipped due to user steering]",
        "[Skipped due to user steering]",
    ]
    # No actual tool execution.
    agent.tool_executor.execute_tool_call.assert_not_awaited()
    # Steering still pending (will be drained at next _react_loop checkpoint).
    assert agent.steering.pending_steering() == 1


@pytest.mark.asyncio
@patch("agent.base.terminal_ui")
async def test_steering_mid_batch_skips_remaining_only(mock_tui):
    """Steering that arrives after tool 1 should skip tools 2 and 3."""
    agent = _make_mock_agent()
    first_tool_ran = {"called": False}

    async def fake_exec(name, args):
        if not first_tool_ran["called"]:
            first_tool_ran["called"] = True
            # Simulate user typing a steer message while this tool is running.
            agent.steering.steer("change course")
            return "executed-a"
        pytest.fail("Should not execute any tool after steering arrives")

    agent.tool_executor.execute_tool_call = AsyncMock(side_effect=fake_exec)

    tcs = [_tc("a", "id-a"), _tc("b", "id-b"), _tc("c", "id-c")]
    results = await agent._execute_tools_sequential(tcs)

    assert [r.tool_call_id for r in results] == ["id-a", "id-b", "id-c"]
    assert results[0].content == "executed-a"
    assert results[1].content == "[Skipped due to user steering]"
    assert results[2].content == "[Skipped due to user steering]"
    # tool a was executed; b and c were skipped (only 1 real exec).
    assert agent.tool_executor.execute_tool_call.await_count == 1


@pytest.mark.asyncio
@patch("agent.base.terminal_ui")
async def test_skipped_tools_are_silent_in_ui(mock_tui):
    """No print_tool_call or print_tool_result for skipped tools (RFC: UI silence)."""
    agent = _make_mock_agent()
    agent.steering.steer("stop")

    tcs = [_tc("a", "id-a"), _tc("b", "id-b")]
    await agent._execute_tools_sequential(tcs)

    # Nothing printed for skipped tools.
    mock_tui.print_tool_call.assert_not_called()
    mock_tui.print_tool_result.assert_not_called()


@pytest.mark.asyncio
@patch("agent.base.terminal_ui")
async def test_skip_preserves_tool_call_id_and_name(mock_tui):
    """Each synthetic result must carry the matching tool_call_id and name."""
    agent = _make_mock_agent()
    agent.steering.steer("x")

    tcs = [_tc("read_file", "call_xyz"), _tc("write_file", "call_abc")]
    results = await agent._execute_tools_sequential(tcs)

    assert isinstance(results[0], ToolResult)
    assert results[0].tool_call_id == "call_xyz"
    assert results[0].name == "read_file"
    assert results[1].tool_call_id == "call_abc"
    assert results[1].name == "write_file"


# --------------------------------------------------------------------------- #
# LoopAgent.run — is_running flag lifecycle
# --------------------------------------------------------------------------- #


def _make_loop_agent_for_run_test():
    from agent.agent import LoopAgent

    agent = object.__new__(LoopAgent)
    agent.llm = MagicMock()
    agent.memory = MagicMock()
    agent.memory.system_messages = ["sys"]
    agent.memory.add_message = AsyncMock()
    agent.memory.save_memory = AsyncMock()
    agent.memory.get_stats = MagicMock(return_value={})
    agent.memory.set_tool_schemas = MagicMock()
    agent.tool_executor = MagicMock()
    agent.tool_executor.get_tool_schemas = MagicMock(return_value=[])
    agent.steering = SteeringQueues()
    agent._react_loop = AsyncMock(return_value="done")
    agent._ralph_loop = AsyncMock(return_value="verified")
    agent._print_memory_stats = MagicMock()
    return agent


@pytest.mark.asyncio
async def test_run_marks_steering_running_during_and_idle_after():
    agent = _make_loop_agent_for_run_test()

    observed_during_run = {}

    async def capture_running(*args, **kwargs):
        observed_during_run["value"] = agent.steering.is_running()
        return "done"

    agent._react_loop = AsyncMock(side_effect=capture_running)

    assert agent.steering.is_running() is False
    result = await agent.run("task")
    assert result == "done"
    assert observed_during_run["value"] is True
    assert agent.steering.is_running() is False


@pytest.mark.asyncio
async def test_run_clears_is_running_even_on_exception():
    """The finally block must reset is_running if the loop raises."""
    agent = _make_loop_agent_for_run_test()
    agent._react_loop = AsyncMock(side_effect=RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        await agent.run("task")

    assert agent.steering.is_running() is False


@pytest.mark.asyncio
async def test_run_with_verify_also_flips_is_running():
    agent = _make_loop_agent_for_run_test()

    observed = {}

    async def capture(*args, **kwargs):
        observed["value"] = agent.steering.is_running()
        return "verified"

    agent._ralph_loop = AsyncMock(side_effect=capture)

    with patch("agent.agent.Config") as mock_config:
        mock_config.RALPH_LOOP_MAX_ITERATIONS = 3
        await agent.run("task", verify=True)

    assert observed["value"] is True
    assert agent.steering.is_running() is False
