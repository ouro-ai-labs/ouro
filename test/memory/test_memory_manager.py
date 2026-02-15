"""Unit tests for MemoryManager."""

from llm.base import LLMMessage
from memory import MemoryManager
from memory.types import CompressionStrategy


class TestMemoryManagerBasics:
    """Test basic MemoryManager functionality."""

    async def test_initialization(self, mock_llm):
        """Test MemoryManager initialization."""
        manager = MemoryManager(mock_llm)

        assert manager.llm == mock_llm
        assert manager.current_tokens == 0
        assert manager.compression_count == 0
        assert len(manager.system_messages) == 0
        assert manager.short_term.count() == 0

    async def test_add_system_message(self, mock_llm):
        """Test that system messages are stored separately."""
        manager = MemoryManager(mock_llm)

        system_msg = LLMMessage(role="system", content="You are a helpful assistant.")
        await manager.add_message(system_msg)

        assert len(manager.system_messages) == 1
        assert manager.system_messages[0] == system_msg
        # System messages don't go to short-term memory
        assert manager.short_term.count() == 0

    async def test_add_user_message(self, mock_llm):
        """Test adding user messages."""
        manager = MemoryManager(mock_llm)

        user_msg = LLMMessage(role="user", content="Hello")
        await manager.add_message(user_msg)

        assert manager.short_term.count() == 1
        assert manager.current_tokens > 0

    async def test_add_assistant_message(self, mock_llm):
        """Test adding assistant messages."""
        manager = MemoryManager(mock_llm)

        assistant_msg = LLMMessage(role="assistant", content="Hi there!")
        await manager.add_message(assistant_msg)

        assert manager.short_term.count() == 1
        assert manager.current_tokens > 0

    async def test_get_context_structure(self, mock_llm, simple_messages):
        """Test context structure with system and recent messages."""
        manager = MemoryManager(mock_llm)

        # Add system message
        system_msg = LLMMessage(role="system", content="You are helpful.")
        await manager.add_message(system_msg)

        # Add regular messages
        for msg in simple_messages:
            await manager.add_message(msg)

        context = manager.get_context_for_llm()

        # Context should have: system message + recent messages
        assert len(context) >= len(simple_messages)
        assert context[0] == system_msg  # System message first

    async def test_reset(self, mock_llm, simple_messages):
        """Test resetting memory manager."""
        manager = MemoryManager(mock_llm)

        # Add some messages
        for msg in simple_messages:
            await manager.add_message(msg)

        # Reset
        manager.reset()

        assert manager.current_tokens == 0
        assert manager.compression_count == 0
        assert len(manager.system_messages) == 0
        assert manager.short_term.count() == 0


class TestMemoryCompression:
    """Test compression triggering and behavior."""

    async def test_compression_on_short_term_full(self, set_memory_config, mock_llm):
        """Test compression triggers when short-term memory is full."""
        set_memory_config(
            MEMORY_SHORT_TERM_SIZE=5,
            MEMORY_COMPRESSION_THRESHOLD=200000,  # Very high to avoid hard limit
        )
        manager = MemoryManager(mock_llm)

        # Add messages until short-term is full
        for i in range(5):
            await manager.add_message(LLMMessage(role="user", content=f"Message {i}"))

        # After 5 messages, compression should have been triggered and short-term cleared
        assert manager.compression_count == 1
        assert manager.was_compressed_last_iteration
        # After compression, short-term is cleared so it's not full
        assert not manager.short_term.is_full()

    async def test_compression_on_hard_limit(self, set_memory_config, mock_llm):
        """Test compression triggers on hard limit (compression threshold)."""
        set_memory_config(
            MEMORY_COMPRESSION_THRESHOLD=100,  # Very low to trigger easily
            MEMORY_SHORT_TERM_SIZE=100,
        )
        manager = MemoryManager(mock_llm)

        # Add long message to exceed hard limit
        long_message = "This is a very long message. " * 100
        await manager.add_message(LLMMessage(role="user", content=long_message))

        assert manager.compression_count >= 1

    async def test_compression_creates_summary(self, set_memory_config, mock_llm, simple_messages):
        """Test that compression creates a summary message in short_term."""
        set_memory_config(
            MEMORY_SHORT_TERM_SIZE=10,  # Large enough to not auto-trigger
            MEMORY_COMPRESSION_THRESHOLD=200000,
        )
        manager = MemoryManager(mock_llm)

        # Add messages
        for msg in simple_messages:
            await manager.add_message(msg)

        # Manually trigger compression with sliding_window strategy (which creates summary)
        result = await manager.compress(strategy=CompressionStrategy.SLIDING_WINDOW)
        assert result is not None
        assert manager.compression_count == 1

        # Check that summary message exists in short_term (at the front)
        context = manager.get_context_for_llm()
        has_summary = any(
            isinstance(msg.content, str)
            and msg.content.startswith("[Previous conversation summary]")
            for msg in context
        )
        assert has_summary, "Summary message should be present after compression"

    async def test_get_stats(self, mock_llm, simple_messages):
        """Test getting memory statistics."""
        manager = MemoryManager(mock_llm)

        for msg in simple_messages:
            await manager.add_message(msg)

        stats = manager.get_stats()

        assert "current_tokens" in stats
        assert "total_input_tokens" in stats
        assert "total_output_tokens" in stats
        assert "compression_count" in stats
        assert "total_savings" in stats
        assert "compression_cost" in stats
        assert "net_savings" in stats
        assert "short_term_count" in stats


