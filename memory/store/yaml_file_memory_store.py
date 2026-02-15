"""YAML file-based memory persistence backend.

Stores each session as a human-readable YAML file under .ouro/sessions/.
Directory structure: .ouro/sessions/YYYY-MM-DD_<uuid[:8]>/session.yaml
"""

import asyncio
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiofiles
import aiofiles.os
import yaml

from llm.message_types import LLMMessage
from memory.serialization import (
    deserialize_message,
    serialize_message,
)
from memory.store.memory_store import MemoryStore
from utils.runtime import get_sessions_dir

logger = logging.getLogger(__name__)


class YamlFileMemoryStore(MemoryStore):
    """YAML file-based persistence backend.

    Each session is stored as a directory containing a session.yaml file.
    An .index.yaml file maps session UUIDs to directory names for fast lookup.
    """

    def __init__(self, sessions_dir: Optional[str] = None):
        """Initialize YAML file backend.

        Args:
            sessions_dir: Path to sessions directory (default: .ouro/sessions/)
        """
        self.sessions_dir = sessions_dir or get_sessions_dir()
        self._write_lock = asyncio.Lock()
        self._index: Optional[Dict[str, str]] = None  # UUID -> dir_name

    async def _ensure_dir(self) -> None:
        """Ensure sessions directory exists."""
        await aiofiles.os.makedirs(self.sessions_dir, exist_ok=True)

    def _session_dir_name(self, session_id: str, created_at: datetime) -> str:
        """Generate directory name for a session.

        Args:
            session_id: Session UUID
            created_at: Session creation time

        Returns:
            Directory name like "2025-01-31_a1b2c3d4"
        """
        date_str = created_at.strftime("%Y-%m-%d")
        short_id = session_id[:8]
        return f"{date_str}_{short_id}"

    def _session_yaml_path(self, dir_name: str) -> str:
        """Get path to session.yaml within a session directory."""
        return os.path.join(self.sessions_dir, dir_name, "session.yaml")

    def _index_path(self) -> str:
        """Get path to the index file."""
        return os.path.join(self.sessions_dir, ".index.yaml")

    async def _load_index(self) -> Dict[str, str]:
        """Load or rebuild the UUID -> dir_name index.

        Returns:
            Dict mapping session UUID to directory name
        """
        if self._index is not None:
            return self._index

        index_path = self._index_path()
        if await asyncio.to_thread(os.path.exists, index_path):
            try:
                async with aiofiles.open(index_path, encoding="utf-8") as f:
                    content = await f.read()
                self._index = yaml.safe_load(content) or {}
                return self._index
            except Exception:
                logger.warning("Failed to load index, rebuilding")

        # Rebuild index by scanning directories
        self._index = await self._rebuild_index()
        return self._index

    async def _rebuild_index(self) -> Dict[str, str]:
        """Rebuild index by scanning session directories.

        Returns:
            Dict mapping session UUID to directory name
        """
        index: Dict[str, str] = {}
        if not await asyncio.to_thread(os.path.exists, self.sessions_dir):
            self._index = index
            return index

        entries = await asyncio.to_thread(os.listdir, self.sessions_dir)
        for entry in entries:
            if entry.startswith("."):
                continue
            yaml_path = self._session_yaml_path(entry)
            if not await asyncio.to_thread(os.path.exists, yaml_path):
                continue
            try:
                async with aiofiles.open(yaml_path, encoding="utf-8") as f:
                    content = await f.read()
                data = yaml.safe_load(content)
                if data and "id" in data:
                    index[data["id"]] = entry
            except Exception:
                logger.warning(f"Failed to read session from {entry}")

        self._index = index
        await self._save_index(index)
        return index

    async def _save_index(self, index: Dict[str, str]) -> None:
        """Save index to disk."""
        index_path = self._index_path()
        tmp_path = index_path + ".tmp"
        content = yaml.dump(index, default_flow_style=False, allow_unicode=True)
        async with aiofiles.open(tmp_path, "w", encoding="utf-8") as f:
            await f.write(content)
        await asyncio.to_thread(os.replace, tmp_path, index_path)

    async def _load_session_data(self, dir_name: str) -> Optional[Dict[str, Any]]:
        """Load raw YAML data from a session directory.

        Args:
            dir_name: Session directory name

        Returns:
            Parsed YAML data or None
        """
        yaml_path = self._session_yaml_path(dir_name)
        if not await asyncio.to_thread(os.path.exists, yaml_path):
            return None
        async with aiofiles.open(yaml_path, encoding="utf-8") as f:
            content = await f.read()
        return yaml.safe_load(content)

    async def _save_session_data(self, dir_name: str, data: Dict[str, Any]) -> None:
        """Atomically write session data to YAML file.

        Args:
            dir_name: Session directory name
            data: Session data to write
        """
        session_dir = os.path.join(self.sessions_dir, dir_name)
        await aiofiles.os.makedirs(session_dir, exist_ok=True)

        yaml_path = self._session_yaml_path(dir_name)
        tmp_path = yaml_path + ".tmp"

        content = yaml.dump(
            data,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            width=120,
        )
        async with aiofiles.open(tmp_path, "w", encoding="utf-8") as f:
            await f.write(content)
        await asyncio.to_thread(os.replace, tmp_path, yaml_path)

    async def _resolve_session_dir(self, session_id: str) -> Optional[str]:
        """Resolve a session ID to its directory name.

        Supports full UUID and prefix matching.

        Args:
            session_id: Full or prefix of session UUID

        Returns:
            Directory name or None
        """
        index = await self._load_index()

        # Exact match
        if session_id in index:
            return index[session_id]

        # Prefix match
        matches = [(sid, dir_name) for sid, dir_name in index.items() if sid.startswith(session_id)]
        if len(matches) == 1:
            return matches[0][1]
        elif len(matches) > 1:
            logger.warning(f"Ambiguous session prefix '{session_id}', {len(matches)} matches")

        return None

    async def create_session(self, metadata: Optional[Dict[str, Any]] = None) -> str:
        await self._ensure_dir()

        session_id = str(uuid.uuid4())
        now = datetime.now()
        dir_name = self._session_dir_name(session_id, now)

        data = {
            "id": session_id,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "system_messages": [],
            "messages": [],
        }

        async with self._write_lock:
            await self._save_session_data(dir_name, data)
            index = await self._load_index()
            index[session_id] = dir_name
            await self._save_index(index)

        logger.info(f"Created session {session_id} in {dir_name}")
        return session_id

    async def save_message(self, session_id: str, message: LLMMessage, tokens: int = 0) -> None:
        dir_name = await self._resolve_session_dir(session_id)
        if not dir_name:
            logger.warning(f"Session {session_id} not found")
            return

        async with self._write_lock:
            data = await self._load_session_data(dir_name)
            if not data:
                logger.warning(f"Session {session_id} not found")
                return

            field = "system_messages" if message.role == "system" else "messages"
            msg_data = serialize_message(message)
            msg_data["tokens"] = tokens
            data[field].append(msg_data)
            data["updated_at"] = datetime.now().isoformat()

            await self._save_session_data(dir_name, data)

    async def save_memory(
        self,
        session_id: str,
        system_messages: List[LLMMessage],
        messages: List[LLMMessage],
    ) -> None:
        dir_name = await self._resolve_session_dir(session_id)
        if not dir_name:
            logger.warning(f"Session {session_id} not found")
            return

        async with self._write_lock:
            data = await self._load_session_data(dir_name)
            if not data:
                logger.warning(f"Session {session_id} not found")
                return

            data["system_messages"] = [serialize_message(msg) for msg in system_messages]

            messages_list = []
            for msg in messages:
                msg_data = serialize_message(msg)
                msg_data["tokens"] = 0
                messages_list.append(msg_data)
            data["messages"] = messages_list

            data["updated_at"] = datetime.now().isoformat()

            await self._save_session_data(dir_name, data)

        logger.debug(
            f"Saved memory for session {session_id}: "
            f"{len(system_messages)} system msgs, "
            f"{len(messages)} messages"
        )

    async def load_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        dir_name = await self._resolve_session_dir(session_id)
        if not dir_name:
            logger.warning(f"Session {session_id} not found")
            return None

        data = await self._load_session_data(dir_name)
        if not data:
            return None

        system_messages = [deserialize_message(msg) for msg in (data.get("system_messages") or [])]
        messages = [deserialize_message(msg) for msg in (data.get("messages") or [])]

        return {
            "config": None,
            "system_messages": system_messages,
            "messages": messages,
            "stats": {
                "created_at": data.get("created_at", ""),
            },
        }

    async def list_sessions(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        await self._ensure_dir()
        index = await self._load_index()

        sessions = []
        for session_id, dir_name in index.items():
            data = await self._load_session_data(dir_name)
            if not data:
                continue

            messages_data = data.get("messages") or []
            system_messages_data = data.get("system_messages") or []

            # Extract first user message as preview
            first_user_msg = ""
            for msg in messages_data:
                if msg.get("role") == "user" and isinstance(msg.get("content"), str):
                    first_user_msg = msg["content"][:100]
                    break

            sessions.append(
                {
                    "id": session_id,
                    "created_at": data.get("created_at", ""),
                    "updated_at": data.get("updated_at", ""),
                    "message_count": len(messages_data),
                    "system_message_count": len(system_messages_data),
                    "preview": first_user_msg,
                }
            )

        # Sort by updated_at descending
        sessions.sort(key=lambda s: s.get("updated_at", ""), reverse=True)

        return sessions[offset : offset + limit]

    async def delete_session(self, session_id: str) -> bool:
        dir_name = await self._resolve_session_dir(session_id)
        if not dir_name:
            return False

        session_dir = os.path.join(self.sessions_dir, dir_name)

        async with self._write_lock:
            # Remove files in directory
            if await asyncio.to_thread(os.path.exists, session_dir):
                entries = await asyncio.to_thread(os.listdir, session_dir)
                for entry in entries:
                    entry_path = os.path.join(session_dir, entry)
                    await aiofiles.os.remove(entry_path)
                await asyncio.to_thread(os.rmdir, session_dir)

            # Update index
            index = await self._load_index()
            # Find and remove by dir_name (session_id might be prefix)
            to_remove = [sid for sid, dn in index.items() if dn == dir_name]
            for sid in to_remove:
                del index[sid]
            await self._save_index(index)

        logger.info(f"Deleted session {session_id}")
        return True

    async def get_session_stats(self, session_id: str) -> Optional[Dict[str, Any]]:
        dir_name = await self._resolve_session_dir(session_id)
        if not dir_name:
            return None

        data = await self._load_session_data(dir_name)
        if not data:
            return None

        messages_data = data.get("messages") or []
        system_messages_data = data.get("system_messages") or []
        total_message_tokens = sum(m.get("tokens", 0) for m in messages_data)

        return {
            "session_id": session_id,
            "created_at": data.get("created_at", ""),
            "updated_at": data.get("updated_at", ""),
            "message_count": len(messages_data),
            "system_message_count": len(system_messages_data),
            "total_message_tokens": total_message_tokens,
        }

    async def find_latest_session(self) -> Optional[str]:
        """Find the most recently updated session ID.

        Returns:
            Session ID or None if no sessions exist
        """
        sessions = await self.list_sessions(limit=1)
        if sessions:
            return sessions[0]["id"]
        return None

    async def find_session_by_prefix(self, prefix: str) -> Optional[str]:
        """Find a session by ID prefix.

        Args:
            prefix: Prefix of session UUID

        Returns:
            Full session ID or None
        """
        index = await self._load_index()
        matches = [sid for sid in index if sid.startswith(prefix)]
        if len(matches) == 1:
            return matches[0]
        elif len(matches) > 1:
            logger.warning(f"Ambiguous prefix '{prefix}': {len(matches)} matches")
        return None
