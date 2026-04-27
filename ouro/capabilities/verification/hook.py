"""VerificationHook — Ralph-style outer-loop verification as a Hook.

When the inner loop returns STOP, this hook asks a Verifier whether the
final answer satisfies the original task. If not, it injects a feedback
user message and asks the loop to RETRY. Stops after `max_iterations`
outer attempts, returning whatever was produced last.
"""

from __future__ import annotations

from ouro.core.llm import LLMMessage, LLMResponse
from ouro.core.log import get_logger
from ouro.core.loop.protocols import (
    ContinueDecision,
    LoopContext,
    NullProgressSink,
    ProgressSink,
)

from .verifier import LLMVerifier, VerificationResult, Verifier

logger = get_logger(__name__)


class VerificationHook:
    """Wraps a `Verifier` (default `LLMVerifier`) into a loop hook.

    Args:
        llm: The LLM adapter used to construct `LLMVerifier` if no `verifier`
            is provided.
        max_iterations: Max outer iterations. After this many, the hook
            stops and returns whatever was produced.
        verifier: Optional custom Verifier (must satisfy the Protocol).
        progress: Optional ProgressSink for spinner during verification call.
    """

    def __init__(
        self,
        llm,
        *,
        max_iterations: int = 3,
        verifier: Verifier | None = None,
        progress: ProgressSink | None = None,
    ) -> None:
        self._max_iterations = max_iterations
        self._progress: ProgressSink = progress or NullProgressSink()
        self._verifier: Verifier = verifier or LLMVerifier(llm, progress=self._progress)
        # Per-run state. Reset in on_run_start.
        self._outer_iteration = 0
        self._previous_results: list[VerificationResult] = []

    # ---- lifecycle ------------------------------------------------------

    async def on_run_start(self, ctx: LoopContext, messages: list[LLMMessage]) -> list[LLMMessage]:
        self._outer_iteration = 0
        self._previous_results = []
        return messages

    # ---- specialty ------------------------------------------------------

    async def on_iteration_end(
        self,
        ctx: LoopContext,
        response: LLMResponse,
        finished: bool,
    ) -> ContinueDecision:
        if not finished:
            return ContinueDecision.cont()

        self._outer_iteration += 1
        if self._outer_iteration >= self._max_iterations:
            ctx.progress.unfinished_answer(
                f"Verification skipped (max iterations " f"{self._max_iterations} reached)."
            )
            return ContinueDecision.stop()

        result_text = ctx.progress  # noqa: F841 — placeholder if needed
        # Extract final answer text from the response.
        final = ""
        try:
            # The response was already passed through after_call; surface text.
            final = (
                response.content
                if isinstance(response.content, str)
                else (
                    "".join(
                        block.get("text", "")
                        for block in (response.content or [])
                        if isinstance(block, dict) and block.get("type") == "text"
                    )
                )
            )
        except Exception:
            final = ""

        verification = await self._verifier.verify(
            task=ctx.task,
            result=final,
            iteration=self._outer_iteration,
            previous_results=self._previous_results,
        )
        self._previous_results.append(verification)

        if verification.complete:
            ctx.progress.info(
                f"✓ Verification passed (attempt {self._outer_iteration}/"
                f"{self._max_iterations}): {verification.reason}"
            )
            return ContinueDecision.stop()

        feedback = (
            f"Your previous answer was reviewed and found incomplete. "
            f"Feedback: {verification.reason}\n\n"
            f"Please address the feedback and provide a complete answer."
        )
        ctx.progress.unfinished_answer(final)
        ctx.progress.info(
            f"⟳ Verification feedback (attempt {self._outer_iteration}/"
            f"{self._max_iterations}): {verification.reason}"
        )
        return ContinueDecision.retry_with_feedback(LLMMessage(role="user", content=feedback))
