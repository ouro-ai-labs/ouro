"""Unified multi-task tool for parallel sub-agent execution."""

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Set

from llm import LLMMessage

from .base import BaseTool

if TYPE_CHECKING:
    from agent.base import BaseAgent


@dataclass
class TaskExecutionResult:
    """Structured result for a single subtask."""

    status: str
    output: str


class MultiTaskTool(BaseTool):
    """Execute multiple sub-agent tasks with optional dependency ordering.

    All sub-agents receive the full tool set (minus multi_task itself to
    prevent recursion). Tasks without dependencies run in parallel; tasks
    with dependencies wait for their prerequisites.
    """

    MAX_PARALLEL = 4
    MAX_RESULT_CHARS = 2000

    def __init__(self, agent: "BaseAgent"):
        self.agent = agent

    @property
    def name(self) -> str:
        return "multi_task"

    @property
    def description(self) -> str:
        return """Execute multiple tasks in parallel using sub-agents.

Use this tool when you need to:
- Run 2+ independent or semi-dependent tasks concurrently
- Gather context from multiple sources in parallel
- Execute a structured plan with dependency relationships

Input parameters:
- tasks (required): Array of task description strings
- dependencies (optional): Object mapping task index to array of prerequisite indices
  Example: {"2": ["0", "1"]} means task 2 waits for tasks 0 and 1
- max_parallel (optional): Maximum concurrent subtasks (default: 4)"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "tasks": {
                "type": "array",
                "description": "List of task descriptions to execute",
                "items": {"type": "string"},
            },
            "dependencies": {
                "type": "object",
                "description": "Map of task index to array of prerequisite indices",
                "additionalProperties": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "default": {},
            },
            "max_parallel": {
                "type": "integer",
                "description": "Maximum number of subtasks to run concurrently (default: 4)",
                "minimum": 1,
                "default": self.MAX_PARALLEL,
            },
        }

    def to_anthropic_schema(self) -> Dict[str, Any]:
        """Convert to Anthropic tool schema format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": self.parameters,
                "required": ["tasks"],
            },
        }

    async def execute(
        self,
        tasks: List[str],
        dependencies: Dict[str, List[str]] = None,
        max_parallel: int | None = None,
    ) -> str:
        if not tasks:
            return "Error: No tasks provided"

        dependencies = dependencies or {}

        parallel_limit = self._resolve_parallel_limit(max_parallel)
        if parallel_limit is None:
            return "Error: max_parallel must be a positive integer"

        validation_error = self._validate_dependencies(tasks, dependencies)
        if validation_error:
            return validation_error

        subtask_tools = self._get_subtask_tools()
        results = await self._execute_with_dependencies(
            tasks, dependencies, subtask_tools, max_parallel=parallel_limit
        )
        return self._format_results(tasks, results)

    # ------------------------------------------------------------------
    # Dependency validation
    # ------------------------------------------------------------------

    def _validate_dependencies(
        self, tasks: List[str], dependencies: Dict[str, List[str]]
    ) -> str | None:
        task_count = len(tasks)

        def _valid_index(s: str) -> int | None:
            try:
                idx = int(s)
                return idx if 0 <= idx < task_count else None
            except ValueError:
                return None

        for task_idx, deps in dependencies.items():
            if _valid_index(task_idx) is None:
                return f"Error: Invalid task index {task_idx}"
            for dep in deps:
                if _valid_index(dep) is None:
                    return f"Error: Invalid dependency index {dep}"

        if self._has_cycle(task_count, dependencies):
            return "Error: Circular dependency detected in tasks"

        return None

    def _has_cycle(self, task_count: int, dependencies: Dict[str, List[str]]) -> bool:
        graph: Dict[int, List[int]] = {i: [] for i in range(task_count)}
        for task_idx, deps in dependencies.items():
            idx = int(task_idx)
            for dep in deps:
                graph[int(dep)].append(idx)

        WHITE, GRAY, BLACK = 0, 1, 2
        colors = [WHITE] * task_count

        def dfs(node: int) -> bool:
            colors[node] = GRAY
            for neighbor in graph[node]:
                if colors[neighbor] == GRAY:
                    return True
                if colors[neighbor] == WHITE and dfs(neighbor):
                    return True
            colors[node] = BLACK
            return False

        return any(colors[i] == WHITE and dfs(i) for i in range(task_count))

    # ------------------------------------------------------------------
    # Tool filtering
    # ------------------------------------------------------------------

    def _get_subtask_tools(self) -> List[Dict[str, Any]]:
        all_tools = self.agent.tool_executor.get_tool_schemas()
        return [
            t
            for t in all_tools
            if (t.get("name") or t.get("function", {}).get("name")) != self.name
        ]

    def _resolve_parallel_limit(self, max_parallel: int | None) -> int | None:
        if max_parallel is None:
            return self.MAX_PARALLEL
        try:
            value = int(max_parallel)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def _execute_with_dependencies(
        self,
        tasks: List[str],
        dependencies: Dict[str, List[str]],
        tools: List[Dict[str, Any]],
        max_parallel: int,
    ) -> Dict[int, TaskExecutionResult]:
        results: Dict[int, TaskExecutionResult] = {}
        successful: Set[int] = set()
        task_count = len(tasks)
        pending: Set[int] = set(range(task_count))

        deps: Dict[int, Set[int]] = {}
        for task_idx, dep_list in dependencies.items():
            deps[int(task_idx)] = {int(d) for d in dep_list}

        while pending:
            blocked: List[int] = []
            for idx in sorted(pending):
                failed_deps = [
                    dep
                    for dep in sorted(deps.get(idx, set()))
                    if dep in results and results[dep].status != "success"
                ]
                if failed_deps:
                    dep_list = ", ".join(str(dep) for dep in failed_deps)
                    results[idx] = TaskExecutionResult(
                        status="skipped",
                        output=f"Skipped: dependency tasks failed ({dep_list}).",
                    )
                    blocked.append(idx)

            for idx in blocked:
                pending.discard(idx)

            ready = [
                i
                for i in range(task_count)
                if i in pending and deps.get(i, set()).issubset(successful)
            ]
            if not ready:
                break

            batch = ready[:max_parallel]
            batch_results = await self._execute_batch(batch, tasks, tools, deps, results)

            for idx, result in batch_results.items():
                results[idx] = result
                pending.discard(idx)
                if result.status == "success":
                    successful.add(idx)

        # Defensive fallback: mark any leftover tasks as skipped.
        for idx in sorted(pending):
            results[idx] = TaskExecutionResult(
                status="skipped",
                output="Skipped: dependencies were not satisfied.",
            )

        return results

    async def _execute_batch(
        self,
        batch: List[int],
        tasks: List[str],
        tools: List[Dict[str, Any]],
        deps: Dict[int, Set[int]],
        previous_results: Dict[int, TaskExecutionResult],
    ) -> Dict[int, TaskExecutionResult]:
        async def run_single(idx: int) -> tuple:
            try:
                dependency_results = {
                    dep: previous_results[dep]
                    for dep in sorted(deps.get(idx, set()))
                    if dep in previous_results
                }
                output = await self._run_subtask(idx, tasks[idx], tools, dependency_results)
                return idx, TaskExecutionResult(status="success", output=output)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                return idx, TaskExecutionResult(status="failed", output=f"Task failed: {str(e)}")

        results = {}
        async with asyncio.TaskGroup() as tg:
            task_list = [tg.create_task(run_single(idx)) for idx in batch]

        for task in task_list:
            idx, result = task.result()
            results[idx] = result

        return results

    async def _run_subtask(
        self,
        idx: int,
        task_desc: str,
        tools: List[Dict[str, Any]],
        dependency_results: Dict[int, TaskExecutionResult],
    ) -> str:
        context = self._build_task_context(dependency_results)

        prompt = f"""<role>
You are a sub-agent executing one task in a parallel plan.
Complete this task using the tools available to you.
</role>

<task>
Task #{idx}: {task_desc}
</task>

{context}

<instructions>
1. Use available tools to accomplish the task
2. Focus ONLY on this specific task
3. Provide a clear summary of what was accomplished
</instructions>

Execute the task now:"""

        messages = [LLMMessage(role="user", content=prompt)]

        return await self.agent._react_loop(
            messages=messages,
            tools=tools,
            use_memory=False,
            save_to_memory=False,
        )

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    def _build_task_context(self, dependency_results: Dict[int, TaskExecutionResult]) -> str:
        if not dependency_results:
            return ""

        parts = ["<dependency_results>"]
        for idx, result in sorted(dependency_results.items()):
            truncated = (
                result.output
                if len(result.output) <= 500
                else result.output[:500] + "... [truncated]"
            )
            parts.append(f"Task #{idx}:\n{truncated}\n")
        parts.append("</dependency_results>")
        return "\n".join(parts)

    def _format_results(self, tasks: List[str], results: Dict[int, TaskExecutionResult]) -> str:
        if not results:
            return "No task results."

        status_map = {
            "success": "Completed",
            "failed": "Failed",
            "skipped": "Skipped",
        }

        parts = ["# Multi-Task Results\n"]
        for idx, task_desc in enumerate(tasks):
            result = results.get(idx)
            if result:
                output = result.output
                if len(output) > self.MAX_RESULT_CHARS:
                    output = output[: self.MAX_RESULT_CHARS] + "... [truncated]"
                status = status_map.get(result.status, result.status.title())
            else:
                output = "Not executed"
                status = "Failed"

            parts.append(f"## Task {idx}: {task_desc[:100]}\n**Status:** {status}\n{output}\n")

        return "\n".join(parts)
