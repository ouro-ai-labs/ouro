"""LLM-based consolidation for long-term memory.

When total memory exceeds a token threshold the consolidator asks an LLM to
merge duplicates, remove stale entries, and compress the content.

The consolidator also supports *promotion*: scanning daily notes for durable
knowledge that should be merged into the permanent ``memory.md``.
"""

import logging
from datetime import date
from typing import TYPE_CHECKING, List, Optional, Tuple

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

PROMOTION_PROMPT = """\
You are a memory triage assistant. You have two inputs:

1. PERMANENT MEMORIES (memory.md) — durable knowledge to keep across sessions:
{permanent}

2. DAILY NOTES — recent running notes from the last few days:
{dailies}

Your job: scan the daily notes for any *durable* knowledge that belongs in \
the permanent file. Durable knowledge includes:
- User preferences and habits
- Key decisions with rationale
- Project conventions and patterns
- Environment facts (toolchain, versions, paths)
- Reusable solutions and insights

Do NOT promote:
- Work-in-progress notes or debugging context
- Session-specific task progress
- Temporary workarounds
- Information already present in permanent memories

Return ONLY the updated permanent memories markdown (with any new entries \
merged in under appropriate headings). If nothing needs promoting, return \
the permanent memories unchanged."""


class LongTermMemoryConsolidator:
    """Consolidates long-term memories using an LLM when they exceed a size threshold."""

    def __init__(self, llm: "LiteLLMAdapter"):
        self.llm = llm

    def should_consolidate(self, *contents: str) -> bool:
        """Check whether combined memory content exceeds the consolidation threshold.

        Accepts one or more content strings (e.g. permanent + dailies).
        """
        threshold = Config.LONG_TERM_MEMORY_CONSOLIDATION_THRESHOLD
        combined = "\n".join(c for c in contents if c)
        return self._estimate_tokens(combined) > threshold

    async def consolidate(self, content: str) -> str:
        """Ask LLM to consolidate memory content.

        Returns:
            Consolidated markdown string, or *content* unchanged on failure.
        """
        prompt = CONSOLIDATION_PROMPT.format(content=content)
        result = await self._call_llm(prompt)
        return result if result is not None else content

    async def promote_from_dailies(
        self,
        permanent: str,
        dailies: List[Tuple[date, str]],
    ) -> Optional[str]:
        """Scan daily notes for durable knowledge and merge into permanent memories.

        Returns:
            Updated permanent memories string, or *None* if nothing to promote.
        """
        if not dailies:
            return None

        dailies_text = "\n".join(
            f"--- {dt.isoformat()} ---\n{content.strip()}" for dt, content in dailies
        )
        prompt = PROMOTION_PROMPT.format(
            permanent=permanent or "(empty)",
            dailies=dailies_text,
        )
        return await self._call_llm(prompt)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _call_llm(self, prompt: str) -> Optional[str]:
        """Send a single-message prompt and return the text, or *None* if empty."""
        response = await self.llm.call_async(
            messages=[LLMMessage(role="user", content=prompt)],
            max_tokens=4096,
        )
        text = response.content if isinstance(response.content, str) else ""
        return text if text.strip() else None

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
