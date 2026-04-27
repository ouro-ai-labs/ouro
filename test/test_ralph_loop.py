"""Tests for VerificationHook (Ralph-style outer-loop verification)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from ouro.capabilities.verification.hook import VerificationHook
from ouro.capabilities.verification.verifier import (
    LLMVerifier,
    VerificationResult,
    Verifier,
)
from ouro.core.llm import LLMResponse, StopReason
from ouro.core.loop import NullProgressSink
from ouro.core.loop.agent import _RunContext
from ouro.core.loop.protocols import ContinueKind

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(content: str = "answer") -> LLMResponse:
    """Build a STOP response carrying `content` as plain text."""
    return LLMResponse(
        content=content,
        stop_reason=StopReason.STOP,
        usage={"input_tokens": 10, "output_tokens": 5},
    )


def _make_ctx(task: str = "Do something") -> _RunContext:
    return _RunContext(task=task, progress=NullProgressSink())


class _StubVerifier:
    """Verifier returning a pre-programmed sequence of results."""

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
# VerificationHook lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_passes_on_first_attempt():
    """When the verifier says complete on iteration 1, the hook returns STOP."""
    verifier = _StubVerifier([VerificationResult(complete=True, reason="Correct")])
    hook = VerificationHook(MagicMock(), max_iterations=3, verifier=verifier)

    ctx = _make_ctx()
    await hook.on_run_start(ctx, [])
    decision = await hook.on_iteration_end(ctx, _make_response("42"), finished=True)

    assert decision.kind == ContinueKind.STOP
    assert verifier._call_count == 1


@pytest.mark.asyncio
async def test_retries_then_passes():
    """Incomplete first → RETRY; complete second → STOP."""
    verifier = _StubVerifier(
        [
            VerificationResult(complete=False, reason="Missing details"),
            VerificationResult(complete=True, reason="Now complete"),
        ]
    )
    hook = VerificationHook(MagicMock(), max_iterations=3, verifier=verifier)

    ctx = _make_ctx("Explain X")
    await hook.on_run_start(ctx, [])

    d1 = await hook.on_iteration_end(ctx, _make_response("incomplete"), finished=True)
    assert d1.kind == ContinueKind.RETRY
    assert "Missing details" in d1.feedback_messages[0].content

    d2 = await hook.on_iteration_end(ctx, _make_response("complete"), finished=True)
    assert d2.kind == ContinueKind.STOP


@pytest.mark.asyncio
async def test_max_iterations_skips_verification():
    """At max_iterations the hook stops without consulting the verifier again."""
    verifier = _StubVerifier(
        [
            VerificationResult(complete=False, reason="nope"),
            VerificationResult(complete=False, reason="still nope"),
        ]
    )
    hook = VerificationHook(MagicMock(), max_iterations=3, verifier=verifier)

    ctx = _make_ctx()
    await hook.on_run_start(ctx, [])

    d1 = await hook.on_iteration_end(ctx, _make_response("first"), finished=True)
    assert d1.kind == ContinueKind.RETRY
    d2 = await hook.on_iteration_end(ctx, _make_response("second"), finished=True)
    assert d2.kind == ContinueKind.RETRY

    # Third pass: hits max_iterations, returns STOP without asking the verifier.
    d3 = await hook.on_iteration_end(ctx, _make_response("third"), finished=True)
    assert d3.kind == ContinueKind.STOP
    assert verifier._call_count == 2


@pytest.mark.asyncio
async def test_finished_false_returns_continue():
    """While the inner loop is still running tool calls, the hook continues."""
    hook = VerificationHook(MagicMock(), max_iterations=3, verifier=_StubVerifier([]))
    ctx = _make_ctx()
    await hook.on_run_start(ctx, [])

    decision = await hook.on_iteration_end(ctx, _make_response(), finished=False)
    assert decision.kind == ContinueKind.CONTINUE


@pytest.mark.asyncio
async def test_custom_verifier_protocol():
    """Any object implementing the Verifier Protocol works."""

    class MyVerifier:
        async def verify(self, task, result, iteration, previous_results):
            return VerificationResult(complete=True, reason="custom verifier says yes")

    assert isinstance(MyVerifier(), Verifier)

    hook = VerificationHook(MagicMock(), max_iterations=3, verifier=MyVerifier())
    ctx = _make_ctx()
    await hook.on_run_start(ctx, [])

    decision = await hook.on_iteration_end(ctx, _make_response("answer"), finished=True)
    assert decision.kind == ContinueKind.STOP


@pytest.mark.asyncio
async def test_run_state_resets_between_runs():
    """on_run_start resets per-run state so subsequent runs start fresh."""
    verifier = _StubVerifier(
        [
            VerificationResult(complete=False, reason="r1"),
            VerificationResult(complete=True, reason="r2"),
        ]
    )
    hook = VerificationHook(MagicMock(), max_iterations=2, verifier=verifier)

    # First run: iter 1 retries, iter 2 caps without consulting the verifier.
    ctx1 = _make_ctx()
    await hook.on_run_start(ctx1, [])
    await hook.on_iteration_end(ctx1, _make_response(), finished=True)  # uses r1
    cap = await hook.on_iteration_end(ctx1, _make_response(), finished=True)  # capped
    assert cap.kind == ContinueKind.STOP
    assert verifier._call_count == 1
    # The hook accumulated previous_results across run 1:
    assert len(hook._previous_results) == 1  # noqa: SLF001

    # on_run_start of run 2 resets both _outer_iteration and _previous_results.
    ctx2 = _make_ctx()
    await hook.on_run_start(ctx2, [])
    assert hook._outer_iteration == 0  # noqa: SLF001
    assert hook._previous_results == []  # noqa: SLF001

    # Run 2 iter 1: not capped, consults the verifier (now r2 — complete).
    decision = await hook.on_iteration_end(ctx2, _make_response(), finished=True)
    assert decision.kind == ContinueKind.STOP
    assert verifier._call_count == 2


# ---------------------------------------------------------------------------
# LLMVerifier parsing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_verifier_complete():
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
