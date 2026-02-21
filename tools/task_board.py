"""Task board tool (v1) for round-based orchestration.

Design goals:
- Extremely small API surface (create/list/get/update/runnable).
- Session-scoped in-memory state with optional hydration/sync to a persistent `tasks.md`.
- Deterministic, machine-readable `tasks.md` via a single fenced JSON block.

This intentionally mirrors the "Tasks as state" pattern: the LLM can plan by mutating a task table,
while the runtime only needs mechanical scheduling rules.
"""

from __future__ import annotations

import json
import os
import re
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .base import BaseTool

_DEFAULT_TASKS_PATH = "tasks.md"
_DEFAULT_STORE = "markdown"  # markdown|dir

_DIR_META = "_meta.json"
_DIR_GROUPS = "_groups.json"  # Reserved for future grouping/UI metadata
_DIR_LOCK = ".lock"


@dataclass
class TaskRecord:
    id: str
    status: str = "pending"  # pending|in_progress|completed|failed
    owner: str | None = None
    blocked_by: list[str] = field(default_factory=list)
    subject: str = ""
    description: str = ""
    active_form: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    artifacts: list[str] = field(default_factory=list)
    errors: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "owner": self.owner,
            "blocked_by": list(self.blocked_by),
            "subject": self.subject,
            "description": self.description,
            "active_form": self.active_form,
            "metadata": dict(self.metadata or {}),
            "summary": self.summary,
            "artifacts": list(self.artifacts or []),
            "errors": self.errors,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskRecord:
        return cls(
            id=str(data.get("id", "")).strip(),
            status=str(data.get("status", "pending")).strip() or "pending",
            owner=(str(data.get("owner")).strip() if data.get("owner") is not None else None),
            blocked_by=[str(x).strip() for x in (data.get("blocked_by") or []) if str(x).strip()],
            subject=str(data.get("subject", "")).strip(),
            description=str(data.get("description", "")).strip(),
            active_form=str(data.get("active_form", "")).strip(),
            metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
            summary=str(data.get("summary", "")).strip(),
            artifacts=[str(x).strip() for x in (data.get("artifacts") or []) if str(x).strip()],
            errors=str(data.get("errors", "")).strip(),
        )


@dataclass
class TaskPlan:
    version: int = 1
    goal: str = ""
    tasks: dict[str, TaskRecord] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": int(self.version),
            "goal": self.goal,
            "tasks": [t.to_dict() for _id, t in sorted(self.tasks.items(), key=lambda kv: kv[0])],
        }


