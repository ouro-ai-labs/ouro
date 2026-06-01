"""MemoryManager — long-term memory + session persistence.

The conversation list itself lives on the loop's
``MessageListContext`` (see ``ouro.core.loop.context``).  This class
owns the parts that belong to the *capability* layer:

- ``YamlFileMemoryStore`` — session save/load on disk.
- ``MemoryBlockManager`` — named, size-bounded markdown blocks for
  cross-session memory; always on. Replaces the old
  ``LongTermMemoryManager`` (memory.md + daily files).
- ``CompactionManager`` — compaction policy + LLM-driven compressor;
  exposed via ``self.compaction`` for ``CompactionHook`` to pick up.
- ``TokenTracker`` — cumulative input/output/cache token + cost
  accounting across the session.

Callers pass a ``MessageListContext`` to ``save_memory``,
``get_stats``, and ``compress``; the manager itself does *not*
hold a copy of the conversation.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ouro.capabilities.compaction import CompactionManager
from ouro.core.llm.message_types import LLMMessage
from ouro.core.loop import MessageListContext
from ouro.core.loop.protocols import NullProgressSink, ProgressSink

from .blocks import MemoryBlockManager
from .token_tracker import TokenTracker

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ouro.core.llm import LiteLLMAdapter


class MemoryManager:
    """Long-term memory + session persistence + compaction wiring."""

    def __init__(
        self,
        llm: LiteLLMAdapter,
        session_id: str | None = None,
        sessions_dir: str | None = None,
        memory_dir: str | None = None,
        progress: ProgressSink | None = None,
    ) -> None:
        self.llm = llm
        self._progress: ProgressSink = progress or NullProgressSink()

        from .store import YamlFileMemoryStore

        self._store = YamlFileMemoryStore(sessions_dir=sessions_dir)

        # Lazy session creation: real session is created on first save.
        if session_id is not None:
            self.session_id: str | None = session_id
            self._session_created = True
        else:
            self.session_id = None
            self._session_created = False

        self.token_tracker = TokenTracker()
        self._compaction = CompactionManager(llm)

        # Conversation recall (FTS5 over historical messages — no embedder).
        # Created lazily on first save_memory; only when feature is enabled.
        self._recall_index: Any = None
        self._recall_memory_dir = memory_dir

        # Memory blocks — always on; replaces the old memory.md + daily files.
        self._long_term: MemoryBlockManager = MemoryBlockManager(llm, memory_dir=memory_dir)

    # ------------------------------------------------------------------
    # Session loading / lookup
    # ------------------------------------------------------------------

    @classmethod
    async def from_session(
        cls,
        session_id: str,
        llm: LiteLLMAdapter,
        sessions_dir: str | None = None,
        memory_dir: str | None = None,
        progress: ProgressSink | None = None,
    ) -> tuple[MemoryManager, MessageListContext]:
        """Load a MemoryManager and the persisted conversation from disk.

        Returns:
            ``(manager, context)`` — caller installs ``context`` as the
            agent's persistent ``MessageListContext`` (e.g.
            ``ComposedAgent.load_session``).
        """
        manager = cls(
            llm=llm,
            session_id=session_id,
            sessions_dir=sessions_dir,
            memory_dir=memory_dir,
            progress=progress,
        )

        session_data = await manager._store.load_session(session_id)
        if not session_data:
            raise ValueError(f"Session {session_id} not found")

        context = MessageListContext(
            system_messages=session_data.get("system_messages") or [],
            detached=session_data.get("messages") or [],
        )

        # Restore token usage statistics if present
        token_stats = session_data.get("token_stats")
        if token_stats:
            manager.token_tracker.total_input_tokens = token_stats.get("total_input_tokens", 0)
            manager.token_tracker.total_output_tokens = token_stats.get("total_output_tokens", 0)
            manager.token_tracker.total_cache_read_tokens = token_stats.get(
                "total_cache_read_tokens", 0
            )
            manager.token_tracker.total_cache_creation_tokens = token_stats.get(
                "total_cache_creation_tokens", 0
            )
            manager.token_tracker.compression_savings = token_stats.get("compression_savings", 0)
            manager.token_tracker.compression_cost = token_stats.get("compression_cost", 0)
            logger.info(
                f"Restored token stats for session {session_id}: "
                f"input={manager.token_tracker.total_input_tokens}, "
                f"output={manager.token_tracker.total_output_tokens}, "
                f"cache_read={manager.token_tracker.total_cache_read_tokens}, "
                f"cache_creation={manager.token_tracker.total_cache_creation_tokens}"
            )

        logger.info(
            f"Loaded session {session_id}: "
            f"{len(context.detached)} messages, "
            f"{len(context.system_messages)} system messages"
        )
        return manager, context

    @staticmethod
    async def list_sessions(
        limit: int = 50, sessions_dir: str | None = None
    ) -> list[dict[str, Any]]:
        from .store import YamlFileMemoryStore

        store = YamlFileMemoryStore(sessions_dir=sessions_dir)
        return await store.list_sessions(limit=limit)

    @staticmethod
    async def find_latest_session(sessions_dir: str | None = None) -> str | None:
        from .store import YamlFileMemoryStore

        store = YamlFileMemoryStore(sessions_dir=sessions_dir)
        return await store.find_latest_session()

    @staticmethod
    async def find_session_by_prefix(prefix: str, sessions_dir: str | None = None) -> str | None:
        from .store import YamlFileMemoryStore

        store = YamlFileMemoryStore(sessions_dir=sessions_dir)
        return await store.find_session_by_prefix(prefix)

    async def _ensure_session(self) -> None:
        """Lazily create a session ID on first persistence.

        Avoids creating empty sessions when ``MemoryManager`` is
        instantiated but no save ever happens.
        """
        if not self._session_created:
            try:
                self.session_id = await self._store.create_session()
                self._session_created = True
                logger.info(f"Created new session: {self.session_id}")
            except Exception as e:
                logger.error(f"Failed to create session: {e}")
                raise RuntimeError(f"Failed to create memory session: {e}") from e

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def long_term(self) -> MemoryBlockManager:
        """Access the long-term memory manager (always available; never None)."""
        return self._long_term

    @property
    def compaction(self) -> CompactionManager:
        """Public handle to the underlying ``CompactionManager``.

        ``CompactionHook`` consumes this in ``AgentBuilder`` /
        ``ComposedAgent.load_session`` to rebind on session load and
        model switch.
        """
        return self._compaction

    def set_todo_context_provider(self, provider) -> None:
        """Forward the todo-context provider through to compaction."""
        self._compaction.set_todo_context_provider(provider)

    # ------------------------------------------------------------------
    # Operations on a MessageListContext
    # ------------------------------------------------------------------

    async def save_single_message(self, message: LLMMessage, tokens: int = 0) -> None:
        """Persist a single message incrementally.

        Used by ``SessionPersistenceHook`` to flush messages to disk
        after every iteration, rather than waiting for the end of the
        turn.  Lazily creates the session on first call.
        """
        if not self._session_created:
            await self._ensure_session()

        if not self._store or not self._session_created or not self.session_id:
            logger.debug("Skipping save_single_message: no session created")
            return

        await self._store.save_message(self.session_id, message, tokens)

    async def save_memory(self, *, context: MessageListContext) -> None:
        """Persist the conversation snapshot to disk.

        Skips entirely (no session file created) when both
        ``system_messages`` and ``detached`` are empty.  Otherwise,
        lazily creates the session on first call.
        """
        sys_msgs = list(context.system_messages)
        messages = context.detached.snapshot()

        if not messages and not sys_msgs:
            logger.debug("Skipping save_memory: empty context")
            return

        if not self._session_created:
            await self._ensure_session()

        if not self._store or not self._session_created or not self.session_id:
            logger.debug("Skipping save_memory: no session created")
            return

        # Build token stats snapshot for persistence
        token_stats = {
            "total_input_tokens": self.token_tracker.total_input_tokens,
            "total_output_tokens": self.token_tracker.total_output_tokens,
            "total_cache_read_tokens": self.token_tracker.total_cache_read_tokens,
            "total_cache_creation_tokens": self.token_tracker.total_cache_creation_tokens,
            "compression_savings": self.token_tracker.compression_savings,
            "compression_cost": self.token_tracker.compression_cost,
        }

        await self._store.save_memory(
            session_id=self.session_id,
            system_messages=sys_msgs,
            messages=messages,
            token_stats=token_stats,
        )
        # Reindex FTS recall — best-effort, never blocks the save path.
        try:
            await self._get_recall_index().reindex_session(self.session_id, messages)
        except Exception:
            logger.warning("Failed to reindex recall FTS", exc_info=True)
        logger.info(f"Saved memory state for session {self.session_id}")

    def _get_recall_index(self) -> Any:
        """Lazy-instantiate the FTS recall index."""
        if self._recall_index is None:
            from ouro.capabilities.memory.recall import RecallIndex
            from ouro.core.runtime import get_memory_dir

            memory_dir = self._recall_memory_dir or get_memory_dir()
            self._recall_index = RecallIndex(memory_dir)
        return self._recall_index

    @property
    def recall_index(self) -> Any:
        """Public accessor for the recall index."""
        return self._get_recall_index()

    def get_stats(self, *, context: MessageListContext) -> dict[str, Any]:
        """Return token usage + cost stats for the current run.

        ``current_tokens`` is recomputed from the passed context each
        call (system + detached).  Token-tracker fields are cumulative
        across the session.
        """
        detached = context.detached.snapshot()
        msg_count = len(detached)
        current_tokens = self._compaction.estimate_tokens(list(context.system_messages) + detached)

        return {
            "current_tokens": current_tokens,
            "total_input_tokens": self.token_tracker.total_input_tokens,
            "total_output_tokens": self.token_tracker.total_output_tokens,
            "cache_read_tokens": self.token_tracker.total_cache_read_tokens,
            "cache_creation_tokens": self.token_tracker.total_cache_creation_tokens,
            "compression_count": self._compaction.compression_count,
            "total_savings": self.token_tracker.compression_savings,
            "compression_cost": self.token_tracker.compression_cost,
            "net_savings": (
                self.token_tracker.compression_savings - self.token_tracker.compression_cost
            ),
            "message_count": msg_count,
            "detached_message_count": msg_count,
            # Legacy alias retained for terminal_ui / bot stats display.
            "short_term_count": msg_count,
            "total_cost": self.token_tracker.get_total_cost(self.llm.model),
            "ltm_enabled": True,
        }

    async def compress(
        self,
        *,
        context: MessageListContext,
        strategy: str | None = None,
    ):
        """Manually compress ``context.detached`` in place.

        Returns the same ``CompressedMemory`` result the
        ``CompactionManager`` produces, or ``None`` when there's
        nothing to compress.
        """
        snap = context.detached.snapshot()
        if not snap:
            logger.warning("No messages to compress")
            return None

        current_tokens = self._compaction.estimate_tokens(list(context.system_messages) + snap)
        compressed = await self._compaction.compress(
            snap,
            strategy=strategy,
            target_tokens=self._compaction._calculate_target_tokens(current_tokens),
        )
        if compressed is None:
            return None

        self.token_tracker.add_compression_savings(compressed.token_savings)
        self.token_tracker.add_compression_cost(compressed.compressed_tokens)
        context.detached.replace(compressed.messages)

        logger.info(
            f"✅ Compression complete: "
            f"{compressed.original_tokens} → {compressed.compressed_tokens} tokens "
            f"({compressed.savings_percentage:.1f}% saved, "
            f"ratio: {compressed.compression_ratio:.2f})"
        )
        return compressed

    def reset(self) -> None:
        """Reset cumulative state (token tracker + compaction state).

        The conversation lives on the caller's ``MessageListContext``;
        clearing that is the caller's responsibility.
        """
        self.token_tracker.reset()
        self._compaction.reset()
