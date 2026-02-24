"""Tests for daily file operations in MemoryStore."""

import os
from datetime import date, timedelta

import pytest

from memory.long_term.store import MemoryStore


@pytest.mark.asyncio
class TestDailyStore:
    async def test_save_and_load_daily(self, tmp_path):
        store = MemoryStore(memory_dir=str(tmp_path / "mem"))
        today = date.today()
        await store.save_daily(today, "- debugging auth bug\n")

        content = await store.load_daily(today)
        assert "debugging auth bug" in content

    async def test_load_daily_missing(self, tmp_path):
        store = MemoryStore(memory_dir=str(tmp_path / "mem"))
        content = await store.load_daily(date(2020, 1, 1))
        assert content == ""

    async def test_append_daily(self, tmp_path):
        store = MemoryStore(memory_dir=str(tmp_path / "mem"))
        today = date.today()
        await store.append_daily(today, "- note 1\n")
        await store.append_daily(today, "- note 2\n")

        content = await store.load_daily(today)
        assert "note 1" in content
        assert "note 2" in content

    async def test_append_daily_creates_file(self, tmp_path):
        store = MemoryStore(memory_dir=str(tmp_path / "mem"))
        today = date.today()
        await store.append_daily(today, "first entry\n")
        assert os.path.isfile(os.path.join(str(tmp_path / "mem"), f"{today.isoformat()}.md"))

    async def test_list_daily_files(self, tmp_path):
        store = MemoryStore(memory_dir=str(tmp_path / "mem"))
        d1 = date(2026, 2, 20)
        d2 = date(2026, 2, 22)
        await store.save_daily(d1, "a")
        await store.save_daily(d2, "b")

        dates = await store.list_daily_files()
        assert dates == [d2, d1]  # descending

    async def test_list_daily_files_ignores_memory_md(self, tmp_path):
        store = MemoryStore(memory_dir=str(tmp_path / "mem"))
        await store.save("permanent content")
        await store.save_daily(date(2026, 1, 1), "daily")

        dates = await store.list_daily_files()
        assert len(dates) == 1
        assert dates[0] == date(2026, 1, 1)

    async def test_load_recent_dailies(self, tmp_path):
        store = MemoryStore(memory_dir=str(tmp_path / "mem"))
        today = date.today()
        yesterday = today - timedelta(days=1)
        two_days_ago = today - timedelta(days=2)

        await store.save_daily(today, "today notes")
        await store.save_daily(yesterday, "yesterday notes")
        await store.save_daily(two_days_ago, "old notes")

        # Window of 2 should get today + yesterday
        recent = await store.load_recent_dailies(2)
        assert len(recent) == 2
        # Oldest first
        assert recent[0][0] == yesterday
        assert recent[1][0] == today
        assert "yesterday notes" in recent[0][1]
        assert "today notes" in recent[1][1]

    async def test_load_recent_dailies_skips_empty(self, tmp_path):
        store = MemoryStore(memory_dir=str(tmp_path / "mem"))
        today = date.today()
        await store.save_daily(today, "today notes")
        # Yesterday has no file — should be skipped

        recent = await store.load_recent_dailies(2)
        assert len(recent) == 1
        assert recent[0][0] == today

    async def test_prune_old_dailies(self, tmp_path):
        store = MemoryStore(memory_dir=str(tmp_path / "mem"))
        today = date.today()
        old = today - timedelta(days=40)
        recent = today - timedelta(days=5)

        await store.save_daily(old, "old content")
        await store.save_daily(recent, "recent content")

        pruned = await store.prune_old_dailies(30)
        assert pruned == 1

        # Old file should be gone
        assert await store.load_daily(old) == ""
        # Recent file should still exist
        assert "recent content" in await store.load_daily(recent)

    async def test_prune_returns_zero_when_nothing_to_prune(self, tmp_path):
        store = MemoryStore(memory_dir=str(tmp_path / "mem"))
        today = date.today()
        await store.save_daily(today, "fresh")

        pruned = await store.prune_old_dailies(30)
        assert pruned == 0

    async def test_permanent_memory_unchanged(self, tmp_path):
        """Verify that permanent load/save still works as before."""
        store = MemoryStore(memory_dir=str(tmp_path / "mem"))
        await store.save("permanent fact")
        content = await store.load()
        assert content == "permanent fact"