class TaskBoardTool(BaseTool):
    """A minimal task board tool for orchestration."""

    @property
    def name(self) -> str:
        return "task_board"

    @property
    def description(self) -> str:
        return (
            "Maintain a task board for round-based orchestration.\n\n"
            "Use this for dependent workflows and map-reduce:\n"
            "- create tasks with blocked_by dependencies\n"
            "- list/get/update task state and attach artifacts/summaries\n"
            "- query runnable tasks\n\n"
            "Optionally persists to tasks.md via a single fenced JSON block."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "operation": {
                "type": "string",
                "description": "create|list|get|update|delete|runnable|hydrate|sync",
            },
            "path": {
                "type": "string",
                "description": f"Path to tasks.md (default: { _DEFAULT_TASKS_PATH })",
                "default": _DEFAULT_TASKS_PATH,
            },
            "store": {
                "type": "string",
                "description": "Persistence backend: markdown|dir (dir uses one JSON file per task)",
                "default": _DEFAULT_STORE,
            },
            "task_list_id": {
                "type": "string",
                "description": "Optional task list id. If set, uses ~/.ouro/tasks/<task_list_id>/ as the store root (dir backend).",
            },
            "goal": {"type": "string", "description": "Plan goal (hydrate/create)"},
            "id": {"type": "string", "description": "Task id (get/update)"},
            "subject": {"type": "string", "description": "Task subject (create)"},
            "description": {"type": "string", "description": "Task description (create)"},
            "active_form": {"type": "string", "description": "Active form (create/update)"},
            "blocked_by": {
                "type": "array",
                "description": "Dependency task ids",
                "items": {"type": "string"},
            },
            "status": {
                "type": "string",
                "description": "pending|in_progress|completed|failed|deleted",
            },
            "owner": {
                "type": "string",
                "description": "Owner label (agent name/worktree path/etc)",
            },
            "summary": {"type": "string", "description": "Short summary to attach"},
            "artifacts": {
                "type": "array",
                "description": "Artifact paths",
                "items": {"type": "string"},
            },
            "errors": {"type": "string", "description": "Error text to attach"},
            "metadata": {"type": "object", "description": "Arbitrary metadata"},
            "limit": {
                "type": "integer",
                "description": "Limit results (list/runnable)",
                "minimum": 1,
                "default": 50,
            },
        }

    def __init__(self) -> None:
        self._plan = TaskPlan()
        self._store: str = _DEFAULT_STORE
        self._path: str = _DEFAULT_TASKS_PATH
        self._task_list_id: str | None = None

    async def execute(
        self,
        operation: str,
        path: str = _DEFAULT_TASKS_PATH,
        store: str = _DEFAULT_STORE,
        task_list_id: str | None = None,
        **kwargs,
    ) -> str:
        op = (operation or "").strip().lower()
        if not op:
            return "Error: operation is required"

        self._store, self._path, self._task_list_id = _resolve_store_path(
            path=path,
            store=store,
            task_list_id=task_list_id,
        )

        # In "dir" mode we assume multiple sessions may share state. Always re-hydrate
        # on entry to avoid stale in-memory state.
        if self._store == "dir" and op not in {"hydrate"}:
            hydrate_out = self._hydrate(goal="")
            if hydrate_out.startswith("Error:"):
                return hydrate_out

        if op == "hydrate":
            goal = (kwargs.get("goal") or "").strip()
            return self._hydrate(goal=goal)

        if op == "sync":
            return self._sync()

        if op == "create":
            subject = (kwargs.get("subject") or "").strip()
            description = (kwargs.get("description") or "").strip()
            active_form = (kwargs.get("active_form") or "").strip()
            blocked_by = kwargs.get("blocked_by") or []
            metadata = kwargs.get("metadata") or {}
            if not subject or not description:
                return "Error: create requires subject and description"
            task_id = self._alloc_id()
            rec = TaskRecord(
                id=task_id,
                subject=subject,
                description=description,
                active_form=active_form,
                blocked_by=[str(x).strip() for x in blocked_by if str(x).strip()],
                metadata=metadata if isinstance(metadata, dict) else {},
            )
            self._plan.tasks[task_id] = rec
            self._sync_best_effort()
            return json.dumps({"id": task_id}, ensure_ascii=True)

        if op == "list":
            limit = _to_pos_int(kwargs.get("limit"), default=50)
            items = []
            for _id, t in sorted(self._plan.tasks.items(), key=lambda kv: kv[0])[:limit]:
                items.append(
                    {
                        "id": t.id,
                        "status": t.status,
                        "owner": t.owner,
                        "blocked_by": t.blocked_by,
                        "subject": t.subject,
                    }
                )
            return json.dumps({"goal": self._plan.goal, "tasks": items}, ensure_ascii=True)

        if op == "get":
            task_id = (kwargs.get("id") or "").strip()
            if not task_id:
                return "Error: get requires id"
            t = self._plan.tasks.get(task_id)
            if not t:
                return "Error: task not found"
            return json.dumps(t.to_dict(), ensure_ascii=True)

        if op == "update":
            task_id = (kwargs.get("id") or "").strip()
            if not task_id:
                return "Error: update requires id"
            t = self._plan.tasks.get(task_id)
            if not t:
                return "Error: task not found"

            # Claude-style lifecycle: "deleted" means remove the task record.
            status_in = kwargs.get("status")
            if status_in is not None and str(status_in).strip().lower() == "deleted":
                self._plan.tasks.pop(task_id, None)
                self._sync_best_effort()
                return "OK"

            for field_name in [
                "status",
                "owner",
                "subject",
                "description",
                "active_form",
                "summary",
                "errors",
            ]:
                if field_name in kwargs and kwargs[field_name] is not None:
                    setattr(t, field_name, str(kwargs[field_name]).strip())

            if "blocked_by" in kwargs and kwargs["blocked_by"] is not None:
                raw = kwargs["blocked_by"]
                if isinstance(raw, list):
                    t.blocked_by = [str(x).strip() for x in raw if str(x).strip()]

            if "artifacts" in kwargs and kwargs["artifacts"] is not None:
                raw = kwargs["artifacts"]
                if isinstance(raw, list):
                    t.artifacts = [str(x).strip() for x in raw if str(x).strip()]

            if "metadata" in kwargs and kwargs["metadata"] is not None:
                raw = kwargs["metadata"]
                if isinstance(raw, dict):
                    t.metadata = raw

            self._sync_best_effort()
            return "OK"

        if op == "delete":
            task_id = (kwargs.get("id") or "").strip()
            if not task_id:
                return "Error: delete requires id"
            if task_id not in self._plan.tasks:
                return "Error: task not found"
            self._plan.tasks.pop(task_id, None)
            self._sync_best_effort()
            return "OK"

        if op == "runnable":
            limit = _to_pos_int(kwargs.get("limit"), default=50)
            runnable = self._runnable_ids()
            return json.dumps({"runnable": runnable[:limit]}, ensure_ascii=True)

        return f"Error: unknown operation '{op}'"

    # ------------------------------------------------------------------
    # Internal state / persistence
    # ------------------------------------------------------------------

    def _hydrate(self, *, goal: str) -> str:
        if self._store == "dir":
            return self._hydrate_dir(goal=goal)
        return self._hydrate_markdown(goal=goal)

    def _sync(self) -> str:
        if self._store == "dir":
            return self._sync_dir()
        return self._sync_markdown()

    def _sync_best_effort(self) -> None:
        # Best-effort persistence so the manager doesn't need to remember to call sync.
        try:
            if self._store == "dir":
                self._sync_dir()
            else:
                self._sync_markdown()
        except Exception:
            return

    # ------------------------------------------------------------------
    # Backends
    # ------------------------------------------------------------------

    def _hydrate_markdown(self, *, goal: str) -> str:
        path = Path(self._path)
        if not path.exists():
            self._plan = TaskPlan(goal=goal or "")
            self._sync_best_effort()
            return "OK"

        lock_path = path.with_suffix(path.suffix + ".lock")
        _touch(lock_path)
        with _file_lock(lock_path):
            try:
                data = path.read_text(encoding="utf-8")
            except OSError:
                return "Error: failed to read tasks file"

        payload = _extract_json_block(data)
        if payload is None:
            return "Error: tasks.md missing JSON block"

        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            return "Error: invalid JSON in tasks.md"

        plan = TaskPlan(
            version=int(obj.get("version", 1) or 1),
            goal=str(obj.get("goal", "")).strip(),
            tasks={},
        )
        for item in obj.get("tasks") or []:
            if not isinstance(item, dict):
                continue
            rec = TaskRecord.from_dict(item)
            if rec.id:
                plan.tasks[rec.id] = rec

        if goal:
            plan.goal = goal
        self._plan = plan
        return "OK"

    def _sync_markdown(self) -> str:
        path = Path(self._path)
        lock_path = path.with_suffix(path.suffix + ".lock")
        _touch(lock_path)
        with _file_lock(lock_path):
            try:
                path.write_text(_render_tasks_md(self._plan), encoding="utf-8")
            except OSError:
                return "Error: failed to write tasks file"
        return "OK"

    def _hydrate_dir(self, *, goal: str) -> str:
        root = Path(self._path)
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError:
            return "Error: failed to create task list dir"

        lock_path = root / _DIR_LOCK
        _touch(lock_path)

        with _file_lock(lock_path):
            meta = {}
            meta_path = root / _DIR_META
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    meta = {}

            plan = TaskPlan(
                version=int(meta.get("version", 1) or 1),
                goal=str(meta.get("goal", "")).strip(),
                tasks={},
            )

            for p in sorted(root.glob("*.json")):
                if p.name.startswith("_"):
                    continue
                try:
                    obj = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    continue

                rec = TaskRecord(
                    id=str(obj.get("id") or "").strip(),
                    status=str(obj.get("status") or "pending").strip() or "pending",
                    owner=(str(obj.get("owner")).strip() if obj.get("owner") is not None else None),
                    blocked_by=[
                        str(x).strip() for x in (obj.get("blockedBy") or []) if str(x).strip()
                    ],
                    subject=str(obj.get("subject") or "").strip(),
                    description=str(obj.get("description") or "").strip(),
                    active_form=str(obj.get("activeForm") or "").strip(),
                    metadata=obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {},
                    summary=str(obj.get("summary") or "").strip(),
                    artifacts=[
                        str(x).strip() for x in (obj.get("artifacts") or []) if str(x).strip()
                    ],
                    errors=str(obj.get("errors") or "").strip(),
                )
                if rec.id:
                    plan.tasks[rec.id] = rec

            if goal:
                plan.goal = goal
            self._plan = plan
            # Ensure meta exists even if empty (avoid re-locking).
            self._sync_dir_unlocked(root)

        return "OK"

    def _sync_dir(self) -> str:
        root = Path(self._path)
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError:
            return "Error: failed to create task list dir"

        lock_path = root / _DIR_LOCK
        _touch(lock_path)

        with _file_lock(lock_path):
            self._sync_dir_unlocked(root)

        return "OK"

    def _sync_dir_unlocked(self, root: Path) -> None:
        """Write dir backend files assuming caller already holds the list lock."""
        blocks = _compute_blocks(self._plan.tasks)

        meta_path = root / _DIR_META
        meta_obj = {"version": int(self._plan.version), "goal": self._plan.goal}
        _atomic_write_json(meta_path, meta_obj)

        desired_files = set()
        for tid, t in self._plan.tasks.items():
            fname = _safe_task_filename(tid)
            desired_files.add(fname)
            obj = {
                "id": t.id,
                "status": t.status,
                "owner": t.owner,
                "blockedBy": list(t.blocked_by or []),
                "blocks": sorted(blocks.get(tid, [])),
                "subject": t.subject,
                "description": t.description,
                "activeForm": t.active_form,
                "metadata": dict(t.metadata or {}),
                # Ouro extensions (not part of Claude's minimal fields).
                "summary": t.summary,
                "artifacts": list(t.artifacts or []),
                "errors": t.errors,
            }
            _atomic_write_json(root / fname, obj)

        for p in root.glob("*.json"):
            if p.name.startswith("_"):
                continue
            if p.name not in desired_files:
                with suppress(OSError):
                    p.unlink()

        # Reserve groups file path (some implementations keep this).
        _touch(root / _DIR_GROUPS)

        # Optional Claude-like behavior: clear completed task tickets once everything is done.
        # Disabled by default because Ouro generally prefers auditability.
        cleanup = os.getenv("OURO_TASKS_AUTO_CLEANUP", "0").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if (
            cleanup
            and self._plan.tasks
            and all(t.status == "completed" for t in self._plan.tasks.values())
        ):
            for p in root.glob("*.json"):
                if p.name.startswith("_"):
                    continue
                with suppress(OSError):
                    p.unlink()

    def _alloc_id(self) -> str:
        max_n = -1
        for task_id in self._plan.tasks:
            m = re.match(r"^T([0-9]+)$", task_id)
            if not m:
                continue
            try:
                n = int(m.group(1))
            except ValueError:
                continue
            max_n = max(max_n, n)
        return f"T{max_n + 1}"

    def _runnable_ids(self) -> list[str]:
        def is_completed(tid: str) -> bool:
            t = self._plan.tasks.get(tid)
            return bool(t and t.status == "completed")

        out: list[str] = []
        for _id, t in sorted(self._plan.tasks.items(), key=lambda kv: kv[0]):
            if t.status != "pending":
                continue
            if t.owner:
                continue
            # Static deps: all blocked_by completed.
            if any((dep and not is_completed(dep)) for dep in (t.blocked_by or [])):
                continue
            out.append(t.id)
        return out


