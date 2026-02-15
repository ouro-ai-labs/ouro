"""Git-backed store for long-term memory.

Memory files live in ~/.ouro/memory/ as markdown files, managed by a local
git repo for change tracking and concurrency detection.
"""

import asyncio
import logging
import os
import shutil
import subprocess
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class MemoryCategory(str, Enum):
    """Categories for long-term memory entries."""

    DECISIONS = "decisions"
    PREFERENCES = "preferences"
    FACTS = "facts"


class GitMemoryStore:
    """Git-backed store for long-term memory markdown files.

    Each category is a free-form markdown file.  The agent decides the
    content and structure; the store just reads/writes raw text.
    """

    def __init__(self, memory_dir: Optional[str] = None):
        if memory_dir is None:
            from utils.runtime import get_memory_dir

            memory_dir = get_memory_dir()
        self.memory_dir = memory_dir
        self._loaded_head: Optional[str] = None

    # ------------------------------------------------------------------
    # Git infrastructure
    # ------------------------------------------------------------------

    async def ensure_repo(self) -> None:
        """Initialize a git repo in memory_dir if one doesn't exist."""
        os.makedirs(self.memory_dir, exist_ok=True)
        git_dir = os.path.join(self.memory_dir, ".git")
        if not os.path.isdir(git_dir):
            await self._run_git("init")
            # Ensure commits work even without a global git config
            await self._run_git("config", "user.name", "ouro")
            await self._run_git("config", "user.email", "ouro@local")
            logger.info("Initialized long-term memory git repo at %s", self.memory_dir)

    async def get_current_head(self) -> Optional[str]:
        """Return current HEAD commit hash, or None if no commits yet."""
        try:
            out = await self._run_git("rev-parse", "HEAD")
            return out.strip() or None
        except subprocess.CalledProcessError:
            return None

    async def has_changed_since_load(self) -> bool:
        """Return True if HEAD differs from the snapshot taken at load time."""
        current = await self.get_current_head()
        return current != self._loaded_head

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def load_all(self) -> dict[MemoryCategory, str]:
        """Read all category markdown files and snapshot the HEAD hash.

        Returns:
            Mapping of category to file content (empty string if missing).
        """
        await self.ensure_repo()
        self._loaded_head = await self.get_current_head()

        memories: dict[MemoryCategory, str] = {}
        for cat in MemoryCategory:
            path = os.path.join(self.memory_dir, f"{cat.value}.md")
            memories[cat] = await asyncio.to_thread(self._read_file, path)
        return memories

    @staticmethod
    def _read_file(path: str) -> str:
        """Synchronously read a memory file as raw text."""
        if not os.path.isfile(path):
            return ""
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except Exception:
            logger.warning("Failed to read memory file %s", path, exc_info=True)
            return ""

    # ------------------------------------------------------------------
    # Write (used by consolidator only)
    # ------------------------------------------------------------------

    async def save_and_commit(
        self,
        memories: dict[MemoryCategory, str],
        message: str,
    ) -> None:
        """Write all category files and create a git commit.

        This is intended for the consolidator after merging/pruning entries.
        Normal agent writes go through file tools + shell git commands.
        """
        await self.ensure_repo()

        for cat in MemoryCategory:
            path = os.path.join(self.memory_dir, f"{cat.value}.md")
            content = memories.get(cat, "")
            await asyncio.to_thread(self._write_file, path, content)

        await self._run_git("add", "-A")

        # Only commit if there are staged changes
        try:
            await self._run_git("diff", "--cached", "--quiet")
            # No changes staged — skip commit
            return
        except subprocess.CalledProcessError:
            # Changes exist — proceed to commit
            pass

        await self._run_git("commit", "-m", message)

    @staticmethod
    def _write_file(path: str, content: str) -> None:
        """Synchronously write a memory file."""
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _run_git(self, *args: str) -> str:
        """Execute a git command in memory_dir via subprocess."""
        git_bin = shutil.which("git") or "git"
        cmd = [git_bin, "-C", self.memory_dir, *args]
        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout
