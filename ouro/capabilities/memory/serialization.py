"""Shared serialization logic for memory persistence.

Provides serialize/deserialize functions for LLMMessage objects,
used by all persistence backends.
"""

import json
from typing import Any, Dict

from llm.message_types import LLMMessage


def serialize_content(content: Any) -> Any:
    """Serialize message content, handling complex objects.

    Args:
        content: Message content (can be string, list, dict, or None)

    Returns:
        JSON-serializable content
    """
    if content is None:
        return None
    elif isinstance(content, str):
        return content
    elif isinstance(content, (list, dict)):
        try:
            json.dumps(content)
            return content
        except (TypeError, ValueError):
            return str(content)
    else:
        return str(content)


def serialize_message(message: LLMMessage) -> Dict[str, Any]:
    """Serialize an LLMMessage to a JSON/YAML-serializable dict.

    Args:
        message: LLMMessage to serialize

    Returns:
        Serializable dict
    """
    result: Dict[str, Any] = {
        "role": message.role,
        "content": serialize_content(message.content),
    }

    # For assistant messages, always include tool_calls (even if None) for completeness
    if message.role == "assistant":
        result["tool_calls"] = (
            message.tool_calls if (hasattr(message, "tool_calls") and message.tool_calls) else None
        )
    elif hasattr(message, "tool_calls") and message.tool_calls:
        result["tool_calls"] = message.tool_calls

    if hasattr(message, "tool_call_id") and message.tool_call_id:
        result["tool_call_id"] = message.tool_call_id

    if hasattr(message, "name") and message.name:
        result["name"] = message.name

    return result


def deserialize_message(data: Dict[str, Any]) -> LLMMessage:
    """Deserialize a dict to an LLMMessage.

    Args:
        data: Dict with message data

    Returns:
        LLMMessage instance
    """
    return LLMMessage(
        role=data["role"],
        content=data.get("content"),
        tool_calls=data.get("tool_calls"),
        tool_call_id=data.get("tool_call_id"),
        name=data.get("name"),
    )
