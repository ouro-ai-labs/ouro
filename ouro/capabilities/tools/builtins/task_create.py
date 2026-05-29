"""TaskCreateTool — create a new persistent task."""

from __future__ import annotations

from typing import Any

from ouro.capabilities.tasks.store import TaskStore
from ouro.capabilities.tools.base import BaseTool


class TaskCreateTool(BaseTool):
    """Create a new task in the persistent task store.

    Use this when you need to break down work into trackable, persistent
    tasks that can be claimed by agents and have dependencies.
    """

    def __init__(self, store: TaskStore):
        self._store = store

    @property
    def name(self) -> str:
        return "task_create"

    @property
    def description(self) -> str:
        return """Create a new task in the persistent task store.

WHEN TO USE:
- Breaking down complex work into smaller, trackable tasks
- Creating tasks that may have dependencies on other tasks
- Assigning work to specific agents (in swarm mode)

EXAMPLES:
- Create a task: {"subject": "Fix authentication bug", "description": "..."}
- Create with dependencies: {"subject": "Refactor DB", "description": "...", "blockedBy": ["1"]}

The task will be created with status "pending" and can be claimed later."""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "subject": {
                "type": "string",
                "description": "Short imperative title for the task (e.g., 'Fix authentication bug')",
            },
            "description": {
                "type": "string",
                "description": "Detailed description of what the task involves",
            },
            "activeForm": {
                "type": "string",
                "description": "Present continuous form (e.g., 'Fixing authentication bug'). Optional.",
            },
            "blockedBy": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of task IDs that must complete before this task can start. Optional.",
            },
            "metadata": {
                "type": "object",
                "description": "Optional key-value metadata for the task.",
            },
        }

    async def execute(
        self,
        subject: str,
        description: str,
        activeForm: str = "",
        blockedBy: list[str] | None = None,
        metadata: dict | None = None,
        **kwargs: Any,
    ) -> str:
        if not subject or not description:
            return "Error: Both 'subject' and 'description' are required"

        task = self._store.create(
            subject=subject,
            description=description,
            activeForm=activeForm or None,
            blockedBy=blockedBy,
            metadata=metadata,
        )

        # Wire blockedBy dependencies bidirectionally
        if blockedBy:
            for blocker_id in blockedBy:
                blocker = self._store.get(blocker_id)
                if blocker:
                    new_blocks = list(blocker.blocks)
                    if task.id not in new_blocks:
                        new_blocks.append(task.id)
                    self._store.update(blocker_id, blocks=new_blocks)
            # Update task's blockedBy
            self._store.update(task.id, blockedBy=list(blockedBy))

        return f"Created task #{task.id}: {task.subject}"
