"""Memory compression using LLM-based summarization."""

import logging
from typing import TYPE_CHECKING, List, Optional, Tuple

from config import Config
from llm.content_utils import extract_text
from llm.message_types import LLMMessage

from .types import CompressedMemory, CompressionStrategy

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from llm import LiteLLMAdapter


class WorkingMemoryCompressor:
    """Compresses conversation history using LLM summarization."""

    # Tools that should NEVER be compressed - their state must be preserved
    # Note: manage_todo_list is NOT protected because its state is managed externally
    # by TodoList object. Instead, we inject current todo state into the summary.
    PROTECTED_TOOLS: set[str] = set()

    # Prefix for summary messages to identify them
    SUMMARY_PREFIX = "[Previous conversation summary]\n"

    COMPRESSION_PROMPT = """You are a memory compression system. Summarize the following conversation messages while preserving:
1. Key decisions and outcomes
2. Important facts, data, and findings
3. Tool usage patterns and results
4. User intent and goals
5. Critical context needed for future interactions

Original messages ({count} messages, ~{tokens} tokens):

{messages}

    Provide a concise but comprehensive summary that captures the essential information. Be specific and include concrete details. Target length: {target_tokens} tokens."""

    def __init__(self, llm: "LiteLLMAdapter"):
        """Initialize compressor.

        Args:
            llm: LLM instance to use for summarization
        """
        self.llm = llm

    async def compress(
        self,
        messages: List[LLMMessage],
        strategy: str = CompressionStrategy.SLIDING_WINDOW,
        target_tokens: Optional[int] = None,
        todo_context: Optional[str] = None,
    ) -> CompressedMemory:
        """Compress messages using specified strategy.

        Args:
            messages: List of messages to compress
            strategy: Compression strategy to use
            target_tokens: Target token count for compressed output
            todo_context: Optional current todo list state to inject into summary

        Returns:
            CompressedMemory object
        """
        if not messages:
            return CompressedMemory(messages=[])

        if target_tokens is None:
            # Calculate target based on config compression ratio
            original_tokens = self._estimate_tokens(messages)
            target_tokens = int(original_tokens * Config.MEMORY_COMPRESSION_RATIO)

        # Select and apply compression strategy
        if strategy == CompressionStrategy.SLIDING_WINDOW:
            return await self._compress_sliding_window(messages, target_tokens, todo_context)
        elif strategy == CompressionStrategy.SELECTIVE:
            return await self._compress_selective(messages, target_tokens, todo_context)
        elif strategy == CompressionStrategy.DELETION:
            return self._compress_deletion(messages)
        else:
            logger.warning(f"Unknown strategy {strategy}, using sliding window")
            return await self._compress_sliding_window(messages, target_tokens, todo_context)

    async def _compress_sliding_window(
        self,
        messages: List[LLMMessage],
        target_tokens: int,
        todo_context: Optional[str] = None,
    ) -> CompressedMemory:
        """Compress using sliding window strategy.

        Summarizes all messages into a single summary. If todo_context is provided,
        it will be appended to the summary to preserve current task state.

        Args:
            messages: Messages to compress
            target_tokens: Target token count
            todo_context: Optional current todo list state to inject

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

        # Extract system messages to preserve them
        system_msgs = [m for m in messages if m.role == "system"]

        # Call LLM to generate summary
        try:
            prompt = LLMMessage(role="user", content=prompt_text)
            response = await self.llm.call_async(messages=[prompt], max_tokens=target_tokens * 2)
            summary_text = self.llm.extract_text(response)

            # Append todo context if available
            if todo_context:
                summary_text = f"{summary_text}\n\n[Current Tasks]\n{todo_context}"

            # Convert summary to a user message
            summary_message = LLMMessage(
                role="user",
                content=f"{self.SUMMARY_PREFIX}{summary_text}",
            )

            # System messages first, then summary
            result_messages = system_msgs + [summary_message]

            # Calculate compression metrics
            compressed_tokens = self._estimate_tokens(result_messages)
            compression_ratio = compressed_tokens / original_tokens if original_tokens > 0 else 0

            return CompressedMemory(
                messages=result_messages,
                original_message_count=len(messages),
                compressed_tokens=compressed_tokens,
                original_tokens=original_tokens,
                compression_ratio=compression_ratio,
                metadata={"strategy": "sliding_window"},
            )
        except Exception as e:
            logger.error(f"Error during compression: {e}")
            # Fallback: keep system messages + first and last non-system message
            non_system = [m for m in messages if m.role != "system"]
            fallback_other = [non_system[0], non_system[-1]] if len(non_system) > 1 else non_system
            fallback_messages = system_msgs + fallback_other
            return CompressedMemory(
                messages=fallback_messages,
                original_message_count=len(messages),
                compressed_tokens=self._estimate_tokens(fallback_messages),
                original_tokens=original_tokens,
                compression_ratio=0.5,
                metadata={"strategy": "sliding_window", "error": str(e)},
            )

    async def _compress_selective(
        self,
        messages: List[LLMMessage],
        target_tokens: int,
        todo_context: Optional[str] = None,
    ) -> CompressedMemory:
        """Compress using selective preservation strategy.

        Preserves important messages (tool calls, system prompts) and
        summarizes the rest. If todo_context is provided, it will be
        appended to the summary to preserve current task state.

        Args:
            messages: Messages to compress
            target_tokens: Target token count
            todo_context: Optional current todo list state to inject

        Returns:
            CompressedMemory object
        """
        # Separate preserved vs compressible messages
        preserved, to_compress = self._separate_messages(messages)

        if not to_compress:
            # Nothing to compress, just return preserved messages
            # Ensure system messages are first
            system_msgs = [m for m in preserved if m.role == "system"]
            other_msgs = [m for m in preserved if m.role != "system"]
            result_messages = system_msgs + other_msgs
            return CompressedMemory(
                messages=result_messages,
                original_message_count=len(messages),
                compressed_tokens=self._estimate_tokens(result_messages),
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
                prompt = LLMMessage(role="user", content=prompt_text)
                response = await self.llm.call_async(
                    messages=[prompt], max_tokens=available_for_summary * 2
                )
                summary_text = self.llm.extract_text(response)

                # Append todo context if available
                if todo_context:
                    summary_text = f"{summary_text}\n\n[Current Tasks]\n{todo_context}"

                # Convert summary to user message
                summary_message = LLMMessage(
                    role="user",
                    content=f"{self.SUMMARY_PREFIX}{summary_text}",
                )
                # Ensure system messages come first, then summary, then other preserved
                system_msgs = [m for m in preserved if m.role == "system"]
                other_msgs = [m for m in preserved if m.role != "system"]
                result_messages = system_msgs + [summary_message] + other_msgs

                summary_tokens = self._estimate_tokens([summary_message])
                compressed_tokens = preserved_tokens + summary_tokens
                compression_ratio = (
                    compressed_tokens / original_tokens if original_tokens > 0 else 0
                )

                return CompressedMemory(
                    messages=result_messages,
                    original_message_count=len(messages),
                    compressed_tokens=compressed_tokens,
                    original_tokens=original_tokens,
                    compression_ratio=compression_ratio,
                    metadata={"strategy": "selective", "preserved_count": len(preserved)},
                )
            except Exception as e:
                logger.error(f"Error during selective compression: {e}")

        # Fallback: just preserve the important messages (no summary)
        # Ensure system messages are first
        system_msgs = [m for m in preserved if m.role == "system"]
        other_msgs = [m for m in preserved if m.role != "system"]
        result_messages = system_msgs + other_msgs
        return CompressedMemory(
            messages=result_messages,
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
            CompressedMemory with empty messages list
        """
        original_tokens = self._estimate_tokens(messages)

        return CompressedMemory(
            messages=[],
            original_message_count=len(messages),
            compressed_tokens=0,
            original_tokens=original_tokens,
            compression_ratio=0.0,
            metadata={"strategy": "deletion"},
        )

    def _separate_messages(
        self, messages: List[LLMMessage]
    ) -> Tuple[List[LLMMessage], List[LLMMessage]]:
        """Separate messages into preserved and compressible.

        Strategy:
        1. Preserve system messages (if configured)
        2. Preserve orphaned tool_use (waiting for tool_result)
        3. Preserve protected tools (todo list, etc.) - NEVER compress these
        4. Preserve the most recent N messages (MEMORY_SHORT_TERM_MIN_SIZE)
        5. **Critical rule**: Tool pairs (tool_use + tool_result) must stay together
           - If one is preserved, the other must be preserved too
           - If one is compressed, the other must be compressed too

        Args:
            messages: All messages

        Returns:
            Tuple of (preserved, to_compress)
        """
        preserve_indices = set()

        # Step 1: Mark system messages for preservation
        for i, msg in enumerate(messages):
            if Config.MEMORY_PRESERVE_SYSTEM_PROMPTS and msg.role == "system":
                preserve_indices.add(i)

        # Step 2: Find tool pairs and orphaned tool_use messages
        tool_pairs, orphaned_tool_use_indices = self._find_tool_pairs(messages)

        # Step 2a: CRITICAL - Preserve orphaned tool_use (waiting for tool_result)
        # These must NEVER be compressed, or we'll lose the tool_use without its result
        for orphan_idx in orphaned_tool_use_indices:
            preserve_indices.add(orphan_idx)

        # Step 2b: Mark protected tools for preservation (CRITICAL for stateful tools)
        protected_pairs = self._find_protected_tool_pairs(messages, tool_pairs)
        for assistant_idx, user_idx in protected_pairs:
            preserve_indices.add(assistant_idx)
            preserve_indices.add(user_idx)

        # Step 3: Preserve the most recent N messages to maintain conversation continuity
        preserve_count = min(Config.MEMORY_SHORT_TERM_MIN_SIZE, len(messages))
        for i in range(len(messages) - preserve_count, len(messages)):
            if i >= 0:
                preserve_indices.add(i)

        # Step 4: Ensure tool pairs stay together (iterate until stable)
        # A single pass can miss pairs: e.g. pair [A, T1] is skipped because
        # neither is preserved, then pair [A, T2] preserves A because T2 is in
        # the recent window — but T1 was already skipped.  Fixed-point loop
        # ensures all pairs containing a preserved index are fully preserved.
        changed = True
        while changed:
            changed = False
            for assistant_idx, user_idx in tool_pairs:
                if assistant_idx in preserve_indices or user_idx in preserve_indices:
                    if assistant_idx not in preserve_indices:
                        preserve_indices.add(assistant_idx)
                        changed = True
                    if user_idx not in preserve_indices:
                        preserve_indices.add(user_idx)
                        changed = True

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
            f"{len(orphaned_tool_use_indices)} orphaned tool_use, "
            f"{preserve_count} recent)"
        )
        return preserved, to_compress

    def _find_tool_pairs(self, messages: List[LLMMessage]) -> tuple[List[List[int]], List[int]]:
        """Find tool_use/tool_result pairs in messages.

        Handles both:
        - New format: assistant.tool_calls + tool role messages
        - Legacy format: tool_use blocks in assistant content + tool_result blocks in user content

        Returns:
            Tuple of (pairs, orphaned_tool_use_indices)
            - pairs: List of [assistant_index, tool_response_index] for matched pairs
            - orphaned_tool_use_indices: List of message indices with unmatched tool_use
        """
        pairs = []
        pending_tool_uses = {}  # tool_id -> message_index

        for i, msg in enumerate(messages):
            # New format: assistant with tool_calls field
            if msg.role == "assistant" and hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                    if tool_id:
                        pending_tool_uses[tool_id] = i

            # Legacy format: assistant with tool_use blocks in content
            elif msg.role == "assistant" and isinstance(msg.content, list):
                for block in msg.content:
                    btype = self._get_block_attr(block, "type")
                    if btype == "tool_use":
                        tool_id = self._get_block_attr(block, "id")
                        if tool_id:
                            pending_tool_uses[tool_id] = i

            # New format: tool role message
            elif msg.role == "tool" and hasattr(msg, "tool_call_id") and msg.tool_call_id:
                tool_call_id = msg.tool_call_id
                if tool_call_id in pending_tool_uses:
                    assistant_idx = pending_tool_uses[tool_call_id]
                    pairs.append([assistant_idx, i])
                    del pending_tool_uses[tool_call_id]

            # Legacy format: user with tool_result blocks in content
            elif msg.role == "user" and isinstance(msg.content, list):
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
            logger.debug(
                f"Found {len(orphaned_indices)} orphaned tool_use without matching tool_result - "
                f"these will be preserved to wait for results"
            )

        return pairs, orphaned_indices

    def _find_protected_tool_pairs(
        self, messages: List[LLMMessage], tool_pairs: List[List[int]]
    ) -> List[List[int]]:
        """Find tool pairs that use protected tools (must never be compressed).

        Handles both new format (tool_calls field) and legacy format (tool_use blocks).

        Args:
            messages: All messages
            tool_pairs: All tool_use/tool_result pairs

        Returns:
            List of protected tool pairs [assistant_index, tool_response_index]
        """
        protected_pairs = []

        for assistant_idx, response_idx in tool_pairs:
            msg = messages[assistant_idx]

            # New format: check tool_calls field
            if msg.role == "assistant" and hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    if isinstance(tc, dict):
                        tool_name = tc.get("function", {}).get("name", "")
                    else:
                        tool_name = (
                            getattr(tc.function, "name", "") if hasattr(tc, "function") else ""
                        )
                    if tool_name in self.PROTECTED_TOOLS:
                        protected_pairs.append([assistant_idx, response_idx])
                        logger.debug(
                            f"Protected tool '{tool_name}' at indices [{assistant_idx}, {response_idx}] - will be preserved"
                        )
                        break

            # Legacy format: check tool_use blocks in content
            elif msg.role == "assistant" and isinstance(msg.content, list):
                for block in msg.content:
                    btype = self._get_block_attr(block, "type")
                    if btype == "tool_use":
                        tool_name = self._get_block_attr(block, "name")
                        if tool_name in self.PROTECTED_TOOLS:
                            protected_pairs.append([assistant_idx, response_idx])
                            logger.debug(
                                f"Protected tool '{tool_name}' at indices [{assistant_idx}, {response_idx}] - will be preserved"
                            )
                            break

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

        Uses centralized extract_text from content_utils.

        Args:
            message: Message to extract from

        Returns:
            Text content
        """
        # Use centralized extraction
        text = extract_text(message.content)

        # For token estimation, also include tool call info as string representation
        if hasattr(message, "tool_calls") and message.tool_calls:
            text += " " + str(message.tool_calls)

        return text if text else str(message.content)

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
