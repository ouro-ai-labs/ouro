"""Structured trace event types for ouro runtime observability."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

TraceStatus = Literal["started", "completed", "failed", "event"]


class TraceEventType(StrEnum):
    """High-level event categories emitted by ouro tracing."""

    RUN = "run"
    AGENT = "agent"
    TASK = "task"
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    MEMORY = "memory"
    PLAN = "plan"
    VERIFY = "verify"
    ERROR = "error"
    LOG = "log"


@dataclass(frozen=True, slots=True)
class TraceError:
    """Bounded error details safe to serialize in trace events."""

    type: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"type": self.type, "message": self.message}


@dataclass(frozen=True, slots=True)
class TraceEvent:
    """Append-only trace event emitted by spans and tracers."""

    event_id: str
    run_id: str
    span_id: str
    parent_span_id: str | None
    timestamp: datetime
    event_type: str
    name: str
    status: TraceStatus
    attributes: dict[str, Any] = field(default_factory=dict)
    agent_id: str | None = None
    task_id: str | None = None
    duration_ms: int | None = None
    error: TraceError | None = None
    links: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""
        data: dict[str, Any] = {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "timestamp": self.timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "event_type": self.event_type,
            "name": self.name,
            "status": self.status,
            "attributes": self.attributes,
        }
        if self.agent_id is not None:
            data["agent_id"] = self.agent_id
        if self.task_id is not None:
            data["task_id"] = self.task_id
        if self.duration_ms is not None:
            data["duration_ms"] = self.duration_ms
        if self.error is not None:
            data["error"] = self.error.to_dict()
        if self.links:
            data["links"] = list(self.links)
        return data


def utc_now() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(UTC)