def _to_pos_int(value: Any, *, default: int) -> int:
    if value is None:
        return default
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return n if n > 0 else default


def _extract_json_block(text: str) -> str | None:
    # Single fenced JSON block. Keep parsing deterministic and avoid fragile regex escaping.
    if not text:
        return None
    lower = text.lower()
    start = lower.find("```json")
    if start < 0:
        return None
    start_nl = text.find("\n", start)
    if start_nl < 0:
        return None
    end = text.find("```", start_nl + 1)
    if end < 0:
        return None
    payload = text[start_nl + 1 : end].strip()
    if not payload.startswith("{"):
        return None
    return payload


def _render_tasks_md(plan: TaskPlan) -> str:
    payload = json.dumps(plan.to_dict(), indent=2, ensure_ascii=True) + "\n"
    return "\n".join(
        [
            "# Task Plan",
            "",
            "This file is machine-written. Edit the JSON block only if you know what you're doing.",
            "",
            "```json",
            payload.rstrip("\n"),
            "```",
            "",
        ]
    )


def _resolve_store_path(
    *,
    path: str,
    store: str,
    task_list_id: str | None,
) -> tuple[str, str, str | None]:
    """Resolve persistence backend and path.

    - Default is markdown `tasks.md` in the current working directory.
    - If task_list_id is provided, use a Claude-like on-disk directory store rooted at
      `~/.ouro/tasks/<task_list_id>/`.
    """
    store_norm = (store or _DEFAULT_STORE).strip().lower() or _DEFAULT_STORE
    env_tid = os.getenv("OURO_TASK_LIST_ID", "").strip()
    tid = (task_list_id or env_tid or "").strip() or None

    if tid:
        root = Path.home() / ".ouro" / "tasks" / tid
        return ("dir", str(root), tid)

    path_norm = (path or _DEFAULT_TASKS_PATH).strip() or _DEFAULT_TASKS_PATH
    if store_norm not in {"markdown", "dir"}:
        store_norm = _DEFAULT_STORE
    return (store_norm, path_norm, None)


def _safe_task_filename(task_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", task_id or "").strip("_")
    if not safe:
        safe = "task"
    return f"{safe}.json"


def _compute_blocks(tasks: dict[str, TaskRecord]) -> dict[str, set[str]]:
    blocks: dict[str, set[str]] = {tid: set() for tid in tasks}
    for tid, t in tasks.items():
        for dep in t.blocked_by or []:
            if dep in blocks:
                blocks[dep].add(tid)
    return blocks


def _atomic_write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    data = json.dumps(obj, indent=2, ensure_ascii=True) + "\n"
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, path)


def _touch(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
    except OSError:
        return


class _file_lock:
    """Best-effort cross-process lock (Unix via fcntl)."""

    def __init__(self, lock_path: Path) -> None:
        self._lock_path = lock_path
        self._fh = None

    def __enter__(self):
        try:
            import fcntl  # type: ignore

            self._fh = open(self._lock_path, "a+", encoding="utf-8")
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        except Exception:
            self._fh = None
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if self._fh is not None:
                import fcntl  # type: ignore

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
                self._fh.close()
        except Exception:
            pass
        self._fh = None
        return False
