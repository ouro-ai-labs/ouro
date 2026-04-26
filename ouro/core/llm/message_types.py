"""Unified message types for LLM interface using LiteLLM/OpenAI standard format.

This module defines the standard message formats used throughout the codebase.
All types follow the OpenAI/LiteLLM format for consistency and serialization.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Union

from typing_extensions import TypedDict

# =============================================================================
# Tool Call Types (OpenAI Standard)
# =============================================================================


class FunctionCall(TypedDict):
    """Function call details within a tool call."""

    name: str
    arguments: str  # JSON string


class ToolCallBlock(TypedDict):
    """A single tool call in OpenAI format."""

    id: str
    type: Literal["function"]
    function: FunctionCall


# =============================================================================
# Stop Reason Constants
# =============================================================================


class StopReason:
    """Standard stop reason constants (OpenAI format)."""

    STOP = "stop"  # Normal completion
    TOOL_CALLS = "tool_calls"  # Model wants to call tools
    LENGTH = "length"  # Max tokens reached

    # Aliases for backward compatibility (Anthropic format)
    _ALIASES = {
        "end_turn": "stop",
        "tool_use": "tool_calls",
        "max_tokens": "length",
    }

    @classmethod
    def normalize(cls, reason: str) -> str:
        """Normalize a stop reason to standard format.

        Args:
            reason: Stop reason (may be in Anthropic or OpenAI format)

        Returns:
            Normalized stop reason in OpenAI format
        """
        return cls._ALIASES.get(reason, reason)


# =============================================================================
# LLM Message (OpenAI Standard)
# =============================================================================


@dataclass
class LLMMessage:
    """Unified message format across all LLM providers.

    Follows OpenAI/LiteLLM format:
    - role: "system", "user", "assistant", or "tool"
    - content: Text content (str), multimodal content blocks (list), or None
    - tool_calls: For assistant role, list of tool calls
    - tool_call_id: For tool role, ID of the tool call this responds to
    - name: For tool role, name of the tool

    This class is fully JSON-serializable via to_dict()/from_dict().
    """

    role: Literal["system", "user", "assistant", "tool"]
    content: Optional[Union[str, List[Dict[str, Any]]]] = None
    tool_calls: Optional[List[ToolCallBlock]] = None
    tool_call_id: Optional[str] = None  # For tool role
    name: Optional[str] = None  # Tool name (for tool role)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization and API calls.

        Returns:
            Dict representation in OpenAI format
        """
        result: Dict[str, Any] = {"role": self.role}

        if self.content is not None:
            result["content"] = self.content

        if self.tool_calls:
            result["tool_calls"] = self.tool_calls

        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id

        if self.name:
            result["name"] = self.name

        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LLMMessage":
        """Create LLMMessage from dictionary.

        Args:
            data: Dictionary with message data

        Returns:
            LLMMessage instance
        """
        return cls(
            role=data["role"],
            content=data.get("content"),
            tool_calls=data.get("tool_calls"),
            tool_call_id=data.get("tool_call_id"),
            name=data.get("name"),
        )

    def has_tool_calls(self) -> bool:
        """Check if message contains tool calls."""
        return bool(self.tool_calls)

    def is_tool_response(self) -> bool:
        """Check if this is a tool response message."""
        return self.role == "tool" and self.tool_call_id is not None


# =============================================================================
# LLM Response (Normalized, No Raw Objects)
# =============================================================================


@dataclass
class LLMResponse:
    """Unified response format across all LLM providers.

    This class stores normalized data, NOT raw provider objects.
    All fields are JSON-serializable.

    Attributes:
        content: Text content from the response (None if only tool calls)
        tool_calls: List of tool calls in OpenAI format
        stop_reason: Normalized stop reason (StopReason constants)
        usage: Token usage dict {"input_tokens": int, "output_tokens": int}
        thinking: Thinking/reasoning content (for models that support it)
    """

    content: Optional[str] = None
    tool_calls: Optional[List[ToolCallBlock]] = None
    stop_reason: str = StopReason.STOP
    usage: Optional[Dict[str, int]] = None
    thinking: Optional[str] = None

    def to_message(self) -> LLMMessage:
        """Convert response to an LLMMessage for storing in conversation history.

        Returns:
            LLMMessage with role="assistant"
        """
        return LLMMessage(
            role="assistant",
            content=self.content,
            tool_calls=self.tool_calls,
        )

    def has_tool_calls(self) -> bool:
        """Check if response contains tool calls."""
        return bool(self.tool_calls)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization.

        Returns:
            Dict representation
        """
        result: Dict[str, Any] = {
            "stop_reason": self.stop_reason,
        }

        if self.content is not None:
            result["content"] = self.content

        if self.tool_calls:
            result["tool_calls"] = self.tool_calls

        if self.usage:
            result["usage"] = self.usage

        if self.thinking:
            result["thinking"] = self.thinking

        return result


# =============================================================================
# Tool Call and Result Types
# =============================================================================


@dataclass
class ToolCall:
    """Parsed tool call for execution.

    This is used after extracting tool calls from the response,
    with arguments already parsed from JSON string to dict.
    """

    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class ToolResult:
    """Result from tool execution.

    Used to format tool results back to the LLM.
    """

    tool_call_id: str
    content: str
    name: Optional[str] = None  # Tool name (optional but recommended)

    def to_message(self) -> LLMMessage:
        """Convert to LLMMessage for conversation history.

        Returns:
            LLMMessage with role="tool"
        """
        return LLMMessage(
            role="tool",
            content=self.content,
            tool_call_id=self.tool_call_id,
            name=self.name,
        )
