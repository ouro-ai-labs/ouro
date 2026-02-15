"""Verification interface and default LLM verifier for the Ralph Loop.

The verifier judges whether the agent's final answer truly satisfies the
original task. If not, feedback is returned so the outer loop can re-enter
the inner ReAct loop with corrective guidance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from llm import LLMMessage
from utils import get_logger
from utils.tui.progress import AsyncSpinner

if TYPE_CHECKING:
    from llm import LiteLLMAdapter
    from utils.tui.terminal_ui import TerminalUI

logger = get_logger(__name__)


@dataclass
class VerificationResult:
    """Result of a verification check."""

    complete: bool
    reason: str


@runtime_checkable
class Verifier(Protocol):
    """Protocol for task-completion verifiers."""

    async def verify(
        self,
        task: str,
        result: str,
        iteration: int,
        previous_results: list[VerificationResult],
    ) -> VerificationResult:
        """Judge whether *result* satisfies *task*.

        Args:
            task: The original user task description.
            result: The agent's final answer from the inner loop.
            iteration: Current outer-loop iteration (1-indexed).
            previous_results: Verification results from earlier iterations.

        Returns:
            VerificationResult indicating completion status and reasoning.
        """
        ...  # pragma: no cover


_VERIFICATION_PROMPT = """\
You are a strict verification assistant. Your job is to determine whether an \
AI agent's answer fully and correctly completes the user's original task.

<task>
{task}
</task>

<agent_answer>
{result}
</agent_answer>

{previous_context}

<judgment_rules>
1. If the task is a ONE-TIME request (e.g. "calculate 1+1", "summarize this file"), \
judge whether the answer is correct and complete.

2. If the task requires MULTIPLE steps and only some were done, respond INCOMPLETE \
with specific feedback on what remains.
</judgment_rules>

Respond with EXACTLY one of:
- COMPLETE: <brief reason why the task is satisfied>
- INCOMPLETE: <specific feedback on what is missing or wrong>

Do NOT restate the answer. Only judge it."""


class LLMVerifier:
    """Default verifier that uses a lightweight LLM call (no tools)."""

    def __init__(self, llm: LiteLLMAdapter, terminal_ui: TerminalUI | None = None):
        self.llm = llm
        self._tui = terminal_ui

    async def verify(
        self,
        task: str,
        result: str,
        iteration: int,
        previous_results: list[VerificationResult],
    ) -> VerificationResult:
        previous_context = ""
        if previous_results:
            lines = []
            for i, pr in enumerate(previous_results, 1):
                status = "complete" if pr.complete else "incomplete"
                lines.append(f"  Attempt {i}: {status} — {pr.reason}")
            previous_context = "Previous verification attempts:\n" + "\n".join(lines)

        prompt = _VERIFICATION_PROMPT.format(
            task=task,
            result=result[:4000],  # Truncate to avoid excessive tokens
            previous_context=previous_context,
        )

        messages = [
            LLMMessage(role="system", content="You are a task-completion verifier."),
            LLMMessage(role="user", content=prompt),
        ]

        console = self._tui.console if self._tui else None
        if console:
            async with AsyncSpinner(console, "Verifying completion..."):
                response = await self.llm.call_async(messages=messages, tools=None, max_tokens=512)
        else:
            response = await self.llm.call_async(messages=messages, tools=None, max_tokens=512)

        text = (response.content or "").strip()
        logger.debug(f"Verification response (iter {iteration}): {text}")

        upper = text.upper()
        if upper.startswith("COMPLETE"):
            reason = text.split(":", 1)[1].strip() if ":" in text else text
            return VerificationResult(complete=True, reason=reason)
        else:
            reason = text.split(":", 1)[1].strip() if ":" in text else text
            return VerificationResult(complete=False, reason=reason)
