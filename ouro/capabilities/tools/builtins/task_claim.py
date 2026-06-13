"""TaskClaimTool — atomically claim a task for the current agent."""

from __future__ import annotations

from typing import Any

from ouro.capabilities.tasks.store import TaskStore
from ouro.capabilities.tools.base import BaseTool
from ouro.core.loop import NullProgressSink, ProgressEvent


class TaskClaimTool(BaseTool):
    """Claim a task from the persistent task store.

    Use this when you want to take ownership of a task and start working on it.
    The claim is atomic — if another agent already claimed it, you will be told.
    """

    def __init__(self, store: TaskStore, agent_id: str | None = None, progress=None):
        self._store = store
        self._agent_id = agent_id
        self._progress = progress or NullProgressSink()

    def set_agent_id(self, agent_id: str) -> None:
        """Late-bind the agent identity (used by AgentBuilder)."""
        self._agent_id = agent_id

    @property
    def name(self) -> str:
        return "task_claim"

    @property
    def description(self) -> str:
        return """Claim a task to start working on it.

WHEN TO USE:
- You want to take ownership of an available task
- You need to prevent other agents from working on the same task

CRITICAL RULES:
- Only claim tasks with status "pending" and no owner
- The task must not be blocked by unresolved dependencies
- You can only have ONE in_progress task at a time

Parameters:
- taskId: ID of the task to claim
- agentId: (optional) Your agent identifier. If omitted, uses the default.

Returns:
- Success: "Claimed task #{id}: {subject}"
- Failure: Error message explaining why (already claimed, blocked, busy, etc.)"""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "taskId": {
                "type": "string",
                "description": "ID of the task to claim",
            },
            "agentId": {
                "type": "string",
                "description": "Your agent identifier (optional, uses default if omitted)",
            },
        }

    async def execute(self, taskId: str, agentId: str = "", **kwargs: Any) -> str:
        owner = agentId or self._agent_id
        if not owner:
            return (
                "Error: No agent identifier provided. Pass agentId parameter or configure the tool."
            )

        result = self._store.claim(taskId, owner)

        if result.success:
            assert result.task is not None
            display = result.task.activeForm or result.task.subject
            self._progress.emit(
                ProgressEvent(
                    kind="task_status",
                    payload={
                        "line": f"[in_progress] #{taskId} ({owner}) {display}",
                        "summary": f"Claimed task #{taskId}: {result.task.subject}",
                        "title": "Task Claimed",
                    },
                )
            )
            return f"Claimed task #{taskId}: {result.task.subject}"

        # Failure cases
        if result.reason == "task_not_found":
            return f"Error: Task #{taskId} not found"
        if result.reason == "already_claimed":
            assert result.task is not None
            return f"Error: Task #{taskId} is already claimed by {result.task.owner}"
        if result.reason == "already_resolved":
            return f"Error: Task #{taskId} is already completed"
        if result.reason == "blocked":
            blockers = result.blocked_by_tasks or []
            return f"Error: Task #{taskId} is blocked by unfinished tasks: {', '.join(f'#{b}' for b in blockers)}"
        if result.reason == "agent_busy":
            busy = result.busy_with_tasks or []
            return (
                f"Error: You are already working on task(s) {', '.join(f'#{b}' for b in busy)}. "
                f"Complete or unassign them before claiming a new task."
            )

        return f"Error: Failed to claim task #{taskId}"
