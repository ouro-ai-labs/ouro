#!/usr/bin/env python3
"""Quick start: Using memory persistence."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from llm.base import LLMMessage
from memory import MemoryConfig, MemoryManager


# Mock LLM for demo (replace with real LLM in production)
class MockLLM:
    provider_name = "Mock"
    model = "mock-model"

    async def call_async(self, messages, **kwargs):
        return {"content": "Mock response"}

    def extract_text(self, response):
        return "Summary of conversation"

    @property
    def supports_tools(self):
        return True


async def main():
    # Initialize
    llm = MockLLM()

    # Option 1: Create new session (persistence is automatic)
    print("\n1️⃣  Creating new session (automatically persisted)...")
    manager = MemoryManager(config=MemoryConfig(), llm=llm, db_path="data/my_app.db")
    session_id = manager.session_id
    print(f"   Session ID: {session_id}")

    # Add messages
    await manager.add_message(LLMMessage(role="user", content="Hello!"))
    await manager.add_message(LLMMessage(role="assistant", content="Hi there!"))
    print("   ✓ Added 2 messages")

    # Save memory state (normally done automatically after await agent.run(...))
    manager.save_memory()
    print("   ✓ Saved to database")

    # Option 2: Load existing session
    print(f"\n2️⃣  Loading session {session_id[:8]}...")
    manager2 = MemoryManager.from_session(session_id=session_id, llm=llm, db_path="data/my_app.db")
    print(f"   ✓ Loaded {manager2.short_term.count()} messages")

    # Continue conversation
    await manager2.add_message(LLMMessage(role="user", content="How are you?"))
    print("   ✓ Continued conversation")

    # View sessions
    print("\n3️⃣  Viewing all sessions...")
    sessions = manager.store.list_sessions(limit=5)
    for s in sessions:
        print(f"   • {s['id'][:8]}... - {s['message_count']} messages")

    print("\n✅ Done! View sessions with:")
    print("   python tools/session_manager.py list --db data/my_app.db")
    print(f"   python tools/session_manager.py show {session_id} --db data/my_app.db\n")


if __name__ == "__main__":
    asyncio.run(main())
