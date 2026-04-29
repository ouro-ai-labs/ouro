"""Tests for VerificationHook (Ralph-style outer-loop verification)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from ouro.capabilities.verification.hook import VerificationHook
from ouro.capabilities.verification.verifier import LLMVerifier, VerificationResult, Verifier
from ouro.core.llm import LLMMessage, LLMResponse, StopReason
from ouro.core.loop import NullProgressSink
from ouro.core.loop.agent import _RunContext
from ouro.core.loop.message_list import MessageList
from ouro.core.loop.protocols import ContinueKind


def _make_response(content: str = "answer") -> LLMResponse:
    return LLMResponse(
        content=content,
        stop_reason=StopReason.STOP,
        usage={"input_tokens": 10, "output_tokens": 5},
    )


def _make_ctx(task: str = "Do something") -> _RunContext:
    return _RunContext(task=task, progress=NullProgressSink())


class _StubVerifier:
    def __init__(self, results: list[VerificationResult]):
        self._results = list(results)
        self._call_count = 0

    async def verify(
        self, task: str, result: str, iteration: int, previous_results: list[VerificationResult]
    ) -> VerificationResult:
        vr = self._results[self._call_count]
        self._call_count += 1
        return vr


@pytest.mark.asyncio
async def test_passes_on_first_attempt():
    verifier = _StubVerifier([VerificationResult(complete=True, reason="Correct")])
    hook = VerificationHook(MagicMock(), max_iterations=3, verifier=verifier)

    ctx = _make_ctx()
    messages = MessageList([LLMMessage(role="user", content=ctx.task)])
    await hook.on_run_start(ctx, messages)
    decision = await hook.on_iteration_end(ctx, messages, _make_response("42"), finished=True)

    assert decision.kind == ContinueKind.STOP
    assert verifier._call_count == 1


@pytest.mark.asyncio
async def test_retries_then_passes():
    verifier = _StubVerifier(
        [
            VerificationResult(complete=False, reason="Missing details"),
            VerificationResult(complete=True, reason="Now complete"),
        ]
    )
    hook = VerificationHook(MagicMock(), max_iterations=3, verifier=verifier)

    ctx = _make_ctx("Explain X")
    messages = MessageList([LLMMessage(role="user", content=ctx.task)])
    await hook.on_run_start(ctx, messages)

    d1 = await hook.on_iteration_end(ctx, messages, _make_response("incomplete"), finished=True)
    assert d1.kind == ContinueKind.RETRY
    assert "Missing details" in d1.feedback_messages[0].content

    d2 = await hook.on_iteration_end(ctx, messages, _make_response("complete"), finished=True)
    assert d2.kind == ContinueKind.STOP


@pytest.mark.asyncio
async def test_max_iterations_skips_verification():
    verifier = _StubVerifier(
        [
            VerificationResult(complete=False, reason="nope"),
            VerificationResult(complete=False, reason="still nope"),
        ]
    )
    hook = VerificationHook(MagicMock(), max_iterations=3, verifier=verifier)

    ctx = _make_ctx()
    messages = MessageList([LLMMessage(role="user", content=ctx.task)])
    await hook.on_run_start(ctx, messages)

    d1 = await hook.on_iteration_end(ctx, messages, _make_response("first"), finished=True)
    assert d1.kind == ContinueKind.RETRY
    d2 = await hook.on_iteration_end(ctx, messages, _make_response("second"), finished=True)
    assert d2.kind == ContinueKind.RETRY
    d3 = await hook.on_iteration_end(ctx, messages, _make_response("third"), finished=True)
    assert d3.kind == ContinueKind.STOP
    assert verifier._call_count == 2


@pytest.mark.asyncio
async def test_finished_false_returns_continue():
    hook = VerificationHook(MagicMock(), max_iterations=3, verifier=_StubVerifier([]))
    ctx = _make_ctx()
    messages = MessageList([LLMMessage(role="user", content=ctx.task)])
    await hook.on_run_start(ctx, messages)

    decision = await hook.on_iteration_end(ctx, messages, _make_response(), finished=False)
    assert decision.kind == ContinueKind.CONTINUE


@pytest.mark.asyncio
async def test_custom_verifier_protocol():
    class MyVerifier:
        async def verify(self, task, result, iteration, previous_results):
            return VerificationResult(complete=True, reason="custom verifier says yes")

    assert isinstance(MyVerifier(), Verifier)

    hook = VerificationHook(MagicMock(), max_iterations=3, verifier=MyVerifier())
    ctx = _make_ctx()
    messages = MessageList([LLMMessage(role="user", content=ctx.task)])
    await hook.on_run_start(ctx, messages)

    decision = await hook.on_iteration_end(ctx, messages, _make_response("answer"), finished=True)
    assert decision.kind == ContinueKind.STOP


@pytest.mark.asyncio
async def test_run_state_resets_between_runs():
    verifier = _StubVerifier(
        [
            VerificationResult(complete=False, reason="r1"),
            VerificationResult(complete=True, reason="r2"),
        ]
    )
    hook = VerificationHook(MagicMock(), max_iterations=2, verifier=verifier)

    ctx1 = _make_ctx()
    messages1 = MessageList([LLMMessage(role="user", content=ctx1.task)])
    await hook.on_run_start(ctx1, messages1)
    await hook.on_iteration_end(ctx1, messages1, _make_response(), finished=True)
    cap = await hook.on_iteration_end(ctx1, messages1, _make_response(), finished=True)
    assert cap.kind == ContinueKind.STOP
    assert verifier._call_count == 1
    assert len(hook._previous_results) == 1  # noqa: SLF001

    ctx2 = _make_ctx()
    messages2 = MessageList([LLMMessage(role="user", content=ctx2.task)])
    await hook.on_run_start(ctx2, messages2)
    assert hook._outer_iteration == 0  # noqa: SLF001
    assert hook._previous_results == []  # noqa: SLF001

    decision = await hook.on_iteration_end(ctx2, messages2, _make_response(), finished=True)
    assert decision.kind == ContinueKind.STOP
    assert verifier._call_count == 2


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
        task="Calculate 1+1", result="2", iteration=1, previous_results=[]
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
        task="Show your work for 1+1", result="2", iteration=1, previous_results=[]
    )

    assert result.complete is False
    assert "does not show" in result.reason
