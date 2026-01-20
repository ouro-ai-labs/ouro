"""Example demonstrating memory management system.

This example shows how memory automatically compresses conversations
to reduce token usage and costs.
"""

import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from llm import LLMMessage
from memory import MemoryManager


class MockLLM:
    """Mock LLM for testing without API calls."""

    def __init__(self):
        self.provider_name = "mock"
        self.model = "mock-model"

    def call(self, messages, tools=None, max_tokens=4096, **kwargs):
        """Mock LLM call that returns a summary."""

        # Return a mock summary
        class MockResponse:
            content = "This is a summary of the conversation so far."
            stop_reason = "end_turn"

        return MockResponse()

    def extract_text(self, response):
        return response.content


def main():
    """Demonstrate memory management."""
    print("=" * 60)
    print("Memory Management System Demo")
    print("=" * 60)

    # Configure memory settings directly via Config class
    # (In production, these would be set via environment variables)
    Config.MEMORY_COMPRESSION_THRESHOLD = 400  # Trigger compression quickly
    Config.MEMORY_SHORT_TERM_SIZE = 5
    Config.MEMORY_COMPRESSION_RATIO = 0.3

    mock_llm = MockLLM()
    memory = MemoryManager(mock_llm)

    print("\nConfiguration:")
    print(f"  Compression threshold: {Config.MEMORY_COMPRESSION_THRESHOLD}")
    print(f"  Short-term size: {Config.MEMORY_SHORT_TERM_SIZE}")

    # Add system message
    print("\n1. Adding system message...")
    memory.add_message(LLMMessage(role="system", content="You are a helpful assistant."))

    # Simulate a conversation
    print("\n2. Simulating conversation with 15 messages...")
    for i in range(15):
        # User message
        user_msg = f"This is user message {i+1}. " + "Some content. " * 20
        memory.add_message(LLMMessage(role="user", content=user_msg))

        # Assistant message
        assistant_msg = f"This is assistant response {i+1}. " + "More content. " * 20
        memory.add_message(LLMMessage(role="assistant", content=assistant_msg))

        # Show compression events
        if memory.was_compressed_last_iteration:
            print(f"   💾 Compression triggered! Saved {memory.last_compression_savings} tokens")

    # Get final statistics
    print("\n3. Final Memory Statistics:")
    print("=" * 60)
    stats = memory.get_stats()

    print(f"Current tokens: {stats['current_tokens']}")
    print(f"Total input tokens: {stats['total_input_tokens']}")
    print(f"Total output tokens: {stats['total_output_tokens']}")
    print(f"Compression count: {stats['compression_count']}")
    print(f"Total savings: {stats['total_savings']} tokens")
    print(f"Compression cost: {stats['compression_cost']} tokens")
    print(f"Net savings: {stats['net_savings']} tokens")
    print(f"Short-term messages: {stats['short_term_count']}")

    # Show context structure
    print("\n4. Context Structure:")
    print("=" * 60)
    context = memory.get_context_for_llm()
    print(f"Total messages in context: {len(context)}")
    for i, msg in enumerate(context):
        role = msg.role.upper()
        content_preview = str(msg.content)[:50] + "..."
        print(f"  [{i+1}] {role}: {content_preview}")

    print("\n✅ Demo complete!")
    print(
        f"\nKey takeaway: Original {stats['total_input_tokens'] + stats['total_output_tokens']} tokens "
        f"compressed to ~{stats['current_tokens']} tokens in context"
    )


if __name__ == "__main__":
    main()
