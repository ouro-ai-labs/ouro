"""Core agent loop primitives.

Public surface:

- `Agent` — class-based ReAct loop with optional hooks.
- `Hook`, `ToolRegistry`, `ProgressSink`, `NullProgressSink`, `LoopContext`
  — protocols capabilities/interfaces implement to plug in.
- `CompactionDecision`, `ContinueDecision`, `ContinueKind` — return types
  used by specialty hooks.
"""

from .agent import Agent
from .protocols import (
    CompactionDecision,
    ContinueDecision,
    ContinueKind,
    Hook,
    LoopContext,
    NullProgressSink,
    ProgressSink,
    ToolRegistry,
)

__all__ = [
    "Agent",
    "CompactionDecision",
    "ContinueDecision",
    "ContinueKind",
    "Hook",
    "LoopContext",
    "NullProgressSink",
    "ProgressSink",
    "ToolRegistry",
]
