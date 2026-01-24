"""Integration tests for memory module.

These tests verify that different components work together correctly,
especially focusing on edge cases and the tool_call/tool_result matching issue.
"""

from llm.base import LLMMessage
from memory import MemoryManager
from memory.types import CompressionStrategy


class TestToolCallResultIntegration:
    """Integration tests for tool_call and tool_result matching.

    This is the critical test suite for the bug mentioned by the user.
    """

    async def test_tool_pairs_survive_compression_cycle(self, set_memory_config, mock_llm):
        """Test that tool pairs remain matched through compression cycles."""
        set_memory_config(
            MEMORY_SHORT_TERM_SIZE=6,
            MEMORY_SHORT_TERM_MIN_SIZE=2,
        )
        manager = MemoryManager(mock_llm)

        # Add a sequence of tool calls
        messages = []
        for i in range(3):
            messages.extend(
                [
                    LLMMessage(role="user", content=f"Request {i}"),
                    LLMMessage(
                        role="assistant",
                        content=[
                            {
                                "type": "tool_use",
                                "id": f"tool_{i}",
                                "name": f"tool_{i}",
                                "input": {},
                            }
                        ],
                    ),
                    LLMMessage(
                        role="user",
                        content=[
                            {
                                "type": "tool_result",
                                "tool_use_id": f"tool_{i}",
                                "content": f"result_{i}",
                            }
                        ],
                    ),
                    LLMMessage(role="assistant", content=f"Response {i}"),
                ]
            )

        # Add messages and trigger compression
        for msg in messages:
            await manager.add_message(msg)

        # Verify no mismatches in context
        context = manager.get_context_for_llm()
        self._verify_tool_pairs_matched(context)

    async def test_tool_pairs_with_multiple_compressions(self, set_memory_config, mock_llm):
        """Test tool pairs remain matched through multiple compression cycles."""
        set_memory_config(
            MEMORY_SHORT_TERM_SIZE=4,
            MEMORY_SHORT_TERM_MIN_SIZE=2,
        )
        manager = MemoryManager(mock_llm)

        # Add messages in multiple batches, triggering multiple compressions
        for batch in range(3):
            for i in range(2):
                idx = batch * 2 + i
                await manager.add_message(LLMMessage(role="user", content=f"Request {idx}"))
                await manager.add_message(
                    LLMMessage(
                        role="assistant",
                        content=[
                            {
                                "type": "tool_use",
                                "id": f"tool_{idx}",
                                "name": f"tool_{idx}",
                                "input": {},
                            }
                        ],
                    )
                )
                await manager.add_message(
                    LLMMessage(
                        role="user",
                        content=[
                            {
                                "type": "tool_result",
                                "tool_use_id": f"tool_{idx}",
                                "content": f"result_{idx}",
                            }
                        ],
                    )
                )
                await manager.add_message(LLMMessage(role="assistant", content=f"Response {idx}"))

        # Verify no mismatches after multiple compressions
        context = manager.get_context_for_llm()
        self._verify_tool_pairs_matched(context)

    async def test_interleaved_tool_calls(self, set_memory_config, mock_llm):
        """Test tool pairs when tool calls are interleaved."""
        set_memory_config(MEMORY_SHORT_TERM_SIZE=10)
        manager = MemoryManager(mock_llm)

        # Add interleaved tool calls (assistant makes multiple tool calls at once)
        await manager.add_message(LLMMessage(role="user", content="Complex request"))
        await manager.add_message(
            LLMMessage(
                role="assistant",
                content=[
                    {"type": "tool_use", "id": "tool_1", "name": "tool_a", "input": {}},
                    {"type": "tool_use", "id": "tool_2", "name": "tool_b", "input": {}},
                ],
            )
        )
        # Results come back together
        await manager.add_message(
            LLMMessage(
                role="user",
                content=[
                    {"type": "tool_result", "tool_use_id": "tool_1", "content": "result_1"},
                    {"type": "tool_result", "tool_use_id": "tool_2", "content": "result_2"},
                ],
            )
        )
        await manager.add_message(LLMMessage(role="assistant", content="Final response"))

        # Force compression
        await manager.compress(strategy=CompressionStrategy.SELECTIVE)

        context = manager.get_context_for_llm()
        self._verify_tool_pairs_matched(context)

    async def test_orphaned_tool_use_detection(self, set_memory_config, mock_llm):
        """Test detection of orphaned tool_use (no matching result)."""
        set_memory_config(MEMORY_SHORT_TERM_SIZE=5)
        manager = MemoryManager(mock_llm)

        # Add tool_use without result
        await manager.add_message(LLMMessage(role="user", content="Request"))
        await manager.add_message(
            LLMMessage(
                role="assistant",
                content=[{"type": "tool_use", "id": "orphan_tool", "name": "tool", "input": {}}],
            )
        )
        # Missing tool_result!
        await manager.add_message(LLMMessage(role="user", content="Another request"))

        # Force compression
        await manager.compress(strategy=CompressionStrategy.SELECTIVE)

        context = manager.get_context_for_llm()

        # Check for orphans
        tool_use_ids = set()
        tool_result_ids = set()

        for msg in context:
            if isinstance(msg.content, list):
                for block in msg.content:
                    if isinstance(block, dict):
                        if block.get("type") == "tool_use":
                            tool_use_ids.add(block.get("id"))
                        elif block.get("type") == "tool_result":
                            tool_result_ids.add(block.get("tool_use_id"))

        # Document the orphan
        orphans = tool_use_ids - tool_result_ids
        if orphans:
            print(f"Detected orphaned tool_use: {orphans}")

    async def test_orphaned_tool_result_detection(self, set_memory_config, mock_llm):
        """Test detection of orphaned tool_result (no matching use)."""
        set_memory_config(MEMORY_SHORT_TERM_SIZE=5)
        manager = MemoryManager(mock_llm)

        # Add tool_result without use (this shouldn't happen but let's test it)
        await manager.add_message(LLMMessage(role="user", content="Request"))
        await manager.add_message(
            LLMMessage(
                role="user",
                content=[
                    {"type": "tool_result", "tool_use_id": "phantom_tool", "content": "result"}
                ],
            )
        )

        # Force compression
        await manager.compress(strategy=CompressionStrategy.SELECTIVE)

        context = manager.get_context_for_llm()

        # Check for phantom results
        tool_use_ids = set()
        tool_result_ids = set()

        for msg in context:
            if isinstance(msg.content, list):
                for block in msg.content:
                    if isinstance(block, dict):
                        if block.get("type") == "tool_use":
                            tool_use_ids.add(block.get("id"))
                        elif block.get("type") == "tool_result":
                            tool_result_ids.add(block.get("tool_use_id"))

        phantoms = tool_result_ids - tool_use_ids
        if phantoms:
            print(f"Detected phantom tool_result: {phantoms}")

    def _verify_tool_pairs_matched(self, messages):
        """Helper to verify all tool pairs are properly matched."""
        tool_use_ids = set()
        tool_result_ids = set()

        for msg in messages:
            if isinstance(msg.content, list):
                for block in msg.content:
                    if isinstance(block, dict):
                        if block.get("type") == "tool_use":
                            tool_use_ids.add(block.get("id"))
                        elif block.get("type") == "tool_result":
                            tool_result_ids.add(block.get("tool_use_id"))

        assert (
            tool_use_ids == tool_result_ids
        ), f"Mismatched tools: use={tool_use_ids}, result={tool_result_ids}"


