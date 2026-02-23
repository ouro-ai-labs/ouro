"""Parallel sub-agent execution for Tasks-based orchestration.

This tool runs multiple fresh ReAct loops (sub-agents) concurrently, each focused
on one TaskStore task ID. On success it writes worker output back to TaskStore as
completed detail (best-effort), and also returns a TaskUpdate-compatible payload.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
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


def _digest(text: str) -> str:
    raw = str(text or "")
    if not raw:
        return ""
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


class SubAgentBatchTool(BaseTool):
    """Run multiple sub-agents in parallel for task IDs."""

    MAX_PARALLEL_CAP = 8
    MAX_CONTEXT_CHARS = 1500
    MAX_UPSTREAM_DETAIL_CHARS = 600
    MAX_UPSTREAM_TASKS = 8
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
            "On success, this tool attempts to write each worker output back to TaskStore as "
            "status=completed + detail. "
            "It also returns a ready-to-apply TaskUpdate(updates=[...]) payload for explicit/main-agent replay if needed."
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
            "TaskGetMany",
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

    async def _get_task(self, task_id: str) -> dict[str, Any] | None:
        raw = await self.agent.tool_executor.execute_tool_call("TaskGet", {"id": task_id})
        try:
            data = json.loads(raw)
        except Exception:
            return None
        task = data.get("task") or {}
        if not isinstance(task, dict):
            return None
        return task

    async def _collect_upstream_outputs(
        self, root_task: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        """Collect completed direct dependency outputs using one TaskGetMany call."""
        deps = [str(x).strip() for x in (root_task.get("blockedBy") or [])]
        deps = [d for d in deps if d][: self.MAX_UPSTREAM_TASKS]
        meta: dict[str, Any] = {
            "upstreamBlockedBy": deps,
            "upstreamIncluded": [],
            "upstreamIncludedCount": 0,
            "upstreamIncludedDetailChars": 0,
        }
        if not deps:
            return ("", meta)

        raw = await self.agent.tool_executor.execute_tool_call("TaskGetMany", {"ids": deps})
        try:
            data = json.loads(raw)
        except Exception:
            return ("", meta)
        tasks = data.get("tasks") or []
        if not isinstance(tasks, list):
            return ("", meta)

        collected: list[str] = []
        for dep in tasks:
            if not isinstance(dep, dict):
                continue
            status = str(dep.get("status", "") or "").strip()
            detail = str(dep.get("detail", "") or "").strip()
            dep_id = str(dep.get("id", "") or "").strip()
            if not dep_id or status != "completed" or not detail:
                continue
            meta["upstreamIncluded"].append(dep_id)
            meta["upstreamIncludedDetailChars"] += len(detail)
            content = str(dep.get("content", "") or "").strip() or f"(task {dep_id})"
            detail = _truncate(detail, self.MAX_UPSTREAM_DETAIL_CHARS)
            collected.append(f"- [{dep_id}] {content}\n  {detail.replace('\\n', '\\n  ')}")

        meta["upstreamIncludedCount"] = len(meta["upstreamIncluded"])
        if not collected:
            return ("", meta)
        return (_truncate("\n".join(collected).strip(), self.MAX_CONTEXT_CHARS), meta)

    async def _build_shared_context(self, root_task: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        simplified = self._extract_simplified_conversation_context()
        upstream, meta = await self._collect_upstream_outputs(root_task)

        if not simplified and not upstream:
            meta["usedUpstreamContext"] = False
            meta["sharedContextChars"] = 0
            meta["sharedContextDigest"] = ""
            return ("", meta)

        parts: list[str] = []
        # Prioritize upstream outputs over general conversation context.
        # Upstream outputs often contain the concrete item list / constraints that leaf tasks must reuse.
        if upstream:
            parts.append("<upstream_outputs>\n" + upstream + "\n</upstream_outputs>")
        if simplified and (not upstream or len(upstream) < (self.MAX_CONTEXT_CHARS * 2 // 3)):
            parts.append("<conversation>\n" + simplified + "\n</conversation>")
        context = _truncate("\n\n".join(parts).strip(), self.MAX_CONTEXT_CHARS)
        meta["usedUpstreamContext"] = bool(upstream)
        meta["sharedContextChars"] = len(context)
        meta["sharedContextDigest"] = _digest(context)
        return (context, meta)

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
   - If <upstream_outputs> provides the concrete item list, definitions, or constraints, treat it as the source of truth. Do not re-identify or re-decide the items.
   - If the task title is ambiguous, use <upstream_outputs> to disambiguate (e.g., full name, domain) before searching.
2. Output:
   - Return a result that the main agent can store verbatim via TaskUpdate(detail=...).
   - Include: (a) key claims (b) supporting evidence/links (c) any caveats.
   - Prefer bullets and structure. Do not intentionally over-compress; it's fine if the result is a bit long.
</contract>

Execute now."""

    def _compact_result(
        self,
        *,
        task_id: str,
        ok: bool,
        debug_meta: dict[str, Any],
        output: str = "",
        error: str = "",
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "taskId": task_id,
            "ok": ok,
            "usedUpstreamContext": bool(debug_meta.get("usedUpstreamContext")),
            "upstreamBlockedBy": list(debug_meta.get("upstreamBlockedBy") or []),
            "upstreamIncluded": list(debug_meta.get("upstreamIncluded") or []),
            "upstreamIncludedCount": int(debug_meta.get("upstreamIncludedCount") or 0),
            "upstreamIncludedDetailChars": int(debug_meta.get("upstreamIncludedDetailChars") or 0),
            "sharedContextChars": int(debug_meta.get("sharedContextChars") or 0),
            "sharedContextDigest": str(debug_meta.get("sharedContextDigest") or ""),
        }
        if ok:
            result.update(
                {
                    "detailChars": len(output),
                    "outputDigest": str(debug_meta.get("outputDigest") or ""),
                    "outputPreview": str(debug_meta.get("outputPreview") or ""),
                }
            )
        else:
            result["error"] = error
        return result

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

        async def _run_one(task_id: str, notes: str) -> dict[str, Any]:
            root_task = await self._get_task(task_id) or {}
            task_content = str(root_task.get("content", "") or "").strip() or f"(task {task_id})"
            context, debug_meta = await self._build_shared_context(root_task)
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
                    output = str(out)
                    debug_meta["outputChars"] = len(output)
                    debug_meta["outputDigest"] = _digest(output)
                    debug_meta["outputPreview"] = _truncate(output, 240)
                    return {"taskId": task_id, "ok": True, "output": output, "debug": debug_meta}
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    debug_meta["outputChars"] = 0
                    debug_meta["outputDigest"] = ""
                    debug_meta["outputPreview"] = ""
                    return {"taskId": task_id, "ok": False, "error": str(e), "debug": debug_meta}

        async with asyncio.TaskGroup() as tg:
            task_list = [tg.create_task(_run_one(r["taskId"], r["notes"])) for r in normalized]

        results = [t.result() for t in task_list]

        applied_updates: list[str] = []
        update_errors: list[dict[str, str]] = []

        store = getattr(self.agent, "task_store", None)
        if store is not None:
            for r in results:
                if r.get("ok") is not True:
                    continue
                task_id = str(r.get("taskId", "")).strip()
                output = str(r.get("output", "") or "").strip()
                if not task_id or not output:
                    continue

                update_applied = False
                if hasattr(store, "update"):
                    try:
                        await store.update(task_id, status="completed", detail=output)
                        applied_updates.append(task_id)
                        update_applied = True
                    except Exception as e:
                        update_errors.append({"id": task_id, "error": str(e)})

                if (not update_applied) and hasattr(store, "stash_detail"):
                    with contextlib.suppress(Exception):
                        await store.stash_detail(task_id, output)

        updates: list[dict[str, Any]] = []
        compact_results: list[dict[str, Any]] = []
        for r in results:
            task_id = str(r.get("taskId", "")).strip()
            if not task_id:
                continue
            debug_meta = r.get("debug") if isinstance(r.get("debug"), dict) else {}
            if r.get("ok") is True:
                output = str(r.get("output", "") or "")
                updates.append(
                    {
                        "id": task_id,
                        "status": "completed",
                        "detail": output,
                        "replaceDetail": True,
                    }
                )
                compact_results.append(
                    self._compact_result(
                        task_id=task_id, ok=True, debug_meta=debug_meta, output=output
                    )
                )
            else:
                compact_results.append(
                    self._compact_result(
                        task_id=task_id,
                        ok=False,
                        debug_meta=debug_meta,
                        error=str(r.get("error", "")),
                    )
                )

        return _json(
            {
                "ok": True,
                "maxParallel": max_parallel,
                "results": compact_results,
                "updates": updates,
                "appliedUpdates": applied_updates,
                "updateErrors": update_errors,
            }
        )
