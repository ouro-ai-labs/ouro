"""OpenAI Codex subscription adapter backed by ChatGPT OAuth.

The ChatGPT subscription Codex endpoint is Responses-compatible but is not
covered by LiteLLM's ChatGPT provider catalog. This adapter keeps the runtime
surface in ouro's standard LLMMessage/LLMResponse types while using the
subscription endpoint directly.
"""

from __future__ import annotations

import base64
import json
import platform
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ouro.core.log import get_logger

from .content_utils import extract_text
from .message_types import LLMMessage, LLMResponse, StopReason, ToolCall, ToolCallBlock, ToolResult
from .retry import with_retry

logger = get_logger(__name__)

DEFAULT_CODEX_BASE_URL = "https://chatgpt.com/backend-api"
JWT_CLAIM_PATH = "https://api.openai.com/auth"


class OpenAICodexAdapter:
    """Adapter for ChatGPT subscription models exposed as openai-codex/*."""

    def __init__(self, model: str, **kwargs: Any):
        self.model = model
        self.model_name = model.split("/", 1)[1] if "/" in model else model
        self.api_base = kwargs.pop("api_base", None)
        self.timeout = kwargs.pop("timeout", 600)
        self._extra_kwargs = kwargs
        logger.info(f"Initialized OpenAI Codex adapter for model: {model}")

    async def call_async(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        token = await self._ensure_access_token()
        account_id = _extract_account_id(token)
        body = self._build_request_body(messages, tools, max_tokens, **kwargs)
        events = await self._request_events(token=token, account_id=account_id, body=body)
        return _convert_response_events(events)

    async def _ensure_access_token(self) -> str:
        from .chatgpt_auth import ChatGPTLoginRequiredError, ensure_chatgpt_access_token

        try:
            return await ensure_chatgpt_access_token(interactive=False)
        except ChatGPTLoginRequiredError as e:
            raise RuntimeError(
                "ChatGPT is not logged in (or your session expired). "
                "Run `/login` to authenticate."
            ) from e

    def _build_request_body(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None,
        max_tokens: int | None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        instructions, input_items = self._convert_messages(messages)
        body: dict[str, Any] = {
            "model": self.model_name,
            "store": False,
            "stream": True,
            "instructions": instructions or "You are a helpful assistant.",
            "input": input_items,
            "text": {"verbosity": kwargs.pop("text_verbosity", "low")},
            "include": ["reasoning.encrypted_content"],
            "tool_choice": "auto",
            "parallel_tool_calls": True,
        }
        if max_tokens is not None:
            body["max_output_tokens"] = max_tokens
        if tools:
            body["tools"] = self._convert_tools(tools)
        if "temperature" in kwargs:
            body["temperature"] = kwargs.pop("temperature")
        if "reasoning_effort" in kwargs:
            body["reasoning"] = {
                "effort": kwargs.pop("reasoning_effort"),
                "summary": kwargs.pop("reasoning_summary", "auto"),
            }
        if "service_tier" in kwargs:
            body["service_tier"] = kwargs.pop("service_tier")

        body.update(kwargs)
        return body

    def _convert_messages(self, messages: list[LLMMessage]) -> tuple[str, list[dict[str, Any]]]:
        instructions: list[str] = []
        input_items: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == "system":
                instructions.append(_message_text(msg))
            elif msg.role == "user":
                input_items.append(
                    {
                        "role": "user",
                        "content": _responses_input_content(msg.content),
                    }
                )
            elif msg.role == "assistant":
                if msg.content:
                    input_items.append(
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": _message_text(msg),
                                    "annotations": [],
                                }
                            ],
                            "status": "completed",
                            "id": f"msg_{uuid.uuid4().hex[:24]}",
                        }
                    )
                for tool_call in msg.tool_calls or []:
                    call_id, item_id = _split_tool_call_id(tool_call["id"])
                    input_items.append(
                        {
                            "type": "function_call",
                            "id": item_id,
                            "call_id": call_id,
                            "name": tool_call["function"]["name"],
                            "arguments": tool_call["function"]["arguments"],
                        }
                    )
            elif msg.role == "tool":
                call_id, _ = _split_tool_call_id(msg.tool_call_id or "")
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": _message_text(msg),
                    }
                )

        return "\n\n".join(part for part in instructions if part), input_items

    def _convert_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["input_schema"],
            }
            for tool in tools
        ]

    @with_retry()
    async def _request_events(
        self,
        *,
        token: str,
        account_id: str,
        body: dict[str, Any],
    ) -> list[dict[str, Any]]:
        headers = _build_sse_headers(token=token, account_id=account_id)
        timeout = httpx.Timeout(float(self.timeout))
        events: list[dict[str, Any]] = []
        async with (
            httpx.AsyncClient(timeout=timeout) as client,
            client.stream(
                "POST",
                _resolve_codex_url(self.api_base),
                headers=headers,
                json=body,
            ) as response,
        ):
            if response.status_code >= 400:
                raise RuntimeError(await _format_error_response(response))
            events.extend([event async for event in _iter_sse_events(response)])
        return events

    def extract_text(self, response: LLMResponse) -> str:
        return response.content or ""

    def extract_tool_calls(self, response: LLMResponse) -> list[ToolCall]:
        if not response.tool_calls:
            return []

        tool_calls: list[ToolCall] = []
        for tc in response.tool_calls:
            try:
                arguments = json.loads(tc["function"]["arguments"])
            except (json.JSONDecodeError, KeyError):
                arguments = {}

            tool_calls.append(
                ToolCall(
                    id=tc["id"],
                    name=tc["function"]["name"],
                    arguments=arguments,
                )
            )
        return tool_calls

    def extract_thinking(self, response: LLMResponse) -> str | None:
        return response.thinking

    def format_tool_results(self, results: list[ToolResult]) -> list[LLMMessage]:
        return [
            LLMMessage(
                role="tool",
                content=result.content,
                tool_call_id=result.tool_call_id,
                name=result.name,
            )
            for result in results
        ]

    @property
    def supports_tools(self) -> bool:
        return True

    @property
    def provider_name(self) -> str:
        return "OPENAI-CODEX"


