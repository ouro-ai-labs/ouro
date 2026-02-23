"""Task graph tools: TaskCreate/TaskUpdate/TaskList/TaskGet.

These tools manage an in-memory task graph (session-scoped). Persistence to
`tasks.md` (hydrate/sync-back) can be layered on later.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from typing import Any

import aiofiles
import aiofiles.os

from agent.tasks import TaskStore, _normalize_task_id
from tools.base import BaseTool


def _json(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def _truncate(text: str, limit: int) -> tuple[str, bool, int]:
    raw = str(text or "")
    if limit <= 0:
        return ("", True, len(raw))
    if len(raw) <= limit:
        return (raw, False, len(raw))
    return (raw[:limit] + "... [truncated]", True, len(raw))


def _normalize_id_list(values: list[str | int | float] | None) -> list[str]:
    if not values:
        return []
    return [_normalize_task_id(v) for v in values]


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


class TaskFanoutTool(BaseTool):
    """Create child tasks for a phase and (optionally) rewrite a join task's dependencies.

    This is a convenience tool to avoid a common orchestration pitfall:
    creating a "container/phase" task and separate leaf tasks, but forgetting to
    update the downstream join task's blockedBy to depend on the leaf tasks.
    """

    def __init__(self, store: TaskStore):
        self._store = store

    @property
    def name(self) -> str:
        return "TaskFanout"

    @property
    def description(self) -> str:
        return (
            "Create multiple child tasks for a phase, making children depend on the phase when the phase is a gate (has output). "
            "Children inherit the phase's blockedBy by default. "
            "Optionally rewrite a join task to depend on the new child task IDs instead of the phase. "
            "Use this when you want true fan-out (N leaf tasks) + join (1 aggregation task) execution.\n\n"
            "Recommended pattern:\n"
            "1) Create an identify task to resolve the concrete item list.\n"
            "2) OPTIONAL: Create a phase/container task blockedBy identify (only if you need a named gate for shared rules).\n"
            "3) Create a join task blockedBy the gate (either identify or phase).\n"
            "4) Call TaskFanout(phaseId, joinId, children=[...]) to create named leaf tasks. You may set phaseId to the identify task directly.\n"
            "   - If the phase has output (detail non-empty or already completed), children depend on phaseId (and can use that output).\n"
            "   - If the phase has no output (pure container), children do NOT depend on phaseId (they only inherit phase.blockedBy), and TaskFanout will auto-complete the phase. Avoid putting placeholder detail on pure containers.\n"
            "5) Run leaf tasks (e.g. via sub_agent_batch), then complete join."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "phaseId": {"type": "string", "description": "Phase/container task ID"},
            "children": {
                "type": "array",
                "description": "Child task specs (one per leaf task)",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "Task description (imperative)",
                        },
                        "activeForm": {
                            "type": "string",
                            "description": "Present continuous form (optional)",
                            "default": "",
                        },
                        "status": {
                            "type": "string",
                            "description": "pending, in_progress, completed (optional; default pending)",
                            "default": "pending",
                        },
                        "blockedBy": {
                            "type": "array",
                            "description": "Explicit blockedBy (optional). If omitted/empty and inheritPhaseBlockedBy=true, inherits phase.blockedBy.",
                            "items": {"type": "string"},
                            "default": [],
                        },
                    },
                    "required": ["content"],
                },
            },
            "joinId": {
                "type": "string",
                "description": "Optional join/aggregation task ID to rewrite dependencies for",
                "default": "",
            },
            "inheritPhaseBlockedBy": {
                "type": "boolean",
                "description": "If child.blockedBy is omitted/empty, inherit phase.blockedBy (default: true)",
                "default": True,
            },
            "dependOnPhase": {
                "type": "boolean",
                "description": "Ensure each child depends on phaseId (default: true). Disable only for special cases.",
                "default": True,
            },
            "reuseExistingByContent": {
                "type": "boolean",
                "description": "If a child task with identical content already exists, reuse it (and update its deps if needed) instead of creating a duplicate (default: true).",
                "default": True,
            },
            "includeRender": {
                "type": "boolean",
                "description": "Include full task renderings (tasksMd/debugTasksMd/tasks) in the response (default: false).",
                "default": False,
            },
        }

    async def execute(
        self,
        phaseId: str,
        children: list[dict[str, Any]],
        joinId: str = "",
        inheritPhaseBlockedBy: bool = True,
        dependOnPhase: bool = True,
        reuseExistingByContent: bool = True,
        includeRender: bool = False,
        **kwargs,
    ) -> str:
        if not phaseId or not str(phaseId).strip():
            return _json({"ok": False, "error": "phaseId must be a non-empty string"})
        if not children:
            return _json({"ok": False, "error": "children must be a non-empty array"})

        phase_id = _normalize_task_id(phaseId)
        phase = await self._store.get(phase_id)
        if not phase:
            return _json({"ok": False, "error": f"phase task not found: {phase_id}"})

        phase_blocked_by = list(getattr(phase, "blocked_by", []) or [])
        phase_detail = str(getattr(phase, "detail", "") or "").strip()
        phase_status = str(getattr(phase, "status", "pending") or "pending").strip()
        phase_is_gate = bool(phase_detail) or (phase_status == "completed")

        effective_depend_on_phase = bool(dependOnPhase) and phase_is_gate

        all_tasks = await self._store.list_tasks()
        existing_by_content: dict[str, list[Any]] = {}
        for t in all_tasks:
            existing_by_content.setdefault(t.content, []).append(t)

        def _desired_blocked_by(explicit: list[str]) -> list[str]:
            blocked: list[str] = []
            if inheritPhaseBlockedBy:
                blocked.extend(phase_blocked_by)
            blocked.extend(explicit)
            if effective_depend_on_phase:
                blocked.append(phase_id)
            blocked = [b for b in blocked if b]
            return _dedupe_keep_order(blocked)

        created_ids: list[str] = []
        reused_ids: list[str] = []
        adopted_ids: list[str] = []
        for child in children:
            content = str(child.get("content", "")).strip()
            if not content:
                return _json({"ok": False, "error": "Each child must include non-empty content"})

            active_form = str(child.get("activeForm", "") or "").strip()
            status = str(child.get("status", "pending") or "pending").strip()

            raw_blocked_by = child.get("blockedBy")
            explicit_blocked_by = _normalize_id_list(raw_blocked_by) if raw_blocked_by else []
            blocked_by = _desired_blocked_by(explicit_blocked_by)

            reused = None
            if reuseExistingByContent:
                candidates = list(existing_by_content.get(content, []))
                for cand in candidates:
                    cand_blocked = list(getattr(cand, "blocked_by", []) or [])
                    if (not effective_depend_on_phase) or (phase_id in cand_blocked):
                        reused = cand
                        break
                # Strict adoption: if there is exactly one candidate with identical content and it
                # hasn't started, has no detail, and has no extra deps beyond what we'd want,
                # then "adopt" it by adding missing deps instead of creating a duplicate.
                if reused is None and len(candidates) == 1:
                    cand = candidates[0]
                    cand_blocked = list(getattr(cand, "blocked_by", []) or [])
                    cand_status = str(getattr(cand, "status", "pending") or "pending")
                    cand_detail = str(getattr(cand, "detail", "") or "")
                    if (
                        cand_status == "pending"
                        and not cand_detail.strip()
                        and set(cand_blocked).issubset(set(blocked_by))
                    ):
                        reused = cand
                        adopted_ids.append(cand.id)

            if reused is not None:
                cand_blocked = list(getattr(reused, "blocked_by", []) or [])
                merged = _dedupe_keep_order([*cand_blocked, *blocked_by])
                merged = [d for d in merged if d != reused.id]
                if not phase_is_gate:
                    merged = [d for d in merged if d != phase_id]
                if merged != cand_blocked:
                    await self._store.update(reused.id, blocked_by=merged)
                reused_ids.append(reused.id)
                created_ids.append(reused.id)
                continue

            created = await self._store.create(
                content=content,
                active_form=active_form or None,
                status=status or "pending",
                blocked_by=blocked_by,
            )
            created_ids.append(created.id)

        # If the phase is a pure container (no output), treat it as completed so it doesn't
        # block leaf task status updates under strict dependency gating.
        if not phase_is_gate and phase_status != "completed":
            # Best-effort; do not fail fanout if the phase can't be updated.
            with contextlib.suppress(Exception):
                await self._store.update(phase_id, status="completed")

        join_id = str(joinId or "").strip()
        join_blocked_by: list[str] | None = None
        if join_id:
            join = await self._store.get(join_id)
            if not join:
                return _json({"ok": False, "error": f"join task not found: {join_id}"})

            existing = list(getattr(join, "blocked_by", []) or [])
            rewritten = [d for d in existing if d not in {phase_id, join_id}]
            rewritten = _dedupe_keep_order([*rewritten, *created_ids])
            await self._store.update(join_id, blocked_by=rewritten)
            join_blocked_by = rewritten

        if join_id and join_blocked_by is None:
            join = await self._store.get(join_id)
            if join:
                join_blocked_by = list(getattr(join, "blocked_by", []) or [])

        payload: dict[str, Any] = {
            "ok": True,
            "phaseId": phase_id,
            "childIds": created_ids,
            "reusedChildIds": reused_ids,
            "adoptedChildIds": adopted_ids,
            "joinId": join_id or None,
            "joinBlockedBy": join_blocked_by,
            "available": await self._store.available_ids(),
        }

        if includeRender:
            tasks = await self._store.list_tasks()
            blocks = _compute_blocks(tasks)
            payload.update(
                {
                    "tasks": [t.to_dict(blocks=blocks.get(t.id, [])) for t in tasks],
                    "tasksMd": await self._store.render_tasks_md(),
                    "debugTasksMd": await self._store.render_debug_tasks_md(),
                }
            )

        return _json(payload)


class TaskDumpMdTool(BaseTool):
    """Persist a human-readable tasks.md snapshot to disk."""

    def __init__(self, store: TaskStore):
        self._store = store
        self._dump_lock = asyncio.Lock()

    @property
    def name(self) -> str:
        return "TaskDumpMd"

    @property
    def description(self) -> str:
        return (
            "Render the current task graph as a human-readable tasks.md and write it to disk. "
            "Uses an atomic replace to avoid partial writes. "
            "When includeDebug=true, also writes a title-focused tasks.debug.md (no long details)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "path": {
                "type": "string",
                "description": "File path to write (default: tasks.md)",
                "default": "tasks.md",
            },
            "includeDebug": {
                "type": "boolean",
                "description": "Also write tasks.debug.md alongside the main file (default: false)",
                "default": False,
            },
        }

    async def execute(self, path: str = "tasks.md", includeDebug: bool = False, **kwargs) -> str:
        if not path or not str(path).strip():
            return _json({"ok": False, "error": "path must be a non-empty string"})

        target_path = os.path.abspath(path)
        target_dir = os.path.dirname(target_path) or "."
        base_name = os.path.basename(target_path)
        tmp_path = os.path.join(target_dir, f".{base_name}.tmp")

        debug_path = None
        debug_tmp_path = None
        if includeDebug:
            root, ext = os.path.splitext(base_name)
            debug_base = f"{root}.debug{ext}" if ext else f"{root}.debug"
            debug_path = os.path.join(target_dir, debug_base)
            debug_tmp_path = os.path.join(target_dir, f".{debug_base}.tmp")

        async with self._dump_lock:
            tasks_md = await self._store.render_tasks_md()
            tasks = await self._store.list_tasks()
            task_count = len(tasks)

            await aiofiles.os.makedirs(target_dir, exist_ok=True)
            async with aiofiles.open(tmp_path, "w", encoding="utf-8") as f:
                await f.write(tasks_md)
            os.replace(tmp_path, target_path)

            if includeDebug and debug_path and debug_tmp_path:
                debug_md = await self._store.render_debug_tasks_md()
                async with aiofiles.open(debug_tmp_path, "w", encoding="utf-8") as f:
                    await f.write(debug_md)
                os.replace(debug_tmp_path, debug_path)

        return _json(
            {
                "ok": True,
                "path": target_path,
                "taskCount": task_count,
                "bytesWritten": len(tasks_md.encode("utf-8")),
                "debugPath": debug_path,
            }
        )


class TaskCreateTool(BaseTool):
    """Create a task node."""

    @property
    def name(self) -> str:
        return "TaskCreate"

    @property
    def description(self) -> str:
        return """Create a task in the session task graph.

