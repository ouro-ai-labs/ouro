"""Demo: Using memory persistence with sessions."""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from llm.base import LLMMessage
from memory import MemoryConfig, MemoryManager


class MockLLM:
    """Mock LLM for demo."""

    def __init__(self):
        self.provider_name = "Mock"
        self.model = "mock-model"

    async def call_async(self, messages, tools=None, max_tokens=4096, **kwargs):
        return {"content": "Mock response", "stop_reason": "end_turn"}

    def extract_text(self, response):
        return "Summary of the conversation"

    @property
    def supports_tools(self):
        return True


async def demo_create_session():
    """Demo: Create a new session and add messages."""
    print("\n" + "=" * 80)
    print("Demo 1: Create a new session (automatically persisted)")
    print("=" * 80)

    # Initialize LLM
    llm = MockLLM()

    # Create manager (persistence is automatic)
    config = MemoryConfig(short_term_message_count=5, target_working_memory_tokens=100)

    manager = MemoryManager(config=config, llm=llm, db_path="data/demo_memory.db")

    session_id = manager.session_id
    print(f"\n✅ Created session: {session_id}")

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

    # Save memory state (normally done automatically after await agent.run(...))
    manager.save_memory()
    print("\n💾 Saved memory to database")

    # Get stats
    stats = manager.store.get_session_stats(session_id)
    print("\n📊 Session Stats:")
    print(f"  Messages: {stats['message_count']}")
    print(f"  System Messages: {stats['system_message_count']}")
    print(f"  Compressions: {stats['compression_count']}")

    return session_id


async def demo_load_session(session_id: str):
    """Demo: Load an existing session."""
    print("\n" + "=" * 80)
    print(f"Demo 2: Load session {session_id}")
    print("=" * 80)

    # Initialize LLM
    llm = MockLLM()

    # Load session
    manager = MemoryManager.from_session(
        session_id=session_id, llm=llm, db_path="data/demo_memory.db"
    )

    print("\n✅ Loaded session with:")
    print(f"  {len(manager.system_messages)} system messages")
    print(f"  {manager.short_term.count()} messages in short-term")
    print(f"  {len(manager.summaries)} summaries")
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

    # Save memory state
    manager.save_memory()
    print("\n💾 Saved memory to database")

    # Get updated stats
    stats = manager.store.get_session_stats(session_id)
    print("\n📊 Updated Stats:")
    print(f"  Messages: {stats['message_count']}")
    print(f"  Compressions: {stats['compression_count']}")


def demo_list_sessions():
    """Demo: List all sessions."""
    print("\n" + "=" * 80)
    print("Demo 3: List all sessions")
    print("=" * 80)

    # Create a temporary manager to access the store
    from memory.store import MemoryStore

    store = MemoryStore(db_path="data/demo_memory.db")
    sessions = store.list_sessions(limit=10)

    print(f"\n📚 Found {len(sessions)} sessions:")
    for session in sessions:
        print(f"\n  ID: {session['id']}")
        print(f"  Created: {session['created_at']}")
        print(f"  Messages: {session['message_count']}")
        print(f"  Summaries: {session['summary_count']}")


async def main():
    """Run all demos."""
    print("\n🚀 Memory Persistence Demo")
    print("=" * 80)

    # Demo 1: Create a new session
    session_id = await demo_create_session()

    # Demo 2: Load the session
    await demo_load_session(session_id)

    # Demo 3: List all sessions
    demo_list_sessions()

    print("\n" + "=" * 80)
    print("✅ Demo complete!")
    print("\nTo view sessions, run:")
    print("  python tools/session_manager.py list --db data/demo_memory.db")
    print(f"  python tools/session_manager.py show {session_id} --db data/demo_memory.db")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
