"""Tests for stale-detection via ReadBeforeWriteRule (mtime + content hash).

Stale detection now lives in ``ReadBeforeWriteRule`` rather than
``SmartEditTool``.  When a file is read, ``FileReadTool`` returns a
``ToolOutput`` with ``metadata={"snapshot": {"mtime": ..., "hash": ...}}``.
The rule stores this snapshot and checks it before allowing any
``smart_edit`` / ``write_file`` on the same path.
"""

from __future__ import annotations

import asyncio
import logging

from ouro.capabilities.rules.read_before_write import (
    ReadBeforeWriteRule,
    _check_stale,
    _content_hash,
)
from ouro.core.llm.message_types import ToolResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class FakeLoopContext:
    """Minimal stand-in for LoopContext."""

    def __init__(self):
        self.task = "test"
        self.iteration = 1
        self.usage_total = {}
        self.stop_reason_last = None

    def add_usage(self, usage):
        pass


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
# _check_stale
# ---------------------------------------------------------------------------


def test_check_stale_mtime_unchanged(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    stat = f.stat()
    assert _check_stale(str(f), stat.st_mtime, _content_hash("x = 1\n")) is None


def test_check_stale_mtime_noise_content_same(tmp_path):
    """mtime drift but content identical → not stale (OS noise)."""
    f = tmp_path / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    stat = f.stat()
    import time

    time.sleep(0.01)
    f.write_text("x = 1\n", encoding="utf-8")
    assert _check_stale(str(f), stat.st_mtime, _content_hash("x = 1\n")) is None


def test_check_stale_real_modification(tmp_path):
    """Content actually changed → stale."""
    f = tmp_path / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    stat = f.stat()
    import time

    time.sleep(0.01)
    f.write_text("x = 2\n", encoding="utf-8")
    msg = _check_stale(str(f), stat.st_mtime, _content_hash("x = 1\n"))
    assert msg is not None
    assert "modified on disk" in msg


def test_check_stale_file_vanished(tmp_path):
    """File deleted after read → let write fail naturally, not stale."""
    f = tmp_path / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    stat = f.stat()
    f.unlink()
    assert _check_stale(str(f), stat.st_mtime, _content_hash("x = 1\n")) is None


# ---------------------------------------------------------------------------
# ReadBeforeWriteRule stale integration
# ---------------------------------------------------------------------------


class FakeToolCall:
    def __init__(self, name, file_path):
        self.name = name
        self.arguments = {"file_path": str(file_path)}
        self.id = "tc-1"


def test_rule_blocks_stale_edit_without_warning_log(tmp_path, caplog):
    """If the file changed after read, before_toolcall blocks the edit quietly."""
    rule = ReadBeforeWriteRule()
    ctx = FakeLoopContext()

    f = tmp_path / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    stat = f.stat()

    # Simulate read_file returning a snapshot
    read_tc = FakeToolCall("read_file", f)
    read_result = ToolResult(
        tool_call_id="tc-1",
        content="x = 1\n",
        metadata={
            "snapshot": {
                "mtime": stat.st_mtime,
                "hash": _content_hash("x = 1\n"),
            }
        },
    )
    rule.after_toolcall(ctx, read_tc, read_result)

    # Modify file behind the rule's back
    f.write_text("x = 2\n", encoding="utf-8")

    # Now try to smart_edit — should be blocked as stale, but not logged as a warning.
    edit_tc = FakeToolCall("smart_edit", f)
    with caplog.at_level(logging.WARNING):
        msg = rule.before_toolcall(ctx, edit_tc)
    assert msg is not None
    assert "modified on disk" in msg
    assert "blocked smart_edit on stale file" not in caplog.text


def test_rule_allows_fresh_edit(tmp_path):
    """If the file hasn't changed, edit is allowed."""
    rule = ReadBeforeWriteRule()
    ctx = FakeLoopContext()

    f = tmp_path / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    stat = f.stat()

    read_tc = FakeToolCall("read_file", f)
    read_result = ToolResult(
        tool_call_id="tc-1",
        content="x = 1\n",
        metadata={
            "snapshot": {
                "mtime": stat.st_mtime,
                "hash": _content_hash("x = 1\n"),
            }
        },
    )
    rule.after_toolcall(ctx, read_tc, read_result)

    # No modification — edit should pass stale check
    edit_tc = FakeToolCall("smart_edit", f)
    assert rule.before_toolcall(ctx, edit_tc) is None


def test_rule_allows_after_write(tmp_path):
    """Writing a file clears the snapshot and allows subsequent edits."""
    rule = ReadBeforeWriteRule()
    ctx = FakeLoopContext()

    f = tmp_path / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")

    # Simulate write_file (no snapshot metadata)
    write_tc = FakeToolCall("write_file", f)
    write_result = ToolResult(tool_call_id="tc-1", content="ok")
    rule.after_toolcall(ctx, write_tc, write_result)

    # Edit should be allowed without stale check
    edit_tc = FakeToolCall("smart_edit", f)
    assert rule.before_toolcall(ctx, edit_tc) is None


def test_rule_resets_per_run(tmp_path):
    """A new run context clears all state."""
    rule = ReadBeforeWriteRule()
    ctx1 = FakeLoopContext()

    f = tmp_path / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    stat = f.stat()

    read_tc = FakeToolCall("read_file", f)
    read_result = ToolResult(
        tool_call_id="tc-1",
        content="x = 1\n",
        metadata={
            "snapshot": {
                "mtime": stat.st_mtime,
                "hash": _content_hash("x = 1\n"),
            }
        },
    )
    rule.after_toolcall(ctx1, read_tc, read_result)

    # New run
    ctx2 = FakeLoopContext()
    edit_tc = FakeToolCall("smart_edit", f)
    # Should be blocked because state was reset
    msg = rule.before_toolcall(ctx2, edit_tc)
    assert msg is not None
    assert "have not read it" in msg
