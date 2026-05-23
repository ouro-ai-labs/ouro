"""Core agent loop primitives.

Public surface:

- `Agent` — class-based ReAct loop with optional hooks.
- `MessageList` — mutable conversation history wrapper owned by the loop.
- `RunStatistic` — mutable per-run state (iterations, token usage).
- `MessageListContext` — loop-level container for system + detached messages.
- `Hook`, `ToolRegistry`, `ProgressSink`, `NullProgressSink`, `LoopContext`
  — protocols capabilities/interfaces implement to plug in.
- `ContinueDecision`, `ContinueKind` — return types used by
  ``on_iteration_end`` (STOP / RETRY / CONTINUE voting).
- `Rule`, `RuleOutcome`, `RuleViolation`, `RepeatedToolCallRule` —
  deterministic pre-dispatch guards over proposed tool calls.
"""

from .agent import Agent
from .context import MessageListContext, RunStatistic
from .message_list import MessageList
from .protocols import (
    ContinueDecision,
    ContinueKind,
    Hook,
    LoopContext,
    NullProgressSink,
    ProgressSink,
    ToolRegistry,
)
from .rules import RepeatedToolCallRule, Rule, RuleOutcome, RuleViolation

__all__ = [
    "Agent",
    "MessageList",
    "MessageListContext",
    "RunStatistic",
    "ContinueDecision",
    "ContinueKind",
    "Hook",
    "LoopContext",
    "NullProgressSink",
    "ProgressSink",
    "ToolRegistry",
    "Rule",
    "RuleOutcome",
    "RuleViolation",
    "RepeatedToolCallRule",
]
