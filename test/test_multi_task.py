"""Tests for the MultiTaskTool."""

from unittest.mock import MagicMock

import pytest

from tools.multi_task import MultiTaskTool


class TestMultiTaskTool:
    """Tests for MultiTaskTool functionality."""

    def test_tool_name(self):
        agent = MagicMock()
        tool = MultiTaskTool(agent)
        assert tool.name == "multi_task"

    def test_tool_description(self):
        agent = MagicMock()
        tool = MultiTaskTool(agent)
        assert "parallel" in tool.description.lower()

    def test_tool_parameters(self):
        agent = MagicMock()
        tool = MultiTaskTool(agent)
        params = tool.parameters
        assert "tasks" in params
        assert params["tasks"]["type"] == "array"
        assert "dependencies" in params
        assert params["dependencies"]["type"] == "object"

    def test_to_anthropic_schema(self):
        agent = MagicMock()
        tool = MultiTaskTool(agent)
        schema = tool.to_anthropic_schema()
        assert schema["name"] == "multi_task"
        assert "description" in schema
        assert "input_schema" in schema
        assert schema["input_schema"]["required"] == ["tasks"]

    @pytest.mark.asyncio
    async def test_execute_empty_tasks(self):
        agent = MagicMock()
        tool = MultiTaskTool(agent)
        result = await tool.execute(tasks=[])
        assert "error" in result.lower()

    # ------------------------------------------------------------------
    # Dependency validation
    # ------------------------------------------------------------------

    def test_validate_dependencies_valid(self):
        agent = MagicMock()
        tool = MultiTaskTool(agent)
        tasks = ["task 1", "task 2", "task 3"]
        dependencies = {"2": ["0", "1"]}
        assert tool._validate_dependencies(tasks, dependencies) is None

    def test_validate_dependencies_invalid_task_index(self):
        agent = MagicMock()
        tool = MultiTaskTool(agent)
        tasks = ["task 1", "task 2"]
        dependencies = {"5": ["0"]}
        result = tool._validate_dependencies(tasks, dependencies)
        assert result is not None
        assert "invalid" in result.lower()

    def test_validate_dependencies_invalid_dep_index(self):
        agent = MagicMock()
        tool = MultiTaskTool(agent)
        tasks = ["task 1", "task 2"]
        dependencies = {"1": ["5"]}
        result = tool._validate_dependencies(tasks, dependencies)
        assert result is not None
        assert "invalid" in result.lower()

    # ------------------------------------------------------------------
    # Cycle detection
    # ------------------------------------------------------------------

    def test_has_cycle_no_cycle(self):
        agent = MagicMock()
        tool = MultiTaskTool(agent)
        dependencies = {"1": ["0"], "2": ["1"]}
        assert tool._has_cycle(3, dependencies) is False

    def test_has_cycle_simple_cycle(self):
        agent = MagicMock()
        tool = MultiTaskTool(agent)
        dependencies = {"1": ["0"], "0": ["1"]}
        assert tool._has_cycle(2, dependencies) is True

    def test_has_cycle_complex_cycle(self):
        agent = MagicMock()
        tool = MultiTaskTool(agent)
        dependencies = {"1": ["0"], "2": ["1"], "0": ["2"]}
        assert tool._has_cycle(3, dependencies) is True

    @pytest.mark.asyncio
    async def test_execute_detects_cycle(self):
        agent = MagicMock()
        tool = MultiTaskTool(agent)
        tasks = ["task 1", "task 2"]
        dependencies = {"0": ["1"], "1": ["0"]}
        result = await tool.execute(tasks=tasks, dependencies=dependencies)
        assert "circular" in result.lower() or "cycle" in result.lower()

    # ------------------------------------------------------------------
    # Result formatting
    # ------------------------------------------------------------------

    def test_format_results(self):
        agent = MagicMock()
        tool = MultiTaskTool(agent)
        tasks = ["Do task A", "Do task B"]
        results = {0: "Result A", 1: "Result B"}
        formatted = tool._format_results(tasks, results)
        assert "Task 0" in formatted
        assert "Task 1" in formatted
        assert "Result A" in formatted
        assert "Result B" in formatted
        assert "Completed" in formatted

    def test_format_results_truncates_long_results(self):
        agent = MagicMock()
        tool = MultiTaskTool(agent)
        tasks = ["Task"]
        long_result = "x" * (tool.MAX_RESULT_CHARS + 1000)
        results = {0: long_result}
        formatted = tool._format_results(tasks, results)
        assert "truncated" in formatted.lower()

    def test_format_results_empty(self):
        agent = MagicMock()
        tool = MultiTaskTool(agent)
        result = tool._format_results(["task"], {})
        assert "no task results" in result.lower()

    # ------------------------------------------------------------------
    # Tool filtering
    # ------------------------------------------------------------------

    def test_get_subtask_tools_excludes_multi_task(self):
        agent = MagicMock()
        agent.tool_executor = MagicMock()
        agent.tool_executor.get_tool_schemas.return_value = [
            {"name": "read_file"},
            {"name": "multi_task"},
            {"name": "shell"},
        ]
        tool = MultiTaskTool(agent)
        subtask_tools = tool._get_subtask_tools()
        names = [t["name"] for t in subtask_tools]
        assert "multi_task" not in names
        assert "read_file" in names
        assert "shell" in names

    # ------------------------------------------------------------------
    # Context building
    # ------------------------------------------------------------------

    def test_build_task_context_empty(self):
        agent = MagicMock()
        tool = MultiTaskTool(agent)
        assert tool._build_task_context({}) == ""

    def test_build_task_context_with_results(self):
        agent = MagicMock()
        tool = MultiTaskTool(agent)
        previous = {0: "Result 0", 1: "Result 1"}
        context = tool._build_task_context(previous)
        assert "Task #0" in context
        assert "Task #1" in context
        assert "Result 0" in context
        assert "Result 1" in context
