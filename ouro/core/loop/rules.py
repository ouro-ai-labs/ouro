"""Loop rules: deterministic pre-dispatch guards.

A *rule* is a deterministic, formal check the agent loop runs over the model's
proposed tool calls *before* dispatching them. Where a hook does broad
lifecycle work (compaction, verification), a rule does one narrow thing: inspect
the proposed ``(name, arguments)`` calls and decide — without calling the LLM —
whether each call may proceed. A rule trades a probabilistic LLM mistake for a
deterministic guarantee, feeding any verdict back to the model as a synthetic
``tool_result`` so it can self-correct on the next turn.

The loop owns the integration (see ``Agent._apply_rules``); rules own only their
verdict and any per-run state. ``ouro.core`` rules stay tool-agnostic — they see
only ``ToolCall`` / ``ToolResult``. Tool-aware rules (e.g. "only modify files
you've read") live in ``ouro.capabilities`` and are injected via the Agent
constructor / ``AgentBuilder``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ouro.core.log import get_logger

if TYPE_CHECKING:
    from ouro.core.llm import ToolCall, ToolResult
    from ouro.core.loop.protocols import LoopContext

logger = get_logger(__name__)


@dataclass(frozen=True)
class RuleViolation:
    """One proposed tool call a rule decided to block.

    ``message`` becomes the synthetic ``tool_result`` content fed back to the
    model in place of dispatching the call, so it should read as actionable
    feedback ("read the file before writing it", etc.).
    """

    tool_call_id: str
    message: str


@dataclass(frozen=True)
class RuleOutcome:
    """A rule's verdict on one iteration's proposed tool calls.

    - ``violations`` — calls to block (by id) with feedback. Siblings not named
      here dispatch normally.
    - ``halt`` — terminate the whole run after this iteration.
    - ``halt_message`` — final answer returned to the caller when ``halt``.
    """

    violations: tuple[RuleViolation, ...] = ()
    halt: bool = False
    halt_message: str | None = None

    @classmethod
    def ok(cls) -> RuleOutcome:
        """No objection — let every proposed call dispatch."""
        return cls()


@runtime_checkable
class Rule(Protocol):
    """A deterministic pre-dispatch check over proposed tool calls.

    Lifecycle (driven by the loop):

    - ``on_run_start`` — reset per-run state at the top of ``Agent.run``.
    - ``check`` — before dispatch, return a ``RuleOutcome`` blocking calls
      and/or halting. Must not call the LLM or perform I/O; it is meant to be
      fast and deterministic.
    - ``observe`` — after dispatch, see the executed ``(ToolCall, ToolResult)``
      pairs so stateful rules can update (e.g. record which files were read).
      Blocked calls are not in ``executed``.
    """

    name: str

    def on_run_start(self) -> None: ...
    def check(self, ctx: LoopContext, tool_calls: list[ToolCall]) -> RuleOutcome: ...
    def observe(self, ctx: LoopContext, executed: list[tuple[ToolCall, ToolResult]]) -> None: ...


def _tool_call_iter_signature(
    tool_calls: list[ToolCall],
) -> tuple[tuple[str, str], ...]:
    """Build a deterministic fingerprint for one iteration's tool_calls.

    Used by ``RepeatedToolCallRule`` to detect when the model is emitting the
    exact same ``(name, arguments)`` batch iteration after iteration. Arguments
    are serialized with ``sort_keys=True`` so key order is normalized;
    non-JSON-safe values fall back to ``str(...)`` so the helper never raises on
    exotic argument types.
    """
    sigs: list[tuple[str, str]] = []
    for tc in tool_calls:
        try:
            args_repr = json.dumps(tc.arguments, sort_keys=True, default=str)
        except (TypeError, ValueError):
            args_repr = repr(tc.arguments)
        sigs.append((tc.name, args_repr))
    return tuple(sigs)


@dataclass
class RepeatedToolCallRule:
    """Circuit-breaker for self-reinforcing tool-call loops.

    Compaction summaries can re-inject pathological tool-call patterns as if
    they were task state, so when the model emits the same ``(name, arguments)``
    iteration ``threshold`` times in a row we block the calls with a "stop
    repeating" feedback (soft intercept), and at ``max_repeats`` we halt the run
    (hard stop). Setting ``threshold <= 0`` disables the breaker entirely.

    This is the generic, tool-agnostic rule that ships on by default; it ports
    the behavior previously baked into ``Agent._apply_repeated_tool_call_guard``.
    """

    threshold: int = 3
    max_repeats: int = 5
    name: str = field(default="repeated_tool_call", init=False)

    def __post_init__(self) -> None:
        self._last_iter_sig: tuple[tuple[str, str], ...] | None = None
        self._repeat_count: int = 0

    def on_run_start(self) -> None:
        self._last_iter_sig = None
        self._repeat_count = 0

    def check(self, ctx: LoopContext, tool_calls: list[ToolCall]) -> RuleOutcome:
        iter_sig = _tool_call_iter_signature(tool_calls)
        if self._last_iter_sig is not None and iter_sig == self._last_iter_sig:
            self._repeat_count += 1
        else:
            self._repeat_count = 1
        self._last_iter_sig = iter_sig

        if self.threshold <= 0:
            return RuleOutcome.ok()

        count = self._repeat_count
        names = [tc.name for tc in tool_calls]

        if count >= self.max_repeats:
            feedback = (
                f"[ouro] Same tool_call(s) repeated {count} times consecutively "
                "with no progress. Terminating to prevent runaway loop."
            )
            logger.warning(
                "RepeatedToolCallRule: hard-stopping after %d consecutive "
                "identical tool_call iterations on iteration %d (names=%s)",
                count,
                ctx.iteration,
                names,
            )
            halt_message = (
                "[ouro] Halted: the model repeated the same tool call "
                f"{count} times without progress ({names}). Please rephrase your "
                "request or restart the session."
            )
            return RuleOutcome(
                violations=tuple(RuleViolation(tc.id, feedback) for tc in tool_calls),
                halt=True,
                halt_message=halt_message,
            )

        if count >= self.threshold:
            feedback = (
                f"[ouro] This exact tool_call has now been issued {count} times "
                "consecutively. The result has not changed. Stop repeating: "
                "either choose a different action, ask the user for clarification, "
                "or finish the task."
            )
            logger.warning(
                "RepeatedToolCallRule: intercepted %d-times-repeated tool_call(s) "
                "on iteration %d (names=%s)",
                count,
                ctx.iteration,
                names,
            )
            return RuleOutcome(
                violations=tuple(RuleViolation(tc.id, feedback) for tc in tool_calls)
            )

        return RuleOutcome.ok()

    def observe(self, ctx: LoopContext, executed: list[tuple[ToolCall, ToolResult]]) -> None:
        # Stateless w.r.t. results; signature tracking happens in ``check``.
        return None
