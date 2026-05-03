"""Capabilities layer: tools, memory, skills, verification, prompts.

Built on top of `ouro.core`. Exposes a Python SDK that wires capabilities
into a working agent via `AgentBuilder` / `ComposedAgent`. Users can also
construct individual hooks (CompactionHook, VerificationHook) and pass
them to the bare `core.loop.Agent` for finer control.
"""

from ouro.capabilities.builder import AgentBuilder, ComposedAgent
from ouro.capabilities.compaction import (
    CompactionHook,
    CompactionManager,
    CompressedMemory,
    CompressionStrategy,
    WorkingMemoryCompressor,
)
from ouro.capabilities.context.env import format_context_prompt
from ouro.capabilities.memory import (
    LongTermMemoryManager,
    MemoryManager,
    TokenTracker,
)
from ouro.capabilities.prompts import DEFAULT_SYSTEM_PROMPT
from ouro.capabilities.skills import SkillInfo, SkillsRegistry, render_skills_section
from ouro.capabilities.todo.state import TodoList
from ouro.capabilities.tools.base import BaseTool
from ouro.capabilities.tools.executor import ToolExecutor
from ouro.capabilities.verification.hook import VerificationHook
from ouro.capabilities.verification.verifier import (
    LLMVerifier,
    VerificationResult,
    Verifier,
)

__all__ = [
    # Top-level convenience
    "AgentBuilder",
    "ComposedAgent",
    # Tools
    "BaseTool",
    "ToolExecutor",
    # Memory
    "MemoryManager",
    "TokenTracker",
    "LongTermMemoryManager",
    # Compaction
    "CompactionManager",
    "CompactionHook",
    "WorkingMemoryCompressor",
    "CompressedMemory",
    "CompressionStrategy",
    # Skills
    "SkillsRegistry",
    "SkillInfo",
    "render_skills_section",
    # Verification
    "Verifier",
    "LLMVerifier",
    "VerificationResult",
    "VerificationHook",
    # Other
    "TodoList",
    "format_context_prompt",
    "DEFAULT_SYSTEM_PROMPT",
]
