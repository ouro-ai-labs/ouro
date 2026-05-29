"""SQLite-backed persistent task store with WAL mode.

Uses aiosqlite for async access and BEGIN IMMEDIATE for atomic claim.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ouro.core.log import get_logger

from .models import Task, TaskStatus

logger = get_logger(__name__)


@dataclass
class ClaimResult:
    """Result of a task claim attempt."""

    success: bool
    reason: (
        Literal[
            "task_not_found",
            "already_claimed",
            "already_resolved",
            "blocked",
            "agent_busy",
        ]
        | None
    ) = None
    task: Task | None = None
    busy_with_tasks: list[str] | None = None
    blocked_by_tasks: list[str] | None = None


class TaskStore:
    """Persistent task store backed by SQLite.

    Each TaskStore instance manages a single task list (one SQLite DB file).
    Multiple agents can share a TaskStore by pointing at the same db_path.
    """

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        # Use stdlib sqlite3 for sync init (schema creation), aiosqlite for async ops
        self._init_db()

    def _init_db(self) -> None:
        """Create tables and indexes if they don't exist."""
        with sqlite3.connect(self._db_path, timeout=30.0) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id          TEXT PRIMARY KEY,
                    subject     TEXT NOT NULL,
                    description TEXT NOT NULL,
                    activeForm  TEXT,
                    owner       TEXT,
                    status      TEXT NOT NULL DEFAULT 'pending',
                    blocks      TEXT NOT NULL DEFAULT '[]',
                    blockedBy   TEXT NOT NULL DEFAULT '[]',
                    metadata    TEXT NOT NULL DEFAULT '{}',
                    created_at  REAL NOT NULL,
                    completed_at REAL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS high_water_mark (
                    task_list_id TEXT PRIMARY KEY,
                    value        INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO high_water_mark (task_list_id, value)
                VALUES ('default', 0)
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_owner ON tasks(owner)")
            conn.commit()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _task_from_row(self, row: sqlite3.Row) -> Task:
        return Task(
            id=row["id"],
            subject=row["subject"],
            description=row["description"],
            activeForm=row["activeForm"],
            owner=row["owner"],
            status=TaskStatus(row["status"]),
            blocks=json.loads(row["blocks"]),
            blockedBy=json.loads(row["blockedBy"]),
            metadata=json.loads(row["metadata"]),
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )

    def _get_next_id(self, conn: sqlite3.Connection) -> str:
        """Atomically increment and return the next task id."""
        cursor = conn.execute(
            "UPDATE high_water_mark SET value = value + 1 WHERE task_list_id = 'default' RETURNING value"
        )
        row = cursor.fetchone()
        return str(row[0])

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(
        self,
        subject: str,
        description: str,
        activeForm: str | None = None,
        owner: str | None = None,
        status: TaskStatus = TaskStatus.PENDING,
        blocks: list[str] | None = None,
        blockedBy: list[str] | None = None,
        metadata: dict | None = None,
    ) -> Task:
        """Create a new task and return it."""
        with sqlite3.connect(self._db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            task_id = self._get_next_id(conn)
            task = Task(
                id=task_id,
                subject=subject,
                description=description,
                activeForm=activeForm,
                owner=owner,
                status=status,
                blocks=blocks or [],
                blockedBy=blockedBy or [],
                metadata=metadata or {},
            )
            conn.execute(
                """
                INSERT INTO tasks (id, subject, description, activeForm, owner, status,
                                   blocks, blockedBy, metadata, created_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.id,
                    task.subject,
                    task.description,
                    task.activeForm,
                    task.owner,
                    task.status.value,
                    json.dumps(task.blocks),
                    json.dumps(task.blockedBy),
                    json.dumps(task.metadata),
                    task.created_at,
                    task.completed_at,
                ),
            )
            conn.commit()
            logger.debug(f"Created task {task.id}: {task.subject}")

        # Wire bidirectional dependencies after commit so other tasks can see this one.
        # We update the *other* task's opposite edge; this task already has the edge
        # that was passed in, so we must not re-add it.
        if blockedBy:
            for blocker_id in blockedBy:
                blocker = self.get(blocker_id)
                if blocker and task.id not in blocker.blocks:
                    new_blocks = list(blocker.blocks)
                    new_blocks.append(task.id)
                    self.update(blocker_id, blocks=new_blocks)
        if blocks:
            for blocked_id in blocks:
                blocked = self.get(blocked_id)
                if blocked and task.id not in blocked.blockedBy:
                    new_blocked_by = list(blocked.blockedBy)
                    new_blocked_by.append(task.id)
                    self.update(blocked_id, blockedBy=new_blocked_by)

        return self.get(task.id) or task

    def get(self, task_id: str) -> Task | None:
        """Get a task by id."""
        with sqlite3.connect(self._db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return self._task_from_row(row) if row else None

    def update(self, task_id: str, **fields) -> Task | None:
        """Update task fields and return the updated task.

        Supported fields: subject, description, activeForm, owner, status,
        blocks, blockedBy, metadata, completed_at.

        Special handling:
        - status='completed' → auto-sets completed_at if not provided
        - status='pending' or 'in_progress' → clears completed_at
        """
        allowed = {
            "subject",
            "description",
            "activeForm",
            "owner",
            "status",
            "blocks",
            "blockedBy",
            "metadata",
            "completed_at",
        }
        updates = {k: v for k, v in fields.items() if k in allowed and v is not ...}
        if not updates:
            return self.get(task_id)

        with sqlite3.connect(self._db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            # Read current task
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not row:
                return None

            # Handle status transitions
            if "status" in updates:
                new_status = updates["status"]
                if isinstance(new_status, TaskStatus):
                    new_status = new_status.value
                updates["status"] = new_status
                if new_status == "completed" and "completed_at" not in updates:
                    import time

                    updates["completed_at"] = time.time()
                elif new_status in ("pending", "in_progress"):
                    updates["completed_at"] = None

            # Serialize JSON fields
            for key in ("blocks", "blockedBy", "metadata"):
                if key in updates:
                    updates[key] = json.dumps(updates[key])

            # Build SET clause
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [task_id]
            conn.execute(f"UPDATE tasks SET {set_clause} WHERE id = ?", values)
            conn.commit()

            # Return updated task
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return self._task_from_row(row)

    def delete(self, task_id: str) -> bool:
        """Delete a task and clean up references in blocks/blockedBy."""
        with sqlite3.connect(self._db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not row:
                return False

            # Remove references from other tasks' blocks/blockedBy
            all_tasks = conn.execute("SELECT id, blocks, blockedBy FROM tasks").fetchall()
            for t_id, blocks_json, blocked_by_json in all_tasks:
                blocks = json.loads(blocks_json)
                blocked_by = json.loads(blocked_by_json)
                changed = False
                if task_id in blocks:
                    blocks.remove(task_id)
                    changed = True
                if task_id in blocked_by:
                    blocked_by.remove(task_id)
                    changed = True
                if changed:
                    conn.execute(
                        "UPDATE tasks SET blocks = ?, blockedBy = ? WHERE id = ?",
                        (json.dumps(blocks), json.dumps(blocked_by), t_id),
                    )

            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            conn.commit()
            logger.debug(f"Deleted task {task_id}")
            return True

    def list_all(self) -> list[Task]:
        """Return all tasks ordered by creation time."""
        with sqlite3.connect(self._db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM tasks ORDER BY created_at").fetchall()
            return [self._task_from_row(r) for r in rows]

    def list_available(self, agent_id: str | None = None) -> list[Task]:
        """Return tasks that are pending, unowned, and not blocked."""
        tasks = self.list_all()
        completed_ids = {t.id for t in tasks if t.status == TaskStatus.COMPLETED}
        available = [t for t in tasks if t.is_available(completed_ids)]
        return available

    # ------------------------------------------------------------------
    # Claim (atomic busy-check)
    # ------------------------------------------------------------------

    def claim(self, task_id: str, agent_id: str) -> ClaimResult:
        """Atomically claim a task for an agent.

        Returns ClaimResult with success=True and the task on success,
        or success=False with a reason on failure.
        """
        with sqlite3.connect(self._db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            try:
                # 1. Read target task
                row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
                if not row:
                    conn.rollback()
                    return ClaimResult(success=False, reason="task_not_found")

                task = self._task_from_row(row)

                # 2. Already claimed by someone else?
                if task.owner is not None and task.owner != agent_id:
                    conn.rollback()
                    return ClaimResult(
                        success=False,
                        reason="already_claimed",
                        task=task,
                    )

                # 3. Already resolved?
                if task.status == TaskStatus.COMPLETED:
                    conn.rollback()
                    return ClaimResult(
                        success=False,
                        reason="already_resolved",
                        task=task,
                    )

                # 4. Blocked?
                all_tasks = conn.execute("SELECT id, status FROM tasks").fetchall()
                completed_ids = {
                    r["id"] for r in all_tasks if r["status"] == TaskStatus.COMPLETED.value
                }
                unresolved_blockers = [b for b in task.blockedBy if b not in completed_ids]
                if unresolved_blockers:
                    conn.rollback()
                    return ClaimResult(
                        success=False,
                        reason="blocked",
                        task=task,
                        blocked_by_tasks=unresolved_blockers,
                    )

                # 5. Agent already busy with another in_progress task?
                busy_rows = conn.execute(
                    "SELECT id FROM tasks WHERE owner = ? AND status = ?",
                    (agent_id, TaskStatus.IN_PROGRESS.value),
                ).fetchall()
                busy_tasks = [r["id"] for r in busy_rows]
                if busy_tasks and task_id not in busy_tasks:
                    conn.rollback()
                    return ClaimResult(
                        success=False,
                        reason="agent_busy",
                        task=task,
                        busy_with_tasks=busy_tasks,
                    )

                # 6. Claim!

                conn.execute(
                    "UPDATE tasks SET owner = ?, status = ?, completed_at = ? WHERE id = ?",
                    (agent_id, TaskStatus.IN_PROGRESS.value, None, task_id),
                )
                conn.commit()

                # Return updated task
                row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
                updated = self._task_from_row(row)
                logger.debug(f"Agent '{agent_id}' claimed task {task_id}")
                return ClaimResult(success=True, task=updated)

            except Exception:
                conn.rollback()
                raise

    def unassign(self, task_id: str) -> Task | None:
        """Remove owner from a task (e.g., on agent crash or timeout)."""
        return self.update(task_id, owner=None, status=TaskStatus.PENDING)

    def get_agent_tasks(self, agent_id: str) -> list[Task]:
        """Return all tasks owned by an agent."""
        with sqlite3.connect(self._db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM tasks WHERE owner = ? ORDER BY created_at",
                (agent_id,),
            ).fetchall()
            return [self._task_from_row(r) for r in rows]