Use tasks for complex work: break down steps, model dependencies via blockedBy/blocks,
and update status as you progress. Prefer Tasks tools over manage_todo_list.

Guidelines:
- Tasks should represent real execution units (leaf work should be its own task).
- If the N items are unknown upfront, create an identify task first; put the resolved item list in that task's `detail` and complete it before creating leaf tasks.
  - The `detail` should be reusable: include the final list using canonical names (no placeholders) and at least 1-3 source links so downstream tasks don't need to re-identify.
- Avoid placeholder leaf tasks like "item 1" / "Song #1" that re-decide the item later; leaf task titles should include the concrete item name.
- Prefer meaningful tasks with output: if you create a gate/identify/phase task, make it produce reusable inputs or constraints in `detail`, then mark it completed. Avoid empty "container" tasks unless you intend to use TaskFanout (which can auto-complete pure containers).
- Avoid redundant parent+child tasks that repeat the same work: if you create a parent like "Analyze Top N items" and also create N leaf analyses, the parent should add reusable value (e.g., normalize the input list, define evaluation dimensions, or record shared constraints in `detail`). Otherwise omit the parent and fan out directly.
- If you already have an identify task that produced the concrete item list, you can fan out directly from that identify task (using TaskFanout with phaseId=identifyId) and skip creating an extra phase task.
- For "analyze Top N items" requests: create N leaf tasks + 1 join task, with join blockedBy the N leaf tasks (TaskFanout can help)."""

    def __init__(self, store: TaskStore):
        self._store = store

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "content": {
                "type": "string",
                "description": "Task description (imperative)",
            },
            "activeForm": {
                "type": "string",
                "description": "Present continuous form (used when in progress)",
                "default": "",
            },
            "detail": {
                "type": "string",
                "description": "Optional long-form detail/result for this task (keep content short).",
                "default": "",
            },
            "status": {
                "type": "string",
                "description": "One of: pending, in_progress, completed",
                "default": "pending",
            },
            "blockedBy": {
                "type": "array",
                "description": "Task IDs that must complete before this task is available",
                "items": {"type": "string"},
                "default": [],
            },
        }

    async def execute(
        self,
        content: str,
        activeForm: str = "",
        detail: str = "",
        status: str = "pending",
        blockedBy: list[str | int | float] | None = None,
        **kwargs,
    ) -> str:
        task = await self._store.create(
            content=content,
            active_form=activeForm or None,
            detail=detail or None,
            status=status,
            blocked_by=_normalize_id_list(blockedBy),
        )
        tasks = await self._store.list_tasks()
        blocks = _compute_blocks(tasks)
        task_dict = task.to_dict(blocks=blocks.get(task.id, []), include_detail=True)
        if isinstance(task_dict.get("detail"), str) and task_dict.get("detail"):
            truncated, was_truncated, total = _truncate(task_dict["detail"], 8000)
            task_dict["detail"] = truncated
            if was_truncated:
                task_dict["detailTruncated"] = True
                task_dict["detailTotalChars"] = total
        return _json(
            {
                "task": task_dict,
                "available": await self._store.available_ids(),
                "tasksMd": await self._store.render_tasks_md(),
                "debugTasksMd": await self._store.render_debug_tasks_md(),
            }
        )


class TaskUpdateTool(BaseTool):
    """Update a task node and/or its dependencies."""

    @property
    def name(self) -> str:
        return "TaskUpdate"

    @property
    def description(self) -> str:
        return """Update an existing task: status/content, and dependency edges.

