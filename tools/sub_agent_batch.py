"""Parallel sub-agent execution for Tasks-based orchestration.

This tool is intentionally minimal: it runs multiple fresh ReAct loops (sub-agents)
concurrently, each focused on a single TaskStore task ID. Sub-agents are expected
to return work output; the main agent is responsible for writing results back to
the Task graph (e.g. via TaskUpdate).
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from llm import LLMMessage

from .base import BaseTool

if TYPE_CHECKING:
    from agent.base import BaseAgent


def _json(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "... [truncated]"


class SubAgentBatchTool(BaseTool):
    """Run multiple sub-agents in parallel for task IDs."""

    MAX_PARALLEL_CAP = 8
    MAX_OUTPUT_CHARS = 4000
    MAX_CONTEXT_CHARS = 1500
    MAX_UPSTREAM_DETAIL_CHARS = 600
    MAX_CONVERSATION_MESSAGES = 6

    def __init__(self, agent: BaseAgent):
        self.agent = agent

    @property
    def name(self) -> str:
        return "sub_agent_batch"

    @property
    def description(self) -> str:
        return (
            "Run multiple sub-agents in parallel, each responsible for one Task ID. "
            "Each sub-agent is a fresh ReAct loop (no memory) and should focus on producing a useful result. "
            "By default, sub-agents do NOT update task status/content; the main agent should apply results with TaskUpdate."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "runs": {
                "type": "array",
                "description": "Sub-agent runs to execute in parallel",
                "items": {
                    "type": "object",
                    "properties": {
                        "taskId": {"type": "string", "description": "Task ID to execute"},
                        "notes": {
                            "type": "string",
                            "description": "Optional additional constraints for this run",
                            "default": "",
                        },
                    },
                    "required": ["taskId"],
                },
            },
            "maxParallel": {
                "type": "integer",
                "description": (
                    f"Max concurrent sub-agents (default: 4, cap: {self.MAX_PARALLEL_CAP})"
                ),
                "default": 4,
            },
        }

    def to_anthropic_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": self.parameters,
                "required": ["runs"],
            },
        }

    def _get_subagent_tools(self) -> list[dict[str, Any]]:
        all_tools = self.agent.tool_executor.get_tool_schemas()

        def _tool_name(schema: dict[str, Any]) -> str | None:
            return schema.get("name") or schema.get("function", {}).get("name")

        excluded = {
            self.name,
            "multi_task",
            # Disallow sub-agents from mutating / querying the task graph directly.
            "TaskCreate",
            "TaskUpdate",
            "TaskList",
            "TaskGet",
            "TaskFanout",
            "TaskDumpMd",
        }
        return [t for t in all_tools if (_tool_name(t) not in excluded)]

    def _extract_simplified_conversation_context(self) -> str:
        """Extract a simplified conversational context (no tool-call traces/results).

        This intentionally excludes tool messages and only includes recent user/assistant text.
        """
        memory = getattr(self.agent, "memory", None)
        short_term = getattr(memory, "short_term", None)
        get_messages = getattr(short_term, "get_messages", None)
        if get_messages is None:
            return ""

        try:
            messages = list(get_messages())
        except Exception:
            return ""

        simplified: list[str] = []
        for msg in reversed(messages):
            role = getattr(msg, "role", None)
            if role not in {"user", "assistant"}:
                continue
            content = getattr(msg, "content", None)
            if isinstance(content, str) and content.strip():
                simplified.append(f"{role}: {content.strip()}")
            if len(simplified) >= self.MAX_CONVERSATION_MESSAGES:
                break

        simplified.reverse()
        return _truncate("\n".join(simplified).strip(), self.MAX_CONTEXT_CHARS)

    async def _collect_direct_upstream_outputs(self, task_id: str) -> str:
        """Collect direct upstream (blockedBy) task outputs to reduce ambiguity.

        Only includes completed upstream tasks, prioritizing their detail (output).
        """
        raw = await self.agent.tool_executor.execute_tool_call("TaskGet", {"id": task_id})
        try:
            data = json.loads(raw)
            task = data.get("task") or {}
        except Exception:
            return ""

        deps = [str(x) for x in (task.get("blockedBy") or []) if str(x).strip()]
        if not deps:
            return ""

        items: list[str] = []
        for dep_id in deps:
            raw_dep = await self.agent.tool_executor.execute_tool_call("TaskGet", {"id": dep_id})
            try:
                dep_data = json.loads(raw_dep)
                dep_task = dep_data.get("task") or {}
            except Exception:
                continue

            status = str(dep_task.get("status", "") or "").strip()
            if status != "completed":
                continue

            content = str(dep_task.get("content", "") or "").strip() or f"(task {dep_id})"
            detail = str(dep_task.get("detail", "") or "").strip()
            if not detail:
                continue

            detail = _truncate(detail, self.MAX_UPSTREAM_DETAIL_CHARS)
            items.append(f"- [{dep_id}] {content}\n  {detail.replace('\\n', '\\n  ')}")

        if not items:
            return ""
        return _truncate("\n".join(items).strip(), self.MAX_CONTEXT_CHARS)

    async def _build_shared_context(self, task_id: str) -> str:
        simplified = self._extract_simplified_conversation_context()
        upstream = await self._collect_direct_upstream_outputs(task_id)

        if not simplified and not upstream:
            return ""

        parts: list[str] = []
        if simplified:
            parts.append("<conversation>\n" + simplified + "\n</conversation>")
        if upstream:
            parts.append("<upstream_outputs>\n" + upstream + "\n</upstream_outputs>")
        return _truncate("\n\n".join(parts).strip(), self.MAX_CONTEXT_CHARS)

    def _build_worker_prompt(
        self, *, task_id: str, task_content: str, notes: str, context: str
    ) -> str:
        extra = notes.strip()
        notes_block = f"\n\n<constraints>\n{extra}\n</constraints>\n" if extra else ""
        context_block = f"\n\n<shared_context>\n{context}\n</shared_context>\n" if context else ""

        return f"""<role>
