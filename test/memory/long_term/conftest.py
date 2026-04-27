"""Fixtures for long-term memory tests."""

import pytest
import pytest_asyncio

from ouro.capabilities.memory.long_term.store import MemoryStore
from ouro.core.llm.message_types import LLMResponse, StopReason


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
async def memory_store(tmp_path):
    """Create a MemoryStore backed by a temp directory."""
    return MemoryStore(memory_dir=str(tmp_path / "memory"))


@pytest.fixture
def sample_content():
    """Sample memory content for testing."""
    return (
        "## Decisions\n\n"
        "- Use async-first architecture\n"
        "- Choose YAML over SQLite\n\n"
        "## Preferences\n\n"
        "- Prefer type hints everywhere\n\n"
        "## Facts\n\n"
        "- Project uses Python 3.12+\n"
    )
