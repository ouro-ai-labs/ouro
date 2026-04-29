"""VerificationHook — Ralph-style outer-loop verification as a Hook.

When the inner loop returns STOP, this hook asks a Verifier whether the
final answer satisfies the original task. If not, it injects a feedback
user message and asks the loop to RETRY. Stops after `max_iterations`
outer attempts, returning whatever was produced last.
"""

from __future__ import annotations

from ouro.core.llm import LLMMessage, LLMResponse
from ouro.core.log import get_logger
from ouro.core.loop.protocols import ContinueDecision, LoopContext, NullProgressSink, ProgressSink

from .verifier import LLMVerifier, VerificationResult, Verifier

logger = get_logger(__name__)


class VerificationHook:
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
        self._outer_iteration = 0
        self._previous_results: list[VerificationResult] = []

    async def on_run_start(self, ctx: LoopContext, messages) -> None:
        self._outer_iteration = 0
        self._previous_results = []

    async def on_iteration_end(
        self,
        ctx: LoopContext,
        messages,
        response: LLMResponse,
        finished: bool,
    ) -> ContinueDecision:
        if not finished:
            return ContinueDecision.cont()

        self._outer_iteration += 1
        if self._outer_iteration >= self._max_iterations:
            ctx.progress.unfinished_answer(
                f"Verification skipped (max iterations {self._max_iterations} reached)."
            )
            return ContinueDecision.stop()

        final = ""
        try:
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
                f"✓ Verification passed (attempt {self._outer_iteration}/{self._max_iterations}): {verification.reason}"
            )
            return ContinueDecision.stop()

        feedback = (
            f"Your previous answer was reviewed and found incomplete. "
            f"Feedback: {verification.reason}\n\n"
            f"Please address the feedback and provide a complete answer."
        )
        ctx.progress.unfinished_answer(final)
        ctx.progress.info(
            f"⟳ Verification feedback (attempt {self._outer_iteration}/{self._max_iterations}): {verification.reason}"
        )
        return ContinueDecision.retry_with_feedback(LLMMessage(role="user", content=feedback))
