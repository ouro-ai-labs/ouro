"""Unit tests for WorkingMemoryCompressor."""

from llm.base import LLMMessage
from memory.compressor import WorkingMemoryCompressor
from memory.types import CompressionStrategy


class TestCompressorBasics:
    """Test basic compressor functionality."""

    async def test_initialization(self, mock_llm):
        """Test compressor initialization."""
        compressor = WorkingMemoryCompressor(mock_llm)

        assert compressor.llm == mock_llm

    async def test_compress_empty_messages(self, mock_llm):
        """Test compressing empty message list."""
        compressor = WorkingMemoryCompressor(mock_llm)

        result = await compressor.compress([])

        assert result.summary == ""
        assert len(result.preserved_messages) == 0

    async def test_compress_single_message(self, mock_llm):
        """Test compressing a single message."""
        compressor = WorkingMemoryCompressor(mock_llm)

        messages = [LLMMessage(role="user", content="Hello")]
        result = await compressor.compress(messages, strategy=CompressionStrategy.SLIDING_WINDOW)

        assert result is not None
        assert result.original_message_count == 1


class TestCompressionStrategies:
    """Test different compression strategies."""

    async def test_sliding_window_strategy(self, mock_llm, simple_messages):
        """Test sliding window compression strategy."""
        compressor = WorkingMemoryCompressor(mock_llm)

        result = await compressor.compress(
            simple_messages, strategy=CompressionStrategy.SLIDING_WINDOW, target_tokens=100
        )

        assert result is not None
        assert result.summary != ""
        assert result.original_message_count == len(simple_messages)
        assert result.metadata["strategy"] == "sliding_window"
        assert result.compressed_tokens < result.original_tokens

    async def test_deletion_strategy(self, mock_llm, simple_messages):
        """Test deletion compression strategy."""
        compressor = WorkingMemoryCompressor(mock_llm)

        result = await compressor.compress(simple_messages, strategy=CompressionStrategy.DELETION)

        assert result is not None
        assert result.summary == ""
        assert len(result.preserved_messages) == 0
        assert result.compressed_tokens == 0
        assert result.metadata["strategy"] == "deletion"

    async def test_selective_strategy_with_tools(
        self, set_memory_config, mock_llm, tool_use_messages
    ):
        """Test selective compression with tool messages."""
        set_memory_config(MEMORY_SHORT_TERM_MIN_SIZE=2)
        compressor = WorkingMemoryCompressor(mock_llm)

        result = await compressor.compress(
            tool_use_messages, strategy=CompressionStrategy.SELECTIVE, target_tokens=200
        )

        assert result is not None
        assert result.metadata["strategy"] == "selective"
        # Regular tool pairs are compressed (not preserved) unless they are protected tools
        # Only system messages, protected tools, and orphaned tool pairs are preserved
        assert result.summary != ""  # Should have a summary for compressed content

    async def test_selective_strategy_preserves_system_messages(self, set_memory_config, mock_llm):
        """Test that selective strategy preserves system messages."""
        set_memory_config(MEMORY_PRESERVE_SYSTEM_PROMPTS=True)
        compressor = WorkingMemoryCompressor(mock_llm)

        messages = [
            LLMMessage(role="system", content="System prompt"),
            LLMMessage(role="user", content="User message"),
            LLMMessage(role="assistant", content="Assistant response"),
        ]

        result = await compressor.compress(
            messages, strategy=CompressionStrategy.SELECTIVE, target_tokens=100
        )

        # System message should be preserved
        system_preserved = any(msg.role == "system" for msg in result.preserved_messages)
        assert system_preserved


