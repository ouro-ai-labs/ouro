"""Tests for bot session router."""

from unittest.mock import MagicMock

from ouro.interfaces.bot.session_router import SessionRouter


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


async def test_cleanup_stale_sessions_no_sessions_dir():
    """cleanup_stale_sessions is a no-op without sessions_dir."""
    router = SessionRouter(agent_factory=_mock_agent_factory)
    removed = await router.cleanup_stale_sessions()
    assert removed == 0


# ---------------------------------------------------------------------------
# reset_session
# ---------------------------------------------------------------------------


async def test_reset_session_destroys_agent():
    router = SessionRouter(agent_factory=_mock_agent_factory)
    await router.get_or_create_agent("feishu", "chat_123")
    assert router.active_session_count == 1

    existed = await router.reset_session("feishu", "chat_123")
    assert existed is True
    assert router.active_session_count == 0
    key = router._session_key("feishu", "chat_123")
    assert key not in router._last_active


async def test_reset_session_nonexistent():
    router = SessionRouter(agent_factory=_mock_agent_factory)
    existed = await router.reset_session("feishu", "no_such_conv")
    assert existed is False


async def test_reset_session_new_agent_after_reset():
    """After reset, get_or_create_agent returns a fresh agent."""
    router = SessionRouter(agent_factory=_mock_agent_factory)
    agent_before = await router.get_or_create_agent("feishu", "chat_123")
    await router.reset_session("feishu", "chat_123")
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
