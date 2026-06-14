"""Dynamic task-graph extension helpers for swarm execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ouro.capabilities.swarm.planner import PlannedTask
from ouro.capabilities.tasks.store import TaskStore


@dataclass
class ReplanOutcome:
    created_task_ids: list[str]


class SwarmReplanner:
    """Append follow-up tasks described by completed worker results."""

    def apply_followups(self, *, completed_task_id: str, store: TaskStore) -> ReplanOutcome:
        task = store.get(completed_task_id)
        if task is None:
            return ReplanOutcome(created_task_ids=[])

        result = task.metadata.get("result")
        if not isinstance(result, dict):
            return ReplanOutcome(created_task_ids=[])

        followups = result.get("followup_tasks") or []
        created: list[str] = []
        for item in followups:
            if not isinstance(item, dict):
                continue
            created_task = store.create(
                subject=item.get("subject", "Follow-up task"),
                description=item.get("description", "Generated follow-up task"),
                activeForm=item.get("activeForm"),
                blockedBy=[completed_task_id],
                metadata={"generated_by": completed_task_id, **dict(item.get("metadata", {}))},
            )
            created.append(created_task.id)
        return ReplanOutcome(created_task_ids=created)


def parse_followup_tasks(items: list[dict[str, Any]]) -> list[PlannedTask]:
    """Normalize follow-up task payloads into the planner's task shape."""
    planned: list[PlannedTask] = []
    for index, item in enumerate(items, start=1):
        planned.append(
            PlannedTask(
                local_id=item.get("local_id", f"followup-{index}"),
                subject=item.get("subject", "Follow-up task"),
                description=item.get("description", "Generated follow-up task"),
                activeForm=item.get("activeForm"),
                blockedBy=list(item.get("blockedBy", [])),
                metadata=dict(item.get("metadata", {})),
            )
        )
    return planned
