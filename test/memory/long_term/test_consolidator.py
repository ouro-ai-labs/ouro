"""Tests for LongTermMemoryConsolidator."""

import pytest

from memory.long_term.consolidator import LongTermMemoryConsolidator
from memory.long_term.store import MemoryCategory


@pytest.mark.asyncio
class TestConsolidator:
    async def test_should_consolidate_below_threshold(self, mock_ltm_llm, monkeypatch):
        from config import Config

        monkeypatch.setattr(Config, "LONG_TERM_MEMORY_CONSOLIDATION_THRESHOLD", 5000)
        consolidator = LongTermMemoryConsolidator(mock_ltm_llm)

        memories = {
            MemoryCategory.DECISIONS: "short",
            MemoryCategory.PREFERENCES: "",
            MemoryCategory.FACTS: "",
        }
        assert not await consolidator.should_consolidate(memories)

    async def test_should_consolidate_above_threshold(self, mock_ltm_llm, monkeypatch):
        from config import Config

        monkeypatch.setattr(Config, "LONG_TERM_MEMORY_CONSOLIDATION_THRESHOLD", 10)
        consolidator = LongTermMemoryConsolidator(mock_ltm_llm)

        memories = {
            MemoryCategory.DECISIONS: "a" * 200,
            MemoryCategory.PREFERENCES: "b" * 200,
            MemoryCategory.FACTS: "c" * 200,
        }
        assert await consolidator.should_consolidate(memories)

    async def test_consolidate_parses_valid_response(self, mock_ltm_llm):
        mock_ltm_llm.response_text = (
            "## decisions\n- merged decision\n\n" "## preferences\n- pref\n\n" "## facts\n- fact\n"
        )
        consolidator = LongTermMemoryConsolidator(mock_ltm_llm)
        original = {
            MemoryCategory.DECISIONS: "- d1\n- d2\n",
            MemoryCategory.PREFERENCES: "- p1\n",
            MemoryCategory.FACTS: "- f1\n",
        }
        result = await consolidator.consolidate(original)
        assert "merged decision" in result[MemoryCategory.DECISIONS]
        assert "pref" in result[MemoryCategory.PREFERENCES]
        assert "fact" in result[MemoryCategory.FACTS]

    async def test_consolidate_falls_back_on_empty(self, mock_ltm_llm):
        mock_ltm_llm.response_text = ""
        consolidator = LongTermMemoryConsolidator(mock_ltm_llm)
        original = {
            MemoryCategory.DECISIONS: "- keep me\n",
            MemoryCategory.PREFERENCES: "",
            MemoryCategory.FACTS: "",
        }
        result = await consolidator.consolidate(original)
        assert result == original

    async def test_consolidate_preserves_missing_categories(self, mock_ltm_llm):
        """If LLM only returns some categories, keep originals for missing ones."""
        mock_ltm_llm.response_text = "## decisions\n- consolidated\n"
        consolidator = LongTermMemoryConsolidator(mock_ltm_llm)
        original = {
            MemoryCategory.DECISIONS: "- d1\n",
            MemoryCategory.PREFERENCES: "- p1\n",
            MemoryCategory.FACTS: "- f1\n",
        }
        result = await consolidator.consolidate(original)
        assert "consolidated" in result[MemoryCategory.DECISIONS]
        # Missing categories preserved from original
        assert result[MemoryCategory.PREFERENCES] == "- p1\n"
        assert result[MemoryCategory.FACTS] == "- f1\n"

    async def test_format_memories_empty(self, mock_ltm_llm):
        consolidator = LongTermMemoryConsolidator(mock_ltm_llm)
        memories = {cat: "" for cat in MemoryCategory}
        text = consolidator._format_memories_text(memories)
        assert text == "(empty)"
