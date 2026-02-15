"""LLM-based consolidation for long-term memory.

When total memory exceeds a token threshold the consolidator asks an LLM to
merge duplicates, remove stale entries, and compress the content.
"""

import logging
from typing import TYPE_CHECKING

from config import Config
from llm.message_types import LLMMessage

from .store import MemoryCategory

if TYPE_CHECKING:
    from llm import LiteLLMAdapter

logger = logging.getLogger(__name__)

# Rough chars-per-token ratio for estimation
_CHARS_PER_TOKEN = 3.5

CONSOLIDATION_PROMPT = """\
You are a memory consolidation assistant. Below are long-term memory entries \
organized by category. Your job is to consolidate them:

1. Merge overlapping or duplicate entries into single, clear statements.
2. Remove entries that are outdated or no longer useful.
3. Preserve all important, actionable information.
4. Target at least 40% reduction in total size while retaining key information.

Return the consolidated memories in the EXACT same format — three sections \
with headers "## decisions", "## preferences", "## facts", each followed \
by its content. Include ALL three headers even if a section is empty.

CURRENT MEMORIES:
{memories_text}"""


class LongTermMemoryConsolidator:
    """Consolidates long-term memories using an LLM when they exceed a size threshold."""

    def __init__(self, llm: "LiteLLMAdapter"):
        self.llm = llm

    async def should_consolidate(
        self,
        memories: dict[MemoryCategory, str],
    ) -> bool:
        """Check whether total memory content exceeds the consolidation threshold."""
        threshold = Config.LONG_TERM_MEMORY_CONSOLIDATION_THRESHOLD
        total_text = self._format_memories_text(memories)
        estimated_tokens = int(len(total_text) / _CHARS_PER_TOKEN)
        return estimated_tokens > threshold

    async def consolidate(
        self,
        memories: dict[MemoryCategory, str],
    ) -> dict[MemoryCategory, str]:
        """Ask LLM to consolidate memories across all categories.

        Returns:
            Consolidated mapping of category → content.
        """
        memories_text = self._format_memories_text(memories)
        prompt = CONSOLIDATION_PROMPT.format(memories_text=memories_text)

        response = await self.llm.call_async(
            messages=[LLMMessage(role="user", content=prompt)],
            max_tokens=4096,
        )

        text = response.content if isinstance(response.content, str) else ""
        return self._parse_response(text, memories)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_memories_text(memories: dict[MemoryCategory, str]) -> str:
        """Format all memories into a single text block for the prompt."""
        parts: list[str] = []
        for cat in MemoryCategory:
            content = memories.get(cat, "").strip()
            if content:
                parts.append(f"## {cat.value}\n{content}")
        return "\n\n".join(parts) if parts else "(empty)"

    @staticmethod
    def _parse_response(
        text: str,
        original: dict[MemoryCategory, str],
    ) -> dict[MemoryCategory, str]:
        """Parse LLM markdown response by splitting on ## headers.

        Falls back to original on failure.
        """
        if not text or not text.strip():
            return original

        result: dict[MemoryCategory, str] = {}
        # Build a lookup from header name to category
        cat_by_name = {cat.value: cat for cat in MemoryCategory}

        # Split text into sections by ## headers
        current_cat: MemoryCategory | None = None
        current_lines: list[str] = []

        for line in text.splitlines():
            stripped = line.strip().lower()
            if stripped.startswith("## "):
                # Flush previous section
                if current_cat is not None:
                    result[current_cat] = "\n".join(current_lines).strip()
                # Start new section
                header = stripped[3:].strip()
                current_cat = cat_by_name.get(header)
                current_lines = []
            else:
                current_lines.append(line)

        # Flush last section
        if current_cat is not None:
            result[current_cat] = "\n".join(current_lines).strip()

        # Fill missing categories from original
        for cat in MemoryCategory:
            if cat not in result:
                result[cat] = original.get(cat, "")

        return result
