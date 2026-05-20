"""Tests for mem0-backed memory stores and long-term memory adapter.

These tests mock the ``mem0.Memory`` class so they run without the
optional ``mem0ai`` dependency being installed.
"""

from __future__ import annotations

import pytest

from ouro.config import Config
from ouro.core.llm.message_types import LLMMessage
from ouro.core.loop import MessageListContext


# ---------------------------------------------------------------------------
# Fake mem0 implementation
# ---------------------------------------------------------------------------


class FakeMem0Memory:
    """In-memory stand-in for ``mem0.Memory``."""

    def __init__(self, config=None):
        self.config = config or {}
        self._memories: list[dict] = []
        self._counter = 0

    def add(self, text, user_id=None, metadata=None):
        self._counter += 1
        entry = {
            "id": f"mem_{self._counter}",
            "memory": text,
            "user_id": user_id,
            "metadata": metadata or {},
            "created_at": "2026-05-19T12:00:00",
            "updated_at": "2026-05-19T12:00:00",
        }
        self._memories.append(entry)
        return entry

    def search(self, query, filters=None, limit=5):
        # Simple substring match for testing; if query is a generic
        # retrieval phrase (e.g. "session conversation") we treat it
        # as "match all" so load_session / _fetch_memories work.
        GENERIC_QUERIES = {"session conversation", "recent activities preferences decisions"}
        results = []
        for mem in self._memories:
            if filters and filters.get("user_id"):
                if mem.get("user_id") != filters["user_id"]:
                    continue
            if query == "*" or query.lower() in GENERIC_QUERIES or query.lower() in mem["memory"].lower():
                results.append(mem)
        return {"results": results[:limit]}

    def delete(self, memory_id):
        self._memories = [m for m in self._memories if m["id"] != memory_id]

    @classmethod
    def from_config(cls, config):
        return cls(config)


@pytest.fixture(autouse=True)
def _patch_mem0(monkeypatch):
    """Inject fake mem0 so imports succeed without the real package."""
    fake_mod = type("fake_mem0", (), {"Memory": FakeMem0Memory})()
    monkeypatch.setitem(__import__("sys").modules, "mem0", fake_mod)


@pytest.fixture(autouse=True)
def _disable_mem0_env(monkeypatch):
    """Ensure MEM0_ENABLED is off by default so other tests are unaffected."""
    monkeypatch.setattr(Config, "MEM0_ENABLED", False)
    monkeypatch.setattr(Config, "LONG_TERM_MEMORY_ENABLED", False)


@pytest.fixture
def mock_llm_mem0(tmp_path, monkeypatch):
    """Mock LLM with mem0-specific patches."""
    from test.memory.conftest import MockLLM

    return MockLLM()


# ---------------------------------------------------------------------------
# Mem0MemoryStore tests
# ---------------------------------------------------------------------------


class TestMem0MemoryStore:
    @pytest.fixture
    def store(self):
        from ouro.capabilities.memory.store.mem0_memory_store import Mem0MemoryStore

        return Mem0MemoryStore()

    async def test_create_session_returns_uuid(self, store):
        sid = await store.create_session()
        assert isinstance(sid, str)
        assert len(sid) == 36  # UUID4 length

    async def test_save_and_load_round_trip(self, store):
        sid = await store.create_session()
        sys_msgs = [LLMMessage(role="system", content="be helpful")]
        msgs = [
            LLMMessage(role="user", content="hello"),
            LLMMessage(role="assistant", content="hi"),
        ]
        await store.save_memory(sid, sys_msgs, msgs)

        loaded = await store.load_session(sid)
        assert loaded is not None
        # Because we don't have raw_messages metadata, fallback wraps as assistant
        assert len(loaded["messages"]) >= 1

    async def test_list_sessions(self, store):
        sid1 = await store.create_session()
        sid2 = await store.create_session()
        await store.save_memory(sid1, [], [LLMMessage(role="user", content="a")])
        await store.save_memory(sid2, [], [LLMMessage(role="user", content="b")])

        sessions = await store.list_sessions(limit=10)
        ids = {s["id"] for s in sessions}
        assert sid1 in ids
        assert sid2 in ids

    async def test_delete_session(self, store):
        sid = await store.create_session()
        await store.save_memory(sid, [], [LLMMessage(role="user", content="x")])
        ok = await store.delete_session(sid)
        assert ok is True
        loaded = await store.load_session(sid)
        assert loaded is None

    async def test_search(self, store):
        sid = await store.create_session()
        await store.add_fact("I love Python", sid)
        await store.add_fact("I hate bugs", sid)

        results = await store.search("love", session_id=sid)
        assert len(results) >= 1
        assert any("Python" in r["memory"] for r in results)

    async def test_get_session_stats(self, store):
        sid = await store.create_session()
        await store.save_memory(sid, [], [LLMMessage(role="user", content="hi")])
        stats = await store.get_session_stats(sid)
        assert stats is not None
        assert stats["session_id"] == sid


