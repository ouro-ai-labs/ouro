"""Memory compression using LLM-based summarization."""
from typing import List, Tuple
import logging

from .types import CompressedMemory, MemoryConfig, CompressionStrategy

logger = logging.getLogger(__name__)


class WorkingMemoryCompressor:
    """Compresses conversation history using LLM summarization."""

    COMPRESSION_PROMPT = """You are a memory compression system. Summarize the following conversation messages while preserving:
1. Key decisions and outcomes
2. Important facts, data, and findings
3. Tool usage patterns and results
4. User intent and goals
5. Critical context needed for future interactions

Original messages ({count} messages, ~{tokens} tokens):

{messages}

Provide a concise but comprehensive summary that captures the essential information. Be specific and include concrete details. Target length: {target_tokens} tokens."""

    def __init__(self, llm: "BaseLLM", config: MemoryConfig):
        """Initialize compressor.

        Args:
            llm: LLM instance to use for summarization
            config: Memory configuration
        """
        self.llm = llm
        self.config = config

    def compress(
        self,
        messages: List["LLMMessage"],
        strategy: str = CompressionStrategy.SLIDING_WINDOW,
        target_tokens: int = None,
    ) -> CompressedMemory:
        """Compress messages using specified strategy.

        Args:
            messages: List of messages to compress
            strategy: Compression strategy to use
            target_tokens: Target token count for compressed output

        Returns:
            CompressedMemory object
        """
        if not messages:
            return CompressedMemory(summary="", preserved_messages=[])

        if target_tokens is None:
            # Calculate target based on config compression ratio
            original_tokens = self._estimate_tokens(messages)
            target_tokens = int(original_tokens * self.config.compression_ratio)

        # Select and apply compression strategy
        if strategy == CompressionStrategy.SLIDING_WINDOW:
            return self._compress_sliding_window(messages, target_tokens)
        elif strategy == CompressionStrategy.SELECTIVE:
            return self._compress_selective(messages, target_tokens)
        elif strategy == CompressionStrategy.DELETION:
            return self._compress_deletion(messages)
        else:
            logger.warning(f"Unknown strategy {strategy}, using sliding window")
            return self._compress_sliding_window(messages, target_tokens)

    def _compress_sliding_window(
        self, messages: List["LLMMessage"], target_tokens: int
    ) -> CompressedMemory:
        """Compress using sliding window strategy.

        Summarizes all messages into a single summary.

        Args:
            messages: Messages to compress
            target_tokens: Target token count

        Returns:
            CompressedMemory object
        """
        # Format messages for summarization
        formatted = self._format_messages_for_summary(messages)
        original_tokens = self._estimate_tokens(messages)

        # Create summarization prompt
        prompt_text = self.COMPRESSION_PROMPT.format(
            count=len(messages),
            tokens=original_tokens,
            messages=formatted,
            target_tokens=target_tokens,
        )

        # Call LLM to generate summary
        try:
            from llm import LLMMessage

            prompt = LLMMessage(role="user", content=prompt_text)
            response = self.llm.call(messages=[prompt], max_tokens=target_tokens * 2)
            summary = self.llm.extract_text(response)

            # Calculate compression metrics
            compressed_tokens = self._estimate_tokens([LLMMessage(role="assistant", content=summary)])
            compression_ratio = compressed_tokens / original_tokens if original_tokens > 0 else 0

            return CompressedMemory(
                summary=summary,
                preserved_messages=[],
                original_message_count=len(messages),
                compressed_tokens=compressed_tokens,
                original_tokens=original_tokens,
                compression_ratio=compression_ratio,
                metadata={"strategy": "sliding_window"},
            )
        except Exception as e:
            logger.error(f"Error during compression: {e}")
            # Fallback: just keep first and last message
            return CompressedMemory(
                summary="[Compression failed, preserving key messages]",
                preserved_messages=[messages[0], messages[-1]] if len(messages) > 1 else messages,
                original_message_count=len(messages),
                compressed_tokens=self._estimate_tokens(messages[:1] + messages[-1:]),
                original_tokens=original_tokens,
                compression_ratio=0.5,
                metadata={"strategy": "sliding_window", "error": str(e)},
            )

    def _compress_selective(
        self, messages: List["LLMMessage"], target_tokens: int
    ) -> CompressedMemory:
        """Compress using selective preservation strategy.

        Preserves important messages (tool calls, system prompts) and
        summarizes the rest.

        Args:
            messages: Messages to compress
            target_tokens: Target token count

        Returns:
            CompressedMemory object
        """
        # Separate preserved vs compressible messages
        preserved, to_compress = self._separate_messages(messages)

        if not to_compress:
            # Nothing to compress
            return CompressedMemory(
                summary="",
                preserved_messages=preserved,
                original_message_count=len(messages),
                compressed_tokens=self._estimate_tokens(preserved),
                original_tokens=self._estimate_tokens(messages),
                compression_ratio=1.0,
                metadata={"strategy": "selective"},
            )

        # Compress the compressible messages
        original_tokens = self._estimate_tokens(messages)
        preserved_tokens = self._estimate_tokens(preserved)
        available_for_summary = target_tokens - preserved_tokens

        if available_for_summary > 0:
            # Generate summary for compressible messages
            formatted = self._format_messages_for_summary(to_compress)
            prompt_text = self.COMPRESSION_PROMPT.format(
                count=len(to_compress),
                tokens=self._estimate_tokens(to_compress),
                messages=formatted,
                target_tokens=available_for_summary,
            )

            try:
                from llm import LLMMessage

                prompt = LLMMessage(role="user", content=prompt_text)
                response = self.llm.call(messages=[prompt], max_tokens=available_for_summary * 2)
                summary = self.llm.extract_text(response)

                summary_tokens = self._estimate_tokens([LLMMessage(role="assistant", content=summary)])
                compressed_tokens = preserved_tokens + summary_tokens
                compression_ratio = compressed_tokens / original_tokens if original_tokens > 0 else 0

                return CompressedMemory(
                    summary=summary,
                    preserved_messages=preserved,
                    original_message_count=len(messages),
                    compressed_tokens=compressed_tokens,
                    original_tokens=original_tokens,
                    compression_ratio=compression_ratio,
                    metadata={"strategy": "selective", "preserved_count": len(preserved)},
                )
            except Exception as e:
                logger.error(f"Error during selective compression: {e}")

        # Fallback: just preserve the important messages
        return CompressedMemory(
            summary="",
            preserved_messages=preserved,
            original_message_count=len(messages),
            compressed_tokens=preserved_tokens,
            original_tokens=original_tokens,
            compression_ratio=preserved_tokens / original_tokens if original_tokens > 0 else 1.0,
            metadata={"strategy": "selective", "preserved_count": len(preserved)},
        )

    def _compress_deletion(self, messages: List["LLMMessage"]) -> CompressedMemory:
        """Simple deletion strategy - no compression, just drop old messages.

        Args:
            messages: Messages (will be deleted)

        Returns:
            CompressedMemory with empty summary
        """
        original_tokens = self._estimate_tokens(messages)

        return CompressedMemory(
            summary="",
            preserved_messages=[],
            original_message_count=len(messages),
            compressed_tokens=0,
            original_tokens=original_tokens,
            compression_ratio=0.0,
            metadata={"strategy": "deletion"},
        )

    def _separate_messages(
        self, messages: List["LLMMessage"]
    ) -> Tuple[List["LLMMessage"], List["LLMMessage"]]:
        """Separate messages into preserved and compressible.

        Args:
            messages: All messages

        Returns:
            Tuple of (preserved, to_compress)
        """
        preserved = []
        to_compress = []

        for msg in messages:
            if self._should_preserve(msg):
                preserved.append(msg)
            else:
                to_compress.append(msg)

        return preserved, to_compress

    def _should_preserve(self, message: "LLMMessage") -> bool:
        """Check if message should be preserved verbatim.

        Args:
            message: Message to check

        Returns:
            True if should preserve
        """
        # Always preserve system prompts
        if self.config.preserve_system_prompts and message.role == "system":
            return True

        # Check for tool calls in content
        if self.config.preserve_tool_calls:
            content = message.content
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") in ["tool_use", "tool_result", "tool_calls"]:
                            return True

        return False

    def _format_messages_for_summary(self, messages: List["LLMMessage"]) -> str:
        """Format messages for inclusion in summary prompt.

        Args:
            messages: Messages to format

        Returns:
            Formatted string
        """
        formatted = []
        for i, msg in enumerate(messages, 1):
            role = msg.role.upper()
            content = self._extract_text_content(msg)
            formatted.append(f"[{i}] {role}: {content}")

        return "\n\n".join(formatted)

    def _extract_text_content(self, message: "LLMMessage") -> str:
        """Extract text content from message.

        Args:
            message: Message to extract from

        Returns:
            Text content
        """
        content = message.content

        if isinstance(content, str):
            return content
        elif isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        text_parts.append(f"[Tool: {block.get('name', 'unknown')}]")
                    elif block.get("type") == "tool_result":
                        text_parts.append("[Tool Result]")
            return " ".join(text_parts)
        else:
            return str(content)

    def _estimate_tokens(self, messages: List["LLMMessage"]) -> int:
        """Estimate token count for messages.

        Args:
            messages: Messages to count

        Returns:
            Estimated token count
        """
        # Simple estimation: 4 characters per token
        total_chars = 0
        for msg in messages:
            content = self._extract_text_content(msg)
            total_chars += len(content)

        return total_chars // 4