class TestToolCallMatching:
    """Test tool_use and tool_result matching scenarios."""

    async def test_tool_pairs_preserved_together(
        self, set_memory_config, mock_llm, tool_use_messages
    ):
        """Test that tool_use and tool_result pairs are preserved together."""
        set_memory_config(
            MEMORY_SHORT_TERM_SIZE=3,
            MEMORY_SHORT_TERM_MIN_SIZE=2,
            MEMORY_COMPRESSION_THRESHOLD=200000,
        )
        manager = MemoryManager(mock_llm)

        # Add tool messages
        for msg in tool_use_messages:
            await manager.add_message(msg)

        # Force compression
        await manager.compress(strategy=CompressionStrategy.SELECTIVE)

        # Get context
        context = manager.get_context_for_llm()

        # Check that tool_use and tool_result are both present
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

        # Every tool_use should have a matching tool_result
        assert (
            tool_use_ids == tool_result_ids
        ), f"Mismatched tool calls: tool_use_ids={tool_use_ids}, tool_result_ids={tool_result_ids}"

    async def test_mismatched_tool_calls_detected(
        self, set_memory_config, mock_llm, mismatched_tool_messages
    ):
        """Test behavior with mismatched tool_use/tool_result pairs."""
        set_memory_config(
            MEMORY_SHORT_TERM_SIZE=4,
            MEMORY_SHORT_TERM_MIN_SIZE=2,
        )
        manager = MemoryManager(mock_llm)

        # Add mismatched tool messages
        for msg in mismatched_tool_messages:
            await manager.add_message(msg)

        # Force compression
        await manager.compress(strategy=CompressionStrategy.SELECTIVE)

        # Get context and check for mismatches
        context = manager.get_context_for_llm()

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

        # This test documents the current behavior with mismatched pairs
        # In the mismatched scenario, we expect tool_1 to be missing its result
        # This is the bug we're trying to catch
        if tool_use_ids != tool_result_ids:
            missing_results = tool_use_ids - tool_result_ids
            missing_uses = tool_result_ids - tool_use_ids
            print(
                f"Detected mismatch - missing results: {missing_results}, missing uses: {missing_uses}"
            )

    async def test_todo_context_provider_integration(
        self, set_memory_config, mock_llm, protected_tool_messages
    ):
        """Test that todo context provider is called during compression.

        Note: manage_todo_list is no longer in PROTECTED_TOOLS. Instead, todo state
        is preserved via todo_context injection from MemoryManager's provider callback.
        """
        set_memory_config(
            MEMORY_SHORT_TERM_SIZE=10,  # Large enough to avoid auto-compression
            MEMORY_SHORT_TERM_MIN_SIZE=1,
        )
        manager = MemoryManager(mock_llm)

        # Set up todo context provider
        todo_context_called = False

        def mock_todo_provider():
            nonlocal todo_context_called
            todo_context_called = True
            return "1. [pending] Test task"

        manager.set_todo_context_provider(mock_todo_provider)

        # Add messages
        for msg in protected_tool_messages:
            await manager.add_message(msg)

        # Manually trigger compression
        compressed = await manager.compress(strategy=CompressionStrategy.SELECTIVE)

        # Verify compression happened and provider was called
        assert compressed is not None
        assert todo_context_called, "Todo context provider should be called during compression"

        # Verify todo context is in the summary
        context = manager.get_context_for_llm()
        summary_has_todo = False
        for msg in context:
            if isinstance(msg.content, str) and "[Current Tasks]" in msg.content:
                summary_has_todo = True
                break

        assert summary_has_todo, "Todo context should be injected into compression summary"

    async def test_multiple_tool_pairs_in_sequence(self, set_memory_config, mock_llm):
        """Test multiple consecutive tool_use/tool_result pairs."""
        set_memory_config(
            MEMORY_SHORT_TERM_SIZE=10,
            MEMORY_SHORT_TERM_MIN_SIZE=2,
        )
        manager = MemoryManager(mock_llm)

        # Create multiple tool pairs
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

        for msg in messages:
            await manager.add_message(msg)

        # Force compression
        await manager.compress(strategy=CompressionStrategy.SELECTIVE)

        # Verify all pairs are matched
        context = manager.get_context_for_llm()
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

        assert tool_use_ids == tool_result_ids