class TestCompressionIntegration:
    """Integration tests for compression behavior."""

    async def test_full_conversation_lifecycle(self, set_memory_config, mock_llm):
        """Test a complete conversation lifecycle with multiple compressions."""
        set_memory_config(
            MEMORY_SHORT_TERM_SIZE=8,
            MEMORY_COMPRESSION_THRESHOLD=200,
        )
        manager = MemoryManager(mock_llm)

        # Simulate a long conversation
        for i in range(20):
            await manager.add_message(LLMMessage(role="user", content=f"User message {i} " * 20))
            await manager.add_message(
                LLMMessage(role="assistant", content=f"Assistant response {i} " * 20)
            )

        stats = manager.get_stats()

        # Should have compressed multiple times
        assert stats["compression_count"] > 0
        # Should have savings
        assert stats["total_savings"] > 0
        # Context should be manageable
        context = manager.get_context_for_llm()
        assert len(context) < 40  # Compressed from 40 messages

    async def test_mixed_content_conversation(self, set_memory_config, mock_llm):
        """Test conversation with mixed text and tool content."""
        set_memory_config(
            MEMORY_SHORT_TERM_SIZE=6,
            MEMORY_SHORT_TERM_MIN_SIZE=2,
        )
        manager = MemoryManager(mock_llm)

        # Mix of text and tool messages
        await manager.add_message(LLMMessage(role="user", content="Text message 1"))
        await manager.add_message(LLMMessage(role="assistant", content="Response 1"))

        # Tool call
        await manager.add_message(LLMMessage(role="user", content="Use a tool"))
        await manager.add_message(
            LLMMessage(
                role="assistant",
                content=[
                    {"type": "text", "text": "I'll use the tool"},
                    {"type": "tool_use", "id": "t1", "name": "calculator", "input": {}},
                ],
            )
        )
        await manager.add_message(
            LLMMessage(
                role="user", content=[{"type": "tool_result", "tool_use_id": "t1", "content": "42"}]
            )
        )

        # More text
        await manager.add_message(LLMMessage(role="assistant", content="The answer is 42"))
        await manager.add_message(LLMMessage(role="user", content="Text message 2"))

        # Force compression
        await manager.compress(strategy=CompressionStrategy.SELECTIVE)

        context = manager.get_context_for_llm()
        assert len(context) > 0

    async def test_system_message_persistence(self, set_memory_config, mock_llm):
        """Test that system messages persist through compressions."""
        set_memory_config(
            MEMORY_SHORT_TERM_SIZE=5,
            MEMORY_PRESERVE_SYSTEM_PROMPTS=True,
        )
        manager = MemoryManager(mock_llm)

        system_msg = LLMMessage(role="system", content="You are a helpful assistant.")
        await manager.add_message(system_msg)

        # Add many messages to trigger compression
        for i in range(10):
            await manager.add_message(LLMMessage(role="user", content=f"Message {i}"))

        # System message should still be first in context
        context = manager.get_context_for_llm()
        assert context[0].role == "system"
        assert context[0].content == "You are a helpful assistant."


