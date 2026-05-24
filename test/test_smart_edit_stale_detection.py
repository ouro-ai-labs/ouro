"""Tests for smart_edit stale-detection (mtime + content hash)."""

from __future__ import annotations

import asyncio

import pytest

from ouro.capabilities.tools.builtins.smart_edit import (
    SmartEditTool,
    _check_stale,
    _content_hash,
    _read_file_with_snapshot,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# _content_hash
# ---------------------------------------------------------------------------


def test_content_hash_deterministic():
    h1 = _content_hash("hello world")
    h2 = _content_hash("hello world")
    assert h1 == h2
    assert len(h1) == 16


def test_content_hash_sensitive():
    assert _content_hash("hello world") != _content_hash("hello world!")


# ---------------------------------------------------------------------------
# _read_file_with_snapshot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_file_with_snapshot(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    content, mtime, hash_val = await _read_file_with_snapshot(f)
    assert content == "x = 1\n"
    assert hash_val == _content_hash("x = 1\n")
    assert isinstance(mtime, float)


# ---------------------------------------------------------------------------
# _check_stale
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_stale_mtime_unchanged(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    content, mtime, hash_val = await _read_file_with_snapshot(f)
    assert await _check_stale(f, mtime, hash_val, content) is None


@pytest.mark.asyncio
async def test_check_stale_mtime_noise_content_same(tmp_path):
    """mtime drift but content identical → not stale (OS noise)."""
    f = tmp_path / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    content, mtime, hash_val = await _read_file_with_snapshot(f)
    # Simulate mtime noise by touching the file with same content
    await asyncio.sleep(0.01)
    f.write_text("x = 1\n", encoding="utf-8")
    assert await _check_stale(f, mtime, hash_val, content) is None


@pytest.mark.asyncio
async def test_check_stale_real_modification(tmp_path):
    """Content actually changed → stale."""
    f = tmp_path / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    content, mtime, hash_val = await _read_file_with_snapshot(f)
    await asyncio.sleep(0.01)
    f.write_text("x = 2\n", encoding="utf-8")
    msg = await _check_stale(f, mtime, hash_val, content)
    assert msg is not None
    assert "modified on disk" in msg
    assert "x = 2" in msg or "x = 1" in msg


@pytest.mark.asyncio
async def test_check_stale_file_vanished(tmp_path):
    """File deleted after read → let write fail naturally, not stale."""
    f = tmp_path / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    content, mtime, hash_val = await _read_file_with_snapshot(f)
    f.unlink()
    assert await _check_stale(f, mtime, hash_val, content) is None


# ---------------------------------------------------------------------------
# SmartEditTool integration with stale detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diff_replace_succeeds_when_fresh(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("def foo():\n    pass\n", encoding="utf-8")
    tool = SmartEditTool()
    result = await tool.execute(
        file_path=str(f),
        mode="diff_replace",
        old_code="    pass",
        new_code="    return 42",
    )
    assert "Successfully edited" in result
    assert "return 42" in f.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_diff_replace_blocked_when_stale(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("def foo():\n    pass\n", encoding="utf-8")
    tool = SmartEditTool()

    # Patch _read_file_with_snapshot to capture the snapshot, then
    # modify the file before the tool writes.
    original_read = _read_file_with_snapshot

    async def _patched_read(path):
        content, mtime, hash_val = await original_read(path)
        # Mutate the file *after* the tool has read it
        f.write_text("def foo():\n    return 0\n", encoding="utf-8")
        await asyncio.sleep(0.01)
        return content, mtime, hash_val

    import ouro.capabilities.tools.builtins.smart_edit as _se

    _se._read_file_with_snapshot = _patched_read
    try:
        result = await tool.execute(
            file_path=str(f),
            mode="diff_replace",
            old_code="    pass",
            new_code="    return 42",
        )
        assert "modified on disk" in result
        # File should NOT have been overwritten
        assert "return 0" in f.read_text(encoding="utf-8")
        assert "return 42" not in f.read_text(encoding="utf-8")
    finally:
        _se._read_file_with_snapshot = original_read


@pytest.mark.asyncio
async def test_smart_insert_blocked_when_stale(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("class A:\n    pass\n", encoding="utf-8")
    tool = SmartEditTool()

    original_read = _read_file_with_snapshot

    async def _patched_read(path):
        content, mtime, hash_val = await original_read(path)
        f.write_text("class A:\n    x = 1\n", encoding="utf-8")
        await asyncio.sleep(0.01)
        return content, mtime, hash_val

    import ouro.capabilities.tools.builtins.smart_edit as _se

    _se._read_file_with_snapshot = _patched_read
    try:
        result = await tool.execute(
            file_path=str(f),
            mode="smart_insert",
            anchor="class A:",
            code="    def run(self): pass",
            position="after",
        )
        assert "modified on disk" in result
    finally:
        _se._read_file_with_snapshot = original_read


@pytest.mark.asyncio
async def test_block_edit_blocked_when_stale(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("line1\nline2\nline3\n", encoding="utf-8")
    tool = SmartEditTool()

    original_read = _read_file_with_snapshot

    async def _patched_read(path):
        content, mtime, hash_val = await original_read(path)
        f.write_text("line1\nmodified\nline3\n", encoding="utf-8")
        await asyncio.sleep(0.01)
        return content, mtime, hash_val

    import ouro.capabilities.tools.builtins.smart_edit as _se

    _se._read_file_with_snapshot = _patched_read
    try:
        result = await tool.execute(
            file_path=str(f),
            mode="block_edit",
            start_line=2,
            end_line=2,
            new_code="replaced",
        )
        assert "modified on disk" in result
    finally:
        _se._read_file_with_snapshot = original_read


@pytest.mark.asyncio
async def test_dry_run_does_not_trigger_stale_check(tmp_path):
    """Dry run should not trigger stale detection (no write happens)."""
    f = tmp_path / "a.py"
    f.write_text("def foo():\n    pass\n", encoding="utf-8")
    tool = SmartEditTool()

    original_read = _read_file_with_snapshot

    async def _patched_read(path):
        content, mtime, hash_val = await original_read(path)
        f.write_text("def foo():\n    return 0\n", encoding="utf-8")
        await asyncio.sleep(0.01)
        return content, mtime, hash_val

    import ouro.capabilities.tools.builtins.smart_edit as _se

    _se._read_file_with_snapshot = _patched_read
    try:
        result = await tool.execute(
            file_path=str(f),
            mode="diff_replace",
            old_code="    pass",
            new_code="    return 42",
            dry_run=True,
        )
        assert "[DRY RUN]" in result
        assert "modified on disk" not in result
    finally:
        _se._read_file_with_snapshot = original_read
