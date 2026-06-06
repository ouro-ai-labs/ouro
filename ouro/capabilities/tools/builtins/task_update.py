"""TaskUpdateTool — update task fields, status, dependencies, and ownership."""

from __future__ import annotations

from typing import Any

from ouro.capabilities.tasks.models import TaskStatus
from ouro.capabilities.tasks.store import TaskStore
from ouro.capabilities.tools.base import BaseTool
from ouro.core.loop import NullProgressSink


class TaskUpdateTool(BaseTool):
    """Update an existing task in the persistent task store.

    Use this to change status, assign ownership, add/remove dependencies,
    or edit task content.
    """

    def __init__(self, store: TaskStore, progress=None):
        self._store = store
        self._progress = progress or NullProgressSink()

    @property
    def name(self) -> str:
        return "task_update"

    @property
    def description(self) -> str:
        return """Update an existing task.

WHEN TO USE:
- Mark a task as in_progress or completed
- Assign/unassign an owner
- Add or remove task dependencies
- Edit task subject or description

CRITICAL RULES:
- To claim a task: set owner to your agent name and status to "in_progress"
- To complete: set status to "completed"
- To delete: set status to "deleted" (permanently removes the task)
- addBlocks / removeBlocks: manage which tasks this task blocks
- addBlockedBy / removeBlockedBy: manage which tasks block this task

EXAMPLES:
- Claim: {"taskId": "1", "owner": "alice", "status": "in_progress"}
- Complete: {"taskId": "1", "status": "completed"}
- Add dependency: {"taskId": "2", "addBlockedBy": ["1"]}
- Delete: {"taskId": "1", "status": "deleted"}"""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "taskId": {
                "type": "string",
                "description": "ID of the task to update",
            },
            "subject": {
                "type": "string",
                "description": "New subject/title. Optional.",
            },
            "description": {
                "type": "string",
                "description": "New description. Optional.",
            },
            "activeForm": {
                "type": "string",
                "description": "New active form. Optional.",
            },
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "completed", "deleted"],
                "description": "New status. Use 'deleted' to remove the task.",
            },
            "owner": {
                "type": "string",
                "description": "Agent name to assign/unassign. Set to empty string to unassign.",
            },
            "addBlocks": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Task IDs to add to this task's blocks list. Optional.",
            },
            "removeBlocks": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Task IDs to remove from this task's blocks list. Optional.",
            },
            "addBlockedBy": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Task IDs to add to this task's blockedBy list. Optional.",
            },
            "removeBlockedBy": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Task IDs to remove from this task's blockedBy list. Optional.",
            },
            "metadata": {
                "type": "object",
                "description": "Merge these key-value pairs into the task's metadata. Optional.",
            },
        }

    async def execute(
        self,
        taskId: str,
        subject: str = "",
        description: str = "",
        activeForm: str = "",
        status: str = "",
        owner: str = "",
        addBlocks: list[str] | None = None,
        removeBlocks: list[str] | None = None,
        addBlockedBy: list[str] | None = None,
        removeBlockedBy: list[str] | None = None,
        metadata: dict | None = None,
        **kwargs: Any,
    ) -> str:
        task = self._store.get(taskId)
        if not task:
            return f"Error: Task #{taskId} not found"

        # Handle deletion
        if status == "deleted":
            self._store.delete(taskId)
            return f"Deleted task #{taskId}"

        # Build update fields
        updates: dict[str, Any] = {}
        if subject:
            updates["subject"] = subject
        if description:
            updates["description"] = description
        if activeForm:
            updates["activeForm"] = activeForm
        if status:
            if status not in ("pending", "in_progress", "completed"):
                return f"Error: Invalid status '{status}'. Must be: pending, in_progress, completed, or deleted"
            updates["status"] = TaskStatus(status)
        if owner != "":
            # Empty string means unassign
            updates["owner"] = owner if owner else None

        # Handle dependency changes bidirectionally
        current_blocks = list(task.blocks)
        current_blocked_by = list(task.blockedBy)

        if addBlocks:
            for bid in addBlocks:
                if bid not in current_blocks:
                    current_blocks.append(bid)
                    # Update the blocked task's blockedBy
                    blocked = self._store.get(bid)
                    if blocked and taskId not in blocked.blockedBy:
                        new_bb = list(blocked.blockedBy)
                        new_bb.append(taskId)
                        self._store.update(bid, blockedBy=new_bb)

        if removeBlocks:
            for bid in removeBlocks:
                if bid in current_blocks:
                    current_blocks.remove(bid)
                    # Update the blocked task's blockedBy
                    blocked = self._store.get(bid)
                    if blocked and taskId in blocked.blockedBy:
                        new_bb = [b for b in blocked.blockedBy if b != taskId]
                        self._store.update(bid, blockedBy=new_bb)

        if addBlockedBy:
            for bid in addBlockedBy:
                if bid not in current_blocked_by:
                    current_blocked_by.append(bid)
                    # Update the blocker task's blocks
                    blocker = self._store.get(bid)
                    if blocker and taskId not in blocker.blocks:
                        new_b = list(blocker.blocks)
                        new_b.append(taskId)
                        self._store.update(bid, blocks=new_b)

        if removeBlockedBy:
            for bid in removeBlockedBy:
                if bid in current_blocked_by:
                    current_blocked_by.remove(bid)
                    # Update the blocker task's blocks
                    blocker = self._store.get(bid)
                    if blocker and taskId in blocker.blocks:
                        new_b = [b for b in blocker.blocks if b != taskId]
                        self._store.update(bid, blocks=new_b)

        if current_blocks != list(task.blocks):
            updates["blocks"] = current_blocks
        if current_blocked_by != list(task.blockedBy):
            updates["blockedBy"] = current_blocked_by

        # Merge metadata
        if metadata:
            merged = dict(task.metadata)
            merged.update(metadata)
            updates["metadata"] = merged

        if not updates:
            return f"No changes for task #{taskId}"

        updated = self._store.update(taskId, **updates)
        if not updated:
            return f"Error: Failed to update task #{taskId}"

        status_str = f"status={updated.status.value}" if status else ""
        owner_str = f"owner={updated.owner}" if owner != "" else ""
        changes = ", ".join(filter(None, [status_str, owner_str]))
        display = updated.activeForm or updated.subject
        line = f"[{updated.status.value}] #{updated.id}"
        if updated.owner:
            line += f" ({updated.owner})"
        line += f" {display}"
        self._progress.event(
            "task_status",
            {
                "line": line,
                "summary": f"Updated task #{taskId}: {changes or 'fields updated'}",
                "title": "Task Updated",
            },
        )
        return f"Updated task #{taskId}: {changes or 'fields updated'}"
