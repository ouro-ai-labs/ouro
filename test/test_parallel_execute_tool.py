"""Tests for the ParallelExecutionTool."""

from unittest.mock import MagicMock

import pytest


class TestParallelExecutionTool:
    """Tests for ParallelExecutionTool functionality."""

    def test_tool_name(self):
        """Test tool name is correct."""
        from tools.parallel_execute import ParallelExecutionTool

        agent = MagicMock()
        tool = ParallelExecutionTool(agent)
        assert tool.name == "parallel_execute"

    def test_tool_description(self):
        """Test tool has description."""
        from tools.parallel_execute import ParallelExecutionTool

        agent = MagicMock()
        tool = ParallelExecutionTool(agent)
        assert "parallel" in tool.description.lower()
        assert "dependencies" in tool.description.lower()

    def test_tool_parameters(self):
        """Test tool parameter schema."""
        from tools.parallel_execute import ParallelExecutionTool

        agent = MagicMock()
        tool = ParallelExecutionTool(agent)
        params = tool.parameters

        assert "tasks" in params
        assert params["tasks"]["type"] == "array"
        assert "dependencies" in params
        assert params["dependencies"]["type"] == "object"

    def test_to_anthropic_schema(self):
        """Test Anthropic schema generation."""
        from tools.parallel_execute import ParallelExecutionTool

        agent = MagicMock()
        tool = ParallelExecutionTool(agent)
        schema = tool.to_anthropic_schema()

        assert schema["name"] == "parallel_execute"
        assert "description" in schema
        assert "input_schema" in schema
        assert schema["input_schema"]["required"] == ["tasks"]

    @pytest.mark.asyncio
    async def test_execute_empty_tasks(self):
        """Test execute with empty tasks returns error."""
        from tools.parallel_execute import ParallelExecutionTool

        agent = MagicMock()
        tool = ParallelExecutionTool(agent)

        result = await tool.execute(tasks=[])
        assert "error" in result.lower()

    def test_validate_dependencies_valid(self):
        """Test validation passes for valid dependencies."""
        from tools.parallel_execute import ParallelExecutionTool

        agent = MagicMock()
        tool = ParallelExecutionTool(agent)

        tasks = ["task 1", "task 2", "task 3"]
        dependencies = {"2": ["0", "1"]}

        result = tool._validate_dependencies(tasks, dependencies)
        assert result is None  # No error

    def test_validate_dependencies_invalid_index(self):
        """Test validation fails for invalid task index."""
        from tools.parallel_execute import ParallelExecutionTool

        agent = MagicMock()
        tool = ParallelExecutionTool(agent)

        tasks = ["task 1", "task 2"]
        dependencies = {"5": ["0"]}  # Index 5 doesn't exist

        result = tool._validate_dependencies(tasks, dependencies)
        assert result is not None
        assert "invalid" in result.lower()

    def test_validate_dependencies_invalid_dep_index(self):
        """Test validation fails for invalid dependency index."""
        from tools.parallel_execute import ParallelExecutionTool

        agent = MagicMock()
        tool = ParallelExecutionTool(agent)

        tasks = ["task 1", "task 2"]
        dependencies = {"1": ["5"]}  # Dependency 5 doesn't exist

        result = tool._validate_dependencies(tasks, dependencies)
        assert result is not None
        assert "invalid" in result.lower()

    def test_has_cycle_no_cycle(self):
        """Test cycle detection returns False for acyclic graph."""
        from tools.parallel_execute import ParallelExecutionTool

        agent = MagicMock()
        tool = ParallelExecutionTool(agent)

        # Linear dependency: 0 -> 1 -> 2
        dependencies = {"1": ["0"], "2": ["1"]}
        assert tool._has_cycle(3, dependencies) is False

    def test_has_cycle_simple_cycle(self):
        """Test cycle detection returns True for simple cycle."""
        from tools.parallel_execute import ParallelExecutionTool

        agent = MagicMock()
        tool = ParallelExecutionTool(agent)

        # Cycle: 0 -> 1 -> 0
        dependencies = {"1": ["0"], "0": ["1"]}
        assert tool._has_cycle(2, dependencies) is True

    def test_has_cycle_complex_cycle(self):
        """Test cycle detection returns True for complex cycle."""
        from tools.parallel_execute import ParallelExecutionTool

        agent = MagicMock()
        tool = ParallelExecutionTool(agent)

        # Cycle: 0 -> 1 -> 2 -> 0
        dependencies = {"1": ["0"], "2": ["1"], "0": ["2"]}
        assert tool._has_cycle(3, dependencies) is True

    @pytest.mark.asyncio
    async def test_execute_detects_cycle(self):
        """Test execute returns error for cyclic dependencies."""
        from tools.parallel_execute import ParallelExecutionTool

        agent = MagicMock()
        tool = ParallelExecutionTool(agent)

        tasks = ["task 1", "task 2"]
        dependencies = {"0": ["1"], "1": ["0"]}

        result = await tool.execute(tasks=tasks, dependencies=dependencies)
        assert "circular" in result.lower() or "cycle" in result.lower()

    def test_allowed_subtask_tools(self):
        """Test that allowed tools include explore_context but not parallel_execute."""
        from tools.parallel_execute import ALLOWED_SUBTASK_TOOLS

        # Should include explore_context (one level nesting)
        assert "explore_context" in ALLOWED_SUBTASK_TOOLS
        # Should NOT include parallel_execute (prevent recursion)
        assert "parallel_execute" not in ALLOWED_SUBTASK_TOOLS
        # Should include common tools
        assert "read_file" in ALLOWED_SUBTASK_TOOLS
        assert "write_file" in ALLOWED_SUBTASK_TOOLS
        assert "shell" in ALLOWED_SUBTASK_TOOLS

    def test_build_task_context_empty(self):
        """Test build_task_context with empty results."""
        from tools.parallel_execute import ParallelExecutionTool

        agent = MagicMock()
        tool = ParallelExecutionTool(agent)

        context = tool._build_task_context({})
        assert context == ""

    def test_build_task_context_with_results(self):
        """Test build_task_context includes previous results."""
        from tools.parallel_execute import ParallelExecutionTool

        agent = MagicMock()
        tool = ParallelExecutionTool(agent)

        previous = {0: "Result 0", 1: "Result 1"}
        context = tool._build_task_context(previous)

        assert "Task #0" in context
        assert "Task #1" in context
        assert "Result 0" in context
        assert "Result 1" in context

    def test_format_results(self):
        """Test format_results creates proper output."""
        from tools.parallel_execute import ParallelExecutionTool

        agent = MagicMock()
        tool = ParallelExecutionTool(agent)

        tasks = ["Do task A", "Do task B"]
        results = {0: "Result A", 1: "Result B"}

        formatted = tool._format_results(tasks, results)

        assert "Task 0" in formatted
        assert "Task 1" in formatted
        assert "Result A" in formatted
        assert "Result B" in formatted
        assert "Completed" in formatted

    def test_format_results_truncates_long_results(self):
        """Test format_results truncates long results."""
        from tools.parallel_execute import ParallelExecutionTool

        agent = MagicMock()
        tool = ParallelExecutionTool(agent)

        tasks = ["Task"]
        long_result = "x" * (tool.MAX_RESULT_CHARS + 1000)
        results = {0: long_result}

        formatted = tool._format_results(tasks, results)
        assert "truncated" in formatted.lower()


class TestParallelExecutionOrder:
    """Tests for dependency-aware execution ordering."""

    def test_independent_tasks_ready_immediately(self):
        """Test that tasks with no dependencies are ready immediately."""
        from tools.parallel_execute import ParallelExecutionTool

        agent = MagicMock()
        tool = ParallelExecutionTool(agent)

        # All tasks are independent
        tasks = ["task 1", "task 2", "task 3"]
        dependencies = {}

        # Validation should pass
        result = tool._validate_dependencies(tasks, dependencies)
        assert result is None

    def test_dependent_tasks_wait_for_prerequisites(self):
        """Test dependency graph is built correctly."""
        from tools.parallel_execute import ParallelExecutionTool

        agent = MagicMock()
        tool = ParallelExecutionTool(agent)

        # Task 2 depends on 0 and 1
        tasks = ["task 1", "task 2", "task 3"]
        dependencies = {"2": ["0", "1"]}

        # No cycle, validation passes
        result = tool._validate_dependencies(tasks, dependencies)
        assert result is None
        assert tool._has_cycle(3, dependencies) is False
