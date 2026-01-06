"""Core memory manager that orchestrates all memory operations."""
from typing import List, Optional, Dict, Any
import logging

from .types import MemoryConfig, CompressedMemory, CompressionStrategy
from .short_term import ShortTermMemory
from .compressor import WorkingMemoryCompressor
from .token_tracker import TokenTracker

logger = logging.getLogger(__name__)


class MemoryManager:
    """Central memory management system."""

    def __init__(self, config: MemoryConfig, llm: "BaseLLM"):
        """Initialize memory manager.

        Args:
            config: Memory configuration
            llm: LLM instance for compression
        """
        self.config = config
        self.llm = llm

        # Initialize components
        self.short_term = ShortTermMemory(max_size=config.short_term_message_count)
        self.compressor = WorkingMemoryCompressor(llm, config)
        self.token_tracker = TokenTracker()

        # Storage for compressed memories and system messages
        self.summaries: List[CompressedMemory] = []
        self.system_messages: List["LLMMessage"] = []

        # State tracking
        self.current_tokens = 0
        self.was_compressed_last_iteration = False
        self.last_compression_savings = 0
        self.compression_count = 0

    def add_message(self, message: "LLMMessage") -> None:
        """Add a message to memory and trigger compression if needed.

        Args:
            message: Message to add
        """
        # Track system messages separately
        if message.role == "system":
            self.system_messages.append(message)
            return

        # Count tokens
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

        # Check if compression is needed
        self.was_compressed_last_iteration = False
        if self.config.enable_compression:
            should_compress, reason = self._should_compress()
            if should_compress:
                logger.info(f"Triggering compression: {reason}")
                self.compress()

    def get_context_for_llm(self) -> List["LLMMessage"]:
        """Get optimized context for LLM call.

        Returns:
            List of messages combining summaries and recent messages
        """
        context = []

        # 1. Add system messages (always included)
        context.extend(self.system_messages)

        # 2. Add compressed summaries as user messages
        for summary in self.summaries:
            if summary.summary:
                from llm import LLMMessage

                context.append(
                    LLMMessage(
                        role="user",
                        content=f"[Previous conversation summary]\n{summary.summary}",
                    )
                )

            # Add any preserved messages from this summary
            context.extend(summary.preserved_messages)

        # 3. Add short-term memory (recent messages)
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

        logger.info(f"Compressing {len(messages)} messages using {strategy} strategy")

        try:
            # Perform compression
            compressed = self.compressor.compress(
                messages, strategy=strategy, target_tokens=self._calculate_target_tokens()
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
            self.current_tokens = self._recalculate_current_tokens()

            logger.info(
                f"Compression complete: saved {compressed.token_savings} tokens "
                f"({compressed.savings_percentage:.1f}%), "
                f"compression ratio: {compressed.compression_ratio:.2f}"
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
        # Hard limit: must compress
        if self.current_tokens > self.config.compression_threshold:
            return True, f"hard_limit ({self.current_tokens} > {self.config.compression_threshold})"

        # Soft limit: compress if over target and have enough messages
        if self.current_tokens > self.config.target_working_memory_tokens:
            if self.short_term.count() > self.config.short_term_message_count:
                return (
                    True,
                    f"soft_limit ({self.current_tokens} > {self.config.target_working_memory_tokens}, "
                    f"{self.short_term.count()} messages)",
                )

        return False, None

    def _select_strategy(self, messages: List["LLMMessage"]) -> str:
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

    def _message_has_tool_calls(self, message: "LLMMessage") -> bool:
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
            "net_savings": self.token_tracker.compression_savings - self.token_tracker.compression_cost,
            "short_term_count": self.short_term.count(),
            "summary_count": len(self.summaries),
            "total_cost": self.token_tracker.get_total_cost(self.llm.model),
            "budget_status": self.token_tracker.get_budget_status(self.config.max_context_tokens),
        }

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
