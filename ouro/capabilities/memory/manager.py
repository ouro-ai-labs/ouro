"""MemoryManager owns the detached message list and provides the *mechanisms*
(persistence, compression, token tracking).  ``MemoryHook`` (in ``hook.py``)
adapts it into the core loop's ``Hook`` protocol; the *policy* (when to
persist, when to compress) lives in ``MemoryHook``.
"""

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import litellm

from ouro.capabilities.compaction import CompactionManager
from ouro.config import Config
from ouro.core.llm.message_types import LLMMessage
from ouro.core.loop import MessageListContext
from ouro.core.loop.protocols import NullProgressSink, ProgressSink

from .token_tracker import TokenTracker

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ouro.core.llm import LiteLLMAdapter

    from .long_term import LongTermMemoryManager


class MemoryManager:
    """Central memory management system with built-in persistence.

    The persistence store is fully owned by MemoryManager and should not
    be created or passed in from outside.
    """

    def __init__(
        self,
        llm: "LiteLLMAdapter",
        session_id: Optional[str] = None,
        sessions_dir: Optional[str] = None,
        memory_dir: Optional[str] = None,
        progress: Optional[ProgressSink] = None,
    ):
        """Initialize memory manager.

        Args:
            llm: LLM instance for compression
            session_id: Optional session ID (if resuming session)
            sessions_dir: Optional custom sessions directory (default: ~/.ouro/sessions/)
            memory_dir: Optional custom long-term memory directory (default: ~/.ouro/memory/)
            progress: Optional ProgressSink for UI feedback during standalone
                compression. Defaults to a no-op sink. The cache-safe
                compaction path driven by the agent loop does NOT use this —
                the loop owns its own spinner there.
        """
        self.llm = llm
        self._progress: ProgressSink = progress or NullProgressSink()

        # Store is fully owned by MemoryManager
        from .store import YamlFileMemoryStore

        self._store = YamlFileMemoryStore(sessions_dir=sessions_dir)

        # Lazy session creation: only create when first message is added
        # If session_id is provided (resuming), use it immediately
        if session_id is not None:
            self.session_id = session_id
            self._session_created = True
        else:
            self.session_id = None
            self._session_created = False

        # Initialize components using Config directly
        # NOTE: short_term memory has been removed.  Message storage now lives
        # in ``MemoryManager._detached_messages``.  MemoryManager provides
        # *hooks* that mutate the message list at lifecycle points.
        self.token_tracker = TokenTracker()

        # Compaction logic is delegated to CompactionManager
        self._compaction = CompactionManager(llm)

        # Storage for system messages — still owned here because they are
        # session-scoped and rarely change.
        self.system_messages: List[LLMMessage] = []

        # State tracking
        self.current_tokens = 0

        # Tool schema token overhead (counted once per session)
        self._tool_schema_tokens: int = 0

        # Long-term memory (cross-session)
        self._long_term = None
        if Config.LONG_TERM_MEMORY_ENABLED:
            from .long_term import LongTermMemoryManager

            self._long_term = LongTermMemoryManager(llm, memory_dir=memory_dir)
            self._compaction.set_long_term(self._long_term)

    @classmethod
    async def from_session(
        cls,
        session_id: str,
        llm: "LiteLLMAdapter",
        sessions_dir: Optional[str] = None,
        memory_dir: Optional[str] = None,
        progress: Optional[ProgressSink] = None,
    ) -> "tuple[MemoryManager, MessageListContext]":
        """Load a MemoryManager and the persisted conversation from disk.

        Returns:
            Tuple of (manager, context).  ``context`` is a fresh
            ``MessageListContext`` populated with the session's
            system messages and detached messages.  Callers (e.g.
            ``ComposedAgent.load_session``) install it as the agent's
            persistent conversation state.
        """
        manager = cls(
            llm=llm,
            session_id=session_id,
            sessions_dir=sessions_dir,
            memory_dir=memory_dir,
            progress=progress,
        )

        # Load session data
        session_data = await manager._store.load_session(session_id)
        if not session_data:
            raise ValueError(f"Session {session_id} not found")

        sys_msgs = list(session_data.get("system_messages") or [])
        detached_msgs = list(session_data.get("messages") or [])

        context = MessageListContext(
            system_messages=sys_msgs,
            detached=detached_msgs,
        )

        # Mirror into the manager's legacy fields so anything still
        # reading them (stats, compress, _recalculate_current_tokens)
        # keeps working until the rest of the refactor lands.
        manager.system_messages = sys_msgs
        manager._detached_messages = detached_msgs
        manager.current_tokens = manager._recalculate_current_tokens()

        logger.info(
            f"Loaded session {session_id}: "
            f"{len(detached_msgs)} messages, "
            f"{manager.current_tokens} tokens"
        )

        return manager, context

    @staticmethod
    async def list_sessions(
        limit: int = 50, sessions_dir: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List saved sessions.

        Args:
            limit: Maximum number of sessions to return
            sessions_dir: Optional custom sessions directory

        Returns:
            List of session summaries
        """
        from .store import YamlFileMemoryStore

        store = YamlFileMemoryStore(sessions_dir=sessions_dir)
        return await store.list_sessions(limit=limit)

    @staticmethod
    async def find_latest_session(sessions_dir: Optional[str] = None) -> Optional[str]:
        """Find the most recently updated session ID.

        Args:
            sessions_dir: Optional custom sessions directory

        Returns:
            Session ID or None if no sessions exist
        """
        from .store import YamlFileMemoryStore

        store = YamlFileMemoryStore(sessions_dir=sessions_dir)
        return await store.find_latest_session()

    @staticmethod
    async def find_session_by_prefix(
        prefix: str, sessions_dir: Optional[str] = None
    ) -> Optional[str]:
        """Find a session by ID prefix.

        Args:
            prefix: Prefix of session UUID
            sessions_dir: Optional custom sessions directory

        Returns:
            Full session ID or None
        """
        from .store import YamlFileMemoryStore

        store = YamlFileMemoryStore(sessions_dir=sessions_dir)
        return await store.find_session_by_prefix(prefix)

    async def _ensure_session(self) -> None:
        """Lazily create session when first needed.

        This avoids creating empty sessions when MemoryManager is instantiated
        but no messages are ever added (e.g., user exits before running any task).

        Raises:
            RuntimeError: If session creation fails
        """
        if not self._session_created:
            try:
                self.session_id = await self._store.create_session()
                self._session_created = True
                logger.info(f"Created new session: {self.session_id}")
            except Exception as e:
                logger.error(f"Failed to create session: {e}")
                raise RuntimeError(f"Failed to create memory session: {e}") from e

    # ==================================================================
    # Public API (used by MemoryHook and other callers)
    # ==================================================================

    async def add_message(self, message: LLMMessage, usage: Dict[str, int] = None) -> None:
        """Add a message to the internal detached list.

        Used by MemoryHook (after_call / after_tool) and legacy callers
        that haven't migrated to the hook API.
        """
        await self._ensure_session()

        if message.role == "system":
            self.system_messages.append(message)
            return

        if usage:
            self.token_tracker.record_usage(usage)

        # Store in a temporary detached list
        if not hasattr(self, "_detached_messages"):
            self._detached_messages: List[LLMMessage] = []
        self._detached_messages.append(message)

        self.current_tokens = self._recalculate_current_tokens()
        self._compaction.was_compressed_last_iteration = False
        should_compress, reason = self._compaction.should_compress(self.current_tokens)
        if should_compress:
            self._compaction.mark_compression_needed(reason or "threshold_exceeded")

    def get_context_for_llm(self) -> List[LLMMessage]:
        """Legacy helper — builds context from internal state.

        Used by callers that still expect MemoryManager to hold messages.
        """
        context = list(self.system_messages)
        if hasattr(self, "_detached_messages"):
            context.extend(self._detached_messages)
        return context

    @property
    def long_term(self) -> Optional["LongTermMemoryManager"]:
        """Access the long-term memory manager (None if disabled)."""
        return self._long_term

    @property
    def compression_count(self) -> int:
        """Pass-through to the underlying ``CompactionManager``.

        Kept as a property so legacy tests / call sites that reach for
        ``memory.compression_count`` still work after compaction was
        extracted into its own subpackage.
        """
        return self._compaction.compression_count

    @property
    def was_compressed_last_iteration(self) -> bool:
        """Pass-through to ``CompactionManager`` for legacy callers."""
        return self._compaction.was_compressed_last_iteration

    @property
    def compaction(self) -> "CompactionManager":
        """Public handle to the underlying CompactionManager.

        Used by ``CompactionHook`` (the new wiring) so capability code
        doesn't have to reach for the private ``_compaction`` attribute.
        Internal callers within this module still use ``self._compaction``.
        """
        return self._compaction

    def set_todo_context_provider(self, provider) -> None:
        """Set a callback to provide current todo context for compression.

        Delegates to the CompactionManager.
        """
        self._compaction.set_todo_context_provider(provider)

    def set_tool_schemas(self, schemas: list) -> None:
        """Calculate and cache the token overhead of tool schemas.

        Tool schemas are sent with every API call but were previously
        not counted towards context size.  This method computes their
        token cost once (schemas don't change within a session).

        Args:
            schemas: List of tool schema dicts (OpenAI function-calling format)
        """
        if not schemas:
            self._tool_schema_tokens = 0
            return

        model = self.llm.model
        dummy_msg = {"role": "user", "content": "x"}
        try:
            base = litellm.token_counter(model=model, messages=[dummy_msg])
            with_tools = litellm.token_counter(model=model, messages=[dummy_msg], tools=schemas)
            self._tool_schema_tokens = max(0, with_tools - base)
        except Exception as e:
            logger.debug(f"Failed to count tool schema tokens: {e}")
            self._tool_schema_tokens = 0

        logger.info(f"Tool schema token overhead: {self._tool_schema_tokens}")

    def needs_compression(self) -> bool:
        """Check if compression is needed (called by _react_loop).

        Delegates to CompactionManager.
        """
        return self._compaction.needs_compression()

    async def _build_compaction_prompt(self) -> LLMMessage:
        """Build the compaction instruction as a user message.

        Delegates to CompactionManager.
        """
        messages = list(getattr(self, "_detached_messages", []))
        return await self._compaction.build_compaction_prompt(messages, self.current_tokens)

    # Legacy alias — some callers still reference get_compaction_prompt()
    async def get_compaction_prompt(self) -> LLMMessage:
        """Deprecated — use ``_build_compaction_prompt()`` instead."""
        return await self._build_compaction_prompt()

    def apply_compression(
        self,
        summary_text: str,
        messages: Optional[List[LLMMessage]] = None,
        usage: Optional[Dict[str, int]] = None,
    ) -> None:
        """Apply the LLM's summary to compress memory.

        Delegates to CompactionManager, then updates internal state.
        """
        if messages is None:
            messages = list(getattr(self, "_detached_messages", []))

        if not messages:
            self._compaction.clear_compression_needed()
            return

        result_messages = self._compaction.apply_compression(summary_text, messages, usage)

        # Track usage from compression LLM call
        if usage:
            self.token_tracker.record_usage(usage)

        # Track compression results in token tracker
        self.token_tracker.add_compression_savings(self._compaction.last_compression_savings)
        self.token_tracker.add_compression_cost(
            self._compaction.compressor._estimate_tokens(result_messages)
        )

        # Replace detached messages with compressed messages
        self._detached_messages = list(result_messages)

        # Update state
        old_tokens = self.current_tokens
        self.current_tokens = self._recalculate_current_tokens()

        msg_count = len(getattr(self, "_detached_messages", []))
        logger.info(
            f"✅ Compression applied: context {old_tokens} → {self.current_tokens} tokens, "
            f"messages now has {msg_count} messages"
        )

    async def compress(
        self,
        strategy: str = None,
        *,
        context: Optional[MessageListContext] = None,
    ):
        """Compress the conversation's detached messages.

        Args:
            strategy: Compression strategy (delegated to CompactionManager).
            context: When provided, compress its ``detached`` MessageList
                in-place and return the result.  Otherwise fall back to
                internal ``_detached_messages``.
        """

        if context is not None:
            messages = context.detached.snapshot()
            current_tokens = self._recalculate_current_tokens(
                system_messages=context.system_messages,
                detached_messages=messages,
            )
        else:
            messages = list(getattr(self, "_detached_messages", []))
            current_tokens = self.current_tokens

        if not messages:
            logger.warning("No messages to compress")
            return None

        compressed = await self._compaction.compress(
            messages,
            strategy=strategy,
            target_tokens=self._compaction._calculate_target_tokens(current_tokens),
        )

        if compressed is None:
            return None

        # Update token tracker
        self.token_tracker.add_compression_savings(compressed.token_savings)
        self.token_tracker.add_compression_cost(compressed.compressed_tokens)

        # Replace detached messages with compressed messages
        if context is not None:
            context.detached.replace(compressed.messages)
            old_tokens = current_tokens
            self.current_tokens = self._recalculate_current_tokens(
                system_messages=context.system_messages,
                detached_messages=compressed.messages,
            )
            msg_count = len(compressed.messages)
        else:
            self._detached_messages = list(compressed.messages)
            old_tokens = self.current_tokens
            self.current_tokens = self._recalculate_current_tokens()
            msg_count = len(getattr(self, "_detached_messages", []))
        logger.info(
            f"✅ Compression complete: {compressed.original_tokens} → {compressed.compressed_tokens} tokens "
            f"({compressed.savings_percentage:.1f}% saved, ratio: {compressed.compression_ratio:.2f}), "
            f"context: {old_tokens} → {self.current_tokens} tokens, "
            f"messages now has {msg_count} messages"
        )

        return compressed

    def _recalculate_current_tokens(
        self,
        *,
        system_messages: Optional[List[LLMMessage]] = None,
        detached_messages: Optional[List[LLMMessage]] = None,
    ) -> int:
        """Recalculate current token count from scratch.

        Includes message tokens + tool schema overhead.

        Args:
            system_messages: Override; if None, use ``self.system_messages``.
            detached_messages: Override; if None, use ``self._detached_messages``.

        Returns:
            Current token count
        """
        provider = self.llm.provider_name.lower()
        model = self.llm.model

        sys_msgs = self.system_messages if system_messages is None else system_messages
        det_msgs = (
            getattr(self, "_detached_messages", [])
            if detached_messages is None
            else detached_messages
        )

        total = 0
        for msg in sys_msgs:
            total += self.token_tracker.count_message_tokens(msg, provider, model)
        for msg in det_msgs:
            total += self.token_tracker.count_message_tokens(msg, provider, model)
        total += self._tool_schema_tokens
        return total

    def get_stats(self, *, context: Optional[MessageListContext] = None) -> Dict[str, Any]:
        """Get memory statistics.

        Args:
            context: When provided, recompute message count and current
                token usage from the loop-owned context (the new flow).
                Falls back to internal ``_detached_messages`` for legacy
                callers.

        Returns:
            Dict with statistics
        """
        if context is not None:
            detached = context.detached.snapshot()
            msg_count = len(detached)
            current_tokens = self._recalculate_current_tokens(
                system_messages=context.system_messages,
                detached_messages=detached,
            )
        else:
            msg_count = len(getattr(self, "_detached_messages", []))
            current_tokens = self.current_tokens
        stats: Dict[str, Any] = {
            "current_tokens": current_tokens,
            "total_input_tokens": self.token_tracker.total_input_tokens,
            "total_output_tokens": self.token_tracker.total_output_tokens,
            "cache_read_tokens": self.token_tracker.total_cache_read_tokens,
            "cache_creation_tokens": self.token_tracker.total_cache_creation_tokens,
            "compression_count": self._compaction.compression_count,
            "total_savings": self.token_tracker.compression_savings,
            "compression_cost": self.token_tracker.compression_cost,
            "net_savings": self.token_tracker.compression_savings
            - self.token_tracker.compression_cost,
            "message_count": msg_count,
            "detached_message_count": msg_count,  # new alias
            "short_term_count": msg_count,  # legacy alias
            "tool_schema_tokens": self._tool_schema_tokens,
            "total_cost": self.token_tracker.get_total_cost(self.llm.model),
            "ltm_enabled": self._long_term is not None,
        }
        return stats

    async def save_memory(self, *, context: Optional[MessageListContext] = None) -> None:
        """Save current conversation state to disk.

        Args:
            context: Source of truth for messages (the loop-owned
                ``MessageListContext``).  When provided, persists its
                ``system_messages`` and ``detached`` snapshot.  Falls
                back to internal ``_detached_messages`` /
                ``system_messages`` for legacy callers (pre-context
                refactor).
        """
        # Lazily create the session on first save when context-driven
        # callers haven't gone through ``add_message`` (which used to
        # call ``_ensure_session``).
        if context is not None and not self._session_created:
            await self._ensure_session()

        if not self._store or not self._session_created or not self.session_id:
            logger.debug("Skipping save_memory: no session created")
            return

        if context is not None:
            sys_msgs = list(context.system_messages)
            messages = context.detached.snapshot()
        else:
            sys_msgs = list(self.system_messages)
            messages = list(getattr(self, "_detached_messages", []))

        if not messages and not sys_msgs:
            logger.debug(f"Skipping save_memory: no messages to save for session {self.session_id}")
            return

        await self._store.save_memory(
            session_id=self.session_id,
            system_messages=sys_msgs,
            messages=messages,
        )
        logger.info(f"Saved memory state for session {self.session_id}")

    def reset(self):
        """Reset memory manager state."""
        if hasattr(self, "_detached_messages"):
            self._detached_messages.clear()
        self.system_messages.clear()
        self.token_tracker.reset()
        self.current_tokens = 0
        self._tool_schema_tokens = 0
        self._compaction.reset()

    def rollback_incomplete_exchange(self) -> None:
        """Rollback the last incomplete assistant response with tool_calls.

        This is used when a task is interrupted before tool execution completes.
        It removes the assistant message if it contains tool_calls but no results.
        The user message is preserved so the agent can see the original question.

        This prevents API errors about missing tool responses on the next turn.
        """
        messages = list(getattr(self, "_detached_messages", []))
        if not messages:
            return

        # Check if last message is an assistant message with tool_calls
        last_msg = messages[-1]
        if last_msg.role == "assistant" and self._compaction._message_has_tool_calls(last_msg):
            # Remove only the assistant message with tool_calls
            # Keep the user message so the agent can still see the question
            self._detached_messages.pop()
            logger.debug("Removed incomplete assistant message with tool_calls")

            # Recalculate token count
            self.current_tokens = self._recalculate_current_tokens()
