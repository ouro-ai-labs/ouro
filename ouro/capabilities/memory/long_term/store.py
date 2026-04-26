"""Simple file-backed store for long-term memory.

Permanent memories live in ``memory.md``; daily running notes live in
``YYYY-MM-DD.md`` files inside the same directory.
"""

import asyncio
import contextlib
import logging
import os
import re
from datetime import date, timedelta
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

_MEMORY_FILE = "memory.md"
_DAILY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")


class MemoryStore:
    """File-backed store for long-term memory (permanent + daily files)."""

    def __init__(self, memory_dir: Optional[str] = None):
        if memory_dir is None:
            from ouro.core.runtime import get_memory_dir

            memory_dir = get_memory_dir()
        self.memory_dir = memory_dir
        os.makedirs(self.memory_dir, exist_ok=True)

    def _daily_path(self, dt: date) -> str:
        return os.path.join(self.memory_dir, f"{dt.isoformat()}.md")

    # ------------------------------------------------------------------
    # Permanent memory (memory.md)
    # ------------------------------------------------------------------

    async def load(self) -> str:
        """Read ``memory.md``.

        Returns:
            Content of ``memory.md`` (empty string if missing).
        """
        path = os.path.join(self.memory_dir, _MEMORY_FILE)
        return await asyncio.to_thread(self._read_file, path)

    async def save(self, content: str) -> None:
        """Write ``memory.md``."""
        path = os.path.join(self.memory_dir, _MEMORY_FILE)
        await asyncio.to_thread(self._write_file, path, content)

    # ------------------------------------------------------------------
    # Daily files (YYYY-MM-DD.md)
    # ------------------------------------------------------------------

    async def load_daily(self, dt: date) -> str:
        """Read a daily file.

        Returns:
            Content of ``YYYY-MM-DD.md`` (empty string if missing).
        """
        return await asyncio.to_thread(self._read_file, self._daily_path(dt))

    async def save_daily(self, dt: date, content: str) -> None:
        """Write a daily file (overwrites)."""
        await asyncio.to_thread(self._write_file, self._daily_path(dt), content)

    async def append_daily(self, dt: date, content: str) -> None:
        """Append *content* to a daily file, creating it if needed."""
        await asyncio.to_thread(self._append_file, self._daily_path(dt), content)

    async def list_daily_files(self) -> List[date]:
        """List daily files sorted descending (most recent first)."""
        return await asyncio.to_thread(self._list_daily_files_sync)

    async def load_recent_dailies(self, window_days: int) -> List[Tuple[date, str]]:
        """Load daily files from the last *window_days* days (non-empty only).

        Returns:
            List of ``(date, content)`` tuples sorted ascending (oldest first).
        """
        today = date.today()
        results: List[Tuple[date, str]] = []
        for offset in range(window_days):
            dt = today - timedelta(days=offset)
            content = await self.load_daily(dt)
            if content.strip():
                results.append((dt, content))
        results.reverse()
        return results

    async def prune_old_dailies(self, retention_days: int) -> int:
        """Delete daily files older than *retention_days*.

        Returns:
            Number of files deleted.
        """
        cutoff = date.today() - timedelta(days=retention_days)
        all_dates = await self.list_daily_files()
        count = 0
        for dt in all_dates:
            if dt < cutoff:
                await asyncio.to_thread(self._remove_file, self._daily_path(dt))
                count += 1
        return count

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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

    @staticmethod
    def _append_file(path: str, content: str) -> None:
        with open(path, "a", encoding="utf-8") as f:
            if f.tell() > 0:
                f.write("\n")
            f.write(content)

    def _list_daily_files_sync(self) -> List[date]:
        if not os.path.isdir(self.memory_dir):
            return []
        dates: List[date] = []
        for name in os.listdir(self.memory_dir):
            if _DAILY_RE.match(name):
                try:
                    dates.append(date.fromisoformat(name.removesuffix(".md")))
                except ValueError:
                    continue
        dates.sort(reverse=True)
        return dates

    @staticmethod
    def _remove_file(path: str) -> None:
        with contextlib.suppress(FileNotFoundError):
            os.remove(path)
