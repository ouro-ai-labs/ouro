#!/usr/bin/env python3
"""Quick start: Using memory persistence."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from memory import MemoryConfig, MemoryManager
from memory.store import MemoryStore
from llm.base import LLMMessage


# Mock LLM for demo (replace with real LLM in production)
class MockLLM:
    provider_name = "Mock"
    model = "mock-model"

    def call(self, messages, **kwargs):
        return {"content": "Mock response"}

    def extract_text(self, response):
        return "Summary of conversation"

    @property
    def supports_tools(self):
        return True


def main():
    # Initialize
    store = MemoryStore(db_path="data/my_app.db")
    llm = MockLLM()

    # Option 1: Create new session with auto-save
    print("\n1️⃣  Creating new session with auto-save...")
    manager = MemoryManager(
        config=MemoryConfig(),
        llm=llm,
        store=store,
        enable_persistence=True  # ← Enable auto-save
    )
    session_id = manager.session_id
    print(f"   Session ID: {session_id}")

    # Add metadata for easy identification
    store.update_session_metadata(session_id, {
        "description": "Quick start demo",
        "version": "1.0"
    })

    # Add messages (automatically saved)
    manager.add_message(LLMMessage(role="user", content="Hello!"))
    manager.add_message(LLMMessage(role="assistant", content="Hi there!"))
    print(f"   ✓ Added 2 messages")

    # Option 2: Load existing session
    print(f"\n2️⃣  Loading session {session_id[:8]}...")
    manager2 = MemoryManager.from_session(
        session_id=session_id,
        llm=llm,
        store=store
    )
    print(f"   ✓ Loaded {manager2.short_term.count()} messages")

    # Continue conversation
    manager2.add_message(LLMMessage(role="user", content="How are you?"))
    print(f"   ✓ Continued conversation")

    # View sessions
    print("\n3️⃣  Viewing all sessions...")
    sessions = store.list_sessions(limit=5)
    for s in sessions:
        print(f"   • {s['id'][:8]}... - {s['message_count']} messages")

    print("\n✅ Done! View sessions with:")
    print(f"   python tools/session_manager.py list")
    print(f"   python tools/session_manager.py show {session_id}\n")


if __name__ == "__main__":
    main()
