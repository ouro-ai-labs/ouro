"""Unit tests for agent composition module (RFC-004)."""

from agent.composition import (
    AgentConfig,
    CompositionPattern,
    CompositionPlan,
    CompositionResult,
    ExplorationAspect,
    SubtaskSpec,
)


class TestCompositionPattern:
    """Test CompositionPattern enum."""

    def test_pattern_values(self):
        """Test that all expected patterns exist."""
        assert CompositionPattern.NONE.value == "none"
        assert CompositionPattern.PLAN_EXECUTE.value == "plan_execute"
        assert CompositionPattern.PARALLEL_EXPLORE.value == "parallel_explore"
        assert CompositionPattern.SEQUENTIAL_DELEGATE.value == "sequential_delegate"

    def test_pattern_from_string(self):
        """Test creating patterns from string values."""
        assert CompositionPattern("none") == CompositionPattern.NONE
        assert CompositionPattern("plan_execute") == CompositionPattern.PLAN_EXECUTE


class TestSubtaskSpec:
    """Test SubtaskSpec dataclass."""

    def test_basic_creation(self):
        """Test creating a basic subtask spec."""
        spec = SubtaskSpec(description="Explore API patterns")

        assert spec.description == "Explore API patterns"
        assert spec.tool_filter is None
        assert spec.inherit_context is True
        assert spec.priority == 0
        assert spec.depends_on == []
        assert spec.id.startswith("subtask_")

    def test_with_tool_filter(self):
        """Test subtask spec with tool filtering."""
        spec = SubtaskSpec(
            description="Read-only exploration",
            tool_filter={"read_file", "glob_files"},
        )

        assert spec.tool_filter == {"read_file", "glob_files"}

    def test_with_dependencies(self):
        """Test subtask spec with dependencies."""
        spec = SubtaskSpec(
            description="Execute after setup",
            depends_on=["subtask_001", "subtask_002"],
        )

        assert len(spec.depends_on) == 2


class TestExplorationAspect:
    """Test ExplorationAspect dataclass."""

    def test_basic_creation(self):
        """Test creating a basic exploration aspect."""
        aspect = ExplorationAspect(
            name="api_patterns",
            description="Discover API design patterns",
        )

        assert aspect.name == "api_patterns"
        assert aspect.description == "Discover API design patterns"
        assert aspect.focus_areas == []
        # Default tool filter for read-only operations
        assert "read_file" in aspect.tool_filter
        assert "glob_files" in aspect.tool_filter

    def test_with_focus_areas(self):
        """Test exploration aspect with focus areas."""
        aspect = ExplorationAspect(
            name="auth_system",
            description="Analyze authentication",
            focus_areas=[
                "How is user authentication handled?",
                "What session management exists?",
            ],
        )

        assert len(aspect.focus_areas) == 2
        assert "authentication" in aspect.focus_areas[0]

    def test_custom_tool_filter(self):
        """Test exploration aspect with custom tool filter."""
        aspect = ExplorationAspect(
            name="code_nav",
            description="Navigate code",
            tool_filter={"code_navigator"},
        )

        assert aspect.tool_filter == {"code_navigator"}


class TestCompositionPlan:
    """Test CompositionPlan dataclass."""

    def test_direct_execution_factory(self):
        """Test creating a direct execution plan."""
        plan = CompositionPlan.direct_execution()

        assert not plan.should_compose
        assert plan.pattern == CompositionPattern.NONE
        assert plan.exploration_aspects == []
        assert plan.subtasks == []

    def test_plan_execute_factory(self):
        """Test creating a plan-execute pattern."""
        aspects = [
            ExplorationAspect(name="a1", description="Aspect 1"),
            ExplorationAspect(name="a2", description="Aspect 2"),
        ]

        plan = CompositionPlan.plan_execute(
            exploration_aspects=aspects,
            reasoning="Complex task requiring exploration",
        )

        assert plan.should_compose
        assert plan.pattern == CompositionPattern.PLAN_EXECUTE
        assert len(plan.exploration_aspects) == 2
        assert "Complex task" in plan.reasoning

    def test_parallel_explore_factory(self):
        """Test creating a parallel exploration pattern."""
        aspects = [
            ExplorationAspect(name="file_structure", description="Explore files"),
        ]

        plan = CompositionPlan.parallel_explore(
            aspects=aspects,
            reasoning="Research task",
        )

        assert plan.should_compose
        assert plan.pattern == CompositionPattern.PARALLEL_EXPLORE

    def test_full_plan_creation(self):
        """Test creating a full composition plan."""
        plan = CompositionPlan(
            should_compose=True,
            pattern=CompositionPattern.PLAN_EXECUTE,
            exploration_aspects=[
                ExplorationAspect(name="aspect1", description="First aspect"),
            ],
            subtasks=[
                SubtaskSpec(description="Subtask 1"),
                SubtaskSpec(description="Subtask 2"),
            ],
            reasoning="Testing full plan",
            metadata={"key": "value"},
        )

        assert plan.should_compose
        assert len(plan.exploration_aspects) == 1
        assert len(plan.subtasks) == 2
        assert plan.metadata["key"] == "value"


class TestCompositionResult:
    """Test CompositionResult dataclass."""

    def test_success_result(self):
        """Test creating a successful result."""
        result = CompositionResult(
            success=True,
            final_answer="Task completed successfully",
            exploration_results={"aspect1": "Found patterns"},
            step_results=[{"step": 1, "result": "done"}],
        )

        assert result.success
        assert "successfully" in result.final_answer
        assert "aspect1" in result.exploration_results
        assert len(result.step_results) == 1

    def test_failure_result(self):
        """Test creating a failure result."""
        result = CompositionResult(
            success=False,
            final_answer="",
            metadata={"error": "Max depth exceeded"},
        )

        assert not result.success
        assert result.final_answer == ""
        assert "error" in result.metadata


class TestAgentConfig:
    """Test AgentConfig dataclass."""

    def test_basic_creation(self):
        """Test creating basic agent config."""
        config = AgentConfig(
            task="Analyze codebase",
            tools=[],  # Empty for testing
            memory_node_id="node-123",
        )

        assert config.task == "Analyze codebase"
        assert config.tools == []
        assert config.memory_node_id == "node-123"
        assert config.tool_filter is None
        assert config.depth == 0

    def test_with_tool_filter(self):
        """Test config with tool filtering."""

        class MockTool:
            def __init__(self, name):
                self.name = name

        tools = [MockTool("read_file"), MockTool("write_file"), MockTool("glob_files")]

        config = AgentConfig(
            task="Read-only task",
            tools=tools,
            memory_node_id="node-456",
            tool_filter={"read_file", "glob_files"},
        )

        filtered = config.get_filtered_tools()

        assert len(filtered) == 2
        assert all(t.name in {"read_file", "glob_files"} for t in filtered)

    def test_no_filter_returns_all(self):
        """Test that no filter returns all tools."""

        class MockTool:
            def __init__(self, name):
                self.name = name

        tools = [MockTool("tool1"), MockTool("tool2")]

        config = AgentConfig(
            task="Full access task",
            tools=tools,
            memory_node_id="node-789",
        )

        filtered = config.get_filtered_tools()

        assert len(filtered) == 2

    def test_with_role_prompt(self):
        """Test config with custom role prompt."""
        config = AgentConfig(
            task="Special task",
            tools=[],
            memory_node_id="node-abc",
            role_prompt="You are a code reviewer.",
        )

        assert "code reviewer" in config.role_prompt
