"""Tests for WebFetchTool."""

import asyncio
import json
import types

import pytest
from requests.structures import CaseInsensitiveDict

from tools.web_fetch import MAX_RESPONSE_BYTES, WebFetchError, WebFetchTool


class FakeResponse:
    def __init__(self, url: str, status_code: int = 200, headers=None, body: bytes = b""):
        self.url = url
        self.status_code = status_code
        self.headers = CaseInsensitiveDict(headers or {})
        self._body = body
        self.encoding = None

    def iter_content(self, chunk_size: int = 65536):
        for idx in range(0, len(self._body), chunk_size):
            yield self._body[idx : idx + chunk_size]

    async def aiter_bytes(self):
        for idx in range(0, len(self._body), 65536):
            yield self._body[idx : idx + 65536]


def parse_result(result: str):
    data = json.loads(result)
    assert "ok" in data
    return data


def build_tool(monkeypatch, responses):
    tool = WebFetchTool()

    async def fake_request(self, client, url, headers, timeout):
        if url not in responses:
            raise AssertionError(f"Unexpected URL: {url}")
        response = responses[url]
        content_length = response.headers.get("content-length")
        if content_length and int(content_length) > MAX_RESPONSE_BYTES:
            raise WebFetchError(
                "too_large",
                "Response too large (exceeds 5MB limit)",
                {"content_length": int(content_length)},
            )
        return response, response._body

    async def fake_resolve_host(_self, _host, _port):
        return ["93.184.216.34"]

    monkeypatch.setattr(tool, "_request", types.MethodType(fake_request, tool))
    monkeypatch.setattr(tool, "_resolve_host", types.MethodType(fake_resolve_host, tool))
    return tool


def test_invalid_url_requires_scheme():
    tool = WebFetchTool()
    result = parse_result(asyncio.run(tool.execute(url="example.com")))
    assert result["ok"] is False
    assert result["error_code"] == "invalid_url"


def test_blocked_localhost():
    tool = WebFetchTool()
    result = parse_result(asyncio.run(tool.execute(url="http://localhost")))
    assert result["ok"] is False
    assert result["error_code"] == "blocked_host"


def test_blocked_ip_literal():
    tool = WebFetchTool()
    result = parse_result(asyncio.run(tool.execute(url="http://127.0.0.1")))
    assert result["ok"] is False
    assert result["error_code"] == "blocked_ip"


def test_redirect_blocked(monkeypatch):
    responses = {
        "http://example.com": FakeResponse(
            "http://example.com",
            status_code=302,
            headers={"location": "http://127.0.0.1"},
        )
    }
    tool = build_tool(monkeypatch, responses)
    result = parse_result(asyncio.run(tool.execute(url="http://example.com")))
    assert result["ok"] is False
    assert result["error_code"] == "redirect_blocked"


def test_too_large(monkeypatch):
    responses = {
        "http://example.com": FakeResponse(
            "http://example.com",
            status_code=200,
            headers={"content-length": str(MAX_RESPONSE_BYTES + 1)},
            body=b"A" * 10,
        )
    }
    tool = build_tool(monkeypatch, responses)
    result = parse_result(asyncio.run(tool.execute(url="http://example.com", format="text")))
    assert result["ok"] is False
    assert result["error_code"] == "too_large"


def test_html_markdown_success(monkeypatch):
    html = "<html><head><title>Title</title></head><body><h1>Title</h1><p>Hello</p></body></html>"
    responses = {
        "http://example.com": FakeResponse(
            "http://example.com",
            status_code=200,
            headers={"content-type": "text/html; charset=utf-8"},
            body=html.encode("utf-8"),
        )
    }
    tool = build_tool(monkeypatch, responses)
    result = parse_result(asyncio.run(tool.execute(url="http://example.com", format="markdown")))
    assert result["ok"] is True
    assert "Title" in result["output"]


@pytest.mark.parametrize("format_value", ["markdown", "text", "html"])
def test_format_variants(monkeypatch, format_value):
    html = "<html><body><p>Content</p></body></html>"
    responses = {
        "http://example.com": FakeResponse(
            "http://example.com",
            status_code=200,
            headers={"content-type": "text/html; charset=utf-8"},
            body=html.encode("utf-8"),
        )
    }
    tool = build_tool(monkeypatch, responses)
    result = parse_result(asyncio.run(tool.execute(url="http://example.com", format=format_value)))
    assert result["ok"] is True
