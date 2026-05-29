"""TaskDeleteTool — delete a task permanently."""

from __future__ import annotations

from typing import Any

from ouro.capabilities.tasks.store import TaskStore
from ouro.capabilities.tools.base import BaseTool


class TaskDeleteTool(BaseTool):
    """Delete a task from the persistent task store.

    Use this to permanently remove a task. This also cleans up
    references in other tasks' blocks/blockedBy lists.
    """

    def __init__(self, store: TaskStore):
        self._store = store

    @property
    def name(self) -> str:
        return "task_delete"

    @property
    def description(self) -> str:
        return """Delete a task permanently.

WHEN TO USE:
- Remove a task that is no longer needed
- Clean up after a task was created by mistake

Note: This also removes the task from other tasks' dependency lists.

Parameters:
- taskId: ID of the task to delete"""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "taskId": {
                "type": "string",
                "description": "ID of the task to delete",
            },
        }

    async def execute(self, taskId: str, **kwargs: Any) -> str:
        task = self._store.get(taskId)
        if not task:
            return f"Error: Task #{taskId} not found"

        self._store.delete(taskId)
        return f"Deleted task #{taskId}: {task.subject}"