class TestEdgeCases:
    """Test edge cases and error scenarios."""

    async def test_empty_memory_compression(self, mock_llm):
        """Test compressing empty memory."""
        manager = MemoryManager(mock_llm)

        result = await manager.compress()
        assert result is None

    async def test_single_message_compression(self, mock_llm):
        """Test compressing with only one message."""
        manager = MemoryManager(mock_llm)

        await manager.add_message(LLMMessage(role="user", content="Hello"))
        result = await manager.compress()

        assert result is not None

    async def test_actual_token_counts(self, mock_llm):
        """Test using actual token counts from LLM response."""
        manager = MemoryManager(mock_llm)

        # Add message with actual token counts
        msg = LLMMessage(role="assistant", content="Response")
        actual_tokens = {"input": 100, "output": 50}

        await manager.add_message(msg, actual_tokens=actual_tokens)

        stats = manager.get_stats()
        assert stats["total_input_tokens"] >= 100
        assert stats["total_output_tokens"] >= 50

    async def test_non_api_messages_do_not_accumulate_tokens(self, mock_llm):
        """Non-API messages should not increase total_input/output_tokens.

        Their tokens are already included in the next API call's
        response.usage.input_tokens, so counting them separately would
        double-count.
        """
        manager = MemoryManager(mock_llm)

        # Add user and tool-result messages (no actual_tokens)
        await manager.add_message(LLMMessage(role="user", content="Hello"))
        await manager.add_message(
            LLMMessage(
                role="user",
                content=[
                    {"type": "tool_result", "tool_use_id": "t1", "content": "result"},
                ],
            )
        )

        stats = manager.get_stats()
        assert stats["total_input_tokens"] == 0
        assert stats["total_output_tokens"] == 0

        # Now add an API message — only its reported tokens should count
        await manager.add_message(
            LLMMessage(role="assistant", content="Response"),
            actual_tokens={"input": 500, "output": 80},
        )

        stats = manager.get_stats()
        assert stats["total_input_tokens"] == 500
        assert stats["total_output_tokens"] == 80

    async def test_compression_with_mixed_content(self, set_memory_config, mock_llm):
        """Test compression with mixed text and tool content."""
        set_memory_config(MEMORY_SHORT_TERM_SIZE=5)
        manager = MemoryManager(mock_llm)

        messages = [
            LLMMessage(role="user", content="Text only"),
            LLMMessage(
                role="assistant",
                content=[
                    {"type": "text", "text": "Response with tool"},
                    {"type": "tool_use", "id": "t1", "name": "tool", "input": {}},
                ],
            ),
            LLMMessage(
                role="user",
                content=[{"type": "tool_result", "tool_use_id": "t1", "content": "result"}],
            ),
            LLMMessage(role="assistant", content="Final response"),
        ]

        for msg in messages:
            await manager.add_message(msg)

        # Should handle mixed content without errors
        result = await manager.compress(strategy=CompressionStrategy.SELECTIVE)
        assert result is not None

    async def test_strategy_auto_selection(self, mock_llm, tool_use_messages, simple_messages):
        """Test automatic strategy selection based on message content."""
        manager = MemoryManager(mock_llm)

        # Add tool messages - should select SELECTIVE strategy
        for msg in tool_use_messages:
            await manager.add_message(msg)

        # Force compression without specifying strategy
        await manager.compress()

        # Verify compression happened
        assert manager.compression_count == 1

        # Test with simple messages - should select different strategy
        manager.reset()
        for msg in simple_messages[:2]:  # Few messages
            await manager.add_message(msg)

        await manager.compress()
        assert manager.compression_count == 1