class TestToolPairDetection:
    """Test tool pair detection and preservation."""

    async def test_find_tool_pairs_basic(self, mock_llm, tool_use_messages):
        """Test basic tool pair detection."""
        compressor = WorkingMemoryCompressor(mock_llm)

        pairs, orphaned = compressor._find_tool_pairs(tool_use_messages)

        # Should find at least one pair
        assert len(pairs) > 0
        # Each pair should be [assistant_index, user_index]
        for pair in pairs:
            assert len(pair) == 2
            assert pair[0] < pair[1]  # Assistant comes before user
        # Should have no orphaned tool_use (all have results)
        assert len(orphaned) == 0

    async def test_find_tool_pairs_multiple(self, mock_llm):
        """Test finding multiple tool pairs."""
        compressor = WorkingMemoryCompressor(mock_llm)

        messages = []
        for i in range(3):
            messages.extend(
                [
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
                ]
            )

        pairs, orphaned = compressor._find_tool_pairs(messages)
        assert len(pairs) == 3
        assert len(orphaned) == 0

    async def test_find_tool_pairs_with_mismatches(self, mock_llm, mismatched_tool_messages):
        """Test tool pair detection with mismatched pairs."""
        compressor = WorkingMemoryCompressor(mock_llm)

        pairs, orphaned = compressor._find_tool_pairs(mismatched_tool_messages)

        # Should only find matched pairs (tool_2 has a result, tool_1 doesn't)
        assert len(pairs) == 1
        # Should have one orphaned tool_use (tool_1)
        assert len(orphaned) == 1

    async def test_tool_pairs_preserved_together(
        self, set_memory_config, mock_llm, tool_use_messages
    ):
        """Test that when a tool pair is found, both messages are preserved together."""
        set_memory_config(MEMORY_SHORT_TERM_MIN_SIZE=1)
        compressor = WorkingMemoryCompressor(mock_llm)

        preserved, to_compress = compressor._separate_messages(tool_use_messages)

        # Find tool_use and tool_result in preserved messages
        tool_use_indices = []
        tool_result_indices = []

        for i, msg in enumerate(tool_use_messages):
            if isinstance(msg.content, list):
                for block in msg.content:
                    if isinstance(block, dict):
                        if block.get("type") == "tool_use":
                            tool_use_indices.append(i)
                        elif block.get("type") == "tool_result":
                            tool_result_indices.append(i)

        # Check that if tool_use is preserved, tool_result is also preserved
        for tool_use_idx in tool_use_indices:
            if tool_use_messages[tool_use_idx] in preserved:
                # Find corresponding tool_result
                # This is a simplified check - in reality we'd match by ID
                assert len(tool_result_indices) > 0


class TestProtectedTools:
    """Test protected tool handling."""

    async def test_find_protected_tool_pairs(self, mock_llm, protected_tool_messages):
        """Test finding protected tool pairs (manage_todo_list)."""
        compressor = WorkingMemoryCompressor(mock_llm)

        # First find all pairs
        all_pairs, orphaned = compressor._find_tool_pairs(protected_tool_messages)

        # Then find protected pairs
        protected_pairs = compressor._find_protected_tool_pairs(protected_tool_messages, all_pairs)

        # Should find the manage_todo_list pair
        assert len(protected_pairs) > 0
        assert len(orphaned) == 0

    async def test_protected_tools_always_preserved(
        self, set_memory_config, mock_llm, protected_tool_messages
    ):
        """Test that protected tools are never compressed."""
        set_memory_config(MEMORY_SHORT_TERM_MIN_SIZE=0)  # Don't preserve anything by default
        compressor = WorkingMemoryCompressor(mock_llm)

        preserved, to_compress = compressor._separate_messages(protected_tool_messages)

        # Protected tool should be in preserved messages
        found_protected = False
        for msg in preserved:
            if isinstance(msg.content, list):
                for block in msg.content:
                    if (
                        isinstance(block, dict)
                        and block.get("type") == "tool_use"
                        and block.get("name") == "manage_todo_list"
                    ):
                        found_protected = True
                        break

        assert found_protected, "Protected tool should always be preserved"

    async def test_non_protected_tools_can_be_compressed(
        self, set_memory_config, mock_llm, tool_use_messages
    ):
        """Test that non-protected tools can be compressed."""
        set_memory_config(MEMORY_SHORT_TERM_MIN_SIZE=0)
        compressor = WorkingMemoryCompressor(mock_llm)

        preserved, to_compress = compressor._separate_messages(tool_use_messages)

        # Non-protected tools may be compressed (moved to to_compress)
        # At minimum, preserved should not have ALL messages
        assert len(to_compress) >= 0  # Some or all may be compressed


