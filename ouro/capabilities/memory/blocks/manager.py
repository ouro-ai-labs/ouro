"""MemoryBlockManager — named, size-bounded markdown blocks for in-context LTM."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ouro.core.llm import LiteLLMAdapter


# Default blocks shipped with ouro. Users can add their own by writing a file
# under ~/.ouro/memory/blocks/; reads will pick it up but no auto-budget is
# applied (treated as ``scratch``-class lenient append).
DEFAULT_BLOCK_BUDGETS: dict[str, int] = {
    "user": 2000,
    "project": 4000,
    "scratch": 16000,
}

# Blocks that should FIFO-truncate rather than reject on overflow.
LENIENT_BLOCKS: set[str] = {"scratch"}


class BlockBudgetExceeded(Exception):
    """Raised when a strict-budget block would overflow."""

    def __init__(self, block: str, current_tokens: int, attempted_tokens: int, budget: int):
        self.block = block
        self.current_tokens = current_tokens
        self.attempted_tokens = attempted_tokens
        self.budget = budget
        super().__init__(
            f"Block {block!r} budget exceeded: would be {attempted_tokens} tokens "
            f"(current {current_tokens}, budget {budget}). "
            f"Trim existing content with operation='replace' before adding more."
        )


@dataclass
class _Block:
    name: str
    content: str
    tokens: int


def _count_tokens(text: str, llm: LiteLLMAdapter | None) -> int:
    """Token count via litellm with a safe fallback heuristic."""
    if not text:
        return 0
    model = getattr(llm, "model", None) if llm is not None else None
    if model:
        try:
            import litellm

            return int(
                litellm.token_counter(
                    model=model,
                    messages=[{"role": "user", "content": text}],
                )
            )
        except Exception:
            pass
    # Fallback heuristic: ~3 chars per token (conservative for English; CJK higher).
    return max(1, len(text) // 3)


def _fifo_truncate(existing: str, addition: str, budget: int, llm: LiteLLMAdapter | None) -> str:
    """Drop oldest paragraphs from *existing* until *existing + addition* fits the budget.

    Splits on blank lines so we trim whole "entries" instead of mid-sentence.
    """
    combined = f"{existing}\n\n{addition}".strip() if existing.strip() else addition.strip()
    if _count_tokens(combined, llm) <= budget:
        return combined

    paragraphs = [p for p in existing.split("\n\n") if p.strip()]
    while paragraphs:
        paragraphs.pop(0)
        candidate = (
            "\n\n".join(paragraphs) + ("\n\n" if paragraphs else "") + addition.strip()
        ).strip()
        if _count_tokens(candidate, llm) <= budget:
            return candidate

    # Even with everything dropped, the addition alone is too large; truncate it.
    head_lines = addition.strip().splitlines()
    while head_lines and _count_tokens("\n".join(head_lines), llm) > budget:
        head_lines.pop(0)
    return "\n".join(head_lines)


_INSTRUCTION_TEMPLATE = """\
<long_term_memory>
You have a persistent memory system in {memory_dir}/blocks/. Each block is
a small markdown file that is always loaded into your system prompt. Edit
them with the ``memory_block_edit`` tool, not generic file tools.

Available blocks (name — budget):
{block_listing}

Current contents:
{block_contents}\
WHEN TO UPDATE:
- ``user``: when you learn something durable about the user (name, role, preferences, habits).
- ``project``: when you learn a reusable fact about the project / environment / repo.
- ``scratch``: for in-flight decisions and recent context that may matter next session.

