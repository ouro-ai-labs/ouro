"""TaskListTool — list all tasks with status and ownership."""

from __future__ import annotations

from typing import Any

from ouro.capabilities.tasks.engine import TaskEngine
from ouro.capabilities.tasks.store import TaskStore
from ouro.capabilities.tools.base import BaseTool
from ouro.core.loop import NullProgressSink


class TaskListTool(BaseTool):
    """List all tasks in the persistent task store.

    Use this to check progress, find available work, or see what
    teammates are working on.
    """

    readonly = True

    def __init__(self, store: TaskStore, progress=None):
        self._engine = TaskEngine(store)
        self._progress = progress or NullProgressSink()

    @property
    def name(self) -> str:
        return "task_list"

    @property
    def description(self) -> str:
        return """List all tasks with their status, owner, and blockers.

WHEN TO USE:
- Check overall progress
- Find available tasks to claim
- See what teammates are working on
- Identify blocked tasks and their dependencies

Returns a formatted list with summary statistics.
No parameters required."""

    @property
    def parameters(self) -> dict[str, Any]:
        return {}

    def execute_structured(self) -> dict[str, Any]:
        """Return a structured task-list event payload for UI/event sinks."""
        view = self._engine.get_task_list_view()
        task_lines = view["task_lines"] if isinstance(view.get("task_lines"), list) else []
        summary = view["summary"] if isinstance(view.get("summary"), str) else None
        counts = view["counts"] if isinstance(view.get("counts"), dict) else {}
        return {
            "kind": "task_list",
            "payload": {
                "task_lines": task_lines,
                "summary": summary,
                "counts": counts,
            },
        }

    async def execute(self, **kwargs: Any) -> str:
        structured = self.execute_structured()
        self._progress.event(structured["kind"], structured["payload"])
        return self._engine.format_task_list()