def _message_text(msg: LLMMessage) -> str:
    if isinstance(msg.content, str):
        return msg.content
    return extract_text(msg.content)


def _responses_input_content(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, list):
        out: list[dict[str, Any]] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text":
                out.append({"type": "input_text", "text": str(block.get("text", ""))})
            elif block_type == "image_url":
                image = block.get("image_url")
                image_url = image.get("url") if isinstance(image, dict) else image
                if image_url:
                    out.append(
                        {
                            "type": "input_image",
                            "detail": "auto",
                            "image_url": str(image_url),
                        }
                    )
        if out:
            return out
    return [{"type": "input_text", "text": extract_text(content)}]


def _split_tool_call_id(tool_call_id: str) -> tuple[str, str | None]:
    if "|" not in tool_call_id:
        return tool_call_id, None
    call_id, item_id = tool_call_id.split("|", 1)
    return call_id, item_id or None


def _extract_account_id(token: str) -> str:
    try:
        parts = token.split(".")
        if len(parts) < 2:
            raise ValueError("invalid JWT")
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8"))
        account_id = payload.get(JWT_CLAIM_PATH, {}).get("chatgpt_account_id")
    except Exception as e:
        raise RuntimeError("Failed to extract ChatGPT account ID from access token.") from e
    if not isinstance(account_id, str) or not account_id:
        raise RuntimeError("ChatGPT account ID is missing from access token.")
    return account_id


def _build_sse_headers(*, token: str, account_id: str) -> dict[str, str]:
    request_id = str(uuid.uuid4())
    return {
        "Authorization": f"Bearer {token}",
        "chatgpt-account-id": account_id,
        "originator": "ouro",
        "User-Agent": f"ouro ({platform.system()} {platform.release()}; {platform.machine()})",
        "OpenAI-Beta": "responses=experimental",
        "accept": "text/event-stream",
        "content-type": "application/json",
        "session-id": request_id,
        "x-client-request-id": request_id,
    }


def _resolve_codex_url(base_url: str | None) -> str:
    raw = base_url.strip() if base_url else DEFAULT_CODEX_BASE_URL
    normalized = raw.rstrip("/")
    if normalized.endswith("/codex/responses"):
        return normalized
    if normalized.endswith("/codex"):
        return f"{normalized}/responses"
    return f"{normalized}/codex/responses"


