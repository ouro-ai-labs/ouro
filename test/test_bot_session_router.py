"""Tests for bot session router."""

import asyncio
from unittest.mock import MagicMock

from bot.session_router import SessionRouter


def _mock_agent_factory():
    """Create a mock agent factory that returns MagicMock agents."""
    return MagicMock()


async def test_get_or_create_agent_creates_new_session():
    router = SessionRouter(agent_factory=_mock_agent_factory)
    assert router.active_session_count == 0

    agent = await router.get_or_create_agent("feishu", "chat_123")
    assert agent is not None
    assert router.active_session_count == 1


async def test_get_or_create_agent_reuses_existing():
    router = SessionRouter(agent_factory=_mock_agent_factory)

    agent1 = await router.get_or_create_agent("feishu", "chat_123")
    agent2 = await router.get_or_create_agent("feishu", "chat_123")
    assert agent1 is agent2
    assert router.active_session_count == 1


async def test_different_conversations_get_different_agents():
    router = SessionRouter(agent_factory=_mock_agent_factory)

    agent1 = await router.get_or_create_agent("feishu", "chat_a")
    agent2 = await router.get_or_create_agent("feishu", "chat_b")
    assert agent1 is not agent2
    assert router.active_session_count == 2


async def test_different_channels_get_different_agents():
    router = SessionRouter(agent_factory=_mock_agent_factory)

    agent1 = await router.get_or_create_agent("feishu", "chat_123")
    agent2 = await router.get_or_create_agent("slack", "chat_123")
    assert agent1 is not agent2
    assert router.active_session_count == 2


async def test_get_lock_returns_asyncio_lock():
    router = SessionRouter(agent_factory=_mock_agent_factory)
    await router.get_or_create_agent("feishu", "chat_123")

    lock = router.get_lock("feishu", "chat_123")
    assert isinstance(lock, asyncio.Lock)


async def test_same_conversation_gets_same_lock():
    router = SessionRouter(agent_factory=_mock_agent_factory)
    await router.get_or_create_agent("feishu", "chat_123")

    lock1 = router.get_lock("feishu", "chat_123")
    lock2 = router.get_lock("feishu", "chat_123")
    assert lock1 is lock2


async def test_cleanup_idle_sessions():
    router = SessionRouter(agent_factory=_mock_agent_factory, idle_timeout=0.0)

    await router.get_or_create_agent("feishu", "chat_123")
    await router.get_or_create_agent("feishu", "chat_456")
    assert router.active_session_count == 2

    # With idle_timeout=0.0, all sessions are immediately idle
    removed = router.cleanup_idle_sessions()
    assert removed == 2
    assert router.active_session_count == 0


async def test_cleanup_preserves_active_sessions():
    router = SessionRouter(agent_factory=_mock_agent_factory, idle_timeout=3600.0)

    await router.get_or_create_agent("feishu", "chat_123")
    assert router.active_session_count == 1

    # With a 1-hour timeout, nothing should be cleaned up
    removed = router.cleanup_idle_sessions()
    assert removed == 0
    assert router.active_session_count == 1


async def test_lock_serializes_access():
    """Verify that the per-conversation lock serializes concurrent access."""
    router = SessionRouter(agent_factory=_mock_agent_factory)
    await router.get_or_create_agent("feishu", "chat_123")
    lock = router.get_lock("feishu", "chat_123")

    order: list[int] = []

    async def task(n: int, delay: float):
        async with lock:
            order.append(n)
            await asyncio.sleep(delay)

    # Task 1 acquires the lock first, task 2 must wait
    await asyncio.gather(task(1, 0.05), task(2, 0.0))
    assert order == [1, 2]


# ---------------------------------------------------------------------------
# reset_session
# ---------------------------------------------------------------------------


async def test_reset_session_destroys_agent():
    router = SessionRouter(agent_factory=_mock_agent_factory)
    await router.get_or_create_agent("feishu", "chat_123")
    assert router.active_session_count == 1

    existed = router.reset_session("feishu", "chat_123")
    assert existed is True
    assert router.active_session_count == 0
    # Lock should also be removed
    key = router._session_key("feishu", "chat_123")
    assert key not in router._locks
    assert key not in router._last_active


def test_reset_session_nonexistent():
    router = SessionRouter(agent_factory=_mock_agent_factory)
    existed = router.reset_session("feishu", "no_such_conv")
    assert existed is False


async def test_reset_session_new_agent_after_reset():
    """After reset, get_or_create_agent returns a fresh agent."""
    router = SessionRouter(agent_factory=_mock_agent_factory)
    agent_before = await router.get_or_create_agent("feishu", "chat_123")
    router.reset_session("feishu", "chat_123")
    agent_after = await router.get_or_create_agent("feishu", "chat_123")
    assert agent_before is not agent_after


# ---------------------------------------------------------------------------
# get_session_age
# ---------------------------------------------------------------------------


def test_get_session_age_no_session():
    router = SessionRouter(agent_factory=_mock_agent_factory)
    assert router.get_session_age("feishu", "chat_123") is None


async def test_get_session_age_returns_positive():
    router = SessionRouter(agent_factory=_mock_agent_factory)
    await router.get_or_create_agent("feishu", "chat_123")
    age = router.get_session_age("feishu", "chat_123")
    assert age is not None
    assert age >= 0
