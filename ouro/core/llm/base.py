"""Base data structures for LLM interface.

This module re-exports types from message_types.py for backward compatibility.
New code should import from llm.message_types or llm directly.
"""

# Re-export all types from message_types for backward compatibility
from .message_types import (
    FunctionCall,
    LLMMessage,
    LLMResponse,
    StopReason,
    ToolCall,
    ToolCallBlock,
    ToolResult,
)

__all__ = [
    "LLMMessage",
    "LLMResponse",
    "ToolCall",
    "ToolResult",
    "ToolCallBlock",
    "FunctionCall",
    "StopReason",
]
