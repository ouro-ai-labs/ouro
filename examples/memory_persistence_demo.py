"""Demo: Using memory persistence with YAML sessions."""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from llm.message_types import LLMMessage, LLMResponse, StopReason
from memory import MemoryManager


class MockLLM:
    """Mock LLM for demo."""

    def __init__(self):
        self.provider_name = "Mock"
        self.model = "mock-model"

    async def call_async(self, messages, tools=None, max_tokens=4096, **kwargs):
        return LLMResponse(
            content="Summary of the conversation",
            stop_reason=StopReason.STOP,
            usage={"input_tokens": 100, "output_tokens": 50},
        )

    def extract_text(self, response):
        return "Summary of the conversation"

    @property
    def supports_tools(self):
        return True


async def demo_create_session():
    """Demo: Create a new session and add messages."""
    print("\n" + "=" * 80)
    print("Demo 1: Create a new session (automatically persisted as YAML)")
    print("=" * 80)

    llm = MockLLM()
    manager = MemoryManager(llm=llm)

    # Add some messages
    messages = [
        LLMMessage(role="system", content="You are a helpful assistant."),
        LLMMessage(role="user", content="Hello! What's the capital of France?"),
        LLMMessage(role="assistant", content="The capital of France is Paris."),
        LLMMessage(role="user", content="What about Germany?"),
        LLMMessage(role="assistant", content="The capital of Germany is Berlin."),
        LLMMessage(role="user", content="And Italy?"),
        LLMMessage(role="assistant", content="The capital of Italy is Rome."),
    ]

    for msg in messages:
        await manager.add_message(msg)
        print(f"  Added message: [{msg.role}] {str(msg.content)[:50]}...")

    await manager.save_memory()
    session_id = manager.session_id
    print(f"\n✅ Created session: {session_id}")

    return session_id


async def demo_load_session(session_id: str):
    """Demo: Load an existing session."""
    print("\n" + "=" * 80)
    print(f"Demo 2: Load session {session_id}")
    print("=" * 80)

    llm = MockLLM()
    manager = await MemoryManager.from_session(session_id=session_id, llm=llm)

    print("\n✅ Loaded session with:")
    print(f"  {len(manager.system_messages)} system messages")
    print(f"  {manager.short_term.count()} messages in short-term")
    print(f"  {manager.current_tokens} current tokens")

    # Add more messages
    print("\n📝 Adding more messages...")
    new_messages = [
        LLMMessage(role="user", content="What about Spain?"),
        LLMMessage(role="assistant", content="The capital of Spain is Madrid."),
    ]

    for msg in new_messages:
        await manager.add_message(msg)
        print(f"  Added: [{msg.role}] {str(msg.content)[:50]}...")

    await manager.save_memory()
    print("\n💾 Saved updated memory")


async def demo_list_sessions():
    """Demo: List all sessions."""
    print("\n" + "=" * 80)
    print("Demo 3: List all sessions")
    print("=" * 80)

    sessions = await MemoryManager.list_sessions(limit=10)

    print(f"\n📚 Found {len(sessions)} sessions:")
    for session in sessions:
        print(f"\n  ID: {session['id']}")
        print(f"  Updated: {session.get('updated_at', session['created_at'])}")
        print(f"  Messages: {session['message_count']}")
        print(f"  Preview: {session.get('preview', 'N/A')}")


async def main():
    """Run all demos."""
    print("\n🚀 Memory Persistence Demo (YAML)")
    print("=" * 80)

    # Demo 1: Create a new session
    session_id = await demo_create_session()

    # Demo 2: Load the session
    await demo_load_session(session_id)

    # Demo 3: List all sessions
    await demo_list_sessions()

    print("\n" + "=" * 80)
    print("✅ Demo complete!")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
