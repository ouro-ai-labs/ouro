"""Centralized content extraction utilities for LLM messages.

This module consolidates all content extraction logic that was previously
scattered across litellm_adapter.py, compressor.py, and token_tracker.py.
"""

from typing import Any, List, Optional

from .message_types import LLMMessage, ToolCallBlock


def extract_text(content: Any) -> str:
    """Extract text content from any message format.

    Handles:
    - String content
    - Message objects with .content attribute
    - List of content blocks (Anthropic format)
    - Dict content blocks

    Args:
        content: Content in any supported format

    Returns:
        Extracted text as string
    """
    if content is None:
        return ""

    if isinstance(content, str):
        return content

    # Handle Message objects (from previous LLM responses)
    if hasattr(content, "content"):
        return extract_text(content.content)

    # Handle list of content blocks
    if isinstance(content, list):
        texts = []
        for block in content:
            text = _extract_text_from_block(block)
            if text:
                texts.append(text)
        return "\n".join(texts) if texts else ""

    # Handle dict content block
    if isinstance(content, dict):
        return _extract_text_from_block(content)

    # Fallback: convert to string
    return str(content)


def _extract_text_from_block(block: Any) -> str:
    """Extract text from a single content block.

    Args:
        block: Content block (dict or object)

    Returns:
        Text content or empty string
    """
    # Handle dict format
    if isinstance(block, dict):
        if block.get("type") == "text":
            return block.get("text", "")
        if "text" in block:
            return block["text"]
        # For tool_use/tool_result, don't include in text extraction
        if block.get("type") in ("tool_use", "tool_result"):
            return ""
        return ""

    # Handle object format (ContentBlock from Anthropic SDK)
    if hasattr(block, "text"):
        return block.text

    if hasattr(block, "type") and block.type == "text":
        return getattr(block, "text", "")

    return ""


def extract_text_from_message(message: LLMMessage) -> str:
    """Extract text content from an LLMMessage.

    For new-format messages, returns the content directly.
    For old-format messages with complex content, extracts text.

    Args:
        message: LLMMessage instance

    Returns:
        Text content
    """
    if message.content is None:
        return ""

    if isinstance(message.content, str):
        return message.content

    # Handle legacy complex content
    return extract_text(message.content)


def extract_tool_calls_from_content(content: Any) -> List[ToolCallBlock]:
    """Extract tool calls from message content.

    Handles both OpenAI format (tool_calls field) and Anthropic format
    (tool_use blocks in content).

    Args:
        content: Message content in any format

    Returns:
        List of tool calls in OpenAI/LiteLLM format
    """
    tool_calls: List[ToolCallBlock] = []

    # Handle Message objects
    if hasattr(content, "tool_calls") and content.tool_calls:
        for tc in content.tool_calls:
            tool_call = _normalize_tool_call(tc)
            if tool_call:
                tool_calls.append(tool_call)
        return tool_calls

    # Handle list of content blocks (Anthropic format)
    if isinstance(content, list):
        for block in content:
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_use"
                or hasattr(block, "type")
                and block.type == "tool_use"
            ):
                tool_call = _anthropic_to_openai_tool_call(block)
                if tool_call:
                    tool_calls.append(tool_call)

    return tool_calls


def _normalize_tool_call(tc: Any) -> Optional[ToolCallBlock]:
    """Normalize a tool call to OpenAI format.

    Args:
        tc: Tool call in any format

    Returns:
        ToolCallBlock in OpenAI format or None
    """
    import json

    # Already in OpenAI dict format
    if isinstance(tc, dict):
        if "function" in tc:
            return tc  # type: ignore
        # Anthropic format in dict
        if tc.get("type") == "tool_use":
            return _anthropic_to_openai_tool_call(tc)

    # OpenAI object format (from LiteLLM)
    if hasattr(tc, "function") and hasattr(tc, "id"):
        arguments = tc.function.arguments
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments)

        return {
            "id": tc.id,
            "type": "function",
            "function": {
                "name": tc.function.name,
                "arguments": arguments,
            },
        }

    # Anthropic object format
    if hasattr(tc, "type") and tc.type == "tool_use":
        return _anthropic_to_openai_tool_call(tc)

    return None


def _anthropic_to_openai_tool_call(block: Any) -> Optional[ToolCallBlock]:
    """Convert Anthropic tool_use block to OpenAI format.

    Args:
        block: Anthropic tool_use block (dict or object)

    Returns:
        ToolCallBlock in OpenAI format or None
    """
    import json

    if isinstance(block, dict):
        tool_id = block.get("id", "")
        name = block.get("name", "")
        input_data = block.get("input", {})
    else:
        tool_id = getattr(block, "id", "")
        name = getattr(block, "name", "")
        input_data = getattr(block, "input", {})

    if not tool_id or not name:
        return None

    # Convert input to JSON string
    arguments = input_data if isinstance(input_data, str) else json.dumps(input_data)

    return {
        "id": tool_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": arguments,
        },
    }


def message_to_dict(message: LLMMessage) -> dict:
    """Convert LLMMessage to dictionary for API calls.

    This is a convenience wrapper around message.to_dict() that also
    handles legacy message formats.

    Args:
        message: LLMMessage instance

    Returns:
        Dictionary in OpenAI format
    """
    # Use the new to_dict if available
    if hasattr(message, "to_dict"):
        return message.to_dict()

    # Legacy format
    result = {"role": message.role}

    if message.content is not None:
        if isinstance(message.content, str):
            result["content"] = message.content
        else:
            # Extract text from complex content
            result["content"] = extract_text(message.content)

    return result


def content_has_tool_calls(content: Any) -> bool:
    """Check if content contains tool calls.

    Args:
        content: Message content in any format

    Returns:
        True if contains tool calls
    """
    # Check for tool_calls field
    if hasattr(content, "tool_calls") and content.tool_calls:
        return True

    # Check for tool_use blocks in list
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") in ("tool_use", "tool_calls"):
                return True
            if hasattr(block, "type") and block.type in ("tool_use", "tool_calls"):
                return True

    return False


def content_has_tool_results(content: Any) -> bool:
    """Check if content contains tool results.

    Args:
        content: Message content in any format

    Returns:
        True if contains tool results
    """
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "tool_result":
                    return True
            elif hasattr(block, "type") and block.type == "tool_result":
                return True

    return False


def estimate_tokens(content: Any) -> int:
    """Estimate token count for content.

    Uses a simple character-based estimation:
    ~3.5 characters per token for mixed content.

    Args:
        content: Content to estimate

    Returns:
        Estimated token count
    """
    text = extract_text(content)
    if not text:
        return 0
    return max(1, int(len(text) / 3.5))
