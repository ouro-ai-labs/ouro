"""Agent module for AgenticLoop framework.

This module provides agent implementations and orchestration:

- ReActAgent: Standard ReAct (Reasoning + Acting) agent
- PlanExecuteAgent: Four-phase plan-and-execute agent
- AgentRuntime: Composable agent runtime for dynamic orchestration (RFC-004)
"""

from .base import BaseAgent
from .composition import (
    AgentConfig,
    CompositionPattern,
    CompositionPlan,
    CompositionResult,
    ExplorationAspect,
    SubtaskSpec,
)
from .plan_execute_agent import PlanExecuteAgent
from .react_agent import ReActAgent
from .runtime import AgentRuntime, MaxAgentsExceededError, MaxDepthExceededError, RuntimeConfig

__all__ = [
    # Core agents
    "BaseAgent",
    "ReActAgent",
    "PlanExecuteAgent",
    # RFC-004: Composable architecture
    "AgentRuntime",
    "RuntimeConfig",
    "AgentConfig",
    "CompositionPattern",
    "CompositionPlan",
    "CompositionResult",
    "ExplorationAspect",
    "SubtaskSpec",
    # Exceptions
    "MaxDepthExceededError",
    "MaxAgentsExceededError",
]