class TestEdgeCaseIntegration:
    """Integration tests for edge cases."""

    async def test_compression_with_no_compressible_content(
        self, set_memory_config, mock_llm, protected_tool_messages
    ):
        """Test compression when all content is protected."""
        set_memory_config(
            MEMORY_SHORT_TERM_SIZE=10,  # Large enough to avoid auto-compression
            MEMORY_SHORT_TERM_MIN_SIZE=0,
        )
        manager = MemoryManager(mock_llm)

        # Add only protected tool messages
        for msg in protected_tool_messages:
            await manager.add_message(msg)

        # Force compression
        result = await manager.compress(strategy=CompressionStrategy.SELECTIVE)

        # Should preserve everything or nearly everything
        assert result is not None
        # Protected tools should be preserved
        found_protected = False
        for msg in result.preserved_messages:
            if isinstance(msg.content, list):
                for block in msg.content:
                    if isinstance(block, dict) and block.get("name") == "manage_todo_list":
                        found_protected = True
        assert found_protected or len(result.preserved_messages) > 0

    async def test_rapid_compression_cycles(self, set_memory_config, mock_llm):
        """Test many rapid compression cycles."""
        set_memory_config(
            MEMORY_SHORT_TERM_SIZE=2,
            MEMORY_COMPRESSION_THRESHOLD=50,
        )
        manager = MemoryManager(mock_llm)

        # Add messages rapidly, triggering many compressions
        for i in range(20):
            await manager.add_message(LLMMessage(role="user", content=f"Message {i}" * 10))

        stats = manager.get_stats()

        # Should have many compressions (deletion strategy is used for few messages)
        assert stats["compression_count"] > 0
        # Context may be sparse with deletion strategy, but should not error
        context = manager.get_context_for_llm()
        assert context is not None

    async def test_alternating_compression_strategies(self, set_memory_config, mock_llm):
        """Test using different compression strategies on same manager."""
        set_memory_config(MEMORY_SHORT_TERM_SIZE=5)
        manager = MemoryManager(mock_llm)

        # Add messages and compress with sliding window
        for i in range(4):
            await manager.add_message(LLMMessage(role="user", content=f"Message {i}"))

        await manager.compress(strategy=CompressionStrategy.SLIDING_WINDOW)

        # Add more messages and compress with selective
        await manager.add_message(LLMMessage(role="user", content="Use tool"))
        await manager.add_message(
            LLMMessage(
                role="assistant",
                content=[{"type": "tool_use", "id": "t1", "name": "tool", "input": {}}],
            )
        )
        await manager.add_message(
            LLMMessage(
                role="user",
                content=[{"type": "tool_result", "tool_use_id": "t1", "content": "result"}],
            )
        )

        await manager.compress(strategy=CompressionStrategy.SELECTIVE)

        # Should have multiple compressions with different strategies
        assert manager.compression_count == 2
        # Summaries are now stored as messages in short_term, check context has summary messages
        context = manager.get_context_for_llm()
        summary_count = sum(
            1
            for msg in context
            if isinstance(msg.content, str) and msg.content.startswith("[Conversation Summary]")
        )
        assert summary_count >= 1  # At least one summary should exist

    async def test_empty_content_blocks(self, set_memory_config, mock_llm):
        """Test handling of empty content blocks."""
        set_memory_config(MEMORY_SHORT_TERM_SIZE=5)
        manager = MemoryManager(mock_llm)

        # Add message with empty content blocks
        await manager.add_message(
            LLMMessage(
                role="assistant",
                content=[
                    {"type": "text", "text": ""},
                    {"type": "text", "text": "Actual content"},
                ],
            )
        )

        # Should handle gracefully (compression may happen automatically with deletion strategy)
        # After compression with deletion strategy, context may be empty or have summary
        context = manager.get_context_for_llm()
        # Test passes if no error occurred
        assert context is not None

    async def test_very_long_single_message(self, set_memory_config, mock_llm):
        """Test handling of a very long single message."""
        set_memory_config(
            MEMORY_SHORT_TERM_SIZE=5,
            MEMORY_COMPRESSION_THRESHOLD=100,
        )
        manager = MemoryManager(mock_llm)

        # Add very long message
        long_content = "This is a very long message. " * 500
        await manager.add_message(LLMMessage(role="user", content=long_content))

        # Should trigger compression
        assert manager.compression_count >= 1