class TestMemoryManagerRollback:
    """Test rollback functionality for interrupted exchanges."""

    async def test_rollback_incomplete_exchange_with_tool_calls(self, mock_llm):
        """Test rollback when last message is assistant with tool_calls."""
        manager = MemoryManager(mock_llm)

        # Add user message
        user_msg = LLMMessage(role="user", content="Search for files")
        await manager.add_message(user_msg)

        # Add assistant message with tool_calls (simulating interrupted execution)
        assistant_msg = LLMMessage(
            role="assistant",
            content=[
                {"type": "text", "text": "I'll search for files"},
                {"type": "tool_use", "id": "t1", "name": "search", "input": {"query": "*.py"}},
            ],
        )
        await manager.add_message(assistant_msg)

        # Should have 2 messages
        assert manager.short_term.count() == 2

        # Rollback incomplete exchange
        manager.rollback_incomplete_exchange()

        # Should only remove the assistant message, keep the user message
        assert manager.short_term.count() == 1
        assert manager.short_term.get_messages()[0].role == "user"

    async def test_rollback_incomplete_exchange_no_rollback_needed(self, mock_llm):
        """Test rollback when last message is complete (no tool_calls)."""
        manager = MemoryManager(mock_llm)

        # Add complete exchange
        user_msg = LLMMessage(role="user", content="Hello")
        assistant_msg = LLMMessage(role="assistant", content="Hi there!")

        await manager.add_message(user_msg)
        await manager.add_message(assistant_msg)

        # Should have 2 messages
        assert manager.short_term.count() == 2

        # Rollback should not remove anything (no tool_calls)
        manager.rollback_incomplete_exchange()

        # Should still have 2 messages
        assert manager.short_term.count() == 2

    async def test_rollback_incomplete_exchange_with_tool_results(self, mock_llm):
        """Test rollback when exchange is complete (has tool results)."""
        manager = MemoryManager(mock_llm)

        # Add complete exchange with tool use and results
        messages = [
            LLMMessage(role="user", content="Search for files"),
            LLMMessage(
                role="assistant",
                content=[
                    {"type": "text", "text": "I'll search"},
                    {"type": "tool_use", "id": "t1", "name": "search", "input": {}},
                ],
            ),
            LLMMessage(
                role="user",
                content=[{"type": "tool_result", "tool_use_id": "t1", "content": "results"}],
            ),
            LLMMessage(role="assistant", content="Here are the results"),
        ]

        for msg in messages:
            await manager.add_message(msg)

        # Should have 4 messages
        assert manager.short_term.count() == 4

        # Rollback should not remove anything (exchange is complete)
        manager.rollback_incomplete_exchange()

        # Should still have 4 messages
        assert manager.short_term.count() == 4

    async def test_rollback_incomplete_exchange_empty_memory(self, mock_llm):
        """Test rollback on empty memory."""
        manager = MemoryManager(mock_llm)

        # Should not crash
        manager.rollback_incomplete_exchange()

        assert manager.short_term.count() == 0

    async def test_rollback_incomplete_exchange_only_user_message(self, mock_llm):
        """Test rollback when only user message exists."""
        manager = MemoryManager(mock_llm)

        user_msg = LLMMessage(role="user", content="Hello")
        await manager.add_message(user_msg)

        # Rollback should not remove user message alone
        manager.rollback_incomplete_exchange()

        # Should still have 1 message
        assert manager.short_term.count() == 1

    async def test_rollback_recalculates_tokens(self, mock_llm):
        """Test that rollback recalculates token count."""
        manager = MemoryManager(mock_llm)

        # Add messages
        user_msg = LLMMessage(role="user", content="Search for files")
        assistant_msg = LLMMessage(
            role="assistant",
            content=[
                {"type": "text", "text": "I'll search"},
                {"type": "tool_use", "id": "t1", "name": "search", "input": {}},
            ],
        )

        await manager.add_message(user_msg)
        initial_tokens = manager.current_tokens

        await manager.add_message(assistant_msg)
        tokens_after_assistant = manager.current_tokens

        assert tokens_after_assistant > initial_tokens

        # Rollback
        manager.rollback_incomplete_exchange()

        # Tokens should be recalculated (should be same as initial since only assistant removed)
        assert manager.current_tokens == initial_tokens
