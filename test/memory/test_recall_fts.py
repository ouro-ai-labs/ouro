"""Unit tests for the SQLite FTS5 recall index."""

import os

import pytest

from ouro.capabilities.memory.recall.sqlite_fts import RecallIndex, _flatten_content
from ouro.core.llm.message_types import LLMMessage


@pytest.fixture
def index(tmp_path):
    return RecallIndex(memory_dir=str(tmp_path / "memdir"))


class TestFlattenContent:
    def test_string(self):
        assert _flatten_content("hello") == "hello"

    def test_none(self):
        assert _flatten_content(None) == ""

    def test_text_blocks(self):
        content = [
            {"type": "text", "text": "alpha"},
            {"type": "tool_use", "id": "x"},  # no text key — skipped
            {"type": "text", "text": "beta"},
        ]
        assert "alpha" in _flatten_content(content)
        assert "beta" in _flatten_content(content)


class TestEmptyDb:
    async def test_search_on_missing_db(self, index):
        # File does not exist yet — search must return empty, never raise.
        assert not os.path.isfile(index.db_path)
        assert await index.search("anything") == []

    async def test_blank_query_returns_empty(self, index):
        await index.reindex_session("s1", [LLMMessage(role="user", content="hello world")])
        assert await index.search("   ") == []


class TestReindexAndSearch:
    async def test_basic_match(self, index):
        msgs = [
            LLMMessage(role="user", content="I love rust language"),
            LLMMessage(role="assistant", content="Rust is memory-safe."),
            LLMMessage(role="user", content="What about go?"),
        ]
        await index.reindex_session("session-1", msgs)
        hits = await index.search("rust")
        assert len(hits) >= 1
        # Most relevant hit should mention rust
        assert "rust" in hits[0]["content"].lower()

    async def test_scope_by_session(self, index):
        await index.reindex_session("sess-a", [LLMMessage(role="user", content="alpha topic")])
        await index.reindex_session("sess-b", [LLMMessage(role="user", content="alpha topic")])
        scoped = await index.search("alpha", session_id="sess-a")
        assert all(h["session_id"] == "sess-a" for h in scoped)
        assert len(scoped) == 1

        global_hits = await index.search("alpha")
        assert len(global_hits) == 2

    async def test_reindex_replaces_old_rows(self, index):
        await index.reindex_session("s", [LLMMessage(role="user", content="original content")])
        await index.reindex_session("s", [LLMMessage(role="user", content="replaced content")])
        hits = await index.search("original")
        assert hits == []
        hits = await index.search("replaced")
        assert len(hits) == 1

    async def test_empty_content_skipped(self, index):
        await index.reindex_session(
            "s",
            [
                LLMMessage(role="user", content=""),
                LLMMessage(role="user", content="real message"),
            ],
        )
        hits = await index.search("real")
        assert len(hits) == 1
        # idx in stored row is the original list index of the kept message
        assert hits[0]["msg_idx"] == 1

    async def test_malformed_query_returns_empty(self, index):
        await index.reindex_session("s", [LLMMessage(role="user", content="hello world")])
        # Unmatched quote — FTS5 raises OperationalError; tool must swallow.
        assert await index.search('"unterminated') == []

    async def test_add_message_incremental(self, index):
        await index.add_message("s", 0, LLMMessage(role="user", content="incremental write"))
        hits = await index.search("incremental")
        assert len(hits) == 1
        assert hits[0]["msg_idx"] == 0

    async def test_delete_session(self, index):
        await index.reindex_session("s", [LLMMessage(role="user", content="to be deleted")])
        removed = await index.delete_session("s")
        assert removed == 1
        assert await index.search("deleted") == []
