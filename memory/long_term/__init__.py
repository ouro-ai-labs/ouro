"""Long-term memory — cross-session persistent memory backed by git.

The facade class `LongTermMemoryManager` is the only public API.
"""

import logging
from typing import TYPE_CHECKING, Optional

from .consolidator import LongTermMemoryConsolidator
from .store import GitMemoryStore, MemoryCategory

if TYPE_CHECKING:
    from llm import LiteLLMAdapter

logger = logging.getLogger(__name__)

__all__ = ["LongTermMemoryManager", "MemoryCategory"]

_INSTRUCTION_TEMPLATE = """\
<long_term_memory_management>
You have a persistent long-term memory stored in {memory_dir}.
Memory files are YAML formatted and organized by category:
- decisions.yaml: Key decisions and their rationale
- preferences.yaml: User preferences, coding style, workflow habits
- facts.yaml: Factual info about projects, environments, tools

CURRENT MEMORIES (loaded at startup):
{formatted_memories}

WHEN TO UPDATE MEMORY:
- User expresses a preference or habit
- An important decision is made with clear rationale
- You learn a new fact about the project/environment that would help in future sessions
- User explicitly asks you to remember something

HOW TO UPDATE MEMORY:
1. Read the target YAML file, add your new entry (keep the plain-list YAML format), and write it back.
2. Commit the change with git so it persists across sessions.

RULES:
- Be selective — only store information useful across FUTURE sessions
- Be concise — each entry should be a single clear statement
- Don't duplicate existing memories listed above
- Don't store transient task details (specific file edits, debugging steps)
</long_term_memory_management>"""


class LongTermMemoryManager:
    """Facade for the long-term memory subsystem.

    Responsibilities:
    - Load memories at session start and format them into a system-prompt section
    - Trigger LLM-based consolidation when total size exceeds a threshold
    - Expose change-detection so callers can tell if another agent mutated memory
    """

    def __init__(self, llm: "LiteLLMAdapter", memory_dir: Optional[str] = None):
        self.store = GitMemoryStore(memory_dir)
        self.consolidator = LongTermMemoryConsolidator(llm)

    async def load_and_format(self) -> Optional[str]:
        """Load memories, consolidate if needed, and return a system-prompt section.

        Returns:
            A string containing the ``<long_term_memory_management>`` XML block
            with current memories and instructions, or *None* if loading fails
            catastrophically.
        """
        try:
            memories = await self.store.load_all()
        except Exception:
            logger.warning("Failed to load long-term memory", exc_info=True)
            # Return template with empty memories so agent can still create new ones
            memories = {cat: [] for cat in MemoryCategory}

        # Consolidate if over threshold
        try:
            if await self.consolidator.should_consolidate(memories):
                logger.info("Long-term memory exceeds threshold — consolidating")
                memories = await self.consolidator.consolidate(memories)
                await self.store.save_and_commit(memories, "memory: consolidate entries")
                # Re-snapshot HEAD so our own consolidation commit doesn't
                # cause has_changed_since_load() to return True.
                self.store._loaded_head = await self.store.get_current_head()
        except Exception:
            logger.warning("Long-term memory consolidation failed", exc_info=True)

        formatted = self._format_memories(memories)
        return _INSTRUCTION_TEMPLATE.format(
            memory_dir=self.store.memory_dir,
            formatted_memories=formatted,
        )

    async def has_changed_since_load(self) -> bool:
        """Proxy to store's HEAD-based change detection."""
        return await self.store.has_changed_since_load()

    @property
    def memory_dir(self) -> str:
        return self.store.memory_dir

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_memories(memories: dict[MemoryCategory, list[str]]) -> str:
        """Format memories for embedding in the instruction template."""
        parts: list[str] = []
        for cat in MemoryCategory:
            entries = memories.get(cat, [])
            header = f"[{cat.value}]"
            if entries:
                lines = "\n".join(f"  - {e}" for e in entries)
                parts.append(f"{header}\n{lines}")
            else:
                parts.append(f"{header}\n  (none)")
        return "\n".join(parts)
