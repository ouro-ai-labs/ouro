"""Core agent loop primitives.

Public surface:

- `Agent` — class-based ReAct loop with optional hooks.
- `MessageList` — mutable conversation history wrapper owned by the loop.
- `Hook`, `ToolRegistry`, `ProgressSink`, `NullProgressSink`, `LoopContext`
  — protocols capabilities/interfaces implement to plug in.
- `CompactionDecision`, `ContinueDecision`, `ContinueKind` — return types
  used by specialty hooks.
"""

from .agent import Agent
from .message_list import MessageList
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
    "MessageList",
    "CompactionDecision",
    "ContinueDecision",
    "ContinueKind",
    "Hook",
    "LoopContext",
    "NullProgressSink",
    "ProgressSink",
    "ToolRegistry",
]
