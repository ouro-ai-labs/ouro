"""Backward compatibility layer for message format migration.

This module provides utilities for converting between old and new message formats,
allowing gradual migration while maintaining backward compatibility.
"""

from typing import Any, Dict, List, Union

from .content_utils import extract_text, extract_tool_calls_from_content
from .message_types import LLMMessage, StopReason


def ensure_new_format(message: Any) -> LLMMessage:
    """Convert any message format to the new LLMMessage format.

    Handles:
    - New LLMMessage instances (passed through)
    - Old LLMMessage with complex content
    - Dict representations
    - Raw message objects from providers

    Args:
        message: Message in any supported format

    Returns:
        LLMMessage in new format
    """
    # Already new format
    if isinstance(message, LLMMessage):
        # Check if it has the new attributes (tool_calls, tool_call_id)
        if hasattr(message, "tool_calls"):
            return message
        # Old format LLMMessage - convert
        return _convert_old_llm_message(message)

    # Dict format
    if isinstance(message, dict):
        return LLMMessage.from_dict(message)

    # Raw message object (from provider)
    return _convert_raw_message(message)


def _convert_old_llm_message(message: LLMMessage) -> LLMMessage:
    """Convert old-format LLMMessage to new format.

    Old format:
    - role: str
    - content: Any (could be str, list of blocks, or Message object)

    New format:
    - role: Literal[...]
    - content: Optional[str]
    - tool_calls: Optional[List[ToolCallBlock]]
    - tool_call_id: Optional[str]
    - name: Optional[str]

    Args:
        message: Old-format LLMMessage

    Returns:
        New-format LLMMessage
    """
    role = message.role
    content = message.content

    # Extract text content
    text_content = extract_text(content) if content else None

    # For empty string, use None
    if text_content == "":
        text_content = None

    # Extract tool calls if present
    tool_calls = extract_tool_calls_from_content(content) if content else None

    # Handle tool result messages (old Anthropic format)
    tool_call_id = None
    name = None

    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                tool_call_id = block.get("tool_use_id")
                # In old format, tool results don't have name
                # Try to extract from content if possible
                text_content = block.get("content", "")
                role = "tool"  # Convert to OpenAI tool role
                break

    return LLMMessage(
        role=role,  # type: ignore
        content=text_content,
        tool_calls=tool_calls if tool_calls else None,
        tool_call_id=tool_call_id,
        name=name,
    )


def _convert_raw_message(message: Any) -> LLMMessage:
    """Convert a raw message object from provider to LLMMessage.

    Args:
        message: Raw message object (e.g., from LiteLLM response)

    Returns:
        LLMMessage
    """
    role = getattr(message, "role", "assistant")
    content = getattr(message, "content", None)

    # Extract text
    text_content = extract_text(content) if content else None
    if text_content == "":
        text_content = None

    # Extract tool calls
    tool_calls = None
    if hasattr(message, "tool_calls") and message.tool_calls:
        tool_calls = extract_tool_calls_from_content(message)

    return LLMMessage(
        role=role,  # type: ignore
        content=text_content,
        tool_calls=tool_calls,
    )


def normalize_stop_reason(reason: str) -> str:
    """Normalize stop reason to OpenAI format.

    Args:
        reason: Stop reason in any format (Anthropic or OpenAI)

    Returns:
        Normalized stop reason
    """
    return StopReason.normalize(reason)


def convert_tool_results_to_messages(
    results: List[Dict[str, Any]],
) -> List[LLMMessage]:
    """Convert tool results from old Anthropic format to new message format.

    Old format (single message with list of tool_result blocks):
    LLMMessage(role="user", content=[
        {"type": "tool_result", "tool_use_id": "...", "content": "..."},
        ...
    ])

    New format (one message per tool result):
    [
        LLMMessage(role="tool", content="...", tool_call_id="...", name="..."),
        ...
    ]

    Args:
        results: List of tool result dicts in Anthropic format

    Returns:
        List of LLMMessages in OpenAI tool format
    """
    return [
        LLMMessage(
            role="tool",
            content=result.get("content", ""),
            tool_call_id=result.get("tool_use_id", ""),
            name=result.get("name"),
        )
        for result in results
        if result.get("type") == "tool_result"
    ]


def format_tool_results_for_api(
    results: List[Dict[str, Any]], use_openai_format: bool = True
) -> Union[LLMMessage, List[LLMMessage]]:
    """Format tool results for API call.

    Args:
        results: List of tool result dicts
        use_openai_format: If True, return list of tool messages (OpenAI format)
                          If False, return single user message (Anthropic format)

    Returns:
        Formatted message(s)
    """
    if use_openai_format:
        return convert_tool_results_to_messages(results)
    else:
        # Old Anthropic format
        return LLMMessage(role="user", content=results)  # type: ignore


def is_new_format_message(message: LLMMessage) -> bool:
    """Check if a message is in the new format.

    New format messages have:
    - content as Optional[str] (not complex types)
    - tool_calls as Optional[List[ToolCallBlock]]

    Args:
        message: LLMMessage to check

    Returns:
        True if new format
    """
    # Check if content is simple (str or None)
    if message.content is not None and not isinstance(message.content, str):
        return False

    # New format messages have tool_calls attribute
    return hasattr(message, "tool_calls")


def migrate_messages(messages: List[LLMMessage]) -> List[LLMMessage]:
    """Migrate a list of messages to new format.

    Args:
        messages: List of messages in any format

    Returns:
        List of messages in new format
    """
    return [ensure_new_format(msg) for msg in messages]