async def _iter_sse_events(response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
    buffer = ""
    async for chunk in response.aiter_text():
        buffer += chunk
        while "\n\n" in buffer:
            raw_event, buffer = buffer.split("\n\n", 1)
            data_lines = [
                line.removeprefix("data:").strip()
                for line in raw_event.splitlines()
                if line.startswith("data:")
            ]
            data = "\n".join(data_lines).strip()
            if not data or data == "[DONE]":
                continue
            event = json.loads(data)
            if isinstance(event, dict):
                yield event


async def _format_error_response(response: httpx.Response) -> str:
    text = await response.aread()
    try:
        payload = json.loads(text.decode("utf-8"))
    except Exception:
        return f"Codex request failed with HTTP {response.status_code}: {text.decode('utf-8')}"
    message = payload.get("detail") or payload.get("message") or payload.get("error") or payload
    return f"Codex request failed with HTTP {response.status_code}: {message}"


def _convert_response_events(events: list[dict[str, Any]]) -> LLMResponse:
    text_parts: list[str] = []
    current_text_parts: list[str] = []
    thinking_parts: list[str] = []
    tool_calls: list[ToolCallBlock] = []
    current_tool: dict[str, Any] | None = None
    current_tool_args = ""
    usage: dict[str, int] | None = None
    stop_reason = StopReason.STOP

    for event in events:
        event_type = event.get("type")
        if event_type == "error":
            raise RuntimeError(str(event.get("message") or event))
        if event_type == "response.failed":
            response = _dict_value(event, "response")
            error = _dict_value(response, "error")
            raise RuntimeError(str(error.get("message") or error.get("code") or event))
        if event_type == "response.output_item.added":
            item = _dict_value(event, "item")
            if item.get("type") == "message":
                current_text_parts = []
            if item.get("type") == "function_call":
                current_tool = item
                current_tool_args = str(item.get("arguments") or "")
        elif event_type == "response.output_text.delta":
            current_text_parts.append(str(event.get("delta") or ""))
        elif event_type in {
            "response.reasoning_summary_text.delta",
            "response.reasoning_text.delta",
        }:
            thinking_parts.append(str(event.get("delta") or ""))
        elif event_type == "response.function_call_arguments.delta":
            current_tool_args += str(event.get("delta") or "")
        elif event_type == "response.function_call_arguments.done":
            current_tool_args = str(event.get("arguments") or current_tool_args)
        elif event_type == "response.output_item.done":
            item = _dict_value(event, "item")
            item_type = item.get("type")
            if item_type == "message":
                item_text_parts = _extract_output_text_from_item(item)
                text_parts.extend(item_text_parts or current_text_parts)
                current_text_parts = []
            elif item_type == "reasoning":
                thinking_parts.extend(_extract_reasoning_from_item(item))
            elif item_type == "function_call":
                source = current_tool if current_tool is not None else item
                arguments = current_tool_args or str(item.get("arguments") or "")
                tool_calls.append(_normalize_codex_tool_call(source, arguments))
                current_tool = None
                current_tool_args = ""
        elif event_type in {"response.completed", "response.done", "response.incomplete"}:
            response = _dict_value(event, "response")
            usage = _normalize_usage(response.get("usage"))
            stop_reason = _map_stop_reason(response.get("status"))

    if tool_calls and stop_reason == StopReason.STOP:
        stop_reason = StopReason.TOOL_CALLS

    text_parts.extend(current_text_parts)
    content = "".join(text_parts) or None
    thinking = "".join(thinking_parts).strip() or None
    return LLMResponse(
        content=content,
        tool_calls=tool_calls or None,
        stop_reason=stop_reason,
        usage=usage,
        thinking=thinking,
    )


def _dict_value(mapping: dict[str, Any], key: str) -> dict[str, Any]:
    value = mapping.get(key)
    return value if isinstance(value, dict) else {}


def _extract_output_text_from_item(item: dict[str, Any]) -> list[str]:
    out: list[str] = []
    content = item.get("content")
    if not isinstance(content, list):
        return out
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "output_text":
            out.append(str(part.get("text") or ""))
        elif part.get("type") == "refusal":
            out.append(str(part.get("refusal") or ""))
    return out


def _extract_reasoning_from_item(item: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key in ("summary", "content"):
        value = item.get(key)
        if isinstance(value, list):
            out.extend(str(part.get("text") or "") for part in value if isinstance(part, dict))
    return out


def _normalize_codex_tool_call(item: dict[str, Any], arguments: str) -> ToolCallBlock:
    call_id = str(item.get("call_id") or item.get("id") or f"call_{uuid.uuid4().hex[:12]}")
    item_id = str(item.get("id") or f"fc_{uuid.uuid4().hex[:12]}")
    return {
        "id": f"{call_id}|{item_id}",
        "type": "function",
        "function": {
            "name": str(item.get("name") or ""),
            "arguments": arguments or "{}",
        },
    }


def _normalize_usage(raw_usage: Any) -> dict[str, int] | None:
    if not isinstance(raw_usage, dict):
        return None
    details = raw_usage.get("input_tokens_details")
    cached = details.get("cached_tokens", 0) if isinstance(details, dict) else 0
    input_tokens = int(raw_usage.get("input_tokens") or 0)
    return {
        "input_tokens": max(0, input_tokens - int(cached or 0)),
        "output_tokens": int(raw_usage.get("output_tokens") or 0),
        "cache_read_tokens": int(cached or 0),
        "cache_creation_tokens": 0,
    }


def _map_stop_reason(status: Any) -> str:
    if status == "incomplete":
        return StopReason.LENGTH
    if status in {"failed", "cancelled"}:
        return "error"
    return StopReason.STOP
