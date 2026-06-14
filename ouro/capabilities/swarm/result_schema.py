"""Structured task-result helpers for swarm execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class TaskExecutionResult:
    """Structured task result persisted into Task V2 metadata."""

    summary: str
    outcome: str = "completed"
    artifacts: list[str] | None = None
    followup_tasks: list[dict[str, Any]] | None = None

    def to_metadata(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "outcome": self.outcome,
            "artifacts": list(self.artifacts or []),
            "followup_tasks": list(self.followup_tasks or []),
        }


def coerce_task_result(raw: str) -> TaskExecutionResult:
    """Wrap a plain worker response into the structured result shape."""
    return TaskExecutionResult(summary=raw.strip() or "Task completed")
