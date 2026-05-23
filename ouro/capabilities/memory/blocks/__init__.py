"""Memory blocks — named, size-bounded markdown files for in-context long-term memory.

Inspired by Letta/MemGPT's core memory: instead of one unbounded ``memory.md``
file edited via generic file tools, ouro maintains a small set of named blocks
under ``~/.ouro/memory/blocks/``. Each block has a token budget enforced at
write time, forcing the agent to make explicit choices about what to keep.

Default blocks:

- ``user`` (~2k tokens) — durable facts about the user (name, role, preferences).
- ``project`` (~4k tokens) — durable facts about the active project / codebase.
- ``scratch`` (~16k tokens) — recent decisions / WIP context. Append-friendly:
  if a write would overflow, the oldest content is dropped (FIFO by paragraph).

Strict blocks (``user``, ``project``) refuse writes that overflow; the tool
surfaces an actionable error so the LLM trims before retrying. Scratch is
lenient so opportunistic appends never silently fail.
"""

from ouro.capabilities.memory.blocks.manager import (
    BlockBudgetExceeded,
    MemoryBlockManager,
)

__all__ = ["BlockBudgetExceeded", "MemoryBlockManager"]