You are a sub-agent executing exactly one task from a shared task graph.
You must focus ONLY on this task and return a concise, high-signal output.
</role>

<task_id>{task_id}</task_id>
<task>
{task_content.strip()}
</task>
{context_block}
{notes_block}
<contract>
1. Execute:
   - Do only the work needed for this task.
   - Avoid unrelated edits and avoid creating scratch artifacts unless necessary.
2. Output:
   - Return a short result that the main agent can paste into TaskUpdate(content=...).
   - Include: (a) key claims (b) supporting evidence/links (c) any caveats.
   - Keep it concise; prefer bullets; no long essays.
</contract>

Execute now."""

    async def execute(
        self,
        runs: list[dict[str, Any]],
        maxParallel: int = 4,
        **kwargs,
    ) -> str:
        if not runs:
            return _json({"ok": False, "error": "runs must be a non-empty array"})

        try:
            max_parallel = int(maxParallel)
        except (TypeError, ValueError):
            max_parallel = 4
        max_parallel = max(1, min(max_parallel, self.MAX_PARALLEL_CAP))

        normalized: list[dict[str, str]] = []
        seen: set[str] = set()
        for r in runs:
            task_id = str(r.get("taskId", "")).strip()
            if not task_id:
                return _json({"ok": False, "error": "Each run must include a non-empty taskId"})
            if task_id in seen:
                return _json({"ok": False, "error": f"Duplicate taskId in runs: {task_id}"})
            seen.add(task_id)
            normalized.append({"taskId": task_id, "notes": str(r.get("notes", "") or "")})

        tools = self._get_subagent_tools()
        semaphore = asyncio.Semaphore(max_parallel)
        results: list[dict[str, Any]]

        async def _get_task_content(task_id: str) -> str:
            # Fetch task content deterministically so sub-agents don't need TaskGet/TaskList tools.
            raw = await self.agent.tool_executor.execute_tool_call("TaskGet", {"id": task_id})
            try:
                data = json.loads(raw)
                task = data.get("task") or {}
                content = str(task.get("content", "") or "").strip()
                if content:
                    return content
            except Exception:
                pass
            return f"(task {task_id})"

        async def _run_one(task_id: str, notes: str) -> dict[str, Any]:
            task_content = await _get_task_content(task_id)
            context = await self._build_shared_context(task_id)
            prompt = self._build_worker_prompt(
                task_id=task_id,
                task_content=task_content,
                notes=notes,
                context=context,
            )
            messages = [LLMMessage(role="user", content=prompt)]
            async with semaphore:
                try:
                    out = await self.agent._react_loop(
                        messages=messages,
                        tools=tools,
                        use_memory=False,
                        save_to_memory=False,
                        task=f"sub_agent:{task_id}",
                    )
                    return {
                        "taskId": task_id,
                        "ok": True,
                        "output": _truncate(str(out), self.MAX_OUTPUT_CHARS),
                    }
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    return {"taskId": task_id, "ok": False, "error": str(e)}

        async with asyncio.TaskGroup() as tg:
            task_list = [tg.create_task(_run_one(r["taskId"], r["notes"])) for r in normalized]

        results = [t.result() for t in task_list]

        return _json({"ok": True, "maxParallel": max_parallel, "results": results})
