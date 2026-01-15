"""Memory compression using LLM-based summarization."""

import logging
from typing import TYPE_CHECKING, List, Optional, Set, Tuple

from llm.base import LLMMessage

from .types import CompressedMemory, CompressionStrategy, MemoryConfig

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from llm import LiteLLMLLM


class WorkingMemoryCompressor:
    """Compresses conversation history using LLM summarization."""

    # Tools that should NEVER be compressed - their state must be preserved
    PROTECTED_TOOLS = {
        "manage_todo_list",  # Todo list state is critical for tracking progress
    }

    COMPRESSION_PROMPT = """You are a memory compression system. Summarize the following conversation messages while preserving:
1. Key decisions and outcomes
2. Important facts, data, and findings
3. Tool usage patterns and results
4. User intent and goals
5. Critical context needed for future interactions

Original messages ({count} messages, ~{tokens} tokens):

{messages}

    Provide a concise but comprehensive summary that captures the essential information. Be specific and include concrete details. Target length: {target_tokens} tokens."""

    def __init__(self, llm: "LiteLLMLLM", config: MemoryConfig):
        """Initialize compressor.

        Args:
            llm: LLM instance to use for summarization
            config: Memory configuration
        """
        self.llm = llm
        self.config = config

    def compress(
        self,
        messages: List[LLMMessage],
        strategy: str = CompressionStrategy.SLIDING_WINDOW,
        target_tokens: Optional[int] = None,
        orphaned_tool_use_ids: Optional[Set[str]] = None,
    ) -> CompressedMemory:
        """Compress messages using specified strategy.

        Args:
            messages: List of messages to compress
            strategy: Compression strategy to use
            target_tokens: Target token count for compressed output
            orphaned_tool_use_ids: Set of tool_use IDs from previous summaries that are
                                   waiting for tool_result in current messages

        Returns:
            CompressedMemory object
        """
        if not messages:
            return CompressedMemory(summary="", preserved_messages=[])

        if target_tokens is None:
            # Calculate target based on config compression ratio
            original_tokens = self._estimate_tokens(messages)
            target_tokens = int(original_tokens * self.config.compression_ratio)

        if orphaned_tool_use_ids is None:
            orphaned_tool_use_ids = set()

        # Select and apply compression strategy
        if strategy == CompressionStrategy.SLIDING_WINDOW:
            return self._compress_sliding_window(messages, target_tokens)
        elif strategy == CompressionStrategy.SELECTIVE:
            return self._compress_selective(messages, target_tokens, orphaned_tool_use_ids)
        elif strategy == CompressionStrategy.DELETION:
            return self._compress_deletion(messages)
        else:
            logger.warning(f"Unknown strategy {strategy}, using sliding window")
            return self._compress_sliding_window(messages, target_tokens)

    def _compress_sliding_window(
        self, messages: List[LLMMessage], target_tokens: int
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
            compressed_tokens = self._estimate_tokens(
                [LLMMessage(role="assistant", content=summary)]
            )
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
        self, messages: List[LLMMessage], target_tokens: int, orphaned_tool_use_ids: set = None
    ) -> CompressedMemory:
        """Compress using selective preservation strategy.

        Preserves important messages (tool calls, system prompts) and
        summarizes the rest.

        Args:
            messages: Messages to compress
            target_tokens: Target token count
            orphaned_tool_use_ids: Set of tool_use IDs from previous summaries

        Returns:
            CompressedMemory object
        """
        if orphaned_tool_use_ids is None:
            orphaned_tool_use_ids = set()

        # Separate preserved vs compressible messages
        preserved, to_compress = self._separate_messages(messages, orphaned_tool_use_ids)

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

                summary_tokens = self._estimate_tokens(
                    [LLMMessage(role="assistant", content=summary)]
                )
                compressed_tokens = preserved_tokens + summary_tokens
                compression_ratio = (
                    compressed_tokens / original_tokens if original_tokens > 0 else 0
                )

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

    def _compress_deletion(self, messages: List[LLMMessage]) -> CompressedMemory:
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
        self, messages: List[LLMMessage], orphaned_tool_use_ids_from_summaries: set = None
    ) -> Tuple[List[LLMMessage], List[LLMMessage]]:
        """Separate messages into preserved and compressible.

        Strategy:
        1. Preserve system messages (if configured)
        2. Preserve protected tools (todo list, etc.) - NEVER compress these
        3. Use selective strategy for other messages (system decides based on recency, importance)
        4. **Critical rule**: Tool pairs (tool_use + tool_result) must stay together
           - If one is preserved, the other must be preserved too
           - If one is compressed, the other must be compressed too
        5. **Critical fix**: Preserve tool_result that match orphaned tool_use from previous summaries

        Args:
            messages: All messages
            orphaned_tool_use_ids_from_summaries: Tool_use IDs from previous summaries waiting for results

        Returns:
            Tuple of (preserved, to_compress)
        """
        if orphaned_tool_use_ids_from_summaries is None:
            orphaned_tool_use_ids_from_summaries = set()

        preserve_indices = set()

        # Step 1: Mark system messages for preservation
        for i, msg in enumerate(messages):
            if self.config.preserve_system_prompts and msg.role == "system":
                preserve_indices.add(i)

        # Step 2: Find tool pairs and orphaned tool_use messages
        tool_pairs, orphaned_tool_use_indices = self._find_tool_pairs(messages)

        # Step 2a: CRITICAL - Preserve orphaned tool_use (waiting for tool_result)
        # These must NEVER be compressed, or we'll lose the tool_use without its result
        for orphan_idx in orphaned_tool_use_indices:
            preserve_indices.add(orphan_idx)

        # Step 2b: CRITICAL FIX - Preserve tool_result that match orphaned tool_use from previous summaries
        # These results finally arrived and must be preserved to match their tool_use
        for i, msg in enumerate(messages):
            if msg.role == "user" and isinstance(msg.content, list):
                for block in msg.content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        tool_use_id = block.get("tool_use_id")
                        if tool_use_id in orphaned_tool_use_ids_from_summaries:
                            preserve_indices.add(i)
                            logger.info(
                                f"Preserving tool_result for orphaned tool_use '{tool_use_id}' from previous summary"
                            )

        # Step 2c: Mark protected tools for preservation (CRITICAL for stateful tools)
        protected_pairs = self._find_protected_tool_pairs(messages, tool_pairs)
        for assistant_idx, user_idx in protected_pairs:
            preserve_indices.add(assistant_idx)
            preserve_indices.add(user_idx)

        # Step 3: Apply selective preservation strategy (keep recent N messages)
        # Preserve last short_term_min_message_count messages by default (sliding window approach)
        preserve_count = min(self.config.short_term_min_message_count, len(messages))
        for i in range(len(messages) - preserve_count, len(messages)):
            if i >= 0:
                preserve_indices.add(i)

        # Step 4: Ensure tool pairs stay together
        for assistant_idx, user_idx in tool_pairs:
            # If either message in the pair is marked for preservation, preserve both
            if assistant_idx in preserve_indices or user_idx in preserve_indices:
                preserve_indices.add(assistant_idx)
                preserve_indices.add(user_idx)
            # Otherwise both will be compressed together

        # Step 5: Build preserved and to_compress lists
        preserved = []
        to_compress = []
        for i, msg in enumerate(messages):
            if i in preserve_indices:
                preserved.append(msg)
            else:
                to_compress.append(msg)

        logger.info(
            f"Separated: {len(preserved)} preserved, {len(to_compress)} to compress "
            f"({len(tool_pairs)} tool pairs, {len(protected_pairs)} protected, "
            f"{len(orphaned_tool_use_indices)} orphaned tool_use)"
        )
        return preserved, to_compress

    def _find_tool_pairs(self, messages: List[LLMMessage]) -> tuple[List[List[int]], List[int]]:
        """Find tool_use/tool_result pairs in messages.

        Returns:
            Tuple of (pairs, orphaned_tool_use_indices)
            - pairs: List of [assistant_index, user_index] for matched pairs
            - orphaned_tool_use_indices: List of message indices with unmatched tool_use
        """
        pairs = []
        pending_tool_uses = {}  # tool_id -> message_index

        for i, msg in enumerate(messages):
            if msg.role == "assistant" and isinstance(msg.content, list):
                # Collect tool_use IDs
                for block in msg.content:
                    btype = self._get_block_attr(block, "type")
                    if btype == "tool_use":
                        tool_id = self._get_block_attr(block, "id")
                        if tool_id:
                            pending_tool_uses[tool_id] = i

            elif msg.role == "user" and isinstance(msg.content, list):
                # Match tool_result with tool_use
                for block in msg.content:
                    btype = self._get_block_attr(block, "type")
                    if btype == "tool_result":
                        tool_use_id = self._get_block_attr(block, "tool_use_id")
                        if tool_use_id in pending_tool_uses:
                            assistant_idx = pending_tool_uses[tool_use_id]
                            pairs.append([assistant_idx, i])
                            del pending_tool_uses[tool_use_id]

        # Remaining items in pending_tool_uses are orphaned (no matching result yet)
        orphaned_indices = list(pending_tool_uses.values())

        if orphaned_indices:
            logger.warning(
                f"Found {len(orphaned_indices)} orphaned tool_use without matching tool_result - "
                f"these will be preserved to wait for results"
            )

        return pairs, orphaned_indices

    def _find_protected_tool_pairs(
        self, messages: List[LLMMessage], tool_pairs: List[List[int]]
    ) -> List[List[int]]:
        """Find tool pairs that use protected tools (must never be compressed).

        Args:
            messages: All messages
            tool_pairs: All tool_use/tool_result pairs

        Returns:
            List of protected tool pairs [assistant_index, user_index]
        """
        protected_pairs = []

        for assistant_idx, user_idx in tool_pairs:
            # Check if this tool pair uses a protected tool
            msg = messages[assistant_idx]
            if msg.role == "assistant" and isinstance(msg.content, list):
                for block in msg.content:
                    btype = self._get_block_attr(block, "type")
                    if btype == "tool_use":
                        tool_name = self._get_block_attr(block, "name")
                        if tool_name in self.PROTECTED_TOOLS:
                            protected_pairs.append([assistant_idx, user_idx])
                            logger.debug(
                                f"Protected tool '{tool_name}' at indices [{assistant_idx}, {user_idx}] - will be preserved"
                            )
                            break  # Only need to find one protected tool in the message

        return protected_pairs

    def _get_block_attr(self, block, attr: str):
        """Get attribute from block (supports dict and object)."""
        if isinstance(block, dict):
            return block.get(attr)
        return getattr(block, attr, None)

    def _format_messages_for_summary(self, messages: List[LLMMessage]) -> str:
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

    def _extract_text_content(self, message: LLMMessage) -> str:
        """Extract text content from message for token estimation.

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
                # For dict format
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    else:
                        # For tool_use/tool_result, use simple representation
                        text_parts.append(str(block))
                # For object format (ContentBlock from Anthropic SDK)
                else:
                    # Simple conversion to string for token estimation
                    text_parts.append(str(block))
            return " ".join(text_parts)
        else:
            return str(content)

    def _estimate_tokens(self, messages: List[LLMMessage]) -> int:
        """Estimate token count for messages.

        Args:
            messages: Messages to count

        Returns:
            Estimated token count
        """
        # Improved estimation: account for message structure and content
        total_chars = 0
        for msg in messages:
            # Add overhead for message structure (role, type fields, etc.)
            total_chars += 20  # ~5 tokens for structure

            # Extract and count content
            content = self._extract_text_content(msg)
            total_chars += len(content)

            # For complex content (lists), add overhead for JSON structure
            if isinstance(msg.content, list):
                # Each block has type, id, etc. fields
                total_chars += len(msg.content) * 30  # ~7 tokens per block overhead

        # More accurate ratio: ~3.5 characters per token for mixed content
        # (English text is ~4 chars/token, code/JSON is ~3 chars/token)
        return int(total_chars / 3.5)
