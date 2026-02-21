"""LLM-based consolidation for long-term memory.

When total memory exceeds a token threshold the consolidator asks an LLM to
merge duplicates, remove stale entries, and compress the content.
"""

import logging
from typing import TYPE_CHECKING

from config import Config
from llm.message_types import LLMMessage

if TYPE_CHECKING:
    from llm import LiteLLMAdapter

logger = logging.getLogger(__name__)

# Fallback chars-per-token ratio (used only when litellm.token_counter fails)
_CHARS_PER_TOKEN = 3.5

CONSOLIDATION_PROMPT = """\
You are a memory consolidation assistant. Below is the content of a long-term \
memory file in markdown format. Your job is to consolidate it:

1. Merge overlapping or duplicate entries into single, clear statements.
2. Remove entries that are outdated or no longer useful.
3. Preserve all important, actionable information.
4. Keep the markdown structure (headings, lists) clean and readable.
5. Target at least 40% reduction in total size while retaining key information.

Return ONLY the consolidated markdown content, nothing else.

CURRENT MEMORIES:
{content}"""


class LongTermMemoryConsolidator:
    """Consolidates long-term memories using an LLM when they exceed a size threshold."""

    def __init__(self, llm: "LiteLLMAdapter"):
        self.llm = llm

    async def should_consolidate(self, content: str) -> bool:
        """Check whether total memory content exceeds the consolidation threshold."""
        threshold = Config.LONG_TERM_MEMORY_CONSOLIDATION_THRESHOLD
        estimated_tokens = self._estimate_tokens(content)
        return estimated_tokens > threshold

    async def consolidate(self, content: str) -> str:
        """Ask LLM to consolidate memory content.

        Returns:
            Consolidated markdown string, or *content* unchanged on failure.
        """
        prompt = CONSOLIDATION_PROMPT.format(content=content)

        response = await self.llm.call_async(
            messages=[LLMMessage(role="user", content=prompt)],
            max_tokens=4096,
        )

        text = response.content if isinstance(response.content, str) else ""
        if not text.strip():
            return content
        return text

    def _estimate_tokens(self, content: str) -> int:
        """Estimate token count, preferring litellm.token_counter."""
        try:
            import litellm

            return litellm.token_counter(
                model=self.llm.model,
                messages=[{"role": "user", "content": content}],
            )
        except Exception:
            return int(len(content) / _CHARS_PER_TOKEN)
