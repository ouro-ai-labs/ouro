"""Tests for the Ralph Loop (outer verification loop)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.verification import LLMVerifier, VerificationResult, Verifier
from llm import LLMMessage, LLMResponse, StopReason

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_llm_response(content: str) -> LLMResponse:
    """Create a simple LLMResponse that triggers StopReason.STOP."""
    return LLMResponse(
        content=content,
        stop_reason=StopReason.STOP,
        usage={"input_tokens": 10, "output_tokens": 5},
    )


class _StubVerifier:
    """Verifier that returns a pre-programmed sequence of results."""

    def __init__(self, results: list[VerificationResult]):
        self._results = list(results)
        self._call_count = 0

    async def verify(
        self,
        task: str,
        result: str,
        iteration: int,
        previous_results: list[VerificationResult],
    ) -> VerificationResult:
        vr = self._results[self._call_count]
        self._call_count += 1
        return vr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_agent():
    """Create a minimal BaseAgent-like object for testing _ralph_loop.

    We patch the heavy dependencies (LLM, memory, tools) so only the loop
    logic is exercised.
    """
    from agent.base import BaseAgent

    # Concrete subclass so we can instantiate without hitting ABC restriction
    class _ConcreteAgent(BaseAgent):
        async def run(self, task: str) -> str:
            raise NotImplementedError

    agent = object.__new__(_ConcreteAgent)

    # Minimal stubs
    agent.llm = MagicMock()
    agent.llm.extract_text = lambda r: r.content or ""

    agent.memory = MagicMock()
    agent.memory.add_message = AsyncMock()
    agent.memory.get_context_for_llm = MagicMock(return_value=[])

    return agent


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ralph_loop_passes_on_first_attempt(mock_agent):
    """Verification passes on the first attempt — returns immediately."""
    mock_agent._react_loop = AsyncMock(return_value="The answer is 42.")

    verifier = _StubVerifier([VerificationResult(complete=True, reason="Correct")])

    result = await mock_agent._ralph_loop(
        messages=[],
        tools=[],
        use_memory=False,
        save_to_memory=False,
        task="What is the answer?",
        max_iterations=3,
        verifier=verifier,
    )

    assert result == "The answer is 42."
    assert mock_agent._react_loop.await_count == 1


@pytest.mark.asyncio
async def test_ralph_loop_retries_then_passes(mock_agent):
    """Verification fails once, feedback injected, then passes on second attempt."""
    mock_agent._react_loop = AsyncMock(
        side_effect=["Incomplete answer", "Complete answer with details"]
    )

    verifier = _StubVerifier(
        [
            VerificationResult(complete=False, reason="Missing details"),
            VerificationResult(complete=True, reason="Now complete"),
        ]
    )

    result = await mock_agent._ralph_loop(
        messages=[],
        tools=[],
        use_memory=False,
        save_to_memory=False,
        task="Explain X",
        max_iterations=3,
        verifier=verifier,
    )

    assert result == "Complete answer with details"
    assert mock_agent._react_loop.await_count == 2


@pytest.mark.asyncio
async def test_ralph_loop_max_iterations_skips_verification(mock_agent):
    """On the last iteration, verification is skipped and the result is returned."""
    mock_agent._react_loop = AsyncMock(side_effect=["first", "second", "third"])

    # Verifier always says incomplete — but the 3rd iteration should skip it
    verifier = _StubVerifier(
        [
            VerificationResult(complete=False, reason="nope"),
            VerificationResult(complete=False, reason="still nope"),
            # This should never be reached
            VerificationResult(complete=False, reason="unreachable"),
        ]
    )

    result = await mock_agent._ralph_loop(
        messages=[],
        tools=[],
        use_memory=False,
        save_to_memory=False,
        task="Do something",
        max_iterations=3,
        verifier=verifier,
    )

    assert result == "third"
    assert mock_agent._react_loop.await_count == 3
    # Only 2 verify calls (iterations 1 and 2; iteration 3 skips verification)
    assert verifier._call_count == 2


@pytest.mark.asyncio
async def test_ralph_loop_custom_verifier_protocol(mock_agent):
    """A custom verifier following the Verifier Protocol works correctly."""

    class MyVerifier:
        async def verify(self, task, result, iteration, previous_results):
            return VerificationResult(complete=True, reason="custom verifier says yes")

    assert isinstance(MyVerifier(), Verifier)

    mock_agent._react_loop = AsyncMock(return_value="answer")

    result = await mock_agent._ralph_loop(
        messages=[],
        tools=[],
        use_memory=False,
        save_to_memory=False,
        task="task",
        max_iterations=3,
        verifier=MyVerifier(),
    )

    assert result == "answer"


@pytest.mark.asyncio
async def test_ralph_loop_injects_feedback_into_messages(mock_agent):
    """When verification fails, feedback is appended as a user message."""
    messages: list[LLMMessage] = []
    mock_agent._react_loop = AsyncMock(side_effect=["bad", "good"])

    verifier = _StubVerifier(
        [
            VerificationResult(complete=False, reason="Missing X"),
            VerificationResult(complete=True, reason="OK"),
        ]
    )

    await mock_agent._ralph_loop(
        messages=messages,
        tools=[],
        use_memory=False,
        save_to_memory=False,
        task="Do Y",
        max_iterations=3,
        verifier=verifier,
    )

    # One feedback message should have been appended
    assert len(messages) == 1
    assert messages[0].role == "user"
    assert "Missing X" in messages[0].content


@pytest.mark.asyncio
async def test_run_dispatches_to_ralph_loop():
    """ReActAgent.run() always uses _ralph_loop."""
    from agent.agent import ReActAgent

    agent = object.__new__(ReActAgent)
    agent.llm = MagicMock()
    agent.memory = MagicMock()
    agent.memory.system_messages = ["sys"]
    agent.memory.add_message = AsyncMock()
    agent.memory.save_memory = AsyncMock()
    agent.memory.get_stats = MagicMock(return_value={})
    agent.tool_executor = MagicMock()
    agent.tool_executor.get_tool_schemas = MagicMock(return_value=[])

    agent._ralph_loop = AsyncMock(return_value="ralph result")
    agent._print_memory_stats = MagicMock()

    with patch("agent.agent.Config") as mock_config:
        mock_config.RALPH_LOOP_MAX_ITERATIONS = 3
        result = await agent.run("test task")

    assert result == "ralph result"
    agent._ralph_loop.assert_awaited_once()


@pytest.mark.asyncio
async def test_llm_verifier_complete():
    """LLMVerifier parses a COMPLETE response correctly."""
    mock_llm = MagicMock()
    mock_llm.call_async = AsyncMock(
        return_value=LLMResponse(
            content="COMPLETE: The answer correctly solves the task.",
            stop_reason=StopReason.STOP,
        )
    )

    verifier = LLMVerifier(mock_llm)
    result = await verifier.verify(
        task="Calculate 1+1",
        result="2",
        iteration=1,
        previous_results=[],
    )

    assert result.complete is True
    assert "correctly solves" in result.reason


@pytest.mark.asyncio
async def test_llm_verifier_incomplete():
    """LLMVerifier parses an INCOMPLETE response correctly."""
    mock_llm = MagicMock()
    mock_llm.call_async = AsyncMock(
        return_value=LLMResponse(
            content="INCOMPLETE: The answer does not show the work.",
            stop_reason=StopReason.STOP,
        )
    )

    verifier = LLMVerifier(mock_llm)
    result = await verifier.verify(
        task="Show your work for 1+1",
        result="2",
        iteration=1,
        previous_results=[],
    )

    assert result.complete is False
    assert "does not show" in result.reason
