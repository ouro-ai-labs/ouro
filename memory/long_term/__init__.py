"""Long-term memory — cross-session persistent memory.

The facade class `LongTermMemoryManager` is the only public API.
"""

import logging
from typing import TYPE_CHECKING, Optional

from .consolidator import LongTermMemoryConsolidator
from .store import MemoryStore

if TYPE_CHECKING:
    from llm import LiteLLMAdapter

logger = logging.getLogger(__name__)

__all__ = ["LongTermMemoryManager"]

_INSTRUCTION_TEMPLATE = """\
<long_term_memory>
You have a persistent long-term memory stored in {memory_dir}/memory.md.

{formatted_memories}\
WHEN TO UPDATE:
- User expresses a preference or habit
- An important decision is made with clear rationale
- You learn a new fact about the project/environment
- User explicitly asks you to remember something

HOW TO UPDATE:
1. Edit memory.md — organize with markdown headings as you see fit
2. Prefix entries with date: `- [YYYY-MM-DD] ...`

RULES:
- Be selective — only store info useful across FUTURE sessions
- Be concise — one line per memory where possible
- Don't duplicate existing memories
- Don't store transient task details
</long_term_memory>"""


class LongTermMemoryManager:
    """Facade for the long-term memory subsystem.

    Responsibilities:
    - Load memories at session start and format them into a system-prompt section
    - Trigger LLM-based consolidation when total size exceeds a threshold
    """

    def __init__(self, llm: "LiteLLMAdapter", memory_dir: Optional[str] = None):
        self.store = MemoryStore(memory_dir)
        self.consolidator = LongTermMemoryConsolidator(llm)

    async def load_and_format(self) -> Optional[str]:
        """Load memories, consolidate if needed, and return a system-prompt section.

        Returns:
            A string containing the ``<long_term_memory>`` XML block
            with current memories and instructions, or *None* if loading fails
            catastrophically.
        """
        try:
            content = await self.store.load()
        except Exception:
            logger.warning("Failed to load long-term memory", exc_info=True)
            content = ""

        # Consolidate if over threshold
        try:
            if await self.consolidator.should_consolidate(content):
                logger.info("Long-term memory exceeds threshold — consolidating")
                content = await self.consolidator.consolidate(content)
                await self.store.save(content)
        except Exception:
            logger.warning("Long-term memory consolidation failed", exc_info=True)

        formatted = self._format_memories(content)
        return _INSTRUCTION_TEMPLATE.format(
            memory_dir=self.store.memory_dir,
            formatted_memories=formatted,
        )

    @property
    def memory_dir(self) -> str:
        return self.store.memory_dir

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_memories(content: str) -> str:
        """Format memories for embedding in the instruction template."""
        stripped = content.strip()
        if stripped:
            return f"CURRENT MEMORIES:\n{stripped}\n\n"
        return ""
