"""Loop rules: deterministic, per-tool-call result control.

A *rule* is a deterministic check the agent loop runs around each individual
tool call. Where a hook does broad lifecycle work (compaction, verification), a
rule does one narrow thing per call: decide, without calling the LLM, whether
to block the call or rewrite its result. A rule trades a probabilistic LLM
mistake for a deterministic guarantee, feeding its verdict back as the call's
``tool_result`` so the model self-corrects.

Two optional hooks — a rule implements whichever it needs:

- ``before_toolcall(ctx, tool_call) -> str | None`` runs *before* dispatch.
  Return a string to **block** the call: it is skipped (never executed) and the
  returned text becomes its ``tool_result``. Return ``None`` to let it run. This
  is the only way to stop a side-effecting call (write/edit/delete/run) from
  actually happening.
- ``after_toolcall(ctx, tool_call, tool_result) -> str | None`` runs *after* a
  dispatched call returns. Return a string to **replace** its result text;
  return ``None`` to leave it unchanged. Use it to rewrite output and/or to
  record state from real results (e.g. which files were read).
- ``after_toolcall_with_metadata(ctx, tool_call, tool_result) -> str | None``
  is an optional variant of ``after_toolcall`` that receives the full
  ``ToolResult`` including its ``metadata`` dict (e.g. ``is_partial_view``).
  It is called **after** ``after_toolcall`` if both are present.

Both are per-tool-call and should be cheap and side-effect-free: no LLM calls
and no heavy or blocking I/O (a quick local check such as ``os.path.exists`` is
fine). A rule never stops the loop; it only blocks or rewrites individual
results. Runaway protection is the loop's own concern (``max_iterations``).

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
    from ouro.core.llm import ToolCall
    from ouro.core.loop.protocols import LoopContext

logger = get_logger(__name__)


@runtime_checkable
class Rule(Protocol):
    """A deterministic, per-tool-call check.

    A rule carries a ``name`` and defines **either or both** of these optional
    hooks (the loop duck-types via ``getattr``, so a rule implements only what
    it needs):

    - ``before_toolcall(ctx, tool_call) -> str | None`` — before dispatch;
      return text to block the call (it is skipped and the text becomes its
      ``tool_result``), or ``None`` to let it run.
    - ``after_toolcall(ctx, tool_call, tool_result) -> str | None`` — after a
      dispatched call; return text to replace its result, or ``None`` to leave
      it (also where stateful rules record from real results).

    The signatures live in the docstring rather than the Protocol body so that
    a rule implementing just one hook still structurally satisfies ``Rule``.
    """

    name: str


def _tool_call_signature(tool_call: ToolCall) -> tuple[str, str]:
    """Build a deterministic ``(name, arguments)`` fingerprint for one call.

    Arguments are serialized with ``sort_keys=True`` so key order is normalized;
    non-JSON-safe values fall back to ``str(...)`` so this never raises on exotic
    argument types.
    """
    try:
        args_repr = json.dumps(tool_call.arguments, sort_keys=True, default=str)
    except (TypeError, ValueError):
        args_repr = repr(tool_call.arguments)
    return (tool_call.name, args_repr)


@dataclass
class RepeatedToolCallRule:
    """Warn the model when it repeats an identical tool call across turns.

    Compaction summaries can re-inject pathological tool-call patterns as if
    they were task state, so when the same ``(name, arguments)`` call recurs on
    consecutive iterations ``threshold`` times we block it and feed back a "stop
    repeating" message as its result. The model is expected to change course;
    the rule never halts the run (``Agent.max_iterations`` is the backstop).

    State is per-call and self-resetting: a new run restarts ``ctx.iteration``
    at 1, which clears stale counts, so the rule needs no lifecycle reset.
    ``threshold <= 0`` disables the check.
    """

    threshold: int = 3
    name: str = field(default="repeated_tool_call", init=False)

    def __post_init__(self) -> None:
        # signature -> (last iteration it was seen on, consecutive-turn count)
        self._counts: dict[tuple[str, str], tuple[int, int]] = {}

    def before_toolcall(self, ctx: LoopContext, tool_call: ToolCall) -> str | None:
        if self.threshold <= 0:
            return None
        iteration = ctx.iteration
        if iteration <= 1:
            # A new run restarts the iteration counter at 1; drop stale state.
            self._counts.clear()

        sig = _tool_call_signature(tool_call)
        last_iter, count = self._counts.get(sig, (0, 0))
        # Consecutive if it recurred on this turn or the immediately prior one.
        count = count + 1 if last_iter and last_iter >= iteration - 1 else 1
        self._counts[sig] = (iteration, count)

        if count < self.threshold:
            return None

        logger.warning(
            "RepeatedToolCallRule: tool_call %r issued %d times across "
            "consecutive iterations (iteration %d)",
            tool_call.name,
            count,
            iteration,
        )
        return (
            f"[ouro] This exact tool_call has now been issued {count} times across "
            "consecutive turns with no change in result. Stop repeating: choose a "
            "different action, ask the user for clarification, or finish the task."
        )
