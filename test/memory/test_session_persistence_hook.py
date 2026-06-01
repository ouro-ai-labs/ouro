"""Unit tests for SessionPersistenceHook.

Verifies that the hook incrementally persists messages after every
iteration, rather than waiting until the end of the turn.
"""

from unittest.mock import AsyncMock

import pytest

from ouro.capabilities.memory.hook import SessionPersistenceHook
from ouro.capabilities.memory.manager import MemoryManager
from ouro.core.llm.base import LLMMessage
from ouro.core.loop.message_list import MessageList
from ouro.core.loop.protocols import ContinueDecision, LoopContext


@pytest.fixture
def mock_loop_ctx():
    """Minimal LoopContext for hook tests."""
    ctx = AsyncMock(spec=LoopContext)
    ctx.progress = AsyncMock()
    ctx.task = "test task"
    return ctx


class TestSessionPersistenceHook:
    async def test_on_run_start_resets_counter(self, mock_llm, mock_loop_ctx):
        """Counter should reset to 0 at the start of each run."""
        memory = MemoryManager(mock_llm)
        hook = SessionPersistenceHook(memory)
        hook._last_saved_count = 5

        messages = MessageList()
        await hook.on_run_start(mock_loop_ctx, messages)

        assert hook._last_saved_count == 0

    async def test_on_iteration_end_saves_new_messages(self, mock_llm, mock_loop_ctx):
        """New messages since last save should be persisted incrementally."""
        memory = MemoryManager(mock_llm)
        # Create a session so session_id is set
        await memory._ensure_session()
        assert memory.session_id is not None

        hook = SessionPersistenceHook(memory)
        messages = MessageList()
        messages.append(LLMMessage(role="user", content="hello"))
        messages.append(LLMMessage(role="assistant", content="hi"))

        result = await hook.on_iteration_end(mock_loop_ctx, messages, response=None, finished=False)

        # Should return CONTINUE (not STOP)
        assert result.kind == ContinueDecision.cont().kind
        # Both messages should have been saved
        assert hook._last_saved_count == 2

        # Verify by loading back
        loaded = await memory._store.load_session(memory.session_id)
        assert len(loaded["messages"]) == 2
        assert loaded["messages"][0].content == "hello"
        assert loaded["messages"][1].content == "hi"

    async def test_on_iteration_end_skips_when_no_new_messages(self, mock_llm, mock_loop_ctx):
        """If no messages were added, nothing should be saved."""
        memory = MemoryManager(mock_llm)
        await memory._ensure_session()

        hook = SessionPersistenceHook(memory)
        hook._last_saved_count = 0
        messages = MessageList()

        result = await hook.on_iteration_end(mock_loop_ctx, messages, response=None, finished=False)

        assert result.kind == ContinueDecision.cont().kind
        assert hook._last_saved_count == 0

    async def test_on_iteration_end_only_saves_increment(self, mock_llm, mock_loop_ctx):
        """Only messages appended since last save should be persisted."""
        memory = MemoryManager(mock_llm)
        await memory._ensure_session()

        hook = SessionPersistenceHook(memory)
        messages = MessageList()
        messages.append(LLMMessage(role="user", content="first"))

        # First save
        await hook.on_iteration_end(mock_loop_ctx, messages, None, False)
        assert hook._last_saved_count == 1

        # Add more messages
        messages.append(LLMMessage(role="assistant", content="second"))
        messages.append(LLMMessage(role="user", content="third"))

        # Second save — should only persist the 2 new ones
        await hook.on_iteration_end(mock_loop_ctx, messages, None, False)
        assert hook._last_saved_count == 3

        loaded = await memory._store.load_session(memory.session_id)
        assert len(loaded["messages"]) == 3
        assert [m.content for m in loaded["messages"]] == ["first", "second", "third"]

    async def test_on_iteration_end_no_session_id(self, mock_llm, mock_loop_ctx):
        """If memory has no session_id, hook should silently continue."""
        memory = MemoryManager(mock_llm)
        # session_id is None by default
        assert memory.session_id is None

        hook = SessionPersistenceHook(memory)
        messages = MessageList()
        messages.append(LLMMessage(role="user", content="hello"))

        result = await hook.on_iteration_end(mock_loop_ctx, messages, response=None, finished=False)

        assert result.kind == ContinueDecision.cont().kind
        assert hook._last_saved_count == 0  # unchanged
