"""Session-scoped task graph for Task* tools.

This module intentionally keeps state in-memory (per agent/session).
Persistence (e.g. tasks.md hydration) can be layered on later.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import yaml

_VALID_STATUSES = {"pending", "in_progress", "completed"}


def _normalize_task_id(value: str | int | float) -> str:
    """Normalize tool-provided ids (LLMs may pass numbers or numeric strings)."""
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError(f"Invalid task id (non-integer float): {value}")
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    value = str(value).strip()
    if not value:
        raise ValueError("Task id must be non-empty")
    return value


@dataclass(slots=True)
class TaskRecord:
    """Single task node in the dependency graph."""

    id: str
    content: str
    active_form: str
    status: str = "pending"
    blocked_by: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.status not in _VALID_STATUSES:
            raise ValueError(f"Invalid task status: {self.status}")

    def to_dict(self, *, blocks: list[str] | None = None) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "activeForm": self.active_form,
            "status": self.status,
            "blockedBy": list(self.blocked_by),
            "blocks": list(blocks or []),
        }


class TaskStore:
    """In-memory, concurrency-safe store for tasks and dependencies."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._tasks: dict[str, TaskRecord] = {}
        self._next_id = 1

    async def create(
        self,
        *,
        content: str,
        active_form: str | None = None,
        status: str = "pending",
        blocked_by: list[str] | None = None,
    ) -> TaskRecord:
        if not content or not str(content).strip():
            raise ValueError("'content' must be a non-empty string")
        if status not in _VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}. Must be one of {_VALID_STATUSES}")

        async with self._lock:
            task_id = str(self._next_id)
            self._next_id += 1

            deps = [_normalize_task_id(x) for x in (blocked_by or [])]
            deps = _dedupe_keep_order([d for d in deps if d != task_id])

            task = TaskRecord(
                id=task_id,
                content=str(content).strip(),
                active_form=str(active_form).strip() if active_form else str(content).strip(),
                status=status,
                blocked_by=deps,
            )
            self._tasks[task_id] = task
            return task

    async def get(self, task_id: str | int | float) -> TaskRecord | None:
        tid = _normalize_task_id(task_id)
        async with self._lock:
            return self._tasks.get(tid)

    async def list_tasks(self) -> list[TaskRecord]:
        async with self._lock:
            # Stable ordering: creation order by numeric id when possible.
            return sorted(self._tasks.values(), key=_task_sort_key)

    async def update(
        self,
        task_id: str | int | float,
        *,
        content: str | None = None,
        active_form: str | None = None,
        status: str | None = None,
        blocked_by: list[str] | None = None,
        add_blocked_by: list[str] | None = None,
        remove_blocked_by: list[str] | None = None,
        add_blocks: list[str] | None = None,
        remove_blocks: list[str] | None = None,
    ) -> TaskRecord:
        tid = _normalize_task_id(task_id)
        async with self._lock:
            task = self._tasks.get(tid)
            if not task:
                raise KeyError(f"Task not found: {tid}")

            if content is not None:
                if not str(content).strip():
                    raise ValueError("'content' must be a non-empty string when provided")
                task.content = str(content).strip()

            if active_form is not None:
                if not str(active_form).strip():
                    raise ValueError("'activeForm' must be a non-empty string when provided")
                task.active_form = str(active_form).strip()

            if status is not None:
                if status not in _VALID_STATUSES:
                    raise ValueError(f"Invalid status: {status}. Must be one of {_VALID_STATUSES}")
                task.status = status

            if blocked_by is not None:
                deps = [_normalize_task_id(x) for x in blocked_by]
                deps = [d for d in deps if d != tid]
                task.blocked_by = _dedupe_keep_order(deps)

            if add_blocked_by:
                to_add = [_normalize_task_id(x) for x in add_blocked_by]
                to_add = [d for d in to_add if d != tid]
                task.blocked_by = _dedupe_keep_order([*task.blocked_by, *to_add])

            if remove_blocked_by:
                to_remove = {_normalize_task_id(x) for x in remove_blocked_by}
                task.blocked_by = [d for d in task.blocked_by if d not in to_remove]

            if add_blocks:
                # "A blocks B" => B.blocked_by includes A
                for target in add_blocks:
                    target_id = _normalize_task_id(target)
                    if target_id == tid:
                        continue
                    other = self._tasks.get(target_id)
                    if not other:
                        raise KeyError(f"Task not found: {target_id}")
                    other.blocked_by = _dedupe_keep_order([*other.blocked_by, tid])

            if remove_blocks:
                for target in remove_blocks:
                    target_id = _normalize_task_id(target)
                    if target_id == tid:
                        continue
                    other = self._tasks.get(target_id)
                    if not other:
                        raise KeyError(f"Task not found: {target_id}")
                    other.blocked_by = [d for d in other.blocked_by if d != tid]

            return task

    async def available_ids(self) -> list[str]:
        async with self._lock:
            return _available_ids_unlocked(self._tasks)

    async def render_debug_tasks_md(self) -> str:
        async with self._lock:
            tasks = sorted(self._tasks.values(), key=_task_sort_key)
            blocks_map = _compute_blocks_unlocked(tasks)
            available = set(_available_ids_unlocked(self._tasks))

        lines: list[str] = ["# tasks.md (debug)", ""]
        for status in ("pending", "in_progress", "completed"):
            subset = [t for t in tasks if t.status == status]
            if not subset:
                continue
            lines.append(f"## {status}")
            for t in subset:
                checkbox = "x" if t.status == "completed" else " "
                deps = ", ".join(t.blocked_by) if t.blocked_by else "-"
                blocks = ", ".join(blocks_map.get(t.id, [])) if blocks_map.get(t.id) else "-"
                avail = "available" if t.id in available else "blocked"
                lines.append(
                    f"- [{checkbox}] {t.id}: {t.content} ({avail}; blockedBy: {deps}; blocks: {blocks})"
                )
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"

    async def render_tasks_md(self) -> str:
        """Render a human-readable `tasks.md` snapshot with optional YAML metadata blocks."""
        async with self._lock:
            tasks = sorted(self._tasks.values(), key=_task_sort_key)

        lines: list[str] = ["# tasks", ""]
        for t in tasks:
            checkbox = "x" if t.status == "completed" else " "
            lines.append(f"- [{checkbox}] {t.id}: {t.content}")

            ouro_yaml: dict[str, object] = {}
            if t.active_form != t.content:
                ouro_yaml["activeForm"] = t.active_form
            if t.blocked_by:
                ouro_yaml["blockedBy"] = list(t.blocked_by)
            if t.status == "in_progress":
                ouro_yaml["status"] = "in_progress"

            if ouro_yaml:
                payload = {"ouro": ouro_yaml}
                dumped = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True).rstrip()
                lines.append("  ```yaml")
                lines.extend([f"  {yaml_line}" for yaml_line in dumped.splitlines()])
                lines.append("  ```")

            lines.append("")

        return "\n".join(lines).rstrip() + "\n"


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _task_sort_key(task: TaskRecord) -> tuple[int, str]:
    try:
        return (0, f"{int(task.id):012d}")
    except ValueError:
        return (1, task.id)


def _compute_blocks_unlocked(tasks: list[TaskRecord]) -> dict[str, list[str]]:
    blocks: dict[str, list[str]] = {t.id: [] for t in tasks}
    for t in tasks:
        for dep in t.blocked_by:
            if dep in blocks:
                blocks[dep].append(t.id)
    for v in blocks.values():
        v.sort(key=_task_id_sort_key)
    return blocks


def _available_ids_unlocked(tasks: dict[str, TaskRecord]) -> list[str]:
    out: list[str] = []
    for t in sorted(tasks.values(), key=_task_sort_key):
        if t.status != "pending":
            continue
        if not t.blocked_by:
            out.append(t.id)
            continue
        blocked = False
        for dep_id in t.blocked_by:
            dep = tasks.get(dep_id)
            if not dep or dep.status != "completed":
                blocked = True
                break
        if not blocked:
            out.append(t.id)
    return out


def _task_id_sort_key(task_id: str) -> tuple[int, str]:
    try:
        return (0, f"{int(task_id):012d}")
    except ValueError:
        return (1, task_id)
