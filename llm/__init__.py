"""LLM module - LiteLLM adapter for unified access to 100+ providers."""

# Import new types from message_types (primary source)
# Import compatibility utilities
from .compat import ensure_new_format, migrate_messages, normalize_stop_reason

# Import utilities
from .content_utils import (
    extract_text,
    extract_text_from_message,
    extract_tool_calls_from_content,
    message_to_dict,
)

# Import adapter
from .litellm_adapter import LiteLLMAdapter
from .message_types import (
    FunctionCall,
    LLMMessage,
    LLMResponse,
    StopReason,
    ToolCall,
    ToolCallBlock,
    ToolResult,
)
from .model_manager import ModelManager, ModelProfile
from .reasoning import REASONING_EFFORT_CHOICES, display_reasoning_effort, normalize_reasoning_effort

__all__ = [
    # Core types
    "LLMMessage",
    "LLMResponse",
    "ToolCall",
    "ToolResult",
    "ToolCallBlock",
    "FunctionCall",
    "StopReason",
    # Adapter
    "LiteLLMAdapter",
    # Model Manager
    "ModelManager",
    "ModelProfile",
    # Reasoning
    "REASONING_EFFORT_CHOICES",
    "normalize_reasoning_effort",
    "display_reasoning_effort",
    # Utilities
    "extract_text",
    "extract_text_from_message",
    "extract_tool_calls_from_content",
    "message_to_dict",
    # Compatibility
    "ensure_new_format",
    "migrate_messages",
    "normalize_stop_reason",
]