# ---------------------------------------------------------------------------
# Mem0LongTermMemory tests
# ---------------------------------------------------------------------------


class TestMem0LongTermMemory:
    @pytest.fixture
    def ltm(self, mock_llm_mem0):
        from ouro.capabilities.memory.long_term.mem0_adapter import Mem0LongTermMemory

        return Mem0LongTermMemory(mock_llm_mem0, user_id="test_user")

    async def test_load_and_format_returns_none_when_empty(self, ltm):
        result = await ltm.load_and_format()
        assert result is None

    async def test_add_and_load_memories(self, ltm):
        await ltm.add_memories_from_conversation(
            [
                LLMMessage(role="user", content="My name is Alice."),
                LLMMessage(role="assistant", content="Nice to meet you, Alice!"),
            ],
            session_id="sess_1",
        )
        result = await ltm.load_and_format()
        assert result is not None
        assert "Alice" in result

    async def test_search(self, ltm):
        await ltm.add_memories_from_conversation(
            [LLMMessage(role="user", content="I prefer dark mode.")],
            session_id="sess_1",
        )
        results = await ltm.search("dark mode")
        assert len(results) >= 1
        assert any("dark mode" in r["memory"] for r in results)

    async def test_add_memories_from_multimodal(self, ltm):
        msg = LLMMessage(
            role="user",
            content=[
                {"type": "text", "text": "Here is an image."},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            ],
        )
        await ltm.add_memories_from_conversation([msg], session_id="sess_2")
        result = await ltm.load_and_format()
        assert result is not None
        assert "image" in result


# ---------------------------------------------------------------------------
# MemoryManager integration with mem0 backend
# ---------------------------------------------------------------------------


class TestMemoryManagerWithMem0:
    async def test_uses_mem0_backend_when_enabled(self, mock_llm_mem0, monkeypatch):
        monkeypatch.setattr(Config, "MEM0_ENABLED", True)
        from ouro.capabilities.memory import MemoryManager

        manager = MemoryManager(mock_llm_mem0)
        from ouro.capabilities.memory.store.mem0_memory_store import Mem0MemoryStore

        assert isinstance(manager._store, Mem0MemoryStore)

    async def test_mem0_ltm_wired_when_enabled(self, mock_llm_mem0, monkeypatch):
        monkeypatch.setattr(Config, "MEM0_ENABLED", True)
        from ouro.capabilities.memory import MemoryManager

        manager = MemoryManager(mock_llm_mem0)
        from ouro.capabilities.memory.long_term.mem0_adapter import Mem0LongTermMemory

        assert isinstance(manager.long_term, Mem0LongTermMemory)

    async def test_save_memory_feeds_ltm(self, mock_llm_mem0, monkeypatch):
        monkeypatch.setattr(Config, "MEM0_ENABLED", True)
        from ouro.capabilities.memory import MemoryManager

        manager = MemoryManager(mock_llm_mem0)
        ctx = MessageListContext(
            system_messages=[LLMMessage(role="system", content="be kind")],
            detached=[LLMMessage(role="user", content="hello")],
        )
        await manager.save_memory(context=ctx)
        assert manager.session_id is not None
        # LTM should have received the conversation
        results = await manager.long_term.search("hello")
        assert len(results) >= 1