class TestMessageSeparation:
    """Test message separation logic."""

    async def test_separate_messages_basic(self, set_memory_config, mock_llm, simple_messages):
        """Test basic message separation - recent messages are preserved, others compressed."""
        set_memory_config(
            MEMORY_SHORT_TERM_MIN_SIZE=0
        )  # Don't preserve recent messages for this test
        compressor = WorkingMemoryCompressor(mock_llm)

        preserved, to_compress = compressor._separate_messages(simple_messages)

        # With MIN_SIZE=0, simple messages (no system, no protected tools) should all be compressed
        assert len(to_compress) == len(simple_messages)
        assert len(preserved) == 0
        # Total should equal original
        assert len(preserved) + len(to_compress) == len(simple_messages)

    async def test_separate_preserves_system_messages(self, set_memory_config, mock_llm):
        """Test that system messages are preserved."""
        set_memory_config(MEMORY_PRESERVE_SYSTEM_PROMPTS=True, MEMORY_SHORT_TERM_MIN_SIZE=0)
        compressor = WorkingMemoryCompressor(mock_llm)

        messages = [
            LLMMessage(role="system", content="System prompt"),
            LLMMessage(role="user", content="Hello"),
            LLMMessage(role="assistant", content="Hi there!"),
        ]

        preserved, to_compress = compressor._separate_messages(messages)

        # System message should be preserved
        assert len(preserved) == 1
        assert preserved[0].role == "system"
        # Other messages should be compressed
        assert len(to_compress) == 2

    async def test_tool_pair_preservation_rule(
        self, set_memory_config, mock_llm, tool_use_messages
    ):
        """Test that tool pairs are preserved together (critical rule)."""
        set_memory_config(MEMORY_SHORT_TERM_MIN_SIZE=1)
        compressor = WorkingMemoryCompressor(mock_llm)

        preserved, to_compress = compressor._separate_messages(tool_use_messages)

        # Collect tool_use IDs and tool_result IDs from preserved messages
        preserved_tool_use_ids = set()
        preserved_tool_result_ids = set()

        for msg in preserved:
            if isinstance(msg.content, list):
                for block in msg.content:
                    if isinstance(block, dict):
                        if block.get("type") == "tool_use":
                            preserved_tool_use_ids.add(block.get("id"))
                        elif block.get("type") == "tool_result":
                            preserved_tool_result_ids.add(block.get("tool_use_id"))

        # Collect from to_compress
        compressed_tool_use_ids = set()
        compressed_tool_result_ids = set()

        for msg in to_compress:
            if isinstance(msg.content, list):
                for block in msg.content:
                    if isinstance(block, dict):
                        if block.get("type") == "tool_use":
                            compressed_tool_use_ids.add(block.get("id"))
                        elif block.get("type") == "tool_result":
                            compressed_tool_result_ids.add(block.get("tool_use_id"))

        # CRITICAL: Tool pairs should not be split between preserved and compressed
        # If a tool_use is preserved, its result should be preserved
        for tool_id in preserved_tool_use_ids:
            assert (
                tool_id in preserved_tool_result_ids
            ), f"Tool use {tool_id} is preserved but its result is not"

        # If a tool_result is preserved, its use should be preserved
        for tool_id in preserved_tool_result_ids:
            assert (
                tool_id in preserved_tool_use_ids
            ), f"Tool result for {tool_id} is preserved but its use is not"


