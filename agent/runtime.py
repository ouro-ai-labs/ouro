"""Agent runtime for coordinating composable agent execution.

This module provides the AgentRuntime class that manages agent spawning,
memory graph coordination, and serves as the main entry point for task execution.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from memory.graph import MemoryGraph
from memory.store import MemoryStore
from tools.base import BaseTool
from utils import get_logger

from .composition import AgentConfig, CompositionPlan, CompositionResult

if TYPE_CHECKING:
    from llm import LiteLLMAdapter

    from .react_agent import ReActAgent

logger = get_logger(__name__)


class MaxDepthExceededError(Exception):
    """Raised when agent nesting depth exceeds the limit."""

    pass


class MaxAgentsExceededError(Exception):
    """Raised when the total number of agents exceeds the limit."""

    pass


@dataclass
class RuntimeConfig:
    """Configuration for the agent runtime.

    Attributes:
        max_depth: Maximum agent nesting depth
        max_agents: Maximum total agents per task
        enable_composition: Whether to enable automatic composition
        enable_persistence: Whether to persist memory graph to database
    """

    max_depth: int = 5
    max_agents: int = 10
    enable_composition: bool = True
    enable_persistence: bool = True


class AgentRuntime:
    """Runtime coordinator for composable agent execution.

    The AgentRuntime manages:
    - Agent spawning with resource limits
    - Memory graph coordination
    - Tool registration and filtering
    - Persistence and session management

    Example:
        ```python
        runtime = AgentRuntime(llm, tools)
        result = await runtime.run("Analyze this codebase and add type hints")
        ```
    """

    def __init__(
        self,
        llm: "LiteLLMAdapter",
        tools: List[BaseTool],
        config: Optional[RuntimeConfig] = None,
        store: Optional[MemoryStore] = None,
        session_id: Optional[str] = None,
    ):
        """Initialize the agent runtime.

        Args:
            llm: LLM adapter for agent calls
            tools: List of available tools
            config: Optional runtime configuration
            store: Optional memory store for persistence
            session_id: Optional session ID for resuming
        """
        self.llm = llm
        self.tools = tools
        self.config = config or RuntimeConfig()

        # Memory graph for context management
        self.memory_graph = MemoryGraph(llm=llm)

        # Persistence
        self.store = store
        self.session_id = session_id
        self._session_created = session_id is not None

        # Agent tracking
        self.agents: Dict[str, ReActAgent] = {}
        self._agent_count = 0

        logger.info(
            f"AgentRuntime initialized with max_depth={self.config.max_depth}, "
            f"max_agents={self.config.max_agents}"
        )

    def spawn_agent(
        self,
        config: AgentConfig,
        depth: int = 0,
    ) -> "ReActAgent":
        """Spawn a new agent with resource limit checking.

        Args:
            config: Configuration for the new agent
            depth: Current nesting depth

        Returns:
            The spawned ReActAgent instance

        Raises:
            MaxDepthExceededError: If depth limit exceeded
            MaxAgentsExceededError: If agent count limit exceeded
        """
        # Import here to avoid circular imports
        from .react_agent import ReActAgent

        # Check resource limits
        if depth >= self.config.max_depth:
            raise MaxDepthExceededError(f"Agent depth {depth} exceeds max {self.config.max_depth}")

        if self._agent_count >= self.config.max_agents:
            raise MaxAgentsExceededError(
                f"Agent count {self._agent_count} exceeds max {self.config.max_agents}"
            )

        # Get memory node for this agent
        node = self.memory_graph.get_node(config.memory_node_id)
        if not node:
            raise ValueError(f"Memory node {config.memory_node_id} not found")

        # Filter tools if specified
        filtered_tools = config.get_filtered_tools()

        # Create the agent with graph-backed memory
        agent = ReActAgent(
            llm=self.llm,
            tools=filtered_tools,
            memory_node=node,
            memory_graph=self.memory_graph,
        )

        # Attach runtime reference for nested spawning
        agent._runtime = self
        agent._depth = depth
        agent._memory_node_id = config.memory_node_id

        # Track the agent
        agent_id = f"agent_{self._agent_count}"
        self.agents[agent_id] = agent
        self._agent_count += 1

        logger.debug(f"Spawned {agent_id} at depth {depth} with node {config.memory_node_id}")

        return agent

    def create_root_agent(self, task: str) -> "ReActAgent":
        """Create the root agent for a task.

        Args:
            task: The task to execute

        Returns:
            The root ReActAgent instance
        """
        # Create root memory node
        root_node = self.memory_graph.create_root_node(metadata={"scope": "root", "task": task})

        # Create agent config
        config = AgentConfig(
            task=task,
            tools=self.tools,
            memory_node_id=root_node.id,
        )

        return self.spawn_agent(config, depth=0)

    def create_child_agent(
        self,
        parent_node_id: str,
        task: str,
        tool_filter: Optional[Set[str]] = None,
        scope: str = "child",
        depth: int = 1,
    ) -> "ReActAgent":
        """Create a child agent with a new memory node.

        Args:
            parent_node_id: Parent memory node ID
            task: The subtask to execute
            tool_filter: Optional set of tool names to allow
            scope: Scope identifier for the memory node
            depth: Current nesting depth

        Returns:
            The child ReActAgent instance
        """
        # Create child memory node
        child_node = self.memory_graph.create_node(
            parent_id=parent_node_id,
            metadata={"scope": scope, "task": task},
        )

        # Create agent config
        config = AgentConfig(
            task=task,
            tools=self.tools,
            memory_node_id=child_node.id,
            tool_filter=tool_filter,
            depth=depth,
        )

        return self.spawn_agent(config, depth=depth)

    async def run(self, task: str) -> str:
        """Execute a task using the composable agent architecture.

        This is the main entry point for task execution. It:
        1. Creates a root agent
        2. Assesses whether composition is needed (if enable_composition=True)
        3. Executes using the appropriate pattern
        4. Returns the final result

        Args:
            task: The task to execute

        Returns:
            The final answer as a string
        """
        logger.info(f"AgentRuntime.run() starting: {task[:100]}...")

        # Create root agent
        root_agent = self.create_root_agent(task)

        try:
            # Execute the task with or without composition assessment
            if self.config.enable_composition:
                result = await root_agent.run_with_composition(task)
            else:
                result = await root_agent.run(task)

            # Save memory if persistence is enabled
            if self.config.enable_persistence and self.store:
                await self._save_session()

            return result

        except Exception as e:
            logger.error(f"Task execution failed: {e}")
            raise

    async def _save_session(self) -> None:
        """Save the current session state to the store."""
        if not self.store:
            return

        try:
            # Ensure session exists
            if not self._session_created:
                self.session_id = await self.store.create_session()
                self._session_created = True

            # Save memory graph (handled by store's graph persistence)
            logger.debug(f"Saved session {self.session_id}")

        except Exception as e:
            logger.error(f"Failed to save session: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get runtime statistics.

        Returns:
            Dict with runtime stats
        """
        return {
            "agent_count": self._agent_count,
            "memory_graph": self.memory_graph.get_stats(),
            "config": {
                "max_depth": self.config.max_depth,
                "max_agents": self.config.max_agents,
            },
        }
