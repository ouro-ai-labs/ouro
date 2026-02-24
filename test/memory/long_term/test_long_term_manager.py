"""Tests for LongTermMemoryManager facade."""

from datetime import date

import pytest

from memory.long_term import LongTermMemoryManager


@pytest.mark.asyncio
class TestLongTermMemoryManager:
    async def test_load_and_format_empty(self, tmp_path, mock_ltm_llm):
        manager = LongTermMemoryManager(mock_ltm_llm, memory_dir=str(tmp_path / "mem"))
        result = await manager.load_and_format()

        assert result is not None
        assert "<long_term_memory>" in result
        assert "</long_term_memory>" in result
        # No DURABLE MEMORIES section when everything is empty
        assert "DURABLE MEMORIES" not in result
        assert str(tmp_path / "mem") in result  # memory_dir injected

    async def test_load_and_format_with_entries(self, tmp_path, mock_ltm_llm, sample_content):
        manager = LongTermMemoryManager(mock_ltm_llm, memory_dir=str(tmp_path / "mem"))
        await manager.store.save(sample_content)

        result = await manager.load_and_format()
        assert "Use async-first architecture" in result
        assert "Prefer type hints everywhere" in result
        assert "Project uses Python 3.12+" in result

    async def test_load_and_format_triggers_consolidation(
        self, tmp_path, mock_ltm_llm, monkeypatch
    ):
        from config import Config

        monkeypatch.setattr(Config, "LONG_TERM_MEMORY_CONSOLIDATION_THRESHOLD", 1)

        mock_ltm_llm.response_text = "- consolidated decision\n- consolidated pref\n"

        manager = LongTermMemoryManager(mock_ltm_llm, memory_dir=str(tmp_path / "mem"))
        big_content = "\n".join(f"- item {i}" for i in range(60)) + "\n"
        await manager.store.save(big_content)

        result = await manager.load_and_format()
        # promotion (1 call) + consolidation (1 call) — but no dailies so promotion is skipped
        # Only consolidation should fire
        assert mock_ltm_llm.call_count >= 1
        assert "consolidated decision" in result

    async def test_load_and_format_no_consolidation_below_threshold(
        self, tmp_path, mock_ltm_llm, monkeypatch
    ):
        from config import Config

        monkeypatch.setattr(Config, "LONG_TERM_MEMORY_CONSOLIDATION_THRESHOLD", 99999)

        manager = LongTermMemoryManager(mock_ltm_llm, memory_dir=str(tmp_path / "mem"))
        await manager.load_and_format()
        assert mock_ltm_llm.call_count == 0

    async def test_memory_dir_property(self, tmp_path, mock_ltm_llm):
        path = str(tmp_path / "mem")
        manager = LongTermMemoryManager(mock_ltm_llm, memory_dir=path)
        assert manager.memory_dir == path

    async def test_format_memories_empty(self, tmp_path, mock_ltm_llm):
        """Empty content should produce no DURABLE MEMORIES section."""
        result = LongTermMemoryManager._format_memories("")
        assert result == ""

    async def test_format_memories_nonempty(self, tmp_path, mock_ltm_llm):
        """Non-empty content should be wrapped in DURABLE MEMORIES."""
        result = LongTermMemoryManager._format_memories("- d1\n- f1\n")
        assert "DURABLE MEMORIES" in result
        assert "d1" in result
        assert "f1" in result

    async def test_load_and_format_includes_dailies(self, tmp_path, mock_ltm_llm, monkeypatch):
        """Daily files should appear in the formatted output."""
        from config import Config

        monkeypatch.setattr(Config, "LONG_TERM_MEMORY_DAILY_WINDOW", 2)
        monkeypatch.setattr(Config, "LONG_TERM_MEMORY_CONSOLIDATION_THRESHOLD", 99999)

        manager = LongTermMemoryManager(mock_ltm_llm, memory_dir=str(tmp_path / "mem"))
        today = date.today()
        await manager.store.save_daily(today, "- worked on auth module\n")

        result = await manager.load_and_format()
        assert "RECENT DAILY NOTES" in result
        assert "worked on auth module" in result
        assert today.isoformat() in result

    async def test_format_dailies_empty(self):
        result = LongTermMemoryManager._format_dailies([])
        assert result == ""

    async def test_format_dailies_nonempty(self):
        dailies = [
            (date(2026, 2, 22), "- note A"),
            (date(2026, 2, 23), "- note B"),
        ]
        result = LongTermMemoryManager._format_dailies(dailies)
        assert "RECENT DAILY NOTES" in result
        assert "2026-02-22" in result
        assert "note A" in result
        assert "2026-02-23" in result
        assert "note B" in result

    async def test_load_and_format_includes_today_file(self, tmp_path, mock_ltm_llm, monkeypatch):
        """Template should reference today's daily file name."""
        from config import Config

        monkeypatch.setattr(Config, "LONG_TERM_MEMORY_CONSOLIDATION_THRESHOLD", 99999)

        manager = LongTermMemoryManager(mock_ltm_llm, memory_dir=str(tmp_path / "mem"))
        result = await manager.load_and_format()
        today_file = f"{date.today().isoformat()}.md"
        assert today_file in result

    async def test_no_llm_call_when_below_threshold_with_dailies(
        self, tmp_path, mock_ltm_llm, monkeypatch
    ):
        """No LLM calls (promote/consolidate) when combined size is below threshold."""
        from config import Config

        monkeypatch.setattr(Config, "LONG_TERM_MEMORY_CONSOLIDATION_THRESHOLD", 99999)

        manager = LongTermMemoryManager(mock_ltm_llm, memory_dir=str(tmp_path / "mem"))
        await manager.store.save("- small permanent\n")
        await manager.store.save_daily(date.today(), "- small daily note\n")

        await manager.load_and_format()
        assert mock_ltm_llm.call_count == 0  # no LLM calls at all

    async def test_promote_and_consolidate_when_combined_exceeds_threshold(
        self, tmp_path, mock_ltm_llm, monkeypatch
    ):
        """Both promote and consolidate fire when permanent + dailies exceed threshold."""
        from config import Config

        monkeypatch.setattr(Config, "LONG_TERM_MEMORY_CONSOLIDATION_THRESHOLD", 1)

        mock_ltm_llm.response_text = "- promoted + consolidated\n"

        manager = LongTermMemoryManager(mock_ltm_llm, memory_dir=str(tmp_path / "mem"))
        await manager.store.save("- permanent fact\n")
        await manager.store.save_daily(date.today(), "- daily note with durable info\n")

        result = await manager.load_and_format()
        # promote (1 call) + consolidate (1 call) = 2
        assert mock_ltm_llm.call_count == 2
        assert "promoted + consolidated" in result
