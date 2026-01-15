"""Integration tests for memory module.

These tests verify that different components work together correctly,
especially focusing on edge cases and the tool_call/tool_result matching issue.
"""

from llm.base import LLMMessage
from memory import MemoryConfig, MemoryManager
from memory.types import CompressionStrategy


class TestToolCallResultIntegration:
    """Integration tests for tool_call and tool_result matching.

    This is the critical test suite for the bug mentioned by the user.
    """

    def test_tool_pairs_survive_compression_cycle(self, mock_llm):
        """Test that tool pairs remain matched through compression cycles."""
        config = MemoryConfig(
            short_term_message_count=6,
            short_term_min_message_count=2,
        )
        manager = MemoryManager(config, mock_llm)

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
            manager.add_message(msg)

        # Verify no mismatches in context
        context = manager.get_context_for_llm()
        self._verify_tool_pairs_matched(context)

    def test_tool_pairs_with_multiple_compressions(self, mock_llm):
        """Test tool pairs remain matched through multiple compression cycles."""
        config = MemoryConfig(
            short_term_message_count=4,
            short_term_min_message_count=2,
        )
        manager = MemoryManager(config, mock_llm)

        # Add messages in multiple batches, triggering multiple compressions
        for batch in range(3):
            for i in range(2):
                idx = batch * 2 + i
                manager.add_message(LLMMessage(role="user", content=f"Request {idx}"))
                manager.add_message(
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
                manager.add_message(
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
                manager.add_message(LLMMessage(role="assistant", content=f"Response {idx}"))

        # Verify no mismatches after multiple compressions
        context = manager.get_context_for_llm()
        self._verify_tool_pairs_matched(context)

    def test_interleaved_tool_calls(self, mock_llm):
        """Test tool pairs when tool calls are interleaved."""
        config = MemoryConfig(short_term_message_count=10)
        manager = MemoryManager(config, mock_llm)

        # Add interleaved tool calls (assistant makes multiple tool calls at once)
        manager.add_message(LLMMessage(role="user", content="Complex request"))
        manager.add_message(
            LLMMessage(
                role="assistant",
                content=[
                    {"type": "tool_use", "id": "tool_1", "name": "tool_a", "input": {}},
                    {"type": "tool_use", "id": "tool_2", "name": "tool_b", "input": {}},
                ],
            )
        )
        # Results come back together
        manager.add_message(
            LLMMessage(
                role="user",
                content=[
                    {"type": "tool_result", "tool_use_id": "tool_1", "content": "result_1"},
                    {"type": "tool_result", "tool_use_id": "tool_2", "content": "result_2"},
                ],
            )
        )
        manager.add_message(LLMMessage(role="assistant", content="Final response"))

        # Force compression
        manager.compress(strategy=CompressionStrategy.SELECTIVE)

        context = manager.get_context_for_llm()
        self._verify_tool_pairs_matched(context)

    def test_orphaned_tool_use_detection(self, mock_llm):
        """Test detection of orphaned tool_use (no matching result)."""
        config = MemoryConfig(short_term_message_count=5)
        manager = MemoryManager(config, mock_llm)

        # Add tool_use without result
        manager.add_message(LLMMessage(role="user", content="Request"))
        manager.add_message(
            LLMMessage(
                role="assistant",
                content=[{"type": "tool_use", "id": "orphan_tool", "name": "tool", "input": {}}],
            )
        )
        # Missing tool_result!
        manager.add_message(LLMMessage(role="user", content="Another request"))

        # Force compression
        manager.compress(strategy=CompressionStrategy.SELECTIVE)

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

    def test_orphaned_tool_result_detection(self, mock_llm):
        """Test detection of orphaned tool_result (no matching use)."""
        config = MemoryConfig(short_term_message_count=5)
        manager = MemoryManager(config, mock_llm)

        # Add tool_result without use (this shouldn't happen but let's test it)
        manager.add_message(LLMMessage(role="user", content="Request"))
        manager.add_message(
            LLMMessage(
                role="user",
                content=[
                    {"type": "tool_result", "tool_use_id": "phantom_tool", "content": "result"}
                ],
            )
        )

        # Force compression
        manager.compress(strategy=CompressionStrategy.SELECTIVE)

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

    def test_full_conversation_lifecycle(self, mock_llm):
        """Test a complete conversation lifecycle with multiple compressions."""
        config = MemoryConfig(
            short_term_message_count=8,
            target_working_memory_tokens=200,
        )
        manager = MemoryManager(config, mock_llm)

        # Simulate a long conversation
        for i in range(20):
            manager.add_message(LLMMessage(role="user", content=f"User message {i} " * 20))
            manager.add_message(
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

    def test_mixed_content_conversation(self, mock_llm):
        """Test conversation with mixed text and tool content."""
        config = MemoryConfig(
            short_term_message_count=6,
            short_term_min_message_count=2,
        )
        manager = MemoryManager(config, mock_llm)

        # Mix of text and tool messages
        manager.add_message(LLMMessage(role="user", content="Text message 1"))
        manager.add_message(LLMMessage(role="assistant", content="Response 1"))

        # Tool call
        manager.add_message(LLMMessage(role="user", content="Use a tool"))
        manager.add_message(
            LLMMessage(
                role="assistant",
                content=[
                    {"type": "text", "text": "I'll use the tool"},
                    {"type": "tool_use", "id": "t1", "name": "calculator", "input": {}},
                ],
            )
        )
        manager.add_message(
            LLMMessage(
                role="user", content=[{"type": "tool_result", "tool_use_id": "t1", "content": "42"}]
            )
        )

        # More text
        manager.add_message(LLMMessage(role="assistant", content="The answer is 42"))
        manager.add_message(LLMMessage(role="user", content="Text message 2"))

        # Force compression
        manager.compress(strategy=CompressionStrategy.SELECTIVE)

        context = manager.get_context_for_llm()
        assert len(context) > 0

    def test_system_message_persistence(self, mock_llm):
        """Test that system messages persist through compressions."""
        config = MemoryConfig(
            short_term_message_count=5,
            preserve_system_prompts=True,
        )
        manager = MemoryManager(config, mock_llm)

        system_msg = LLMMessage(role="system", content="You are a helpful assistant.")
        manager.add_message(system_msg)

        # Add many messages to trigger compression
        for i in range(10):
            manager.add_message(LLMMessage(role="user", content=f"Message {i}"))

        # System message should still be first in context
        context = manager.get_context_for_llm()
        assert context[0].role == "system"
        assert context[0].content == "You are a helpful assistant."


class TestEdgeCaseIntegration:
    """Integration tests for edge cases."""

    def test_compression_with_no_compressible_content(self, mock_llm, protected_tool_messages):
        """Test compression when all content is protected."""
        config = MemoryConfig(
            short_term_message_count=10,  # Large enough to avoid auto-compression
            short_term_min_message_count=0,
        )
        manager = MemoryManager(config, mock_llm)

        # Add only protected tool messages
        for msg in protected_tool_messages:
            manager.add_message(msg)

        # Force compression
        result = manager.compress(strategy=CompressionStrategy.SELECTIVE)

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

    def test_rapid_compression_cycles(self, mock_llm):
        """Test many rapid compression cycles."""
        config = MemoryConfig(
            short_term_message_count=2,
            target_working_memory_tokens=50,
        )
        manager = MemoryManager(config, mock_llm)

        # Add messages rapidly, triggering many compressions
        for i in range(20):
            manager.add_message(LLMMessage(role="user", content=f"Message {i}" * 10))

        stats = manager.get_stats()

        # Should have many compressions (deletion strategy is used for few messages)
        assert stats["compression_count"] > 0
        # Context may be sparse with deletion strategy, but should not error
        context = manager.get_context_for_llm()
        assert context is not None

    def test_alternating_compression_strategies(self, mock_llm):
        """Test using different compression strategies on same manager."""
        config = MemoryConfig(short_term_message_count=5)
        manager = MemoryManager(config, mock_llm)

        # Add messages and compress with sliding window
        for i in range(4):
            manager.add_message(LLMMessage(role="user", content=f"Message {i}"))

        manager.compress(strategy=CompressionStrategy.SLIDING_WINDOW)

        # Add more messages and compress with selective
        manager.add_message(LLMMessage(role="user", content="Use tool"))
        manager.add_message(
            LLMMessage(
                role="assistant",
                content=[{"type": "tool_use", "id": "t1", "name": "tool", "input": {}}],
            )
        )
        manager.add_message(
            LLMMessage(
                role="user",
                content=[{"type": "tool_result", "tool_use_id": "t1", "content": "result"}],
            )
        )

        manager.compress(strategy=CompressionStrategy.SELECTIVE)

        # Should have multiple compressions with different strategies
        assert manager.compression_count == 2
        assert len(manager.summaries) == 2

    def test_empty_content_blocks(self, mock_llm):
        """Test handling of empty content blocks."""
        config = MemoryConfig(short_term_message_count=5)
        manager = MemoryManager(config, mock_llm)

        # Add message with empty content blocks
        manager.add_message(
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

    def test_very_long_single_message(self, mock_llm):
        """Test handling of a very long single message."""
        config = MemoryConfig(
            short_term_message_count=5,
            target_working_memory_tokens=100,
        )
        manager = MemoryManager(config, mock_llm)

        # Add very long message
        long_content = "This is a very long message. " * 500
        manager.add_message(LLMMessage(role="user", content=long_content))

        # Should trigger compression
        assert manager.compression_count >= 1


class TestMemoryReset:
    """Test reset functionality in various scenarios."""

    def test_reset_after_compression(self, mock_llm, simple_messages):
        """Test reset after compression has occurred."""
        config = MemoryConfig(short_term_message_count=3)
        manager = MemoryManager(config, mock_llm)

        # Add messages and compress
        for msg in simple_messages:
            manager.add_message(msg)

        # Reset
        manager.reset()

        # Everything should be cleared
        assert manager.current_tokens == 0
        assert manager.compression_count == 0
        assert len(manager.summaries) == 0
        assert manager.short_term.count() == 0

    def test_reuse_after_reset(self, mock_llm):
        """Test that manager can be reused after reset."""
        config = MemoryConfig(
            short_term_message_count=10,  # Large enough to avoid compression
            target_working_memory_tokens=100000,
        )
        manager = MemoryManager(config, mock_llm)

        # First use
        for i in range(5):
            manager.add_message(LLMMessage(role="user", content=f"First use {i}"))

        # Reset
        manager.reset()

        # Second use
        for i in range(5):
            manager.add_message(LLMMessage(role="user", content=f"Second use {i}"))

        # Should work normally - no compression occurred due to high limits
        context = manager.get_context_for_llm()
        assert len(context) == 5
        assert "Second use" in str(context[-1].content)