Use `detail` to store long-form results/notes. Keep `content` short and stable (task title).
If downstream tasks depend on this task, make sure `detail` contains the concrete outputs/constraints they need before marking it completed.
When you finish a task, prefer writing the full result into `detail` (verbatim if available, e.g. from sub_agent_batch) rather than compressing it into a short summary.
By default, `detail` is append-only; set replaceDetail=true to overwrite/clear.

Batch updates:
- You can update multiple tasks in one call via `updates=[{id, ...}, ...]` (useful after sub_agent_batch returns N results).

Dependency rules:
- You may only edit dependency edges (blockedBy/addBlockedBy/removeBlockedBy/addBlocks/removeBlocks) for tasks that are pending.
- If you need to change dependencies after work has started, explicitly reopen the task first with status="pending", then edit dependencies, then start again.

Notes on dependency fields:
- blockedBy replaces the full dependency list for this task.
- addBlockedBy/removeBlockedBy incrementally edit blockedBy.
- addBlocks/removeBlocks edit reverse edges (A blocks B => B.blockedBy includes A).

Tool response:
- For single-task updates (id=...), the response includes the updated task's long-form `detail` (bounded/truncated when very large)."""

    def __init__(self, store: TaskStore):
        self._store = store

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "id": {
                "type": "string",
                "description": "Task id to update",
                "default": None,
            },
            "updates": {
                "type": "array",
                "description": "Batch updates (optional): list of task update objects",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "Task id"},
                        "content": {
                            "type": "string",
                            "description": "New imperative description",
                            "default": None,
                        },
                        "activeForm": {
                            "type": "string",
                            "description": "New present continuous form",
                            "default": None,
                        },
                        "detail": {
                            "type": "string",
                            "description": "Long-form detail/result",
                            "default": None,
                        },
                        "replaceDetail": {
                            "type": "boolean",
                            "description": "If true, overwrite any existing detail. If false (default), append non-empty detail.",
                            "default": False,
                        },
                        "status": {
                            "type": "string",
                            "description": "New status: pending, in_progress, completed",
                            "default": None,
                        },
                        "blockedBy": {
                            "type": "array",
                            "description": "Replace dependencies",
                            "items": {"type": "string"},
                            "default": None,
                        },
                        "addBlockedBy": {
                            "type": "array",
                            "description": "Add dependencies",
                            "items": {"type": "string"},
                            "default": None,
                        },
                        "removeBlockedBy": {
                            "type": "array",
                            "description": "Remove dependencies",
                            "items": {"type": "string"},
                            "default": None,
                        },
                        "addBlocks": {
                            "type": "array",
                            "description": "Add reverse edges: this task blocks those task ids",
                            "items": {"type": "string"},
                            "default": None,
                        },
                        "removeBlocks": {
                            "type": "array",
                            "description": "Remove reverse edges: this task no longer blocks those ids",
                            "items": {"type": "string"},
                            "default": None,
                        },
                    },
                    "required": ["id"],
                },
                "default": None,
            },
            "content": {
                "type": "string",
                "description": "New imperative description (optional)",
                "default": None,
            },
            "activeForm": {
                "type": "string",
                "description": "New present continuous form (optional)",
                "default": None,
            },
            "detail": {
                "type": "string",
                "description": "Long-form detail/result (optional; does not change the task title)",
                "default": None,
            },
            "replaceDetail": {
                "type": "boolean",
                "description": "If true, overwrite any existing detail. If false (default), new non-empty detail is appended to existing detail (never clears).",
                "default": False,
            },
            "status": {
                "type": "string",
                "description": "New status: pending, in_progress, completed (optional)",
                "default": None,
            },
            "blockedBy": {
                "type": "array",
                "description": "Replace dependencies (optional)",
                "items": {"type": "string"},
                "default": None,
            },
            "addBlockedBy": {
                "type": "array",
                "description": "Add dependencies (optional)",
                "items": {"type": "string"},
                "default": None,
            },
            "removeBlockedBy": {
                "type": "array",
                "description": "Remove dependencies (optional)",
                "items": {"type": "string"},
                "default": None,
            },
            "addBlocks": {
                "type": "array",
                "description": "Add reverse edges: this task blocks those task ids (optional)",
                "items": {"type": "string"},
                "default": None,
            },
            "removeBlocks": {
                "type": "array",
                "description": "Remove reverse edges: this task no longer blocks those ids (optional)",
                "items": {"type": "string"},
                "default": None,
            },
        }

    async def execute(
        self,
        id: str | int | float | None = None,
        updates: list[dict[str, Any]] | None = None,
        content: str | None = None,
        activeForm: str | None = None,
        detail: str | None = None,
        replaceDetail: bool = False,
        status: str | None = None,
        blockedBy: list[str | int | float] | None = None,
        addBlockedBy: list[str | int | float] | None = None,
        removeBlockedBy: list[str | int | float] | None = None,
        addBlocks: list[str | int | float] | None = None,
        removeBlocks: list[str | int | float] | None = None,
        **kwargs,
    ) -> str:
        if updates is not None:
            if id is not None or any(
                x is not None
                for x in (
                    content,
                    activeForm,
                    detail,
                    status,
                    blockedBy,
                    addBlockedBy,
                    removeBlockedBy,
                    addBlocks,
                    removeBlocks,
                )
            ):
                raise ValueError(
                    "When using updates=[...], do not also pass top-level task fields."
                )
            if not isinstance(updates, list) or not updates:
                raise ValueError("'updates' must be a non-empty array when provided")

            # Snapshot for append-only detail behavior.
            tasks = await self._store.list_tasks()
            by_id = {t.id: t for t in tasks}

            normalized: list[dict[str, Any]] = []
            seen: set[str] = set()
            for u in updates:
                if not isinstance(u, dict):
                    raise ValueError("Each item in updates must be an object")
                raw_id = u.get("id")
                if raw_id is None:
                    raise ValueError("Each update must include a non-empty id")
                tid = _normalize_task_id(raw_id)
                if tid in seen:
                    raise ValueError(f"Duplicate id in updates: {tid}")
                seen.add(tid)

                u_detail = u.get("detail")
                u_replace = bool(u.get("replaceDetail", False))
                if u_detail is not None and not u_replace:
                    if not str(u_detail).strip():
                        u_detail = None
                    else:
                        existing = by_id.get(tid)
                        if existing and getattr(existing, "detail", None):
                            existing_detail = str(existing.detail or "")
                            if existing_detail.strip() and str(u_detail) not in existing_detail:
                                u_detail = (
                                    existing_detail.rstrip()
                                    + "\n\n---\n\n"
                                    + str(u_detail).lstrip()
                                )

                normalized.append(
                    {
                        "id": tid,
                        "content": u.get("content"),
                        "active_form": u.get("activeForm"),
                        "detail": u_detail,
                        "status": u.get("status"),
                        "blocked_by": (
                            _normalize_id_list(u.get("blockedBy"))
                            if u.get("blockedBy") is not None
                            else None
                        ),
                        "add_blocked_by": _normalize_id_list(u.get("addBlockedBy")) or None,
                        "remove_blocked_by": _normalize_id_list(u.get("removeBlockedBy")) or None,
                        "add_blocks": _normalize_id_list(u.get("addBlocks")) or None,
                        "remove_blocks": _normalize_id_list(u.get("removeBlocks")) or None,
                    }
                )

            updated_tasks = await self._store.update_many(normalized)
            tasks2 = await self._store.list_tasks()
            blocks2 = _compute_blocks(tasks2)
            tasks2_by_id = {t.id: t for t in tasks2}
            update_debug: list[dict[str, Any]] = []
            for updated_task in updated_tasks:
                record = tasks2_by_id.get(updated_task.id, updated_task)
                record_dict = record.to_dict(
                    blocks=blocks2.get(record.id, []), include_detail=False
                )
                detail_text = str(getattr(record, "detail", "") or "")
                detail_preview = _truncate(detail_text, 240)[0] if detail_text else ""
                update_debug.append(
                    {
                        "id": record_dict.get("id"),
                        "status": record_dict.get("status"),
                        "detailChars": record_dict.get("detailChars", 0),
                        "detailDigest": record_dict.get("detailDigest", ""),
                        "detailPreview": detail_preview,
                    }
                )
            return _json(
                {
                    "tasks": [t.to_dict(blocks=blocks2.get(t.id, [])) for t in updated_tasks],
                    "updateDebug": update_debug,
                    "available": await self._store.available_ids(),
                    "tasksMd": await self._store.render_tasks_md(),
                    "debugTasksMd": await self._store.render_debug_tasks_md(),
                }
            )

        if id is None:
            raise ValueError("TaskUpdate requires either id=... or updates=[...]")

        # Detail is append-only by default to avoid accidental clobbering of long results.
        # Clearing or overwriting requires replaceDetail=true.
        if detail is not None and not replaceDetail:
            if not str(detail).strip():
                detail = None
            else:
                existing = await self._store.get(id)
                if existing and getattr(existing, "detail", None):
                    existing_detail = str(existing.detail or "")
                    if existing_detail.strip() and str(detail) not in existing_detail:
                        detail = existing_detail.rstrip() + "\n\n---\n\n" + str(detail).lstrip()

        updated = await self._store.update(
            id,
            content=content,
            active_form=activeForm,
            detail=detail,
            status=status,
            blocked_by=_normalize_id_list(blockedBy) if blockedBy is not None else None,
            add_blocked_by=_normalize_id_list(addBlockedBy) or None,
            remove_blocked_by=_normalize_id_list(removeBlockedBy) or None,
            add_blocks=_normalize_id_list(addBlocks) or None,
            remove_blocks=_normalize_id_list(removeBlocks) or None,
        )
        tasks3 = await self._store.list_tasks()
        blocks3 = _compute_blocks(tasks3)

        # For single-task updates, include the task's long-form detail (bounded) so downstream steps
        # can reliably reuse it via the tool result (not only via TaskGet).
        task_dict = updated.to_dict(blocks=blocks3.get(updated.id, []), include_detail=True)
        detail_max = 8000
        if isinstance(task_dict.get("detail"), str) and task_dict.get("detail"):
            truncated, was_truncated, total = _truncate(task_dict["detail"], detail_max)
            task_dict["detail"] = truncated
            if was_truncated:
                task_dict["detailTruncated"] = True
                task_dict["detailTotalChars"] = total

        update_debug = {
            "id": task_dict.get("id"),
            "status": task_dict.get("status"),
            "detailChars": task_dict.get("detailChars", 0),
            "detailDigest": task_dict.get("detailDigest", ""),
            "detailPreview": (
                _truncate(str(task_dict.get("detail") or ""), 240)[0]
                if str(task_dict.get("detail") or "")
                else ""
            ),
        }
        return _json(
            {
                "task": task_dict,
                "updateDebug": update_debug,
                "available": await self._store.available_ids(),
                "tasksMd": await self._store.render_tasks_md(),
                "debugTasksMd": await self._store.render_debug_tasks_md(),
            }
        )


