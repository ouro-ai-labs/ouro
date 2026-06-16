"""Structured task-result helpers for swarm execution."""

from __future__ import annotations

import json
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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskExecutionResult:
        return cls(
            summary=str(data.get("summary", "Task completed")),
            outcome=str(data.get("outcome", "completed")),
            artifacts=[str(item) for item in data.get("artifacts", [])],
            followup_tasks=[
                item for item in data.get("followup_tasks", []) if isinstance(item, dict)
            ],
        )


def coerce_task_result(raw: str) -> TaskExecutionResult:
    """Parse a worker result, preferring explicit JSON over free text.

    Workers may either return plain text or a JSON object shaped like
    ``TaskExecutionResult.to_metadata()``.
    """
    text = raw.strip()
    if not text:
        return TaskExecutionResult(summary="Task completed", artifacts=[], followup_tasks=[])

    parsed = _extract_json_object(text)
    if isinstance(parsed, dict):
        return TaskExecutionResult.from_dict(parsed)

    return TaskExecutionResult(summary=text, artifacts=[], followup_tasks=[])


def _extract_json_object(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        return None
    try:
        payload = json.loads(text[start:end])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None
