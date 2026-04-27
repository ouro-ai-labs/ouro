"""Core layer: agent loop primitives + LLM/message/tool-call wrappers.

This is ouro's lowest layer. It depends on `litellm` and standard library
only — never on `ouro.capabilities` or `ouro.interfaces`.

Public SDK surface:

- Loop: `Agent`, `Hook`, `ToolRegistry`, `ProgressSink`, `NullProgressSink`,
  `LoopContext`, `CompactionDecision`, `ContinueDecision`, `ContinueKind`.
- LLM types: `LLMMessage`, `LLMResponse`, `ToolCall`, `ToolResult`,
  `ToolCallBlock`, `FunctionCall`, `StopReason`.
- LLM client: `LiteLLMAdapter`, `ModelManager`, `ModelProfile`.
- Reasoning helpers: `REASONING_EFFORT_CHOICES`, `normalize_reasoning_effort`,
  `display_reasoning_effort`.
- Content helpers: `extract_text`, `extract_text_from_message`,
  `extract_tool_calls_from_content`, `message_to_dict`.
- Format compat: `ensure_new_format`, `migrate_messages`,
  `normalize_stop_reason`.
- Runtime helpers: `get_runtime_dir`, `get_sessions_dir`, `get_memory_dir`,
  `ensure_runtime_dirs`.
- Logging: `get_logger`, `setup_logger`, `get_log_file_path`.
"""

import contextlib

from ouro.core.llm import (
    REASONING_EFFORT_CHOICES,
    FunctionCall,
    LiteLLMAdapter,
    LLMMessage,
    LLMResponse,
    ModelManager,
    ModelProfile,
    StopReason,
    ToolCall,
    ToolCallBlock,
    ToolResult,
    display_reasoning_effort,
    ensure_new_format,
    extract_text,
    extract_text_from_message,
    extract_tool_calls_from_content,
    message_to_dict,
    migrate_messages,
    normalize_reasoning_effort,
    normalize_stop_reason,
)
from ouro.core.log import get_log_file_path, get_logger, setup_logger
from ouro.core.loop import (
    Agent,
    CompactionDecision,
    ContinueDecision,
    ContinueKind,
    Hook,
    LoopContext,
    NullProgressSink,
    ProgressSink,
    ToolRegistry,
)
from ouro.core.runtime import (
    ensure_runtime_dirs,
    get_runtime_dir,
)

# get_sessions_dir / get_memory_dir live in runtime.py with various other
# helpers; re-export the ones the SDK calls out, fall back gracefully if a
# helper isn't present in older runtime modules.
with contextlib.suppress(ImportError):
    from ouro.core.runtime import get_sessions_dir
with contextlib.suppress(ImportError):
    from ouro.core.runtime import get_memory_dir

__all__ = [
    # Loop
    "Agent",
    "Hook",
    "ToolRegistry",
    "ProgressSink",
    "NullProgressSink",
    "LoopContext",
    "CompactionDecision",
    "ContinueDecision",
    "ContinueKind",
    # LLM types
    "LLMMessage",
    "LLMResponse",
    "ToolCall",
    "ToolResult",
    "ToolCallBlock",
    "FunctionCall",
    "StopReason",
    # LLM client
    "LiteLLMAdapter",
    "ModelManager",
    "ModelProfile",
    # Reasoning
    "REASONING_EFFORT_CHOICES",
    "normalize_reasoning_effort",
    "display_reasoning_effort",
    # Content helpers
    "extract_text",
    "extract_text_from_message",
    "extract_tool_calls_from_content",
    "message_to_dict",
    # Compat
    "ensure_new_format",
    "migrate_messages",
    "normalize_stop_reason",
    # Runtime
    "get_runtime_dir",
    "ensure_runtime_dirs",
    "get_sessions_dir",
    "get_memory_dir",
    # Logging
    "get_logger",
    "setup_logger",
    "get_log_file_path",
]