RULES:
- Strict blocks (``user``, ``project``) refuse writes that exceed the budget — trim first.
- ``scratch`` auto-evicts oldest content; safe to append.
- Be concise: one line per memory where possible.
- Don't duplicate content between blocks.
</long_term_memory>"""


class MemoryBlockManager:
    """File-backed manager for named markdown memory blocks.

    Blocks live at ``<memory_dir>/blocks/<name>.md``. Reads are async; writes
    serialize on a single lock to avoid two compaction-time appends racing.
    """

    def __init__(
        self,
        llm: LiteLLMAdapter | None = None,
        memory_dir: str | None = None,
        block_budgets: dict[str, int] | None = None,
    ) -> None:
        if memory_dir is None:
            from ouro.core.runtime import get_memory_dir

            memory_dir = get_memory_dir()
        self.memory_dir = memory_dir
        self.blocks_dir = os.path.join(memory_dir, "blocks")
        self.llm = llm
        self.block_budgets = dict(block_budgets or DEFAULT_BLOCK_BUDGETS)
        self._lock = asyncio.Lock()

    # ---- low-level I/O ---------------------------------------------------

    def _path(self, block: str) -> str:
        return os.path.join(self.blocks_dir, f"{block}.md")

    def _read_sync(self, block: str) -> str:
        path = self._path(block)
        if not os.path.isfile(path):
            return ""
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except OSError:
            logger.warning("Failed to read block %s", block, exc_info=True)
            return ""

    def _write_sync(self, block: str, content: str) -> None:
        os.makedirs(self.blocks_dir, exist_ok=True)
        path = self._path(block)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)

    async def read(self, block: str) -> str:
        return await asyncio.to_thread(self._read_sync, block)

    # ---- mutation API ----------------------------------------------------

    def _budget(self, block: str) -> int:
        return self.block_budgets.get(block, DEFAULT_BLOCK_BUDGETS.get("scratch", 16000))

    def _is_lenient(self, block: str) -> bool:
        return block in LENIENT_BLOCKS or block not in self.block_budgets

    async def replace(self, block: str, old: str, new: str) -> _Block:
        """Replace *old* substring with *new* in *block*.

        If *old* is empty the entire block is replaced with *new*. Raises
        ``BlockBudgetExceeded`` for strict blocks that would overflow.
        """
        async with self._lock:
            current = await self.read(block)
            if old:
                if old not in current:
                    raise ValueError(
                        f"`old` not found verbatim in block {block!r}. Read the "
                        f"block first to copy the exact text."
                    )
                updated = current.replace(old, new, 1)
            else:
                updated = new

            return await self._commit(block, updated)

    async def append(self, block: str, content: str, *, separator: str = "\n\n") -> _Block:
        """Append *content* to *block*. Lenient blocks FIFO-truncate on overflow."""
        async with self._lock:
            current = await self.read(block)
            budget = self._budget(block)
            if self._is_lenient(block):
                merged = _fifo_truncate(current, content, budget, self.llm)
                return await self._commit(block, merged, skip_budget_check=True)
            new_content = (
                f"{current.rstrip()}{separator}{content.strip()}"
                if current.strip()
                else content.strip()
            )
            return await self._commit(block, new_content)

    async def _commit(self, block: str, content: str, *, skip_budget_check: bool = False) -> _Block:
        budget = self._budget(block)
        tokens = _count_tokens(content, self.llm)
        if not skip_budget_check and tokens > budget:
            current_tokens = _count_tokens(await self.read(block), self.llm)
            raise BlockBudgetExceeded(block, current_tokens, tokens, budget)
        await asyncio.to_thread(self._write_sync, block, content)
        logger.debug("Wrote block %s: %d tokens (budget %d)", block, tokens, budget)
        return _Block(name=block, content=content, tokens=tokens)

    # ---- helpers for compaction integration ------------------------------

    async def append_scratch(self, content: str) -> None:
        """Lenient append to ``scratch``. Never raises — for compaction use."""
        if not content or not content.strip():
            return
        try:
            await self.append("scratch", content)
        except Exception:
            logger.warning("Failed to append to scratch block", exc_info=True)

    async def read_scratch(self) -> str:
        return await self.read("scratch")

    # ---- system-prompt rendering -----------------------------------------

    async def load_and_format(self) -> str | None:
        """Build the ``<long_term_memory>`` section for the system prompt."""
        listing_lines: list[str] = []
        content_lines: list[str] = []
        any_content = False
        for name in sorted(self.block_budgets.keys()):
            budget = self.block_budgets[name]
            body = (await self.read(name)).strip()
            listing_lines.append(f"- {name} — {budget} tokens")
            if body:
                any_content = True
                content_lines.append(f"--- {name} ---\n{body}")
        if any_content:
            block_contents = "\n\n".join(content_lines) + "\n\n"
        else:
            block_contents = "(all blocks are currently empty)\n\n"
        return _INSTRUCTION_TEMPLATE.format(
            memory_dir=self.memory_dir,
            block_listing="\n".join(listing_lines),
            block_contents=block_contents,
        )

    # ---- introspection ---------------------------------------------------

    async def stats(self) -> dict[str, dict[str, Any]]:
        """Return {block_name: {tokens, budget, full_pct}} for diagnostics."""
        out: dict[str, dict[str, Any]] = {}
        for name, budget in self.block_budgets.items():
            body = await self.read(name)
            tokens = _count_tokens(body, self.llm)
            out[name] = {
                "tokens": tokens,
                "budget": budget,
                "full_pct": round(100.0 * tokens / budget, 1) if budget else 0.0,
            }
        return out
