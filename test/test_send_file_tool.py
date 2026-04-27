"""Tests for the send_file tool."""

from __future__ import annotations

import os
import tempfile

import pytest

from ouro.capabilities.tools.builtins.send_file_tool import SendFileContext, SendFileTool


@pytest.fixture
def ctx():
    return SendFileContext()


@pytest.fixture
def tool(ctx):
    return SendFileTool(ctx)


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


async def test_relative_path_error(tool):
    result = await tool.execute(file_path="relative/path.txt")
    assert "must be absolute" in result


async def test_nonexistent_file_error(tool):
    result = await tool.execute(file_path="/tmp/nonexistent_file_12345.txt")
    assert "file not found" in result


async def test_file_too_large(tool, tmp_path):
    big_file = tmp_path / "big.bin"
    # Create a file just over 50 MB
    big_file.write_bytes(b"\x00" * (50 * 1024 * 1024 + 1))
    result = await tool.execute(file_path=str(big_file))
    assert "too large" in result


async def test_context_not_set(tool):
    """When send_fn is not set, the tool returns an error."""
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        f.write(b"hello")
        f.flush()
        path = f.name
    try:
        result = await tool.execute(file_path=path)
        assert "failed to send" in result.lower() or "not available" in result.lower()
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# Success tests
# ---------------------------------------------------------------------------


async def test_valid_file_sends(ctx, tool):
    """A valid absolute file path triggers the send callback."""
    sent: list[dict] = []

    async def fake_send(**kwargs):
        sent.append(kwargs)
        return True

    ctx.set_send_fn(fake_send)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"%PDF-1.4 fake")
        f.flush()
        path = f.name
    try:
        result = await tool.execute(file_path=path)
        assert "File sent" in result
        assert len(sent) == 1
        assert sent[0]["file_path"] == path
        assert sent[0]["filename"] == os.path.basename(path)
        assert sent[0]["mime_type"] == "application/pdf"
    finally:
        os.unlink(path)


async def test_filename_defaults_to_basename(ctx, tool):
    """When no filename is given, basename is used."""
    sent: list[dict] = []

    async def fake_send(**kwargs):
        sent.append(kwargs)
        return True

    ctx.set_send_fn(fake_send)

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, prefix="report_") as f:
        f.write(b"a,b,c")
        f.flush()
        path = f.name
    try:
        await tool.execute(file_path=path)
        assert sent[0]["filename"] == os.path.basename(path)
    finally:
        os.unlink(path)


async def test_custom_filename(ctx, tool):
    """Explicit filename overrides basename."""
    sent: list[dict] = []

    async def fake_send(**kwargs):
        sent.append(kwargs)
        return True

    ctx.set_send_fn(fake_send)

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        f.write(b"data")
        f.flush()
        path = f.name
    try:
        result = await tool.execute(file_path=path, filename="custom_name.txt")
        assert "File sent: custom_name.txt" in result
        assert sent[0]["filename"] == "custom_name.txt"
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# SendFileContext tests
# ---------------------------------------------------------------------------


async def test_context_clear():
    ctx = SendFileContext()
    called = False

    async def fn(**kwargs):
        nonlocal called
        called = True
        return True

    ctx.set_send_fn(fn)
    ctx.clear()
    result = await ctx.send(file_path="/tmp/x")
    assert result is False
    assert not called