class TaskListTool(BaseTool):
    """List tasks."""

    readonly = True

    @property
    def name(self) -> str:
        return "TaskList"

    @property
    def description(self) -> str:
        return (
            "List all tasks in the session task graph, plus which tasks are available to start. "
            "Use this to confirm there are no pending/in_progress tasks left before finishing."
        )

    def __init__(self, store: TaskStore):
        self._store = store

    @property
    def parameters(self) -> dict[str, Any]:
        return {}

    async def execute(self, **kwargs) -> str:
        tasks = await self._store.list_tasks()
        blocks = _compute_blocks(tasks)
        return _json(
            {
                "tasks": [t.to_dict(blocks=blocks.get(t.id, [])) for t in tasks],
                "available": await self._store.available_ids(),
                "tasksMd": await self._store.render_tasks_md(),
                "debugTasksMd": await self._store.render_debug_tasks_md(),
            }
        )


class TaskGetTool(BaseTool):
    """Get a single task by id."""

    readonly = True

    @property
    def name(self) -> str:
        return "TaskGet"

    @property
    def description(self) -> str:
        return (
            "Get a single task by id (includes long-form detail when present). "
            "If you need multiple tasks' details, prefer TaskGetMany(ids=[...]) to reduce tool calls."
        )

    def __init__(self, store: TaskStore):
        self._store = store

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "id": {
                "type": "string",
                "description": "Task id",
            }
        }

    async def execute(self, id: str | int | float, **kwargs) -> str:
        task = await self._store.get(id)
        if not task:
            return _json({"error": "Task not found", "id": str(id)})

        tasks = await self._store.list_tasks()
        blocks = _compute_blocks(tasks)
        return _json(
            {
                "task": task.to_dict(blocks=blocks.get(task.id, []), include_detail=True),
                "available": await self._store.available_ids(),
                "tasksMd": await self._store.render_tasks_md(),
                "debugTasksMd": await self._store.render_debug_tasks_md(),
            }
        )


