"""Tests for MemoryStore."""

import pytest

from memory.long_term.store import MemoryStore


@pytest.mark.asyncio
class TestMemoryStore:
    async def test_load_creates_dir(self, tmp_path):
        store = MemoryStore(memory_dir=str(tmp_path / "mem"))
        content = await store.load()
        assert content == ""
        assert (tmp_path / "mem").is_dir()

    async def test_save_and_load_roundtrip(self, memory_store, sample_content):
        await memory_store.save(sample_content)
        loaded = await memory_store.load()
        assert loaded == sample_content

    async def test_load_empty(self, memory_store):
        content = await memory_store.load()
        assert content == ""

    async def test_save_overwrites(self, memory_store):
        await memory_store.save("first")
        await memory_store.save("second")
        loaded = await memory_store.load()
        assert loaded == "second"

    async def test_save_empty_clears(self, memory_store, sample_content):
        await memory_store.save(sample_content)
        await memory_store.save("")
        loaded = await memory_store.load()
        assert loaded == ""

    async def test_preserves_arbitrary_markdown(self, memory_store):
        content = "# My Notes\n\nWe chose React for the frontend.\n\n- item 1\n- item 2\n"
        await memory_store.save(content)
        loaded = await memory_store.load()
        assert loaded == content
