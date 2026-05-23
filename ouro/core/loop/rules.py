"""Loop rules: deterministic per-call tool-result substitution.

A *rule* is a deterministic, formal check the agent loop runs over the model's
proposed tool calls *before* dispatching them. Where a hook does broad
lifecycle work (compaction, verification), a rule does one narrow thing: inspect
the proposed ``(name, arguments)`` calls and, without calling the LLM, decide
which calls to block. A blocked call is **not** dispatched — the loop
substitutes the rule's feedback message as that call's ``tool_result``, so the
model sees a deterministic error/hint and self-corrects on the next turn.

A rule never stops the loop. It only replaces results; runaway protection is
the loop's own concern (``max_iterations``). This keeps the rule contract
small: every rule, from the generic repeat breaker to a tool-aware
read-before-write check, answers the same question — "which of these calls
should I replace, and with what message?"

``ouro.core`` rules stay tool-agnostic — they see only ``ToolCall`` /
``ToolResult``. Tool-aware rules (e.g. "only modify files you've read") live in
``ouro.capabilities`` and are injected via the Agent constructor / ``AgentBuilder``.
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

    ``violations`` names the calls to block (by id) with feedback; the loop
    substitutes that feedback as their ``tool_result`` instead of dispatching
    them. Calls not named here dispatch normally.
    """

    violations: tuple[RuleViolation, ...] = ()

    @classmethod
    def ok(cls) -> RuleOutcome:
        """No objection — let every proposed call dispatch."""
        return cls()


@runtime_checkable
class Rule(Protocol):
    """A deterministic pre-dispatch check over proposed tool calls.

    Lifecycle (driven by the loop):

    - ``on_run_start`` — reset per-run state at the top of ``Agent.run``.
    - ``check`` — before dispatch, return a ``RuleOutcome`` naming the calls to
      block. Must not call the LLM or perform I/O; it is meant to be fast and
      deterministic. A rule blocks calls; it never stops the loop.
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
    """Warn the model when it repeats an identical tool-call batch.

    Compaction summaries can re-inject pathological tool-call patterns as if
    they were task state, so when the model emits the same ``(name, arguments)``
    batch ``threshold`` times in a row we block the calls and substitute a "stop
    repeating" feedback as their results. The model sees the warning and is
    expected to change course on the next turn; the rule never halts the run
    (``Agent.max_iterations`` remains the ultimate backstop). Setting
    ``threshold <= 0`` disables the check entirely.

    This is the generic, tool-agnostic rule that ships on by default.
    """

    threshold: int = 3
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

        if self.threshold <= 0 or self._repeat_count < self.threshold:
            return RuleOutcome.ok()

        count = self._repeat_count
        feedback = (
            f"[ouro] This exact tool_call has now been issued {count} times "
            "consecutively. The result has not changed. Stop repeating: either "
            "choose a different action, ask the user for clarification, or "
            "finish the task."
        )
        logger.warning(
            "RepeatedToolCallRule: intercepted %d-times-repeated tool_call(s) "
            "on iteration %d (names=%s)",
            count,
            ctx.iteration,
            [tc.name for tc in tool_calls],
        )
        return RuleOutcome(tuple(RuleViolation(tc.id, feedback) for tc in tool_calls))

    def observe(self, ctx: LoopContext, executed: list[tuple[ToolCall, ToolResult]]) -> None:
        # Stateless w.r.t. results; signature tracking happens in ``check``.
        return None