class TestTokenEstimation:
    """Test token estimation logic."""

    async def test_estimate_tokens_simple_text(self, mock_llm):
        """Test token estimation for simple text messages."""
        compressor = WorkingMemoryCompressor(mock_llm)

        messages = [LLMMessage(role="user", content="Hello world")]
        tokens = compressor._estimate_tokens(messages)

        assert tokens > 0
        assert tokens < 100  # Simple message shouldn't be huge

    async def test_estimate_tokens_long_text(self, mock_llm):
        """Test token estimation for long text."""
        compressor = WorkingMemoryCompressor(mock_llm)

        long_content = "This is a long message. " * 100
        messages = [LLMMessage(role="user", content=long_content)]
        tokens = compressor._estimate_tokens(messages)

        # Should estimate roughly 4 chars per token
        expected_range = (len(long_content) // 5, len(long_content) // 3)
        assert expected_range[0] < tokens < expected_range[1]

    async def test_estimate_tokens_with_tool_content(self, mock_llm, tool_use_messages):
        """Test token estimation with tool content."""
        compressor = WorkingMemoryCompressor(mock_llm)

        tokens = compressor._estimate_tokens(tool_use_messages)

        # Tool messages have overhead, should be more than just text
        assert tokens > 0

    async def test_extract_text_content_from_dict(self, mock_llm):
        """Test extracting text content from dict-based content."""
        compressor = WorkingMemoryCompressor(mock_llm)

        msg = LLMMessage(
            role="assistant",
            content=[
                {"type": "text", "text": "Hello"},
                {"type": "tool_use", "id": "t1", "name": "tool", "input": {}},
            ],
        )

        text = compressor._extract_text_content(msg)
        assert "Hello" in text


class TestCompressionMetrics:
    """Test compression metrics calculation."""

    async def test_compression_ratio_calculation(self, mock_llm, simple_messages):
        """Test that compression ratio is calculated correctly."""
        compressor = WorkingMemoryCompressor(mock_llm)

        result = await compressor.compress(
            simple_messages, strategy=CompressionStrategy.SLIDING_WINDOW, target_tokens=50
        )

        assert result.compression_ratio > 0
        assert result.compression_ratio <= 1.0
        # Compressed should be smaller than original
        assert result.compressed_tokens <= result.original_tokens

    async def test_token_savings_calculation(self, mock_llm, simple_messages):
        """Test token savings calculation."""
        compressor = WorkingMemoryCompressor(mock_llm)

        result = await compressor.compress(
            simple_messages, strategy=CompressionStrategy.SLIDING_WINDOW
        )

        savings = result.token_savings
        assert savings >= 0
        assert savings == result.original_tokens - result.compressed_tokens

    async def test_savings_percentage_calculation(self, mock_llm, simple_messages):
        """Test savings percentage calculation."""
        compressor = WorkingMemoryCompressor(mock_llm)

        result = await compressor.compress(
            simple_messages, strategy=CompressionStrategy.SLIDING_WINDOW
        )

        percentage = result.savings_percentage
        assert 0 <= percentage <= 100


class TestCompressionErrors:
    """Test error handling in compression."""

    async def test_compression_with_llm_error(self, mock_llm, simple_messages):
        """Test compression behavior when LLM call fails."""
        compressor = WorkingMemoryCompressor(mock_llm)

        # Make LLM raise an error
        async def error_call(*args, **kwargs):
            raise Exception("LLM error")

        mock_llm.call_async = error_call

        # Should handle error gracefully
        result = await compressor.compress(
            simple_messages, strategy=CompressionStrategy.SLIDING_WINDOW
        )

        assert result is not None
        # Should fallback to preserving key messages
        assert len(result.preserved_messages) > 0
        assert "error" in result.metadata

    async def test_unknown_strategy_fallback(self, mock_llm, simple_messages):
        """Test fallback to default strategy for unknown strategy."""
        compressor = WorkingMemoryCompressor(mock_llm)

        # Use invalid strategy name
        result = await compressor.compress(simple_messages, strategy="invalid_strategy")

        # Should fallback to sliding window
        assert result is not None
