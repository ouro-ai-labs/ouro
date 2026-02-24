"""Long-term memory — cross-session persistent memory.

The facade class `LongTermMemoryManager` is the only public API.

Storage layout::

    ~/.ouro/memory/
    ├── memory.md          # Decisions, preferences, durable facts
    ├── 2026-02-23.md      # Today's running notes/context
    ├── 2026-02-22.md      # Yesterday's notes
    └── ...
"""

import logging
from datetime import date
from typing import TYPE_CHECKING, List, Optional, Tuple

from config import Config

from .consolidator import LongTermMemoryConsolidator
from .store import MemoryStore

if TYPE_CHECKING:
    from llm import LiteLLMAdapter

logger = logging.getLogger(__name__)

__all__ = ["LongTermMemoryManager"]

_INSTRUCTION_TEMPLATE = """\
<long_term_memory>
You have a persistent long-term memory system in {memory_dir}/.

It uses two kinds of files:
- **memory.md** — Durable knowledge: decisions, preferences, project facts, environment details.
- **YYYY-MM-DD.md** — Daily notes: work-in-progress, debugging context, session progress.

{formatted_permanent}\
{formatted_dailies}\
WHEN TO UPDATE memory.md (durable):
- User expresses a preference or habit
- An important decision is made with clear rationale
- You learn a reusable fact about the project/environment
- User explicitly asks you to remember something

WHEN TO UPDATE today's daily file (ephemeral):
- Work-in-progress notes and debugging context
- Session-specific task progress
- Temporary workarounds and observations

HOW TO UPDATE:
1. Edit memory.md for durable knowledge — organize with markdown headings
2. Edit {today_file} for today's running notes

RULES:
- Be selective — only store info useful across FUTURE sessions
- Be concise — one line per memory where possible
- Don't duplicate between files
- Durable facts belong in memory.md, not daily files
</long_term_memory>"""


class LongTermMemoryManager:
    """Facade for the long-term memory subsystem.

    Responsibilities:
    - Load permanent memories + recent daily files at session start
    - Trigger LLM-based consolidation when permanent memory exceeds a threshold
    - Promote durable knowledge from daily files to memory.md
    - Prune old daily files beyond the retention window
    """

    def __init__(self, llm: "LiteLLMAdapter", memory_dir: Optional[str] = None):
        self.store = MemoryStore(memory_dir)
        self.consolidator = LongTermMemoryConsolidator(llm)

    async def load_and_format(self) -> Optional[str]:
        """Load memories, consolidate/promote if needed, and return a system-prompt section.

        Returns:
            A string containing the ``<long_term_memory>`` XML block
            with current memories and instructions, or *None* if loading fails
            catastrophically.
        """
        # 1. Load permanent memory
        try:
            permanent = await self.store.load()
        except Exception:
            logger.warning("Failed to load long-term memory", exc_info=True)
            permanent = ""

        # 2. Load recent daily files
        try:
            dailies = await self.store.load_recent_dailies(Config.LONG_TERM_MEMORY_DAILY_WINDOW)
        except Exception:
            logger.warning("Failed to load daily memory files", exc_info=True)
            dailies = []

        # 3. Promote + consolidate (only when combined size exceeds threshold)
        dailies_text = "\n".join(c for _, c in dailies) if dailies else ""
        if self.consolidator.should_consolidate(permanent, dailies_text):
            # 3a. Promote durable knowledge from daily files → memory.md
            try:
                if dailies:
                    promoted = await self.consolidator.promote_from_dailies(permanent, dailies)
                    if promoted is not None and promoted != permanent:
                        permanent = promoted
                        await self.store.save(permanent)
                        logger.info("Promoted durable knowledge from daily files to memory.md")
            except Exception:
                logger.warning("Daily promotion failed", exc_info=True)

            # 3b. Consolidate permanent memory
            try:
                logger.info("Long-term memory exceeds threshold — consolidating")
                permanent = await self.consolidator.consolidate(permanent)
                await self.store.save(permanent)
            except Exception:
                logger.warning("Long-term memory consolidation failed", exc_info=True)

        # 5. Prune old daily files
        try:
            pruned = await self.store.prune_old_dailies(Config.LONG_TERM_MEMORY_DAILY_RETENTION)
            if pruned:
                logger.info("Pruned %d old daily memory files", pruned)
        except Exception:
            logger.warning("Failed to prune old daily files", exc_info=True)

        # 6. Format into system prompt
        formatted_permanent = self._format_memories(permanent)
        formatted_dailies = self._format_dailies(dailies)
        today_file = f"{date.today().isoformat()}.md"
        return _INSTRUCTION_TEMPLATE.format(
            memory_dir=self.store.memory_dir,
            formatted_permanent=formatted_permanent,
            formatted_dailies=formatted_dailies,
            today_file=today_file,
        )

    @property
    def memory_dir(self) -> str:
        return self.store.memory_dir

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_memories(content: str) -> str:
        """Format permanent memories for embedding in the instruction template."""
        stripped = content.strip()
        if stripped:
            return f"DURABLE MEMORIES (memory.md):\n{stripped}\n\n"
        return ""

    @staticmethod
    def _format_dailies(dailies: List[Tuple[date, str]]) -> str:
        """Format daily file contents for embedding in the instruction template."""
        if not dailies:
            return ""
        parts = ["RECENT DAILY NOTES:"]
        for dt, content in dailies:
            parts.append(f"\n--- {dt.isoformat()} ---\n{content.strip()}")
        return "\n".join(parts) + "\n\n"
