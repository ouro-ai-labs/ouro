"""Simple file-backed store for long-term memory.

Memory is stored as a single ``memory.md`` file in ~/.ouro/memory/.
"""

import asyncio
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_MEMORY_FILE = "memory.md"


class MemoryStore:
    """File-backed store for a single long-term memory markdown file."""

    def __init__(self, memory_dir: Optional[str] = None):
        if memory_dir is None:
            from utils.runtime import get_memory_dir

            memory_dir = get_memory_dir()
        self.memory_dir = memory_dir

    async def load(self) -> str:
        """Read ``memory.md``.

        Returns:
            Content of ``memory.md`` (empty string if missing).
        """
        os.makedirs(self.memory_dir, exist_ok=True)
        path = os.path.join(self.memory_dir, _MEMORY_FILE)
        return await asyncio.to_thread(self._read_file, path)

    async def save(self, content: str) -> None:
        """Write ``memory.md``."""
        os.makedirs(self.memory_dir, exist_ok=True)
        path = os.path.join(self.memory_dir, _MEMORY_FILE)
        await asyncio.to_thread(self._write_file, path, content)

    @staticmethod
    def _read_file(path: str) -> str:
        if not os.path.isfile(path):
            return ""
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except Exception:
            logger.warning("Failed to read memory file %s", path, exc_info=True)
            return ""

    @staticmethod
    def _write_file(path: str, content: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
