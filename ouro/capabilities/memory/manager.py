"""Core memory manager that orchestrates all memory operations."""

import logging
import re
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

import litellm

from ouro.config import Config
from ouro.core.llm.content_utils import content_has_tool_calls
from ouro.core.llm.message_types import LLMMessage
from ouro.interfaces.tui import terminal_ui
from ouro.interfaces.tui.progress import AsyncSpinner

from .compressor import WorkingMemoryCompressor
from .short_term import ShortTermMemory
from .token_tracker import TokenTracker
from .types import CompressedMemory, CompressionStrategy

logger = logging.getLogger(__name__)

_LTM_BLOCK_RE = re.compile(
    r"<long_term_memories>\s*(.*?)\s*</long_term_memories>",
    re.DOTALL,
)


def _strip_ltm_block(text: str) -> str:
    """Remove ``<long_term_memories>...</long_term_memories>`` from *text*."""
    return _LTM_BLOCK_RE.sub("", text).strip()


def _extract_ltm_block(text: str) -> str:
    """Return the content inside ``<long_term_memories>`` or empty string."""
    m = _LTM_BLOCK_RE.search(text)
    return m.group(1).strip() if m else ""


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
    ):
        """Initialize memory manager.

        Args:
            llm: LLM instance for compression
            session_id: Optional session ID (if resuming session)
            sessions_dir: Optional custom sessions directory (default: ~/.ouro/sessions/)
            memory_dir: Optional custom long-term memory directory (default: ~/.ouro/memory/)
        """
        self.llm = llm

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
        self.short_term = ShortTermMemory()
        self.compressor = WorkingMemoryCompressor(llm)
        self.token_tracker = TokenTracker()

        # Storage for system messages
        self.system_messages: List[LLMMessage] = []

        # State tracking
        self.current_tokens = 0
        self.was_compressed_last_iteration = False
        self.last_compression_savings = 0
        self.compression_count = 0

        # Deferred compression: set by add_message(), consumed by _react_loop()
        self._compression_needed = False

        # Tool schema token overhead (counted once per session)
        self._tool_schema_tokens: int = 0

        # Optional callback to get current todo context for compression
        self._todo_context_provider: Optional[Callable[[], Optional[str]]] = None

        # Long-term memory (cross-session)
        self._long_term = None
        if Config.LONG_TERM_MEMORY_ENABLED:
            from .long_term import LongTermMemoryManager

            self._long_term = LongTermMemoryManager(llm, memory_dir=memory_dir)

    @classmethod
    async def from_session(
        cls,
        session_id: str,
        llm: "LiteLLMAdapter",
        sessions_dir: Optional[str] = None,
        memory_dir: Optional[str] = None,
    ) -> "MemoryManager":
        """Load a MemoryManager from a saved session.

        Args:
            session_id: Session ID to load
            llm: LLM instance for compression
            sessions_dir: Optional custom sessions directory
            memory_dir: Optional custom long-term memory directory

        Returns:
            MemoryManager instance with loaded state
        """
        manager = cls(
            llm=llm, session_id=session_id, sessions_dir=sessions_dir, memory_dir=memory_dir
        )

        # Load session data
        session_data = await manager._store.load_session(session_id)
        if not session_data:
            raise ValueError(f"Session {session_id} not found")

        # Restore state
        manager.system_messages = session_data["system_messages"]

        # Add messages to short-term memory (including any summary messages)
        for msg in session_data["messages"]:
            manager.short_term.add_message(msg)

        # Recalculate tokens
        manager.current_tokens = manager._recalculate_current_tokens()

        logger.info(
            f"Loaded session {session_id}: "
            f"{len(session_data['messages'])} messages, "
            f"{manager.current_tokens} tokens"
        )

        return manager

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

    async def add_message(self, message: LLMMessage, usage: Dict[str, int] = None) -> None:
        """Add a message to memory and trigger compression if needed.

        Args:
            message: Message to add
            usage: Optional usage dict from LLM response (response.usage).
                   Keys: input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens.
        """
        # Ensure session exists before adding messages
        await self._ensure_session()

        # Track system messages separately
        if message.role == "system":
            self.system_messages.append(message)
            return

        # Record token usage if provided
        if usage:
            self.token_tracker.record_usage(usage)
            logger.debug(
                f"API usage: input={usage.get('input_tokens', 0)}, "
                f"output={usage.get('output_tokens', 0)}, "
                f"cache_read={usage.get('cache_read_tokens', 0)}, "
                f"cache_creation={usage.get('cache_creation_tokens', 0)}"
            )
        # Non-API messages (user, tool results) are not tracked here — their
        # tokens will be counted in the next API call's response.usage.input_tokens.

        # Add to short-term memory
        self.short_term.add_message(message)

        # Recalculate current tokens based on actual stored content
        # This gives accurate count for compression decisions
        self.current_tokens = self._recalculate_current_tokens()

        # Log memory state (stored content size, not API usage)
        logger.debug(
            f"Memory state: {self.current_tokens} stored tokens, "
            f"{self.short_term.count()} messages"
        )

        # Check if compression is needed (deferred to _react_loop for cache-safe forking)
        self.was_compressed_last_iteration = False
        should_compress, reason = self._should_compress()
        if should_compress:
            self._compression_needed = True
            logger.info(f"🗜️  Compression needed: {reason} (deferred to react loop)")
        else:
            # Log compression check details
            logger.debug(
                f"Compression check: stored={self.current_tokens}, "
                f"threshold={Config.MEMORY_COMPRESSION_THRESHOLD}"
            )

    def get_context_for_llm(self) -> List[LLMMessage]:
        """Get optimized context for LLM call.

        Returns:
            List of messages: system messages + short-term messages (which includes summaries)
        """
        context = []

        # 1. Add system messages (always included)
        context.extend(self.system_messages)

        # 2. Add short-term memory (includes summary messages and recent messages)
        context.extend(self.short_term.get_messages())

        return context

    @property
    def long_term(self) -> Optional["LongTermMemoryManager"]:
        """Access the long-term memory manager (None if disabled)."""
        return self._long_term

    def set_todo_context_provider(self, provider: Callable[[], Optional[str]]) -> None:
        """Set a callback to provide current todo context for compression.

        The provider should return a formatted string of current todo items,
        or None if no todos exist. This context will be injected into
        compression summaries to preserve task state.

        Args:
            provider: Callable that returns current todo context string or None
        """
        self._todo_context_provider = provider

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

        Returns:
            True if compression should be performed on the next loop iteration
        """
        return self._compression_needed

    async def get_compaction_prompt(self) -> LLMMessage:
        """Build the compaction instruction as a user message.

        Delegates to the compressor for prompt generation. The resulting prompt
        does NOT include the conversation messages (they are already in the LLM
        context), so the LLM call reuses the cached prefix.

        When long-term memory is enabled, the prompt also asks the LLM to
        extract durable memories in a ``<long_term_memories>`` XML block,
        and includes already-saved daily memories to avoid duplicates.

        Returns:
            LLMMessage with role="user" containing the compaction instruction
        """
        from datetime import date

        messages = self.short_term.get_messages()
        strategy = self._select_strategy(messages)
        target_tokens = self._calculate_target_tokens()
        todo_context = self._todo_context_provider() if self._todo_context_provider else None

        # Read today's daily file so the LLM knows what's already saved
        existing_memories = ""
        if self._long_term is not None:
            try:
                existing_memories = await self._long_term.store.load_daily(date.today())
            except Exception:
                logger.debug("Failed to read today's daily file for compaction", exc_info=True)

        prompt_text = self.compressor.build_compaction_prompt(
            messages,
            strategy,
            target_tokens,
            todo_context,
            ltm_enabled=self._long_term is not None,
            existing_memories=existing_memories,
        )
        return LLMMessage(role="user", content=prompt_text)

    def _assemble_compressed_messages(
        self,
        messages: List[LLMMessage],
        summary_message: LLMMessage,
        strategy: str,
    ) -> List[LLMMessage]:
        """Assemble the post-compression message list.

        For sliding_window: just the summary message.
        For selective: summary + preserved non-system messages.

        Args:
            messages: Original messages before compression
            summary_message: Summary message from the compressor
            strategy: Compression strategy used

        Returns:
            Final message list to replace short-term memory contents
        """
        if strategy == CompressionStrategy.SELECTIVE:
            preserved, _ = self.compressor._separate_messages(messages)
            non_system_preserved = [m for m in preserved if m.role != "system"]
            return [summary_message] + non_system_preserved
        return [summary_message]

    def apply_compression(self, summary_text: str, usage: Optional[Dict[str, int]] = None) -> None:
        """Apply the LLM's summary to compress memory.

        This is the counterpart to get_compaction_prompt() — called after
        the LLM produces the summary in the react loop.

        When long-term memory is enabled, this also extracts and persists
        any ``<long_term_memories>`` block from the summary.

        Args:
            summary_text: The LLM-generated summary text
            usage: Optional token usage from the compression LLM call
        """
        messages = self.short_term.get_messages()
        if not messages:
            self._compression_needed = False
            return

        strategy = self._select_strategy(messages)
        todo_context = self._todo_context_provider() if self._todo_context_provider else None

        logger.info(
            f"🗜️  Applying compression to {len(messages)} messages using {strategy} strategy"
        )

        # Extract and persist long-term memories before stripping from summary
        if self._long_term is not None:
            self._extract_and_save_ltm(summary_text)

        # Strip the <long_term_memories> block from the summary so it doesn't
        # consume short-term context tokens.
        summary_text = _strip_ltm_block(summary_text)

        # Inject todo context into summary
        if todo_context and "[Current Tasks]" not in summary_text:
            summary_text = f"{summary_text}\n\n[Current Tasks]\n{todo_context}"

        # Build summary message
        summary_message = LLMMessage(
            role="user",
            content=f"{self.compressor.SUMMARY_PREFIX}{summary_text}",
        )

        # Assemble final message list and calculate metrics
        original_tokens = self.compressor._estimate_tokens(messages)
        result_messages = self._assemble_compressed_messages(messages, summary_message, strategy)
        compressed_tokens = self.compressor._estimate_tokens(result_messages)
        token_savings = original_tokens - compressed_tokens

        # Track usage from compression LLM call
        if usage:
            self.token_tracker.record_usage(usage)

        # Track compression results
        self.compression_count += 1
        self.was_compressed_last_iteration = True
        self.last_compression_savings = token_savings
        self.token_tracker.add_compression_savings(token_savings)
        self.token_tracker.add_compression_cost(compressed_tokens)

        # Replace short-term memory with compressed messages
        self.short_term.clear()
        for msg in result_messages:
            self.short_term.add_message(msg)

        # Update state
        old_tokens = self.current_tokens
        self.current_tokens = self._recalculate_current_tokens()
        self._compression_needed = False

        compression_ratio = compressed_tokens / original_tokens if original_tokens > 0 else 0
        savings_pct = (token_savings / original_tokens * 100) if original_tokens > 0 else 0
        logger.info(
            f"✅ Compression complete: {original_tokens} → {compressed_tokens} tokens "
            f"({savings_pct:.1f}% saved, ratio: {compression_ratio:.2f}), "
            f"context: {old_tokens} → {self.current_tokens} tokens, "
            f"short_term now has {self.short_term.count()} messages"
        )

    async def compress(self, strategy: str = None) -> Optional[CompressedMemory]:
        """Compress current short-term memory.

        After compression, the compressed messages (including any summary as user message)
        are put back into short_term as regular messages.

        Args:
            strategy: Compression strategy (None = auto-select)

        Returns:
            CompressedMemory object if compression was performed
        """
        messages = self.short_term.get_messages()
        message_count = len(messages)

        if not messages:
            logger.warning("No messages to compress")
            return None

        # Auto-select strategy if not specified
        if strategy is None:
            strategy = self._select_strategy(messages)

        logger.info(f"🗜️  Compressing {message_count} messages using {strategy} strategy")

        try:
            # Get todo context if provider is set
            todo_context = None
            if self._todo_context_provider:
                todo_context = self._todo_context_provider()

            # Perform compression with TUI spinner
            async with AsyncSpinner(terminal_ui.console, "Compressing memory...", title="Working"):
                compressed = await self.compressor.compress(
                    messages,
                    strategy=strategy,
                    target_tokens=self._calculate_target_tokens(),
                    todo_context=todo_context,
                )

            # Track compression results
            self.compression_count += 1
            self.was_compressed_last_iteration = True
            self.last_compression_savings = compressed.token_savings

            # Update token tracker
            self.token_tracker.add_compression_savings(compressed.token_savings)
            self.token_tracker.add_compression_cost(compressed.compressed_tokens)

            # Replace short-term memory with compressed messages
            self.short_term.clear()
            for msg in compressed.messages:
                self.short_term.add_message(msg)

            # Update current token count
            old_tokens = self.current_tokens
            self.current_tokens = self._recalculate_current_tokens()

            # Clear the deferred compression flag
            self._compression_needed = False

            # Log compression results
            logger.info(
                f"✅ Compression complete: {compressed.original_tokens} → {compressed.compressed_tokens} tokens "
                f"({compressed.savings_percentage:.1f}% saved, ratio: {compressed.compression_ratio:.2f}), "
                f"context: {old_tokens} → {self.current_tokens} tokens, "
                f"short_term now has {self.short_term.count()} messages"
            )

            return compressed

        except Exception as e:
            logger.error(f"Compression failed: {e}")
            return None

    def _should_compress(self) -> tuple[bool, Optional[str]]:
        """Check if compression should be triggered.

        Returns:
            Tuple of (should_compress, reason)
        """
        if not Config.MEMORY_ENABLED:
            return False, "compression_disabled"

        # Token hard limit: must compress
        if self.current_tokens > Config.MEMORY_COMPRESSION_THRESHOLD:
            return (
                True,
                f"hard_limit ({self.current_tokens} > {Config.MEMORY_COMPRESSION_THRESHOLD})",
            )

        return False, None

    def _select_strategy(self, messages: List[LLMMessage]) -> str:
        """Auto-select compression strategy based on message characteristics.

        Args:
            messages: Messages to analyze

        Returns:
            Strategy name
        """
        # Check for tool calls
        has_tool_calls = any(self._message_has_tool_calls(msg) for msg in messages)

        # Select strategy
        if has_tool_calls:
            # Preserve tool calls
            return CompressionStrategy.SELECTIVE
        elif len(messages) < 5:
            # Too few messages, just delete
            return CompressionStrategy.DELETION
        else:
            # Default: sliding window
            return CompressionStrategy.SLIDING_WINDOW

    def _message_has_tool_calls(self, message: LLMMessage) -> bool:
        """Check if message contains tool calls.

        Handles both new format (tool_calls field) and legacy format (content blocks).

        Args:
            message: Message to check

        Returns:
            True if contains tool calls
        """
        # New format: check tool_calls field
        if hasattr(message, "tool_calls") and message.tool_calls:
            return True

        # New format: tool role message
        if message.role == "tool":
            return True

        # Legacy/centralized check on content
        return content_has_tool_calls(message.content)

    def _calculate_target_tokens(self) -> int:
        """Calculate target token count for compression.

        Returns:
            Target token count
        """
        original_tokens = self.current_tokens
        target = int(original_tokens * Config.MEMORY_COMPRESSION_RATIO)
        return max(target, 500)  # Minimum 500 tokens for summary

    def _recalculate_current_tokens(self) -> int:
        """Recalculate current token count from scratch.

        Includes message tokens + tool schema overhead.

        Returns:
            Current token count
        """
        provider = self.llm.provider_name.lower()
        model = self.llm.model

        total = 0

        # Count system messages
        for msg in self.system_messages:
            total += self.token_tracker.count_message_tokens(msg, provider, model)

        # Count short-term messages (includes summary messages)
        for msg in self.short_term.get_messages():
            total += self.token_tracker.count_message_tokens(msg, provider, model)

        # Add tool schema overhead
        total += self._tool_schema_tokens

        return total

    def get_stats(self) -> Dict[str, Any]:
        """Get memory statistics.

        Returns:
            Dict with statistics
        """
        stats: Dict[str, Any] = {
            "current_tokens": self.current_tokens,
            "total_input_tokens": self.token_tracker.total_input_tokens,
            "total_output_tokens": self.token_tracker.total_output_tokens,
            "cache_read_tokens": self.token_tracker.total_cache_read_tokens,
            "cache_creation_tokens": self.token_tracker.total_cache_creation_tokens,
            "compression_count": self.compression_count,
            "total_savings": self.token_tracker.compression_savings,
            "compression_cost": self.token_tracker.compression_cost,
            "net_savings": self.token_tracker.compression_savings
            - self.token_tracker.compression_cost,
            "short_term_count": self.short_term.count(),
            "tool_schema_tokens": self._tool_schema_tokens,
            "total_cost": self.token_tracker.get_total_cost(self.llm.model),
            "ltm_enabled": self._long_term is not None,
        }
        return stats

    async def save_memory(self):
        """Save current memory state to store.

        This saves the complete memory state including:
        - System messages
        - Short-term messages (which includes summary messages after compression)

        Call this method after completing a task or at key checkpoints.
        """
        # Skip if no session was created (no messages were ever added)
        if not self._store or not self._session_created or not self.session_id:
            logger.debug("Skipping save_memory: no session created")
            return

        messages = self.short_term.get_messages()

        # Skip saving if there are no messages (empty conversation)
        if not messages and not self.system_messages:
            logger.debug(f"Skipping save_memory: no messages to save for session {self.session_id}")
            return

        await self._store.save_memory(
            session_id=self.session_id,
            system_messages=self.system_messages,
            messages=messages,
        )
        logger.info(f"Saved memory state for session {self.session_id}")

    def reset(self):
        """Reset memory manager state."""
        self.short_term.clear()
        self.system_messages.clear()
        self.token_tracker.reset()
        self.current_tokens = 0
        self._tool_schema_tokens = 0
        self.was_compressed_last_iteration = False
        self.last_compression_savings = 0
        self.compression_count = 0
        self._compression_needed = False

    def _extract_and_save_ltm(self, summary_text: str) -> None:
        """Extract ``<long_term_memories>`` from *summary_text* and append to today's daily file.

        Runs synchronously (file I/O via asyncio.to_thread happens inside
        the store) but is called from the synchronous ``apply_compression``,
        so we schedule the async save as a fire-and-forget task.
        """
        import asyncio
        from datetime import date

        new_memories = _extract_ltm_block(summary_text)
        if not new_memories or self._long_term is None:
            return

        ltm = self._long_term

        async def _save() -> None:
            try:
                await ltm.store.append_daily(date.today(), new_memories + "\n")
                logger.info("Saved %d chars of long-term memories to daily file", len(new_memories))
            except Exception:
                logger.warning("Failed to save long-term memories during compaction", exc_info=True)

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_save())
        except RuntimeError:
            # No running loop — shouldn't happen in normal flow, but be safe
            logger.debug("No running event loop; skipping LTM save")

    def rollback_incomplete_exchange(self) -> None:
        """Rollback the last incomplete assistant response with tool_calls.

        This is used when a task is interrupted before tool execution completes.
        It removes the assistant message if it contains tool_calls but no results.
        The user message is preserved so the agent can see the original question.

        This prevents API errors about missing tool responses on the next turn.
        """
        messages = self.short_term.get_messages()
        if not messages:
            return

        # Check if last message is an assistant message with tool_calls
        last_msg = messages[-1]
        if last_msg.role == "assistant" and self._message_has_tool_calls(last_msg):
            # Remove only the assistant message with tool_calls
            # Keep the user message so the agent can still see the question
            self.short_term.remove_last(1)
            logger.debug("Removed incomplete assistant message with tool_calls")

            # Recalculate token count
            self.current_tokens = self._recalculate_current_tokens()
