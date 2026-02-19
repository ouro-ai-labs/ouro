"""Unified multi-task tool for parallel sub-agent execution."""

import asyncio
import os
import shutil
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
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
    artifact_path: str = "UNAVAILABLE"
    fetch_hint: str = "NONE"
    template_conformant: bool = False
    non_conformant_context: str = ""


class MultiTaskTool(BaseTool):
    """Execute multiple sub-agent tasks with optional dependency ordering.

    All sub-agents receive the full tool set (minus multi_task itself to
    prevent recursion). Tasks without dependencies run in parallel; tasks
    with dependencies wait for their prerequisites.
    """

    MAX_PARALLEL = 4
    MAX_RESULT_CHARS = 2000
    NON_CONFORMANT_PREVIEW_CHARS = 500

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
        artifact_root = self._prepare_artifact_run_dir()
        results = await self._execute_with_dependencies(
            tasks,
            dependencies,
            subtask_tools,
            artifact_root=artifact_root,
            max_parallel=parallel_limit,
        )
        dag_path = self._write_dag_visualization(tasks, dependencies, results, artifact_root)

        if not self._should_keep_artifacts():
            self._cleanup_artifact_run_dir(artifact_root)
            self._mark_artifacts_cleaned(results)
            if dag_path != "UNAVAILABLE":
                dag_path = "CLEANED"

        return self._format_results(tasks, results, dag_path=dag_path)

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
        artifact_root: Path | None,
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
            batch_results = await self._execute_batch(
                batch,
                tasks,
                tools,
                deps,
                results,
                artifact_root=artifact_root,
            )

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
        artifact_root: Path | None,
    ) -> Dict[int, TaskExecutionResult]:
        async def run_single(idx: int) -> tuple:
            try:
                dependency_results = {
                    dep: previous_results[dep]
                    for dep in sorted(deps.get(idx, set()))
                    if dep in previous_results
                }
                output = await self._run_subtask(idx, tasks[idx], tools, dependency_results)
                return idx, self._build_success_result(
                    idx=idx,
                    task_desc=tasks[idx],
                    output=output,
                    artifact_root=artifact_root,
                )
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

    def _build_success_result(
        self,
        idx: int,
        task_desc: str,
        output: str,
        artifact_root: Path | None,
    ) -> TaskExecutionResult:
        summary, key_findings, errors = self._extract_structured_sections(output)
        template_conformant = all([summary, key_findings, errors])
        fetch_hint = "NONE" if template_conformant else "REQUIRED"
        non_conformant_context = (
            ""
            if template_conformant
            else self._build_non_conformant_context(output)
        )
        artifact_path = self._write_task_artifact(
            artifact_root=artifact_root,
            idx=idx,
            task_desc=task_desc,
            output=output,
            summary=summary or "",
            key_findings=key_findings or "",
            errors=errors or "",
        )

        return TaskExecutionResult(
            status="success",
            output=output,
            summary=summary or "",
            key_findings=key_findings or "",
            errors=errors or "",
            artifact_path=artifact_path,
            fetch_hint=fetch_hint,
            template_conformant=template_conformant,
            non_conformant_context=non_conformant_context,
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
        key_findings = _normalize(sections["key_findings"])
        errors = _normalize(sections["errors"])
        return summary, key_findings, errors

    def _build_non_conformant_context(self, text: str) -> str:
        trimmed = text.strip()
        if not trimmed:
            return "(empty output)"
        if len(trimmed) <= self.NON_CONFORMANT_PREVIEW_CHARS:
            return trimmed
        return trimmed[: self.NON_CONFORMANT_PREVIEW_CHARS] + "... [truncated preview]"

    def _has_meaningful_errors(self, errors: str) -> bool:
        normalized = errors.strip().lower()
        return normalized not in {"", "none", "- none", "n/a", "no errors"}

    def _prepare_artifact_run_dir(self) -> Path | None:
        run_id = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        run_dir = Path.cwd() / ".ouro_artifacts" / run_id
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None
        return run_dir

    def _write_task_artifact(
        self,
        artifact_root: Path | None,
        idx: int,
        task_desc: str,
        output: str,
        summary: str,
        key_findings: str,
        errors: str,
    ) -> str:
        if artifact_root is None:
            return "UNAVAILABLE"

        artifact_path = artifact_root / f"task_{idx}.md"
        content = "\n".join(
            [
                "# Task Artifact",
                "",
                f"task_idx: {idx}",
                f"task_desc: {task_desc}",
                "",
                "## SUMMARY",
                summary or "(missing)",
                "",
                "## KEY_FINDINGS",
                key_findings or "(missing)",
                "",
                "## ERRORS",
                errors or "(missing)",
                "",
                "## RAW_OUTPUT",
                output,
            ]
        )
        try:
            artifact_path.write_text(content, encoding="utf-8")
        except OSError:
            return "UNAVAILABLE"
        return str(artifact_path)

    def _read_artifact_content(self, artifact_path: str) -> str | None:
        if not artifact_path or artifact_path == "UNAVAILABLE":
            return None

        try:
            return Path(artifact_path).read_text(encoding="utf-8")
        except OSError:
            return None

    def _should_keep_artifacts(self) -> bool:
        keep_flag = os.getenv("OURO_KEEP_MULTITASK_ARTIFACTS")
        if keep_flag is not None:
            return keep_flag.strip().lower() in {"1", "true", "yes", "on"}

        verbose_flag = os.getenv("OURO_VERBOSE", "0")
        return verbose_flag.strip().lower() in {"1", "true", "yes", "on"}

    def _cleanup_artifact_run_dir(self, artifact_root: Path | None) -> None:
        if artifact_root is None:
            return
        try:
            shutil.rmtree(artifact_root)
        except OSError:
            return

    def _mark_artifacts_cleaned(self, results: Dict[int, TaskExecutionResult]) -> None:
        for result in results.values():
            if result.artifact_path and result.artifact_path != "UNAVAILABLE":
                result.artifact_path = "CLEANED"

    def _sanitize_mermaid_label(self, value: str) -> str:
        text = value.replace("\n", " ").replace('"', "'").strip()
        text = text.replace("[", "(").replace("]", ")")
        return text if text else "(empty task)"

    def _write_dag_visualization(
        self,
        tasks: List[str],
        dependencies: Dict[str, List[str]],
        results: Dict[int, TaskExecutionResult],
        artifact_root: Path | None,
    ) -> str:
        if artifact_root is None:
            return "UNAVAILABLE"

        dag_path = artifact_root / "dag.mmd"
        lines = ["flowchart TD"]

        for idx, task in enumerate(tasks):
            result = results.get(idx)
            status = result.status if result else "not_executed"
            fetch_hint = result.fetch_hint if result else "NONE"
            template_conformant = (
                "true" if result and result.template_conformant else "false"
            )
            task_label = self._sanitize_mermaid_label(task)[:80]
            lines.append(
                f'    T{idx}["#{idx} {task_label}<br/>status={status}<br/>fetch={fetch_hint}<br/>conformant={template_conformant}"]'
            )

        for task_idx in sorted(dependencies.keys(), key=int):
            for dep_idx in sorted(dependencies[task_idx], key=int):
                lines.append(f"    T{int(dep_idx)} --> T{int(task_idx)}")

        try:
            dag_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError:
            return "UNAVAILABLE"
        return str(dag_path)

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    def _build_task_context(self, dependency_results: Dict[int, TaskExecutionResult]) -> str:
        if not dependency_results:
            return ""

        parts = ["<dependency_results>"]
        for idx, result in sorted(dependency_results.items()):
            parts.append(
                f"Task #{idx} TEMPLATE_CONFORMANT: "
                f"{'true' if result.template_conformant else 'false'}"
            )
            parts.append(f"Task #{idx} FETCH_HINT: {result.fetch_hint}")

            if result.template_conformant:
                summary = result.summary.strip() or "(empty summary)"
                parts.append(f"Task #{idx} SUMMARY:\n{summary}\n")
            else:
                preview = result.non_conformant_context or self._build_non_conformant_context(
                    result.output
                )
                parts.append(f"Task #{idx} NON_CONFORMANT_CONTEXT:\n{preview}\n")

            artifact_path = result.artifact_path or "UNAVAILABLE"
            fetched_artifact = None
            if result.fetch_hint == "REQUIRED":
                fetched_artifact = self._read_artifact_content(artifact_path)
                if fetched_artifact is None:
                    artifact_path = "UNAVAILABLE"

            parts.append(f"Task #{idx} ARTIFACT_PATH: {artifact_path}")

            if result.fetch_hint == "REQUIRED":
                if fetched_artifact is None:
                    parts.append(f"Task #{idx} FETCHED_ARTIFACT: UNAVAILABLE")
                else:
                    parts.append(f"Task #{idx} FETCHED_ARTIFACT:\n{fetched_artifact}\n")

            if self._has_meaningful_errors(result.errors):
                parts.append(f"Task #{idx} ERRORS:\n{result.errors}\n")
        parts.append("</dependency_results>")
        return "\n".join(parts)

    def _format_results(
        self,
        tasks: List[str],
        results: Dict[int, TaskExecutionResult],
        dag_path: str = "UNAVAILABLE",
    ) -> str:
        if not results:
            return "No task results."

        status_map = {
            "success": "Completed",
            "failed": "Failed",
            "skipped": "Skipped",
        }

        parts = ["# Multi-Task Results\n"]
        if dag_path:
            parts.append(f"DAG_PATH: {dag_path}\n")
        for idx, task_desc in enumerate(tasks):
            result = results.get(idx)
            if result:
                status = status_map.get(result.status, result.status.title())
                if result.template_conformant and result.summary:
                    sections = [f"SUMMARY: {result.summary}"]
                    if result.key_findings:
                        sections.append(f"KEY_FINDINGS:\n{result.key_findings}")
                    if self._has_meaningful_errors(result.errors):
                        sections.append(f"ERRORS:\n{result.errors}")
                else:
                    preview = result.non_conformant_context or self._build_non_conformant_context(
                        result.output
                    )
                    sections = [f"NON_CONFORMANT_CONTEXT:\n{preview}"]
                    if result.key_findings:
                        sections.append(f"KEY_FINDINGS:\n{result.key_findings}")
                    if self._has_meaningful_errors(result.errors):
                        sections.append(f"ERRORS:\n{result.errors}")

                if result.status == "success":
                    sections.append(
                        "TEMPLATE_CONFORMANT: "
                        + ("true" if result.template_conformant else "false")
                    )
                    sections.append(f"FETCH_HINT: {result.fetch_hint}")
                    sections.append(
                        f"ARTIFACT_PATH: {result.artifact_path or 'UNAVAILABLE'}"
                    )

                output = "\n".join(sections)
                if len(output) > self.MAX_RESULT_CHARS:
                    output = output[: self.MAX_RESULT_CHARS] + "... [truncated]"
            else:
                output = "Not executed"
                status = "Failed"

            parts.append(f"## Task {idx}: {task_desc[:100]}\n**Status:** {status}\n{output}\n")

        return "\n".join(parts)
