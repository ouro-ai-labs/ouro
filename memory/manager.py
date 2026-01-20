"""Core memory manager that orchestrates all memory operations."""

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from config import Config
from llm.base import LLMMessage

from .compressor import WorkingMemoryCompressor
from .short_term import ShortTermMemory
from .store import MemoryStore
from .token_tracker import TokenTracker
from .tool_result_processor import ToolResultProcessor
from .tool_result_store import ToolResultStore
from .types import CompressedMemory, CompressionStrategy

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from llm import LiteLLMLLM


class MemoryManager:
    """Central memory management system with built-in persistence."""

    def __init__(
        self,
        llm: "LiteLLMLLM",
        store: Optional[MemoryStore] = None,
        session_id: Optional[str] = None,
        db_path: str = "data/memory.db",
    ):
        """Initialize memory manager.

        Args:
            llm: LLM instance for compression
            store: Optional MemoryStore for persistence (if None, creates default store)
            session_id: Optional session ID (if resuming session)
            db_path: Path to database file (default: data/memory.db)
        """
        self.llm = llm
        self._db_path = db_path

        # Always create/use store for persistence
        if store is None:
            store = MemoryStore(db_path=db_path)
        self.store = store

        # Lazy session creation: only create when first message is added
        # If session_id is provided (resuming), use it immediately
        if session_id is not None:
            self.session_id = session_id
            self._session_created = True
        else:
            self.session_id = None
            self._session_created = False

        # Initialize components using Config directly
        self.short_term = ShortTermMemory(max_size=Config.MEMORY_SHORT_TERM_SIZE)
        self.compressor = WorkingMemoryCompressor(llm)
        self.token_tracker = TokenTracker()

        # Initialize tool result processing components (always enabled)
        self.tool_result_processor = ToolResultProcessor(
            storage_threshold=Config.TOOL_RESULT_STORAGE_THRESHOLD,
            summary_model=Config.TOOL_RESULT_SUMMARY_MODEL,
        )
        storage_path = Config.TOOL_RESULT_STORAGE_PATH
        self.tool_result_store = ToolResultStore(db_path=storage_path)
        logger.info(
            f"Tool result processing enabled with external storage: {storage_path or 'in-memory'}"
        )

        # Storage for system messages (summaries are now stored as regular messages in short_term)
        self.system_messages: List[LLMMessage] = []

        # State tracking
        self.current_tokens = 0
        self.was_compressed_last_iteration = False
        self.last_compression_savings = 0
        self.compression_count = 0

        # Summary message prefix for identification
        self.SUMMARY_PREFIX = "[Conversation Summary]\n"

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

        # Create manager (config is now read from Config class directly)
        manager = cls(llm=llm, store=store, session_id=session_id)

        # Restore state
        manager.system_messages = session_data["system_messages"]
        manager.compression_count = session_data["stats"]["compression_count"]

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

    def _ensure_session(self) -> None:
        """Lazily create session when first needed.

        This avoids creating empty sessions when MemoryManager is instantiated
        but no messages are ever added (e.g., user exits before running any task).
        """
        if not self._session_created:
            self.session_id = self.store.create_session()
            self._session_created = True
            logger.info(f"Created new session: {self.session_id}")

    def add_message(self, message: LLMMessage, actual_tokens: Dict[str, int] = None) -> None:
        """Add a message to memory and trigger compression if needed.

        Args:
            message: Message to add
            actual_tokens: Optional dict with actual token counts from LLM response
                          Format: {"input": int, "output": int}
        """
        # Ensure session exists before adding messages
        self._ensure_session()

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
            f"{self.short_term.count()}/{Config.MEMORY_SHORT_TERM_SIZE} messages, "
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
                f"threshold={Config.MEMORY_COMPRESSION_THRESHOLD}, "
                f"short_term_full={self.short_term.is_full()}"
            )

        # Recalculate current tokens to account for messages evicted from short-term memory
        # Note: compress() already recalculates, so only do this if we didn't compress
        if not self.was_compressed_last_iteration:
            self.current_tokens = self._recalculate_current_tokens()

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

    def compress(self, strategy: str = None) -> Optional[CompressedMemory]:
        """Compress current short-term memory.

        After compression, summary and preserved messages are put back into short_term
        as regular messages, so they can participate in future compressions.

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
            # Perform compression
            compressed = self.compressor.compress(
                messages,
                strategy=strategy,
                target_tokens=self._calculate_target_tokens(),
            )

            # Track compression results
            self.compression_count += 1
            self.was_compressed_last_iteration = True
            self.last_compression_savings = compressed.token_savings

            # Update token tracker
            self.token_tracker.add_compression_savings(compressed.token_savings)

            # Estimate tokens used for compression (the summary generation)
            compression_cost = compressed.compressed_tokens
            self.token_tracker.add_compression_cost(compression_cost)

            # Remove compressed messages from short-term memory
            self.short_term.remove_first(message_count)

            # Rebuild short_term with: summary + preserved messages (in order)
            # Get any remaining messages (added after compression started)
            remaining_messages = self.short_term.get_messages()
            self.short_term.clear()

            # 1. Add summary first (represents older context)
            if compressed.summary:
                summary_message = LLMMessage(
                    role="user",
                    content=f"{self.SUMMARY_PREFIX}{compressed.summary}",
                )
                self.short_term.add_message(summary_message)

            # 2. Add preserved messages in order
            for msg in compressed.preserved_messages:
                self.short_term.add_message(msg)

            # 3. Add any remaining messages
            for msg in remaining_messages:
                self.short_term.add_message(msg)

            # Update current token count
            old_tokens = self.current_tokens
            self.current_tokens = self._recalculate_current_tokens()

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

        # Hard limit: must compress
        if self.current_tokens > Config.MEMORY_COMPRESSION_THRESHOLD:
            return (
                True,
                f"hard_limit ({self.current_tokens} > {Config.MEMORY_COMPRESSION_THRESHOLD})",
            )

        # CRITICAL: Compress when short-term memory is full to prevent eviction
        # If we don't compress, the next message will cause deque to evict the oldest message,
        # which may break tool_use/tool_result pairs
        if self.short_term.is_full():
            return (
                True,
                f"short_term_full ({self.short_term.count()}/{Config.MEMORY_SHORT_TERM_SIZE} messages, "
                f"current tokens: {self.current_tokens})",
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
        target = int(original_tokens * Config.MEMORY_COMPRESSION_RATIO)
        return max(target, 500)  # Minimum 500 tokens for summary

    def process_tool_result(
        self, tool_name: str, tool_call_id: str, result: str, context: str = ""
    ) -> str:
        """Process a tool result with intelligent summarization and automatic external storage.

        Key behavior: If the result is modified (truncated/processed) in any way,
        the original is automatically stored externally so it can be retrieved later.

        Args:
            tool_name: Name of the tool that produced the result
            tool_call_id: ID of the tool call
            result: Raw tool result string
            context: Optional context about the task

        Returns:
            Processed result (may include reference to stored original if modified)
        """
        # Process the result through unified processor
        processed_result, was_modified = self.tool_result_processor.process_result(
            tool_name=tool_name, result=result, context=context
        )

        # Core logic: If result was modified, store the original for later retrieval
        if was_modified:
            result_tokens = self.tool_result_processor.estimate_tokens(result)
            logger.info(
                f"Tool result was modified, storing original: {tool_name} ({result_tokens} tokens)"
            )

            # Store the full original result
            result_id = self.tool_result_store.store_result(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                content=result,  # Store original, not processed
                summary=processed_result,  # Processed version as summary
                token_count=result_tokens,
            )

            # Append retrieval hint to processed result
            retrieval_hint = (
                f"\n\n[Original result stored as #{result_id} - "
                f"use retrieve_tool_result tool to access full content]"
            )
            return processed_result + retrieval_hint

        return processed_result

    def retrieve_tool_result(self, result_id: str) -> Optional[str]:
        """Retrieve a tool result from external storage.

        Args:
            result_id: ID returned by process_tool_result

        Returns:
            Full tool result content, or None if not found
        """
        return self.tool_result_store.retrieve_result(result_id)

    def get_tool_result_stats(self) -> Dict[str, Any]:
        """Get statistics about stored tool results.

        Returns:
            Dictionary with statistics
        """
        stats = self.tool_result_store.get_stats()
        stats["enabled"] = True
        return stats

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

        # Count short-term messages (includes summary messages)
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
            "total_cost": self.token_tracker.get_total_cost(self.llm.model),
        }

    def save_memory(self):
        """Save current memory state to store.

        This saves the complete memory state including:
        - System messages
        - Short-term messages (which includes summary messages after compression)

        Call this method after completing a task or at key checkpoints.
        """
        # Skip if no session was created (no messages were ever added)
        if not self.store or not self._session_created or not self.session_id:
            logger.debug("Skipping save_memory: no session created")
            return

        messages = self.short_term.get_messages()

        # Skip saving if there are no messages (empty conversation)
        if not messages and not self.system_messages:
            logger.debug(f"Skipping save_memory: no messages to save for session {self.session_id}")
            return

        self.store.save_memory(
            session_id=self.session_id,
            system_messages=self.system_messages,
            messages=messages,
            summaries=[],  # Summaries are now part of messages
        )
        logger.info(f"Saved memory state for session {self.session_id}")

    def reset(self):
        """Reset memory manager state."""
        self.short_term.clear()
        self.system_messages.clear()
        self.token_tracker.reset()
        self.current_tokens = 0
        self.was_compressed_last_iteration = False
        self.last_compression_savings = 0
        self.compression_count = 0
