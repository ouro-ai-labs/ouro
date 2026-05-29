"""TaskGetTool — get details of a single task."""

from __future__ import annotations

from typing import Any

from ouro.capabilities.tasks.store import TaskStore
from ouro.capabilities.tools.base import BaseTool


class TaskGetTool(BaseTool):
    """Get detailed information about a specific task.

    Use this when you need to inspect a task's full details including
    description, dependencies, metadata, etc.
    """

    readonly = True

    def __init__(self, store: TaskStore):
        self._store = store

    @property
    def name(self) -> str:
        return "task_get"

    @property
    def description(self) -> str:
        return """Get detailed information about a specific task.

WHEN TO USE:
- Inspect a task's full description and metadata
- Check a task's dependencies (blocks / blockedBy)
- Verify ownership before claiming

Parameters:
- taskId: ID of the task to retrieve"""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "taskId": {
                "type": "string",
                "description": "ID of the task to retrieve",
            },
        }

    async def execute(self, taskId: str, **kwargs: Any) -> str:
        task = self._store.get(taskId)
        if not task:
            return f"Error: Task #{taskId} not found"

        lines = [
            f"Task #{task.id}: {task.subject}",
            f"Status: {task.status.value}",
            f"Owner: {task.owner or '(unassigned)'}",
            f"Description: {task.description}",
        ]

        if task.activeForm:
            lines.append(f"Active Form: {task.activeForm}")
        if task.blocks:
            lines.append(f"Blocks: {', '.join(f'#{b}' for b in task.blocks)}")
        if task.blockedBy:
            lines.append(f"Blocked By: {', '.join(f'#{b}' for b in task.blockedBy)}")
        if task.metadata:
            lines.append(f"Metadata: {task.metadata}")

        lines.append(f"Created: {task.created_at}")
        if task.completed_at:
            lines.append(f"Completed: {task.completed_at}")

        return "\n".join(lines)
