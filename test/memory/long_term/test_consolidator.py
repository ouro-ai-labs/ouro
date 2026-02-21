"""Tests for LongTermMemoryConsolidator."""

import pytest

from memory.long_term.consolidator import LongTermMemoryConsolidator


@pytest.mark.asyncio
class TestConsolidator:
    async def test_should_consolidate_below_threshold(self, mock_ltm_llm, monkeypatch):
        from config import Config

        monkeypatch.setattr(Config, "LONG_TERM_MEMORY_CONSOLIDATION_THRESHOLD", 5000)
        consolidator = LongTermMemoryConsolidator(mock_ltm_llm)
        assert not await consolidator.should_consolidate("short")

    async def test_should_consolidate_above_threshold(self, mock_ltm_llm, monkeypatch):
        from config import Config

        monkeypatch.setattr(Config, "LONG_TERM_MEMORY_CONSOLIDATION_THRESHOLD", 10)
        consolidator = LongTermMemoryConsolidator(mock_ltm_llm)
        assert await consolidator.should_consolidate("a" * 200)

    async def test_consolidate_returns_llm_output(self, mock_ltm_llm):
        mock_ltm_llm.response_text = "- consolidated decision\n- consolidated pref\n"
        consolidator = LongTermMemoryConsolidator(mock_ltm_llm)
        result = await consolidator.consolidate("- d1\n- d2\n- p1\n")
        assert "consolidated decision" in result
        assert mock_ltm_llm.call_count == 1

    async def test_consolidate_falls_back_on_empty(self, mock_ltm_llm):
        mock_ltm_llm.response_text = ""
        consolidator = LongTermMemoryConsolidator(mock_ltm_llm)
        original = "- keep me\n"
        result = await consolidator.consolidate(original)
        assert result == original

    async def test_estimate_tokens_fallback(self, mock_ltm_llm):
        """Fallback to char-ratio when litellm is unavailable for the model."""
        consolidator = LongTermMemoryConsolidator(mock_ltm_llm)
        # With mock model, litellm may fall back to char ratio
        tokens = consolidator._estimate_tokens("hello world")
        assert tokens > 0
