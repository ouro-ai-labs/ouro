"""Fixtures for long-term memory tests."""

import pytest
import pytest_asyncio

from llm.message_types import LLMResponse, StopReason
from memory.long_term.store import GitMemoryStore, MemoryCategory


class MockLTMLLM:
    """Minimal mock LLM for long-term memory tests."""

    def __init__(self):
        self.provider_name = "mock"
        self.model = "mock-model"
        self.call_count = 0
        self.last_messages = None
        self.response_text = ""

    async def call_async(self, messages, tools=None, max_tokens=4096, **kwargs):
        self.call_count += 1
        self.last_messages = messages
        return LLMResponse(
            content=self.response_text,
            stop_reason=StopReason.STOP,
            usage={"input_tokens": 100, "output_tokens": 50},
        )


@pytest.fixture
def mock_ltm_llm():
    return MockLTMLLM()


@pytest_asyncio.fixture
async def git_store(tmp_path):
    """Create a GitMemoryStore backed by a temp directory."""
    store = GitMemoryStore(memory_dir=str(tmp_path / "memory"))
    await store.ensure_repo()
    return store


@pytest.fixture
def sample_memories():
    """Sample memories for testing."""
    return {
        MemoryCategory.DECISIONS: "- Use async-first architecture\n- Choose YAML over SQLite\n",
        MemoryCategory.PREFERENCES: "- Prefer type hints everywhere\n",
        MemoryCategory.FACTS: "- Project uses Python 3.12+\n",
    }
