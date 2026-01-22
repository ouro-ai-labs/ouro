"""Base data structures for LLM interface."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union


@dataclass
class LLMMessage:
    """Unified message format across all LLM providers.

    This class represents a message in the conversation, supporting both
    simple text content and structured content with tool calls.

    Attributes:
        role: Message role ("user", "assistant", "system")
        content: Message content (string or list of content blocks for tool results)
        tool_calls: Optional list of tool calls (for assistant messages with tool use)
    """

    role: str
    content: Union[str, List[Dict[str, Any]]]
    tool_calls: Optional[List["ToolCall"]] = None


@dataclass
class LLMResponse:
    """Unified response format across all LLM providers.

    Attributes:
        message: Structured LLMMessage object
        stop_reason: Reason for stopping ("end_turn", "tool_use", "max_tokens", etc.)
        usage: Token usage statistics
        _raw_message: Internal field for provider-specific features (e.g., thinking)
    """

    message: "LLMMessage"
    stop_reason: str
    usage: Optional[Dict[str, int]] = None
    _raw_message: Any = None  # Internal: original provider message for special features


@dataclass
class ToolCall:
    """Unified tool call format."""

    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class ToolResult:
    """Unified tool result format."""

    tool_call_id: str
    content: str