class TaskGetManyTool(BaseTool):
    """Get multiple tasks by ids."""

    readonly = True

    @property
    def name(self) -> str:
        return "TaskGetMany"

    @property
    def description(self) -> str:
        return (
            "Get multiple tasks by id (each includes long-form detail when present). "
            "Use this to fetch N leaf task outputs for a join/summarization step in one call."
        )

    def __init__(self, store: TaskStore):
        self._store = store

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "ids": {
                "type": "array",
                "description": "Task ids to fetch",
                "items": {"type": "string"},
            }
        }

    async def execute(self, ids: list[str | int | float], **kwargs) -> str:
        normalized = _normalize_id_list(ids)
        if not normalized:
            return _json({"ok": False, "error": "'ids' must be a non-empty array"})

        tasks = await self._store.list_tasks()
        blocks = _compute_blocks(tasks)
        by_id = {t.id: t for t in tasks}

        out_tasks = []
        missing = []
        for tid in normalized:
            t = by_id.get(tid)
            if not t:
                missing.append(tid)
                continue
            out_tasks.append(t.to_dict(blocks=blocks.get(t.id, []), include_detail=True))

        return _json(
            {
                "ok": True,
                "tasks": out_tasks,
                "missing": missing,
                "available": await self._store.available_ids(),
            }
        )


def _compute_blocks(tasks) -> dict[str, list[str]]:
    blocks: dict[str, list[str]] = {t.id: [] for t in tasks}
    for t in tasks:
        for dep in t.blocked_by:
            if dep in blocks:
                blocks[dep].append(t.id)
    for v in blocks.values():
        v.sort(key=_blocks_sort_key)
    return blocks


def _blocks_sort_key(task_id: str) -> tuple[int, str]:
    try:
        return (0, f"{int(task_id):012d}")
    except ValueError:
        return (1, task_id)
