"""Unit tests for TokenTracker with litellm-based counting."""

from llm.message_types import LLMMessage
from memory.token_tracker import TokenTracker


class TestTokenCounterAccuracy:
    """Test that litellm.token_counter produces reasonable counts."""

    def test_english_text(self):
        """Test token counting for simple English text."""
        tracker = TokenTracker()
        msg = LLMMessage(role="user", content="Hello, how are you doing today?")
        tokens = tracker.count_message_tokens(msg, "openai", "gpt-4o")
        # English: roughly 1 token per word, plus message overhead
        assert 5 < tokens < 30

    def test_chinese_text(self):
        """Test token counting for Chinese text — the key improvement."""
        tracker = TokenTracker()
        msg = LLMMessage(role="user", content="你好，今天天气怎么样？我想去公园散步。")
        tokens = tracker.count_message_tokens(msg, "anthropic", "claude-sonnet-4-20250514")
        # Chinese uses more tokens per character than English.
        # The old 3.5 chars/token heuristic would severely undercount.
        assert tokens > 5

    def test_code_content(self):
        """Test token counting for code."""
        tracker = TokenTracker()
        code = """def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)
"""
        msg = LLMMessage(role="user", content=code)
        tokens = tracker.count_message_tokens(msg, "openai", "gpt-4o")
        assert tokens > 10

    def test_json_content(self):
        """Test token counting for JSON data."""
        tracker = TokenTracker()
        json_str = '{"name": "Alice", "age": 30, "hobbies": ["reading", "coding", "hiking"]}'
        msg = LLMMessage(role="user", content=json_str)
        tokens = tracker.count_message_tokens(msg, "openai", "gpt-4o")
        assert tokens > 10

    def test_message_with_tool_calls(self):
        """Test token counting for assistant message with tool_calls."""
        tracker = TokenTracker()
        msg = LLMMessage(
            role="assistant",
            content=None,
            tool_calls=[
                {
                    "id": "call_abc123",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": '{"path": "/tmp/test.py"}',
                    },
                }
            ],
        )
        tokens = tracker.count_message_tokens(msg, "openai", "gpt-4o")
        assert tokens > 5

    def test_tool_role_message(self):
        """Test token counting for tool response messages."""
        tracker = TokenTracker()
        msg = LLMMessage(
            role="tool",
            content="File contents: print('hello world')",
            tool_call_id="call_abc123",
            name="read_file",
        )
        tokens = tracker.count_message_tokens(msg, "openai", "gpt-4o")
        assert tokens > 5


class TestTokenCache:
    """Test that the content-based cache works correctly."""

    def test_cache_hit(self):
        """Same message content should return cached result."""
        tracker = TokenTracker()
        msg = LLMMessage(role="user", content="Hello world")

        first = tracker.count_message_tokens(msg, "openai", "gpt-4o")
        second = tracker.count_message_tokens(msg, "openai", "gpt-4o")
        assert first == second
        assert len(tracker._token_cache) == 1

    def test_cache_miss_on_different_content(self):
        """Different message content should be cached separately."""
        tracker = TokenTracker()
        msg1 = LLMMessage(role="user", content="Hello")
        msg2 = LLMMessage(role="user", content="Goodbye")

        tracker.count_message_tokens(msg1, "openai", "gpt-4o")
        tracker.count_message_tokens(msg2, "openai", "gpt-4o")
        assert len(tracker._token_cache) == 2

    def test_cache_cleared_on_reset(self):
        """Reset should clear the cache."""
        tracker = TokenTracker()
        msg = LLMMessage(role="user", content="Hello")
        tracker.count_message_tokens(msg, "openai", "gpt-4o")
        assert len(tracker._token_cache) == 1

        tracker.reset()
        assert len(tracker._token_cache) == 0

    def test_cache_key_includes_tool_calls(self):
        """Messages with different tool_calls should have different cache keys."""
        tracker = TokenTracker()
        msg1 = LLMMessage(
            role="assistant",
            content=None,
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "foo", "arguments": "{}"},
                }
            ],
        )
        msg2 = LLMMessage(
            role="assistant",
            content=None,
            tool_calls=[
                {
                    "id": "call_2",
                    "type": "function",
                    "function": {"name": "bar", "arguments": "{}"},
                }
            ],
        )
        tracker.count_message_tokens(msg1, "openai", "gpt-4o")
        tracker.count_message_tokens(msg2, "openai", "gpt-4o")
        assert len(tracker._token_cache) == 2


class TestCostTracking:
    """Test cost calculation."""

    def test_calculate_cost_default(self):
        """Test cost calculation with default pricing."""
        tracker = TokenTracker()
        tracker.record_usage({"input_tokens": 1000, "output_tokens": 500})
        cost = tracker.calculate_cost("unknown-model")
        assert cost > 0

    def test_get_net_savings(self):
        """Test net savings calculation."""
        tracker = TokenTracker()
        tracker.record_usage({"input_tokens": 10000, "output_tokens": 5000})
        tracker.add_compression_savings(3000)
        tracker.add_compression_cost(500)

        savings = tracker.get_net_savings("gpt-4o")
        assert savings["net_tokens"] == 2500
        assert savings["savings_percentage"] > 0
