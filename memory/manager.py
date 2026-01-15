"""Core memory manager that orchestrates all memory operations."""

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from llm.base import LLMMessage

from .compressor import WorkingMemoryCompressor
from .short_term import ShortTermMemory
from .store import MemoryStore
from .token_tracker import TokenTracker
from .types import CompressedMemory, CompressionStrategy, MemoryConfig

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from llm import LiteLLMLLM


class MemoryManager:
    """Central memory management system with built-in persistence."""

    def __init__(
        self,
        config: MemoryConfig,
        llm: "LiteLLMLLM",
        store: Optional[MemoryStore] = None,
        session_id: Optional[str] = None,
        db_path: str = "data/memory.db",
    ):
        """Initialize memory manager.

        Args:
            config: Memory configuration
            llm: LLM instance for compression
            store: Optional MemoryStore for persistence (if None, creates default store)
            session_id: Optional session ID (if resuming session)
            db_path: Path to database file (default: data/memory.db)
        """
        self.config = config
        self.llm = llm

        # Always create/use store for persistence
        if store is None:
            store = MemoryStore(db_path=db_path)
        self.store = store

        # Create new session or use existing one
        if session_id is None:
            self.session_id = store.create_session()
            logger.info(f"Created new session: {self.session_id}")
        else:
            self.session_id = session_id

        # Initialize components
        self.short_term = ShortTermMemory(max_size=config.short_term_message_count)
        self.compressor = WorkingMemoryCompressor(llm, config)
        self.token_tracker = TokenTracker()

        # Storage for compressed memories and system messages
        self.summaries: List[CompressedMemory] = []
        self.system_messages: List[LLMMessage] = []

        # State tracking
        self.current_tokens = 0
        self.was_compressed_last_iteration = False
        self.last_compression_savings = 0
        self.compression_count = 0

    @classmethod
    def from_session(
        cls,
        session_id: str,
        llm: "LiteLLMLLM",
        store: Optional[MemoryStore] = None,
        db_path: str = "data/memory.db",
    ) -> "MemoryManager":
        """Load a MemoryManager from a saved session.

        Args:
            session_id: Session ID to load
            llm: LLM instance for compression
            store: Optional MemoryStore instance (if None, creates default store)
            db_path: Path to database file (default: data/memory.db)

        Returns:
            MemoryManager instance with loaded state
        """
        # Create store if not provided
        if store is None:
            store = MemoryStore(db_path=db_path)

        # Load session data
        session_data = store.load_session(session_id)
        if not session_data:
            raise ValueError(f"Session {session_id} not found")

        # Get config (use loaded config or default)
        config = session_data["config"] or MemoryConfig()

        # Create manager
        manager = cls(config=config, llm=llm, store=store, session_id=session_id)

        # Restore state
        manager.system_messages = session_data["system_messages"]
        manager.summaries = session_data["summaries"]
        manager.compression_count = session_data["stats"]["compression_count"]

        # Add messages to short-term memory
        for msg in session_data["messages"]:
            manager.short_term.add_message(msg)

        # Recalculate tokens
        manager.current_tokens = manager._recalculate_current_tokens()

        logger.info(
            f"Loaded session {session_id}: "
            f"{len(session_data['messages'])} messages, "
            f"{len(session_data['summaries'])} summaries, "
            f"{manager.current_tokens} tokens"
        )

        return manager

    def add_message(self, message: LLMMessage, actual_tokens: Dict[str, int] = None) -> None:
        """Add a message to memory and trigger compression if needed.

        Args:
            message: Message to add
            actual_tokens: Optional dict with actual token counts from LLM response
                          Format: {"input": int, "output": int}
        """
        # Track system messages separately
        if message.role == "system":
            self.system_messages.append(message)
            return

        # Count tokens (use actual if provided, otherwise estimate)
        if actual_tokens:
            # Use actual token counts from LLM response
            input_tokens = actual_tokens.get("input", 0)
            output_tokens = actual_tokens.get("output", 0)
            tokens = input_tokens + output_tokens

            self.token_tracker.add_input_tokens(input_tokens)
            self.token_tracker.add_output_tokens(output_tokens)
        else:
            # Estimate token count
            provider = self.llm.provider_name.lower()
            model = self.llm.model
            tokens = self.token_tracker.count_message_tokens(message, provider, model)

            # Update token count
            if message.role == "assistant":
                self.token_tracker.add_output_tokens(tokens)
            else:
                self.token_tracker.add_input_tokens(tokens)

        self.current_tokens += tokens

        # Add to short-term memory
        self.short_term.add_message(message)

        # Log memory state for debugging
        logger.debug(
            f"Memory state: {self.current_tokens} tokens, "
            f"{self.short_term.count()}/{self.config.short_term_message_count} messages, "
            f"full={self.short_term.is_full()}"
        )

        # Check if compression is needed
        self.was_compressed_last_iteration = False
        should_compress, reason = self._should_compress()
        if should_compress:
            logger.info(f"🗜️  Triggering compression: {reason}")
            self.compress()
        else:
            # Log why compression was NOT triggered
            logger.debug(
                f"Compression check: current={self.current_tokens}, "
                f"threshold={self.config.compression_threshold}, "
                f"target={self.config.target_working_memory_tokens}, "
                f"short_term_full={self.short_term.is_full()}"
            )

        # Recalculate current tokens to account for messages evicted from short-term memory
        # Note: compress() already recalculates, so only do this if we didn't compress
        if not self.was_compressed_last_iteration:
            self.current_tokens = self._recalculate_current_tokens()

    def get_context_for_llm(self) -> List[LLMMessage]:
        """Get optimized context for LLM call.

        Returns:
            List of messages combining summaries and recent messages
        """
        context = []

        # 1. Add system messages (always included)
        context.extend(self.system_messages)

        # 2. Add summaries
        for summary in self.summaries:
            # add summary text (if any)
            if summary.summary:
                context.append(
                    LLMMessage(
                        role="user",
                        content=f"[Previous conversation summary]\n{summary.summary}",
                    )
                )

        # 3. Add preserved messages
        for summary in self.summaries:
            context.extend(summary.preserved_messages)

        # 4. Add short-term memory (recent messages)
        context.extend(self.short_term.get_messages())

        return context

    def compress(self, strategy: str = None) -> Optional[CompressedMemory]:
        """Compress current short-term memory.

        Args:
            strategy: Compression strategy (None = auto-select)

        Returns:
            CompressedMemory object if compression was performed
        """
        messages = self.short_term.get_messages()

        if not messages:
            logger.warning("No messages to compress")
            return None

        # Auto-select strategy if not specified
        if strategy is None:
            strategy = self._select_strategy(messages)

        logger.info(f"🗜️  Compressing {len(messages)} messages using {strategy} strategy")

        try:
            # CRITICAL: Find orphaned tool_use IDs from previous summaries
            # These tool_use are waiting for tool_result that might be in current short_term
            orphaned_tool_use_ids = self._get_orphaned_tool_use_ids_from_summaries()

            # Perform compression (pass orphaned IDs so compressor can protect matching tool_results)
            compressed = self.compressor.compress(
                messages,
                strategy=strategy,
                target_tokens=self._calculate_target_tokens(),
                orphaned_tool_use_ids=orphaned_tool_use_ids,
            )

            # Track compression results
            self.summaries.append(compressed)
            self.compression_count += 1
            self.was_compressed_last_iteration = True
            self.last_compression_savings = compressed.token_savings

            # Update token tracker
            self.token_tracker.add_compression_savings(compressed.token_savings)

            # Estimate tokens used for compression (the summary generation)
            compression_cost = compressed.compressed_tokens
            self.token_tracker.add_compression_cost(compression_cost)

            # Clear short-term memory
            self.short_term.clear()

            # Update current token count
            old_tokens = self.current_tokens
            self.current_tokens = self._recalculate_current_tokens()

            # Log compression results
            logger.info(
                f"✅ Compression complete: {compressed.original_tokens} → {compressed.compressed_tokens} tokens "
                f"({compressed.savings_percentage:.1f}% saved, ratio: {compressed.compression_ratio:.2f}), "
                f"context: {old_tokens} → {self.current_tokens} tokens"
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
        if not self.config.enable_compression:
            return False, "compression_disabled"

        # Hard limit: must compress
        if self.current_tokens > self.config.compression_threshold:
            return True, f"hard_limit ({self.current_tokens} > {self.config.compression_threshold})"

        # CRITICAL: Compress when short-term memory is full to prevent eviction
        # If we don't compress, the next message will cause deque to evict the oldest message,
        # which may break tool_use/tool_result pairs
        if self.short_term.is_full():
            return (
                True,
                f"short_term_full ({self.short_term.count()}/{self.config.short_term_message_count} messages, "
                f"current tokens: {self.current_tokens})",
            )

        # Soft limit: compress if over target token count
        if self.current_tokens > self.config.target_working_memory_tokens:
            return (
                True,
                f"soft_limit ({self.current_tokens} > {self.config.target_working_memory_tokens})",
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

        Args:
            message: Message to check

        Returns:
            True if contains tool calls
        """
        content = message.content
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") in ["tool_use", "tool_result", "tool_calls"]:
                        return True
        return False

    def _calculate_target_tokens(self) -> int:
        """Calculate target token count for compression.

        Returns:
            Target token count
        """
        original_tokens = self.current_tokens
        target = int(original_tokens * self.config.compression_ratio)
        return max(target, 500)  # Minimum 500 tokens for summary

    def _get_orphaned_tool_use_ids_from_summaries(self) -> set:
        """Get tool_use IDs from summaries that don't have matching tool_result yet.

        These are tool_use that were preserved in previous compressions but their
        tool_result might arrive in later messages (in current short_term).

        Returns:
            Set of tool_use IDs that are waiting for results
        """
        orphaned_ids = set()

        for summary in self.summaries:
            # Collect tool_use IDs from preserved messages
            tool_use_ids = set()
            tool_result_ids = set()

            for msg in summary.preserved_messages:
                if isinstance(msg.content, list):
                    for block in msg.content:
                        if isinstance(block, dict):
                            if block.get("type") == "tool_use":
                                tool_use_ids.add(block.get("id"))
                            elif block.get("type") == "tool_result":
                                tool_result_ids.add(block.get("tool_use_id"))

            # Orphaned = tool_use without result in the same summary
            summary_orphaned = tool_use_ids - tool_result_ids
            orphaned_ids.update(summary_orphaned)

        if orphaned_ids:
            logger.debug(
                f"Found {len(orphaned_ids)} orphaned tool_use IDs in summaries: {orphaned_ids}"
            )

        return orphaned_ids

    def _recalculate_current_tokens(self) -> int:
        """Recalculate current token count from scratch.

        Returns:
            Current token count
        """
        provider = self.llm.provider_name.lower()
        model = self.llm.model

        total = 0

        # Count system messages
        for msg in self.system_messages:
            total += self.token_tracker.count_message_tokens(msg, provider, model)

        # Count summaries
        for summary in self.summaries:
            total += summary.compressed_tokens

        # Count short-term messages
        for msg in self.short_term.get_messages():
            total += self.token_tracker.count_message_tokens(msg, provider, model)

        return total

    def get_stats(self) -> Dict[str, Any]:
        """Get memory statistics.

        Returns:
            Dict with statistics
        """
        return {
            "current_tokens": self.current_tokens,
            "total_input_tokens": self.token_tracker.total_input_tokens,
            "total_output_tokens": self.token_tracker.total_output_tokens,
            "compression_count": self.compression_count,
            "total_savings": self.token_tracker.compression_savings,
            "compression_cost": self.token_tracker.compression_cost,
            "net_savings": self.token_tracker.compression_savings
            - self.token_tracker.compression_cost,
            "short_term_count": self.short_term.count(),
            "summary_count": len(self.summaries),
            "total_cost": self.token_tracker.get_total_cost(self.llm.model),
            "budget_status": self.token_tracker.get_budget_status(self.config.max_context_tokens),
        }

    def save_memory(self):
        """Save current memory state to store.

        This saves the complete memory state including:
        - System messages
        - Short-term messages
        - Summaries

        Call this method after completing a task or at key checkpoints.
        """
        if not self.store or not self.session_id:
            return

        messages = self.short_term.get_messages()

        # Skip saving if there are no messages (empty conversation)
        if not messages and not self.system_messages and not self.summaries:
            logger.debug(f"Skipping save_memory: no messages to save for session {self.session_id}")
            return

        self.store.save_memory(
            session_id=self.session_id,
            system_messages=self.system_messages,
            messages=messages,
            summaries=self.summaries,
        )
        logger.info(f"Saved memory state for session {self.session_id}")

    def reset(self):
        """Reset memory manager state."""
        self.short_term.clear()
        self.summaries.clear()
        self.system_messages.clear()
        self.token_tracker.reset()
        self.current_tokens = 0
        self.was_compressed_last_iteration = False
        self.last_compression_savings = 0
        self.compression_count = 0
