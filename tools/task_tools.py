"""Task graph tools: TaskCreate/TaskUpdate/TaskList/TaskGet.

These tools manage an in-memory task graph (session-scoped). Persistence to
`tasks.md` (hydrate/sync-back) can be layered on later.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import aiofiles
import aiofiles.os

from agent.tasks import TaskStore, _normalize_task_id
from tools.base import BaseTool


def _json(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def _normalize_id_list(values: list[str | int | float] | None) -> list[str]:
    if not values:
        return []
    return [_normalize_task_id(v) for v in values]


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
            "Uses an atomic replace to avoid partial writes."
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
and update status as you progress. Prefer Tasks tools over manage_todo_list."""

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
        status: str = "pending",
        blockedBy: list[str | int | float] | None = None,
        **kwargs,
    ) -> str:
        task = await self._store.create(
            content=content,
            active_form=activeForm or None,
            status=status,
            blocked_by=_normalize_id_list(blockedBy),
        )
        tasks = await self._store.list_tasks()
        blocks = _compute_blocks(tasks)
        return _json(
            {
                "task": task.to_dict(blocks=blocks.get(task.id, [])),
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

Notes on dependency fields:
- blockedBy replaces the full dependency list for this task.
- addBlockedBy/removeBlockedBy incrementally edit blockedBy.
- addBlocks/removeBlocks edit reverse edges (A blocks B => B.blockedBy includes A)."""

    def __init__(self, store: TaskStore):
        self._store = store

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "id": {
                "type": "string",
                "description": "Task id to update",
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
        id: str | int | float,
        content: str | None = None,
        activeForm: str | None = None,
        status: str | None = None,
        blockedBy: list[str | int | float] | None = None,
        addBlockedBy: list[str | int | float] | None = None,
        removeBlockedBy: list[str | int | float] | None = None,
        addBlocks: list[str | int | float] | None = None,
        removeBlocks: list[str | int | float] | None = None,
        **kwargs,
    ) -> str:
        updated = await self._store.update(
            id,
            content=content,
            active_form=activeForm,
            status=status,
            blocked_by=_normalize_id_list(blockedBy) if blockedBy is not None else None,
            add_blocked_by=_normalize_id_list(addBlockedBy) or None,
            remove_blocked_by=_normalize_id_list(removeBlockedBy) or None,
            add_blocks=_normalize_id_list(addBlocks) or None,
            remove_blocks=_normalize_id_list(removeBlocks) or None,
        )
        tasks = await self._store.list_tasks()
        blocks = _compute_blocks(tasks)
        return _json(
            {
                "task": updated.to_dict(blocks=blocks.get(updated.id, [])),
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
        return "List all tasks in the session task graph, plus which tasks are available to start."

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
        return "Get a single task by id."

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
                "task": task.to_dict(blocks=blocks.get(task.id, [])),
                "available": await self._store.available_ids(),
                "tasksMd": await self._store.render_tasks_md(),
                "debugTasksMd": await self._store.render_debug_tasks_md(),
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