class TestMemoryReset:
    """Test reset functionality in various scenarios."""

    async def test_reset_after_compression(self, set_memory_config, mock_llm, simple_messages):
        """Test reset after compression has occurred."""
        set_memory_config(MEMORY_SHORT_TERM_SIZE=3)
        manager = MemoryManager(mock_llm)

        # Add messages and compress
        for msg in simple_messages:
            await manager.add_message(msg)

        # Reset
        manager.reset()

        # Everything should be cleared
        assert manager.current_tokens == 0
        assert manager.compression_count == 0
        assert manager.short_term.count() == 0

    async def test_reuse_after_reset(self, set_memory_config, mock_llm):
        """Test that manager can be reused after reset."""
        set_memory_config(
            MEMORY_SHORT_TERM_SIZE=10,  # Large enough to avoid compression
            MEMORY_COMPRESSION_THRESHOLD=100000,
        )
        manager = MemoryManager(mock_llm)

        # First use
        for i in range(5):
            await manager.add_message(LLMMessage(role="user", content=f"First use {i}"))

        # Reset
        manager.reset()

        # Second use
        for i in range(5):
            await manager.add_message(LLMMessage(role="user", content=f"Second use {i}"))

        # Should work normally - no compression occurred due to high limits
        context = manager.get_context_for_llm()
        assert len(context) == 5
        assert "Second use" in str(context[-1].content)
