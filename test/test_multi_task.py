"""Tests for the MultiTaskTool."""

from unittest.mock import MagicMock

import pytest

from tools.multi_task import MultiTaskTool, TaskExecutionResult


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
        assert "max_parallel" in params
        assert params["max_parallel"]["type"] == "integer"

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

    @pytest.mark.asyncio
    async def test_execute_invalid_max_parallel(self):
        agent = MagicMock()
        tool = MultiTaskTool(agent)
        result = await tool.execute(tasks=["task"], max_parallel=0)
        assert "max_parallel" in result

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
        results = {
            0: TaskExecutionResult(status="success", output="Result A"),
            1: TaskExecutionResult(status="success", output="Result B"),
        }
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
        results = {0: TaskExecutionResult(status="success", output=long_result)}
        formatted = tool._format_results(tasks, results)
        assert "truncated" in formatted.lower()

    def test_format_results_shows_skipped_status(self):
        agent = MagicMock()
        tool = MultiTaskTool(agent)
        tasks = ["Task"]
        results = {0: TaskExecutionResult(status="skipped", output="dependency failed")}
        formatted = tool._format_results(tasks, results)
        assert "Skipped" in formatted

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
        previous = {
            0: TaskExecutionResult(status="success", output="Result 0"),
            1: TaskExecutionResult(status="success", output="Result 1"),
        }
        context = tool._build_task_context(previous)
        assert "Task #0" in context
        assert "Task #1" in context
        assert "Result 0" in context
        assert "Result 1" in context

    def test_extract_structured_sections(self):
        agent = MagicMock()
        tool = MultiTaskTool(agent)
        output = """SUMMARY: Best option found.
KEY_FINDINGS:
- price: $620
- route: SFO->NRT
ERRORS:
- none
"""
        summary, key_findings, errors = tool._extract_structured_sections(output)
        assert summary == "Best option found."
        assert "price: $620" in key_findings
        assert errors == "- none"

    def test_build_task_context_prefers_summary(self):
        agent = MagicMock()
        tool = MultiTaskTool(agent)
        noisy = "logline " * 200 + "SUMMARY: should not be used from raw"
        previous = {
            0: TaskExecutionResult(
                status="success",
                output=noisy,
                summary="cheapest fare is $620",
                key_findings="- SFO->NRT",
                errors="none",
            )
        }
        context = tool._build_task_context(previous)
        assert "cheapest fare is $620" in context
        assert "logline" not in context

    def test_build_task_context_fallback_preserves_tail_when_no_summary(self):
        agent = MagicMock()
        tool = MultiTaskTool(agent)
        output = ("A" * 700) + "TAIL-IMPORTANT"
        previous = {
            0: TaskExecutionResult(status="success", output=output),
        }
        context = tool._build_task_context(previous)
        assert "TAIL-IMPORTANT" in context
        assert "[truncated]" in context

    def test_format_results_prefers_structured_summary_when_present(self):
        agent = MagicMock()
        tool = MultiTaskTool(agent)
        tasks = ["Task"]
        results = {
            0: TaskExecutionResult(
                status="success",
                output="raw output",
                summary="summary text",
                key_findings="- finding",
                errors="none",
            )
        }
        formatted = tool._format_results(tasks, results)
        assert "SUMMARY: summary text" in formatted
        assert "KEY_FINDINGS" in formatted
        assert "raw output" not in formatted

    # ------------------------------------------------------------------
    # Execution behavior
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_execute_with_dependencies_skips_on_failed_dependency(self):
        agent = MagicMock()
        tool = MultiTaskTool(agent)

        async def fake_run_subtask(
            idx, task_desc, tools, dependency_results
        ):  # pragma: no cover - callback
            if idx == 0:
                raise RuntimeError("boom")
            return f"ok-{idx}"

        tool._run_subtask = fake_run_subtask  # type: ignore[method-assign]

        results = await tool._execute_with_dependencies(
            tasks=["t0", "t1"],
            dependencies={"1": ["0"]},
            tools=[],
            max_parallel=2,
        )

        assert results[0].status == "failed"
        assert results[1].status == "skipped"
        assert "dependency tasks failed" in results[1].output

    @pytest.mark.asyncio
    async def test_execute_with_dependencies_respects_max_parallel(self):
        agent = MagicMock()
        tool = MultiTaskTool(agent)
        batches: list[list[int]] = []

        async def fake_execute_batch(
            batch, tasks, tools, deps, previous_results
        ):  # pragma: no cover - callback
            batches.append(list(batch))
            return {idx: TaskExecutionResult(status="success", output=f"ok-{idx}") for idx in batch}

        tool._execute_batch = fake_execute_batch  # type: ignore[method-assign]

        results = await tool._execute_with_dependencies(
            tasks=["a", "b", "c"],
            dependencies={},
            tools=[],
            max_parallel=2,
        )

        assert batches == [[0, 1], [2]]
        assert all(result.status == "success" for result in results.values())

    @pytest.mark.asyncio
    async def test_execute_batch_passes_only_direct_dependency_results(self):
        agent = MagicMock()
        tool = MultiTaskTool(agent)
        captured_dependencies = {}

        async def fake_run_subtask(
            idx, task_desc, tools, dependency_results
        ):  # pragma: no cover - callback
            captured_dependencies[idx] = sorted(dependency_results.keys())
            return "done"

        tool._run_subtask = fake_run_subtask  # type: ignore[method-assign]

        await tool._execute_batch(
            batch=[2],
            tasks=["t0", "t1", "t2"],
            tools=[],
            deps={2: {0, 1}},
            previous_results={
                0: TaskExecutionResult(status="success", output="r0"),
                1: TaskExecutionResult(status="success", output="r1"),
                99: TaskExecutionResult(status="success", output="noise"),
            },
        )

        assert captured_dependencies[2] == [0, 1]

    @pytest.mark.asyncio
    async def test_long_output_tail_summary_is_used_for_dependency_context(self):
        agent = MagicMock()
        tool = MultiTaskTool(agent)
        tail_summary = "SUMMARY: cheapest fare is $620"
        output = ("verbose log line\n" * 200) + tail_summary + "\nERRORS:\n- none\n"

        success_result = tool._build_success_result(output)
        context = tool._build_task_context({0: success_result})

        assert "cheapest fare is $620" in context
        assert "verbose log line" not in context
