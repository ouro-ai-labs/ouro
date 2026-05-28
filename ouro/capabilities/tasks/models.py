"""Task V2 data models."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    """Status of a task."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


@dataclass
class Task:
    """A persistent task with dependency support.

    Inspired by claude-code's Task V2 schema, adapted for Python + SQLite.
    """

    id: str  # monotonic integer as string
    subject: str  # imperative title
    description: str
    activeForm: str | None = None  # present continuous form
    owner: str | None = None  # agent name / id
    status: TaskStatus = TaskStatus.PENDING
    blocks: list[str] = field(default_factory=list)  # task ids this task blocks
    blockedBy: list[str] = field(default_factory=list)  # task ids blocking this task
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=lambda: time.time())
    completed_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary (JSON-friendly)."""
        return {
            "id": self.id,
            "subject": self.subject,
            "description": self.description,
            "activeForm": self.activeForm,
            "owner": self.owner,
            "status": self.status.value,
            "blocks": self.blocks,
            "blockedBy": self.blockedBy,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Task:
        """Deserialize from dictionary."""
        return cls(
            id=str(data["id"]),
            subject=data["subject"],
            description=data["description"],
            activeForm=data.get("activeForm"),
            owner=data.get("owner"),
            status=TaskStatus(data.get("status", "pending")),
            blocks=list(data.get("blocks", [])),
            blockedBy=list(data.get("blockedBy", [])),
            metadata=dict(data.get("metadata", {})),
            created_at=float(data.get("created_at", time.time())),
            completed_at=float(data["completed_at"]) if data.get("completed_at") else None,
        )

    def is_available(self, completed_ids: set[str]) -> bool:
        """Return True if task is pending, unowned, and all blockers resolved."""
        return (
            self.status == TaskStatus.PENDING
            and self.owner is None
            and all(b in completed_ids for b in self.blockedBy)
        )
