"""Task engine — dependency resolution and high-level operations."""

from __future__ import annotations

from ouro.core.log import get_logger

from .models import Task, TaskStatus
from .store import TaskStore

logger = get_logger(__name__)


class TaskEngine:
    """High-level task operations built on TaskStore.

    Provides convenience methods for dependency management and batch
    operations that would be awkward to express as individual store calls.
    """

    def __init__(self, store: TaskStore) -> None:
        self.store = store

    # ------------------------------------------------------------------
    # Dependency helpers
    # ------------------------------------------------------------------

    def add_dependency(self, task_id: str, blocked_by: str) -> Task | None:
        """Make task_id blocked by blocked_by (bidirectional).

        Returns the updated task, or None if not found.
        """
        task = self.store.get(task_id)
        blocker = self.store.get(blocked_by)
        if not task or not blocker:
            return None

        # Update task.blockedBy
        new_blocked_by = list(task.blockedBy)
        if blocked_by not in new_blocked_by:
            new_blocked_by.append(blocked_by)

        # Update blocker.blocks
        new_blocks = list(blocker.blocks)
        if task_id not in new_blocks:
            new_blocks.append(task_id)

        self.store.update(blocked_by, blocks=new_blocks)
        return self.store.update(task_id, blockedBy=new_blocked_by)

    def remove_dependency(self, task_id: str, blocked_by: str) -> Task | None:
        """Remove the blocked_by dependency from task_id (bidirectional).

        Returns the updated task, or None if not found.
        """
        task = self.store.get(task_id)
        blocker = self.store.get(blocked_by)
        if not task or not blocker:
            return None

        new_blocked_by = [b for b in task.blockedBy if b != blocked_by]
        new_blocks = [b for b in blocker.blocks if b != task_id]

        self.store.update(blocked_by, blocks=new_blocks)
        return self.store.update(task_id, blockedBy=new_blocked_by)

    def get_dependency_chain(self, task_id: str) -> list[str]:
        """Return all task ids that must complete before task_id can start.

        Includes direct and transitive blockers (DFS).
        """
        visited: set[str] = set()
        stack = [task_id]
        chain: list[str] = []

        while stack:
            current_id = stack.pop()
            if current_id in visited:
                continue
            visited.add(current_id)

            task = self.store.get(current_id)
            if not task:
                continue

            for blocker_id in task.blockedBy:
                if blocker_id not in visited:
                    chain.append(blocker_id)
                    stack.append(blocker_id)

        return chain

    # ------------------------------------------------------------------
    # Batch operations
    # ------------------------------------------------------------------

    def create_with_dependencies(
        self,
        subject: str,
        description: str,
        blocked_by: list[str] | None = None,
        blocks: list[str] | None = None,
        **kwargs,
    ) -> Task | None:
        """Create a task and wire up dependencies in one shot.

        blocked_by: task ids that block this new task
        blocks: task ids that this new task blocks
        """
        task = self.store.create(subject=subject, description=description, **kwargs)

        # Wire blocked_by (this task is blocked by existing tasks)
        if blocked_by:
            for blocker_id in blocked_by:
                blocker = self.store.get(blocker_id)
                if blocker:
                    new_blocks = list(blocker.blocks)
                    if task.id not in new_blocks:
                        new_blocks.append(task.id)
                    self.store.update(blocker_id, blocks=new_blocks)

            # Update this task's blockedBy
            self.store.update(task.id, blockedBy=list(blocked_by))

        # Wire blocks (this task blocks existing tasks)
        if blocks:
            for blocked_id in blocks:
                blocked = self.store.get(blocked_id)
                if blocked:
                    new_blocked_by = list(blocked.blockedBy)
                    if task.id not in new_blocked_by:
                        new_blocked_by.append(task.id)
                    self.store.update(blocked_id, blockedBy=new_blocked_by)

            # Update this task's blocks
            self.store.update(task.id, blocks=list(blocks))

        # Return fully updated task
        return self.store.get(task.id)

    def complete_task(self, task_id: str) -> Task | None:
        """Mark a task as completed and return it."""
        return self.store.update(task_id, status=TaskStatus.COMPLETED)

    def get_available_tasks(self) -> list[Task]:
        """Return all tasks that are ready to be claimed."""
        return self.store.list_available()

    def get_blocked_tasks(self) -> list[Task]:
        """Return tasks that have unresolved blockers."""
        all_tasks = self.store.list_all()
        completed_ids = {t.id for t in all_tasks if t.status == TaskStatus.COMPLETED}
        return [
            t for t in all_tasks if t.blockedBy and not all(b in completed_ids for b in t.blockedBy)
        ]

    def format_task_list(self, tasks: list[Task] | None = None) -> str:
        """Format tasks for display, similar to TodoList.format_list()."""
        if tasks is None:
            tasks = self.store.list_all()

        if not tasks:
            return "No tasks in the list"

        all_tasks = {t.id: t for t in self.store.list_all()}
        completed_ids = {t.id for t in all_tasks.values() if t.status == TaskStatus.COMPLETED}

        lines = ["Current Task List:"]
        for task in tasks:
            owner_str = f" ({task.owner})" if task.owner else ""
            blockers = [b for b in task.blockedBy if b not in completed_ids]
            blocked_str = (
                f" [blocked by {', '.join(f'#{b}' for b in blockers)}]" if blockers else ""
            )

            display = task.activeForm or task.subject
            lines.append(f"#{task.id} [{task.status.value}]{owner_str} {display}{blocked_str}")

        # Summary
        pending = sum(1 for t in tasks if t.status == TaskStatus.PENDING)
        in_progress = sum(1 for t in tasks if t.status == TaskStatus.IN_PROGRESS)
        completed = sum(1 for t in tasks if t.status == TaskStatus.COMPLETED)

        lines.append(
            f"\nSummary: {completed} completed, {in_progress} in progress, {pending} pending"
        )

        return "\n".join(lines)
