"""Parallel execution tool for dependency-aware task execution."""

import asyncio
from typing import TYPE_CHECKING, Any, Dict, List, Set

from llm import LLMMessage

from .base import BaseTool

if TYPE_CHECKING:
    from agent.base import BaseAgent


# Allowed tools for subtask execution
# Note: explore_context is allowed (one level of nesting), but parallel_execute is NOT
ALLOWED_SUBTASK_TOOLS = {
    "glob_files",
    "grep_content",
    "read_file",
    "write_file",
    "edit_file",
    "smart_edit",
    "search_files",
    "code_navigator",
    "shell",
    "calculate",
    "web_search",
    "web_fetch",
    "explore_context",  # Allow one level of nesting
    # "parallel_execute" - NOT included to prevent recursion
}


class ParallelExecutionTool(BaseTool):
    """Tool for executing tasks with dependencies in parallel.

    This tool enables the main agent to execute multiple tasks concurrently
    while respecting dependency relationships between them.

    Key features:
    - Dependency-aware execution ordering
    - Parallel execution of independent tasks
    - Cycle detection to prevent deadlocks
    - One level of nesting (subtasks can use explore_context but not parallel_execute)
    """

    # Configuration
    MAX_PARALLEL_TASKS = 4
    MAX_RESULT_CHARS = 2000

    def __init__(self, agent: "BaseAgent"):
        """Initialize parallel execution tool.

        Args:
            agent: The parent agent instance that will execute tasks
        """
        self.agent = agent

    @property
    def name(self) -> str:
        return "parallel_execute"

    @property
    def description(self) -> str:
        return """Execute multiple tasks with dependencies in parallel.

Use this tool when you need to:
- Execute 3+ independent or semi-dependent tasks concurrently
- Perform operations that can be parallelized for efficiency
- Execute a structured plan with dependency relationships

DO NOT use this for:
- Simple sequential tasks (execute them directly)
- Tasks with complex interdependencies (use regular sequential execution)
- Single tasks (use regular tools directly)

Input parameters:
- tasks (required): Array of task descriptions (strings)
- dependencies (optional): Object mapping task index to array of dependency indices
  Example: {"2": ["0", "1"]} means task 2 depends on tasks 0 and 1

The tool executes tasks in batches based on dependency order.
Tasks with no unmet dependencies run in parallel."""

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
                "description": "Map of task index to array of dependency indices",
                "additionalProperties": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "default": {},
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

    async def execute(self, tasks: List[str], dependencies: Dict[str, List[str]] = None) -> str:
        """Execute tasks with dependency awareness.

        Args:
            tasks: List of task descriptions
            dependencies: Map of task index to dependency indices

        Returns:
            Combined results from all tasks
        """
        if not tasks:
            return "Error: No tasks provided"

        dependencies = dependencies or {}

        # Validate dependencies
        validation_error = self._validate_dependencies(tasks, dependencies)
        if validation_error:
            return validation_error

        # Get allowed tools for subtasks
        subtask_tools = self._get_subtask_tools()

        # Execute tasks in dependency order
        results = await self._execute_with_dependencies(tasks, dependencies, subtask_tools)

        # Format and return results
        return self._format_results(tasks, results)

    def _validate_dependencies(
        self, tasks: List[str], dependencies: Dict[str, List[str]]
    ) -> str | None:
        """Validate dependency graph for cycles and invalid references.

        Args:
            tasks: List of task descriptions
            dependencies: Dependency mapping

        Returns:
            Error message if invalid, None if valid
        """
        task_count = len(tasks)

        def validate_index(index_str: str, max_val: int) -> int | None:
            """Validate and convert string index to int. Returns None if invalid."""
            try:
                idx = int(index_str)
                return idx if 0 <= idx < max_val else None
            except ValueError:
                return None

        # Check for invalid task indices
        for task_idx, deps in dependencies.items():
            if validate_index(task_idx, task_count) is None:
                return f"Error: Invalid task index {task_idx}"

            for dep in deps:
                if validate_index(dep, task_count) is None:
                    return f"Error: Invalid dependency index {dep}"

        # Check for cycles using DFS
        if self._has_cycle(task_count, dependencies):
            return "Error: Circular dependency detected in tasks"

        return None

    def _has_cycle(self, task_count: int, dependencies: Dict[str, List[str]]) -> bool:
        """Detect cycles in dependency graph using DFS.

        Args:
            task_count: Number of tasks
            dependencies: Dependency mapping

        Returns:
            True if cycle exists
        """
        # Build adjacency list
        graph: Dict[int, List[int]] = {i: [] for i in range(task_count)}
        for task_idx, deps in dependencies.items():
            idx = int(task_idx)
            for dep in deps:
                graph[int(dep)].append(idx)

        # DFS cycle detection
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

    def _get_subtask_tools(self) -> List[Dict[str, Any]]:
        """Get filtered tools for subtask execution.

        Returns:
            List of tool schemas allowed for subtasks
        """
        all_tools = self.agent.tool_executor.get_tool_schemas()
        return [
            t
            for t in all_tools
            if t.get("name") in ALLOWED_SUBTASK_TOOLS
            or t.get("function", {}).get("name") in ALLOWED_SUBTASK_TOOLS
        ]

    async def _execute_with_dependencies(
        self,
        tasks: List[str],
        dependencies: Dict[str, List[str]],
        tools: List[Dict[str, Any]],
    ) -> Dict[int, str]:
        """Execute tasks respecting dependency order.

        Args:
            tasks: List of task descriptions
            dependencies: Dependency mapping
            tools: Available tools for subtasks

        Returns:
            Dict mapping task index to result
        """
        results: Dict[int, str] = {}
        completed: Set[int] = set()
        task_count = len(tasks)

        # Convert dependencies to int keys
        deps: Dict[int, Set[int]] = {}
        for task_idx, dep_list in dependencies.items():
            deps[int(task_idx)] = {int(d) for d in dep_list}

        while len(completed) < task_count:
            # Find tasks ready to execute (no unmet dependencies)
            ready = []
            for i in range(task_count):
                if i not in completed:
                    task_deps = deps.get(i, set())
                    if task_deps.issubset(completed):
                        ready.append(i)

            if not ready:
                # No progress possible - should not happen after cycle check
                break

            # Limit batch size
            batch = ready[: self.MAX_PARALLEL_TASKS]

            # Execute batch in parallel
            batch_results = await self._execute_batch(batch, tasks, tools, results)

            # Update results and completed set
            for idx, result in batch_results.items():
                results[idx] = result
                completed.add(idx)

        return results

    async def _execute_batch(
        self,
        batch: List[int],
        tasks: List[str],
        tools: List[Dict[str, Any]],
        previous_results: Dict[int, str],
    ) -> Dict[int, str]:
        """Execute a batch of tasks in parallel.

        Args:
            batch: List of task indices to execute
            tasks: Full task list
            tools: Available tools
            previous_results: Results from completed tasks

        Returns:
            Dict mapping task index to result
        """

        async def execute_single(idx: int) -> tuple:
            task_desc = tasks[idx]
            try:
                result = await self._execute_single_task(idx, task_desc, tools, previous_results)
                return idx, result
            except asyncio.CancelledError:
                raise
            except Exception as e:
                return idx, f"Task failed: {str(e)}"

        # Since execute_single catches all exceptions internally (except CancelledError),
        # any ExceptionGroup raised here indicates cancellation which should propagate
        results = {}
        async with asyncio.TaskGroup() as tg:
            task_list = [tg.create_task(execute_single(idx)) for idx in batch]

        for task in task_list:
            idx, result = task.result()
            results[idx] = result

        return results

    async def _execute_single_task(
        self,
        idx: int,
        task_desc: str,
        tools: List[Dict[str, Any]],
        previous_results: Dict[int, str],
    ) -> str:
        """Execute a single task using isolated mini-loop.

        Args:
            idx: Task index
            task_desc: Task description
            tools: Available tools
            previous_results: Results from completed tasks

        Returns:
            Task result string
        """
        # Build context from previous results
        context = self._build_task_context(previous_results)

        # Build task prompt
        prompt = f"""<role>
You are executing a subtask as part of a larger parallel execution.
Focus on completing this specific task efficiently.
</role>

<task>
Task #{idx}: {task_desc}
</task>

{context}

<instructions>
1. Execute the task using available tools
2. Focus ONLY on completing this specific task
3. Provide a clear summary of what was accomplished
4. Do NOT try to execute other tasks
</instructions>

Execute the task now:"""

        messages = [LLMMessage(role="user", content=prompt)]

        # Run in isolated context
        result = await self.agent._react_loop(
            messages=messages,
            tools=tools,
            use_memory=False,
            save_to_memory=False,
        )

        return result

    def _build_task_context(self, previous_results: Dict[int, str]) -> str:
        """Build context string from previous task results.

        Args:
            previous_results: Results from completed tasks

        Returns:
            Context string
        """
        if not previous_results:
            return ""

        parts = ["<previous_results>"]
        for idx, result in sorted(previous_results.items()):
            # Truncate long results
            truncated = result
            if len(result) > 500:
                truncated = result[:500] + "... [truncated]"
            parts.append(f"Task #{idx}:\n{truncated}\n")
        parts.append("</previous_results>")

        return "\n".join(parts)

    def _format_results(self, tasks: List[str], results: Dict[int, str]) -> str:
        """Format all task results into a combined summary.

        Args:
            tasks: Original task list
            results: Dict mapping task index to result

        Returns:
            Formatted combined results
        """
        parts = ["# Parallel Execution Results\n"]

        for idx, task_desc in enumerate(tasks):
            result = results.get(idx, "Not executed")

            # Truncate long results
            if len(result) > self.MAX_RESULT_CHARS:
                result = result[: self.MAX_RESULT_CHARS] + "... [truncated]"

            status = "Completed" if idx in results else "Failed"
            parts.append(f"## Task {idx}: {task_desc[:100]}\n**Status:** {status}\n{result}\n")

        return "\n".join(parts)
