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
    summary: str = ""
    key_findings: str = ""
    errors: str = ""


class MultiTaskTool(BaseTool):
    """Execute multiple sub-agent tasks with optional dependency ordering.

    All sub-agents receive the full tool set (minus multi_task itself to
    prevent recursion). Tasks without dependencies run in parallel; tasks
    with dependencies wait for their prerequisites.
    """

    MAX_PARALLEL = 4
    MAX_RESULT_CHARS = 2000
    SUMMARY_MAX_CHARS = 300
    CONTEXT_FALLBACK_CHARS = 500

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
                        errors=f"dependency tasks failed ({dep_list})",
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
                errors="dependencies were not satisfied",
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
                return idx, self._build_success_result(output)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                message = f"Task failed: {str(e)}"
                return idx, TaskExecutionResult(status="failed", output=message, errors=str(e))

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
3. Final response MUST follow this exact structure:
   SUMMARY: <concise summary, max 300 chars>
   KEY_FINDINGS:
   - <finding 1>
   - <finding 2>
   ERRORS:
   - none (if no errors) OR list concrete errors
</instructions>

Execute the task now:"""

        messages = [LLMMessage(role="user", content=prompt)]

        return await self.agent._react_loop(
            messages=messages,
            tools=tools,
            use_memory=False,
            save_to_memory=False,
        )

    def _build_success_result(self, output: str) -> TaskExecutionResult:
        summary, key_findings, errors = self._extract_structured_sections(output)
        return TaskExecutionResult(
            status="success",
            output=output,
            summary=summary or "",
            key_findings=key_findings or "",
            errors=errors or "",
        )

    def _extract_structured_sections(
        self, output: str
    ) -> tuple[str | None, str | None, str | None]:
        section_aliases = {
            "summary": "SUMMARY:",
            "key_findings": "KEY_FINDINGS:",
            "errors": "ERRORS:",
        }
        sections: Dict[str, List[str]] = {name: [] for name in section_aliases}
        active_section: str | None = None

        for raw_line in output.splitlines():
            stripped = raw_line.strip()
            matched_section = None

            upper = stripped.upper()
            for section_name, prefix in section_aliases.items():
                if upper.startswith(prefix):
                    matched_section = section_name
                    active_section = section_name
                    inline = stripped[len(prefix) :].strip()
                    if inline:
                        sections[section_name].append(inline)
                    break

            if matched_section is not None:
                continue

            if active_section is not None:
                sections[active_section].append(stripped)

        def _normalize(lines: List[str]) -> str | None:
            cleaned = [line for line in lines if line.strip()]
            if not cleaned:
                return None
            return "\n".join(cleaned).strip()

        summary = _normalize(sections["summary"])
        if summary and len(summary) > self.SUMMARY_MAX_CHARS:
            summary = summary[: self.SUMMARY_MAX_CHARS] + "... [truncated]"

        key_findings = _normalize(sections["key_findings"])
        errors = _normalize(sections["errors"])
        return summary, key_findings, errors

    def _truncate_for_context_fallback(self, text: str) -> str:
        if len(text) <= self.CONTEXT_FALLBACK_CHARS:
            return text

        head = int(self.CONTEXT_FALLBACK_CHARS * 0.65)
        tail = self.CONTEXT_FALLBACK_CHARS - head
        return f"{text[:head]}... [truncated] ...{text[-tail:]}"

    def _has_meaningful_errors(self, errors: str) -> bool:
        normalized = errors.strip().lower()
        return normalized not in {"", "none", "- none", "n/a", "no errors"}

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    def _build_task_context(self, dependency_results: Dict[int, TaskExecutionResult]) -> str:
        if not dependency_results:
            return ""

        parts = ["<dependency_results>"]
        for idx, result in sorted(dependency_results.items()):
            summary = result.summary or self._truncate_for_context_fallback(result.output)
            parts.append(f"Task #{idx} SUMMARY:\n{summary}\n")

            if self._has_meaningful_errors(result.errors):
                truncated_errors = self._truncate_for_context_fallback(result.errors)
                parts.append(f"Task #{idx} ERRORS:\n{truncated_errors}\n")
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
                status = status_map.get(result.status, result.status.title())
                if result.summary:
                    sections = [f"SUMMARY: {result.summary}"]
                    if result.key_findings:
                        sections.append(f"KEY_FINDINGS:\n{result.key_findings}")
                    if self._has_meaningful_errors(result.errors):
                        sections.append(f"ERRORS:\n{result.errors}")
                    output = "\n".join(sections)
                else:
                    output = result.output
                    if len(output) > self.MAX_RESULT_CHARS:
                        output = output[: self.MAX_RESULT_CHARS] + "... [truncated]"
            else:
                output = "Not executed"
                status = "Failed"

            parts.append(f"## Task {idx}: {task_desc[:100]}\n**Status:** {status}\n{output}\n")

        return "\n".join(parts)
