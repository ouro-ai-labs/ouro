import base64
import json

import httpx
import pytest

from ouro.core.llm.message_types import LLMMessage, StopReason
from ouro.core.llm.model_manager import ModelManager, ModelProfile
from ouro.core.llm.openai_codex_adapter import (
    OpenAICodexAdapter,
    _build_sse_headers,
    _convert_response_events,
    _extract_account_id,
    _resolve_codex_url,
)


def _jwt(payload: dict) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"header.{encoded}.signature"


def test_extract_account_id_from_chatgpt_access_token() -> None:
    token = _jwt({"https://api.openai.com/auth": {"chatgpt_account_id": "acct_123"}})

    assert _extract_account_id(token) == "acct_123"


def test_build_sse_headers_include_chatgpt_codex_requirements() -> None:
    headers = _build_sse_headers(token="token", account_id="acct_123")

    assert headers["Authorization"] == "Bearer token"
    assert headers["chatgpt-account-id"] == "acct_123"
    assert headers["OpenAI-Beta"] == "responses=experimental"
    assert headers["accept"] == "text/event-stream"
    assert headers["content-type"] == "application/json"
    assert headers["originator"] == "ouro"
    assert headers["session-id"]
    assert headers["x-client-request-id"] == headers["session-id"]


def test_resolve_codex_url_normalizes_base_url() -> None:
    assert _resolve_codex_url(None) == "https://chatgpt.com/backend-api/codex/responses"
    assert (
        _resolve_codex_url("https://chatgpt.com/backend-api")
        == "https://chatgpt.com/backend-api/codex/responses"
    )
    assert (
        _resolve_codex_url("https://chatgpt.com/backend-api/codex")
        == "https://chatgpt.com/backend-api/codex/responses"
    )
    assert (
        _resolve_codex_url("https://chatgpt.com/backend-api/codex/responses")
        == "https://chatgpt.com/backend-api/codex/responses"
    )


def test_build_request_body_uses_responses_protocol() -> None:
    adapter = OpenAICodexAdapter("openai-codex/gpt-5.5")
    body = adapter._build_request_body(
        [
            LLMMessage(role="system", content="Be brief."),
            LLMMessage(role="user", content="Call a tool."),
        ],
        tools=[
            {
                "name": "lookup",
                "description": "Look up a value",
                "input_schema": {"type": "object", "properties": {}},
            }
        ],
        max_tokens=123,
    )

    assert body["model"] == "gpt-5.5"
    assert body["stream"] is True
    assert body["store"] is False
    assert body["instructions"] == "Be brief."
    assert "max_output_tokens" not in body
    assert body["input"] == [
        {"role": "user", "content": [{"type": "input_text", "text": "Call a tool."}]}
    ]
    assert body["tools"] == [
        {
            "type": "function",
            "name": "lookup",
            "description": "Look up a value",
            "parameters": {"type": "object", "properties": {}},
        }
    ]


def test_build_request_body_drops_unsupported_max_output_tokens_kwarg() -> None:
    adapter = OpenAICodexAdapter("openai-codex/gpt-5.5")
    body = adapter._build_request_body(
        [LLMMessage(role="user", content="hello")],
        tools=None,
        max_tokens=None,
        max_output_tokens=123,
    )

    assert "max_output_tokens" not in body


def test_convert_response_events_extracts_text_tool_calls_and_usage() -> None:
    response = _convert_response_events(
        [
            {"type": "response.output_text.delta", "delta": "Hello"},
            {
                "type": "response.output_item.added",
                "item": {
                    "type": "function_call",
                    "id": "fc_123",
                    "call_id": "call_123",
                    "name": "lookup",
                    "arguments": "",
                },
            },
            {"type": "response.function_call_arguments.delta", "delta": '{"q"'},
            {"type": "response.function_call_arguments.done", "arguments": '{"q":"x"}'},
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "function_call",
                    "id": "fc_123",
                    "call_id": "call_123",
                    "name": "lookup",
                    "arguments": '{"q":"x"}',
                },
            },
            {
                "type": "response.completed",
                "response": {
                    "status": "completed",
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 3,
                        "input_tokens_details": {"cached_tokens": 4},
                    },
                },
            },
        ]
    )

    assert response.content == "Hello"
    assert response.stop_reason == StopReason.TOOL_CALLS
    assert response.tool_calls == [
        {
            "id": "call_123|fc_123",
            "type": "function",
            "function": {"name": "lookup", "arguments": '{"q":"x"}'},
        }
    ]
    assert response.usage == {
        "input_tokens": 6,
        "output_tokens": 3,
        "cache_read_tokens": 4,
        "cache_creation_tokens": 0,
    }


def test_convert_response_events_prefers_done_text_over_duplicate_deltas() -> None:
    response = _convert_response_events(
        [
            {
                "type": "response.output_item.added",
                "item": {"type": "message"},
            },
            {"type": "response.output_text.delta", "delta": "Hel"},
            {"type": "response.output_text.delta", "delta": "lo"},
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Hello",
                        }
                    ],
                },
            },
            {"type": "response.completed", "response": {"status": "completed"}},
        ]
    )

    assert response.content == "Hello"


def test_openai_codex_model_does_not_require_api_key(tmp_path) -> None:
    manager = ModelManager(config_path=str(tmp_path / "models.yaml"))
    valid, message = manager.validate_model(ModelProfile(model_id="openai-codex/gpt-5.5"))

    assert valid is True
    assert message == ""


async def test_call_async_formats_codex_request_errors(monkeypatch) -> None:
    adapter = OpenAICodexAdapter("openai-codex/gpt-5.5")
    token = _jwt({"https://api.openai.com/auth": {"chatgpt_account_id": "acct_123"}})

    async def fake_access_token() -> str:
        return token

    async def fake_request_events(**_kwargs):
        raise httpx.ConnectError("")

    monkeypatch.setattr(adapter, "_ensure_access_token", fake_access_token)
    monkeypatch.setattr(adapter, "_request_events", fake_request_events)

    with pytest.raises(RuntimeError) as exc_info:
        await adapter.call_async([LLMMessage(role="user", content="hello")])

    message = str(exc_info.value)
    assert "Unable to connect to the ChatGPT Codex endpoint" in message
    assert "https://chatgpt.com/backend-api/codex/responses" in message
    assert "proxy/VPN" in message
    assert isinstance(exc_info.value.__cause__, httpx.ConnectError)
