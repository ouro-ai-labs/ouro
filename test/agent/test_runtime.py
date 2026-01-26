"""Unit tests for AgentRuntime (RFC-004)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.runtime import (
    AgentRuntime,
    MaxAgentsExceededError,
    MaxDepthExceededError,
    RuntimeConfig,
)


class MockTool:
    """Mock tool for testing."""

    def __init__(self, name):
        self.name = name


class MockLLM:
    """Mock LLM adapter for testing."""

    provider_name = "test"
    model = "test-model"

    async def call_async(self, **kwargs):
        return MagicMock(
            content="Test response",
            stop_reason="stop",
            usage={"input_tokens": 10, "output_tokens": 5},
        )

    def extract_text(self, response):
        return response.content

    def extract_tool_calls(self, response):
        return []


class TestRuntimeConfig:
    """Test RuntimeConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = RuntimeConfig()

        assert config.max_depth == 5
        assert config.max_agents == 10
        assert config.enable_composition is True
        assert config.enable_persistence is True

    def test_custom_config(self):
        """Test custom configuration values."""
        config = RuntimeConfig(
            max_depth=5,
            max_agents=20,
            enable_composition=False,
        )

        assert config.max_depth == 5
        assert config.max_agents == 20
        assert config.enable_composition is False


class TestAgentRuntimeBasics:
    """Test basic AgentRuntime functionality."""

    def test_initialization(self):
        """Test runtime initialization."""
        llm = MockLLM()
        tools = [MockTool("tool1"), MockTool("tool2")]

        runtime = AgentRuntime(llm=llm, tools=tools)

        assert runtime.llm is llm
        assert len(runtime.tools) == 2
        assert runtime.config.max_depth == 5
        assert len(runtime.agents) == 0

    def test_initialization_with_config(self):
        """Test runtime initialization with custom config."""
        llm = MockLLM()
        tools = []
        config = RuntimeConfig(max_depth=5, max_agents=15)

        runtime = AgentRuntime(llm=llm, tools=tools, config=config)

        assert runtime.config.max_depth == 5
        assert runtime.config.max_agents == 15


class TestAgentSpawning:
    """Test agent spawning functionality."""

    def test_create_root_agent(self):
        """Test creating root agent."""
        llm = MockLLM()
        tools = [MockTool("tool1")]

        runtime = AgentRuntime(llm=llm, tools=tools)
        agent = runtime.create_root_agent(task="Test task")

        assert agent is not None
        assert len(runtime.agents) == 1
        assert runtime.memory_graph.root_id is not None

    def test_create_child_agent(self):
        """Test creating child agent."""
        llm = MockLLM()
        tools = [MockTool("tool1")]

        runtime = AgentRuntime(llm=llm, tools=tools)
        root = runtime.create_root_agent(task="Root task")

        child = runtime.create_child_agent(
            parent_node_id=root._memory_node_id,
            task="Child task",
            scope="test",
        )

        assert child is not None
        assert len(runtime.agents) == 2

    def test_max_depth_exceeded(self):
        """Test that max depth is enforced."""
        llm = MockLLM()
        tools = [MockTool("tool1")]
        config = RuntimeConfig(max_depth=1)

        runtime = AgentRuntime(llm=llm, tools=tools, config=config)

        # Create root at depth 0
        root = runtime.create_root_agent(task="Root")

        # Try to create child at depth 1 (should fail with max_depth=1)
        with pytest.raises(MaxDepthExceededError):
            runtime.create_child_agent(
                parent_node_id=root._memory_node_id,
                task="Child",
                depth=1,
            )

    def test_max_agents_exceeded(self):
        """Test that max agents is enforced."""
        llm = MockLLM()
        tools = [MockTool("tool1")]
        config = RuntimeConfig(max_agents=2)

        runtime = AgentRuntime(llm=llm, tools=tools, config=config)

        # Create agents up to limit
        root = runtime.create_root_agent(task="Root")
        runtime.create_child_agent(
            parent_node_id=root._memory_node_id,
            task="Child 1",
        )

        # Third agent should fail
        with pytest.raises(MaxAgentsExceededError):
            runtime.create_child_agent(
                parent_node_id=root._memory_node_id,
                task="Child 2",
            )

    def test_spawn_with_tool_filter(self):
        """Test spawning agent with tool filter."""
        llm = MockLLM()
        tools = [MockTool("read_file"), MockTool("write_file")]

        runtime = AgentRuntime(llm=llm, tools=tools)
        root = runtime.create_root_agent(task="Root")

        child = runtime.create_child_agent(
            parent_node_id=root._memory_node_id,
            task="Read only",
            tool_filter={"read_file"},
        )

        # Check that child has filtered tools
        assert child is not None


class TestRuntimeStats:
    """Test runtime statistics."""

    def test_get_stats(self):
        """Test getting runtime stats."""
        llm = MockLLM()
        tools = [MockTool("tool1")]

        runtime = AgentRuntime(llm=llm, tools=tools)
        runtime.create_root_agent(task="Test")

        stats = runtime.get_stats()

        assert stats["agent_count"] == 1
        assert "memory_graph" in stats
        assert stats["config"]["max_depth"] == 5


class TestMemoryNodeConfiguration:
    """Test memory node configuration through runtime."""

    def test_root_agent_has_memory_node(self):
        """Test that root agent has memory node assigned."""
        llm = MockLLM()
        tools = []

        runtime = AgentRuntime(llm=llm, tools=tools)
        agent = runtime.create_root_agent(task="Test")

        assert agent._memory_node_id is not None
        node = runtime.memory_graph.get_node(agent._memory_node_id)
        assert node is not None
        assert node.metadata.get("scope") == "root"

    def test_child_agent_linked_to_parent(self):
        """Test that child agent's memory node is linked to parent."""
        llm = MockLLM()
        tools = []

        runtime = AgentRuntime(llm=llm, tools=tools)
        root = runtime.create_root_agent(task="Root")
        child = runtime.create_child_agent(
            parent_node_id=root._memory_node_id,
            task="Child",
        )

        child_node = runtime.memory_graph.get_node(child._memory_node_id)
        assert root._memory_node_id in child_node.parent_ids


class TestRuntimeIntegration:
    """Integration tests for runtime with mocked agents."""

    @pytest.mark.asyncio
    async def test_run_simple_task(self):
        """Test running a simple task through runtime."""
        llm = MockLLM()
        tools = []

        # Mock the agent's run method
        with patch("agent.react_agent.ReActAgent.run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "Task completed"

            runtime = AgentRuntime(llm=llm, tools=tools)
            result = await runtime.run("Simple task")

            assert result == "Task completed"
            mock_run.assert_called_once_with("Simple task")
