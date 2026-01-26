"""Tests for the ExploreTool."""

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestExploreTool:
    """Tests for ExploreTool functionality."""

    def test_tool_name(self):
        """Test tool name is correct."""
        from tools.explore import ExploreTool

        agent = MagicMock()
        tool = ExploreTool(agent)
        assert tool.name == "explore_context"

    def test_tool_description(self):
        """Test tool has description."""
        from tools.explore import ExploreTool

        agent = MagicMock()
        tool = ExploreTool(agent)
        assert "exploration" in tool.description.lower()

    def test_tool_parameters(self):
        """Test tool parameter schema."""
        from tools.explore import ExploreTool

        agent = MagicMock()
        tool = ExploreTool(agent)
        params = tool.parameters

        assert "tasks" in params
        assert params["tasks"]["type"] == "array"

    def test_to_anthropic_schema(self):
        """Test Anthropic schema generation."""
        from tools.explore import ExploreTool

        agent = MagicMock()
        tool = ExploreTool(agent)
        schema = tool.to_anthropic_schema()

        assert schema["name"] == "explore_context"
        assert "description" in schema
        assert "input_schema" in schema
        assert schema["input_schema"]["required"] == ["tasks"]

    @pytest.mark.asyncio
    async def test_execute_empty_tasks(self):
        """Test execute with empty tasks returns error."""
        from tools.explore import ExploreTool

        agent = MagicMock()
        tool = ExploreTool(agent)

        result = await tool.execute(tasks=[])
        assert "error" in result.lower()

    @pytest.mark.asyncio
    async def test_execute_limits_parallel_explorations(self):
        """Test that execute limits number of parallel explorations."""
        from tools.explore import ExploreTool

        agent = MagicMock()
        agent.tool_executor = MagicMock()
        agent.tool_executor.get_tool_schemas.return_value = []
        agent._react_loop = AsyncMock(return_value="Test result")

        tool = ExploreTool(agent)

        # Try to run more than MAX_PARALLEL_EXPLORATIONS tasks
        tasks = [{"aspect": f"aspect_{i}", "description": f"description_{i}"} for i in range(10)]

        await tool.execute(tasks=tasks)

        # Should only have called _react_loop MAX_PARALLEL_EXPLORATIONS times
        assert agent._react_loop.call_count <= tool.MAX_PARALLEL_EXPLORATIONS

    def test_format_results_truncates_long_results(self):
        """Test that format_results truncates long results."""
        from tools.explore import ExploreTool

        agent = MagicMock()
        tool = ExploreTool(agent)

        # Create a very long result
        long_result = "x" * (tool.MAX_RESULT_CHARS + 1000)
        results = {"test_aspect": long_result}

        formatted = tool._format_results(results)

        # Should contain truncated marker
        assert "truncated" in formatted.lower()

    def test_format_results_empty(self):
        """Test format_results with empty results."""
        from tools.explore import ExploreTool

        agent = MagicMock()
        tool = ExploreTool(agent)

        result = tool._format_results({})
        assert "no exploration results" in result.lower()

    def test_exploration_tools_filter(self):
        """Test that only exploration tools are allowed."""
        from tools.explore import ExploreTool

        # Verify the allowed tools set
        assert "glob_files" in ExploreTool.EXPLORATION_TOOLS
        assert "grep_content" in ExploreTool.EXPLORATION_TOOLS
        assert "read_file" in ExploreTool.EXPLORATION_TOOLS
        assert "web_search" in ExploreTool.EXPLORATION_TOOLS
        assert "web_fetch" in ExploreTool.EXPLORATION_TOOLS
        # Should NOT include write tools
        assert "write_file" not in ExploreTool.EXPLORATION_TOOLS
        assert "edit_file" not in ExploreTool.EXPLORATION_TOOLS


class TestExplorerPrompt:
    """Tests for the exploration prompt."""

    def test_prompt_contains_placeholders(self):
        """Test that prompt contains required placeholders."""
        from tools.explore import GENERAL_EXPLORER_PROMPT

        assert "{aspect}" in GENERAL_EXPLORER_PROMPT
        assert "{description}" in GENERAL_EXPLORER_PROMPT

    def test_prompt_mentions_read_only(self):
        """Test that prompt mentions read-only nature."""
        from tools.explore import GENERAL_EXPLORER_PROMPT

        # Should mention not making changes
        assert "not" in GENERAL_EXPLORER_PROMPT.lower() or "no" in GENERAL_EXPLORER_PROMPT.lower()
        assert "change" in GENERAL_EXPLORER_PROMPT.lower()
