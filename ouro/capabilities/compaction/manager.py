"""CompactionManager — owns compaction policy and orchestrates compression.

This class extracts the compaction-related logic from MemoryManager so that
the memory package can focus on persistence, session management, and token
tracking, while compaction lives in its own capability package.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from ouro.config import Config
from ouro.core.llm.content_utils import content_has_tool_calls
from ouro.core.llm.message_types import LLMMessage

from .compressor import WorkingMemoryCompressor
from .types import CompressedMemory, CompressionStrategy

logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from ouro.core.llm import LLMAdapter


class CompactionManager:
    """Orchestrates working-memory compression.

    Owns the ``WorkingMemoryCompressor``, decides *when* and *how* to
    compress, and applies compression results back to a message list.

    This class is stateless with respect to the message list — it operates
    on lists passed in by callers (e.g. ``MemoryManager``).
    """

    def __init__(self, llm: LLMAdapter) -> None:
        self.llm = llm
        self.compressor = WorkingMemoryCompressor(llm)

        # State tracking (mirrors what MemoryManager used to own)
        self.was_compressed_last_iteration = False
        self.last_compression_savings = 0
        self.compression_count = 0

        # Deferred compression flag
        self._compression_needed = False

        # Optional callback to get current todo context for compression
        self._todo_context_provider: Callable[[], str | None] | None = None

    # ------------------------------------------------------------------
    # Policy / decision-making
    # ------------------------------------------------------------------

    def should_compress(self, current_tokens: int) -> tuple[bool, str | None]:
        """Check if compression should be triggered.

        Args:
            current_tokens: Current token count to check against threshold.

        Returns:
            Tuple of (should_compress, reason)
        """
        if not Config.MEMORY_ENABLED:
            return False, "compression_disabled"

        if current_tokens > Config.MEMORY_COMPRESSION_THRESHOLD:
            return (
                True,
                f"hard_limit ({current_tokens} > {Config.MEMORY_COMPRESSION_THRESHOLD})",
            )

        return False, None

    def mark_compression_needed(self, reason: str) -> None:
        """Set the deferred compression flag."""
        self._compression_needed = True
        logger.info(f"🗜️  Compression needed: {reason} (deferred to react loop)")

    def needs_compression(self) -> bool:
        """Check if deferred compression is pending."""
        return self._compression_needed

    def clear_compression_needed(self) -> None:
        """Clear the deferred compression flag."""
        self._compression_needed = False

    def estimate_tokens(self, messages: list[LLMMessage]) -> int:
        """Estimate the token cost of a message list.

        Used by ``CompactionHook`` each iteration to decide whether
        compression should fire — replaces the legacy flow where
        ``MemoryManager.add_message`` updated an internal token count
        and flipped a deferred flag.
        """
        return self.compressor._estimate_tokens(messages)

    # ------------------------------------------------------------------
    # Prompt building (cache-safe fork)
    # ------------------------------------------------------------------

    async def build_compaction_prompt(
        self,
        messages: list[LLMMessage],
        current_tokens: int,
    ) -> LLMMessage:
        """Build the compaction instruction as a user message.

        Delegates to the compressor for prompt generation. The resulting prompt
        does NOT include the conversation messages (they are already in the LLM
        context), so the LLM call reuses the cached prefix.

        Args:
            messages: Messages being compressed.
            current_tokens: Current token count (used to calculate target).

        Returns:
            LLMMessage with role="user" containing the compaction instruction.
        """
        strategy = self._select_strategy(messages)
        target_tokens = self._calculate_target_tokens(current_tokens)
        todo_context = self._todo_context_provider() if self._todo_context_provider else None

        prompt_text = self.compressor.build_compaction_prompt(
            messages,
            strategy,
            target_tokens,
            todo_context,
        )
        return LLMMessage(role="user", content=prompt_text)

    # Legacy alias
    async def get_compaction_prompt(
        self,
        messages: list[LLMMessage],
        current_tokens: int,
    ) -> LLMMessage:
        """Deprecated — use ``build_compaction_prompt()`` instead."""
        return await self.build_compaction_prompt(messages, current_tokens)

    # ------------------------------------------------------------------
    # Applying compression results
    # ------------------------------------------------------------------

    def apply_compression(
        self,
        summary_text: str,
        messages: list[LLMMessage],
        usage: dict[str, int] | None = None,
    ) -> list[LLMMessage]:
        """Apply the LLM's summary to compress a message list.

        Args:
            summary_text: The LLM-generated summary text.
            messages: The message list to compress.
            usage: Optional token usage from the compression LLM call.

        Returns:
            The compressed message list.
        """
        if not messages:
            self._compression_needed = False
            return list(messages)

        strategy = self._select_strategy(messages)
        todo_context = self._todo_context_provider() if self._todo_context_provider else None

        logger.info(
            f"🗜️  Applying compression to {len(messages)} messages using {strategy} strategy"
        )

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

        # Track compression results
        self.compression_count += 1
        self.was_compressed_last_iteration = True
        self.last_compression_savings = token_savings

        # Clear the deferred flag
        self._compression_needed = False

        compression_ratio = compressed_tokens / original_tokens if original_tokens > 0 else 0
        savings_pct = (token_savings / original_tokens * 100) if original_tokens > 0 else 0
        logger.info(
            f"✅ Compression complete: {original_tokens} → {compressed_tokens} tokens "
            f"({savings_pct:.1f}% saved, ratio: {compression_ratio:.2f}), "
            f"messages now has {len(result_messages)} messages"
        )

        return result_messages

    # ------------------------------------------------------------------
    # Standalone compression (non-cache-safe path)
    # ------------------------------------------------------------------

    async def compress(
        self,
        messages: list[LLMMessage],
        strategy: str | None = None,
        target_tokens: int | None = None,
    ) -> CompressedMemory | None:
        """Compress messages using the compressor.

        After compression, the compressed messages (including any summary as
        user message) are returned in a ``CompressedMemory`` object.

        Args:
            messages: Messages to compress.
            strategy: Compression strategy (None = auto-select).
            target_tokens: Target token count for compressed output.

        Returns:
            CompressedMemory object if compression was performed.
        """
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

            # Calculate target if not provided
            if target_tokens is None:
                original_tokens = self.compressor._estimate_tokens(messages)
                target_tokens = self._calculate_target_tokens(original_tokens)

            compressed = await self.compressor.compress(
                messages,
                strategy=strategy,
                target_tokens=target_tokens,
                todo_context=todo_context,
            )

            # Track compression results
            self.compression_count += 1
            self.was_compressed_last_iteration = True
            self.last_compression_savings = compressed.token_savings

            # Clear the deferred flag
            self._compression_needed = False

            # Log compression results
            logger.info(
                f"✅ Compression complete: {compressed.original_tokens} → {compressed.compressed_tokens} tokens "
                f"({compressed.savings_percentage:.1f}% saved, ratio: {compressed.compression_ratio:.2f}), "
                f"messages now has {len(compressed.messages)} messages"
            )

            return compressed

        except Exception as e:
            logger.error(f"Compression failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def set_todo_context_provider(self, provider: Callable[[], str | None]) -> None:
        """Set a callback to provide current todo context for compression."""
        self._todo_context_provider = provider

    def _select_strategy(self, messages: list[LLMMessage]) -> str:
        """Auto-select compression strategy based on message characteristics."""
        has_tool_calls = any(self._message_has_tool_calls(msg) for msg in messages)

        if has_tool_calls:
            return CompressionStrategy.SELECTIVE
        elif len(messages) < 5:
            return CompressionStrategy.DELETION
        else:
            return CompressionStrategy.SLIDING_WINDOW

    @staticmethod
    def _message_has_tool_calls(message: LLMMessage) -> bool:
        """Check if message contains tool calls."""
        if hasattr(message, "tool_calls") and message.tool_calls:
            return True
        if message.role == "tool":
            return True
        return content_has_tool_calls(message.content)

    def _calculate_target_tokens(self, current_tokens: int) -> int:
        """Calculate target token count for compression."""
        target = int(current_tokens * Config.MEMORY_COMPRESSION_RATIO)
        return max(target, 500)  # Minimum 500 tokens for summary

    def _assemble_compressed_messages(
        self,
        messages: list[LLMMessage],
        summary_message: LLMMessage,
        strategy: str,
    ) -> list[LLMMessage]:
        """Assemble the post-compression message list."""
        if strategy == CompressionStrategy.SELECTIVE:
            preserved, _ = self.compressor._separate_messages(messages)
            non_system_preserved = [m for m in preserved if m.role != "system"]
            return [summary_message] + non_system_preserved
        return [summary_message]

    def reset(self) -> None:
        """Reset compaction state."""
        self.was_compressed_last_iteration = False
        self.last_compression_savings = 0
        self.compression_count = 0
        self._compression_needed = False
