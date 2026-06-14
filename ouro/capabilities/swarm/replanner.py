"""Dynamic task-graph extension helpers for swarm execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ouro.capabilities.swarm.planner import PlannedTask
from ouro.capabilities.tasks.store import TaskStore


@dataclass
class ReplanOutcome:
    created_task_ids: list[str]
    skipped_duplicates: int = 0


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
        normalized = parse_followup_tasks([item for item in followups if isinstance(item, dict)])
        created: list[str] = []
        skipped_duplicates = 0
        for item in normalized:
            if self._would_duplicate_followup(
                completed_task_id=completed_task_id,
                planned=item,
                store=store,
            ):
                skipped_duplicates += 1
                continue
            created_task = store.create(
                subject=item.subject,
                description=item.description,
                activeForm=item.activeForm,
                blockedBy=[completed_task_id],
                metadata={"generated_by": completed_task_id, **item.metadata},
            )
            created.append(created_task.id)
        return ReplanOutcome(created_task_ids=created, skipped_duplicates=skipped_duplicates)

    def _would_duplicate_followup(
        self,
        *,
        completed_task_id: str,
        planned: PlannedTask,
        store: TaskStore,
    ) -> bool:
        for existing in store.list_all():
            if existing.id == completed_task_id:
                continue
            if existing.subject != planned.subject:
                continue
            if existing.description != planned.description:
                continue
            generated_by = existing.metadata.get("generated_by")
            if generated_by == completed_task_id:
                return True
            if completed_task_id in existing.blockedBy:
                return True
        return False


def parse_followup_tasks(items: list[dict[str, Any]]) -> list[PlannedTask]:
    """Normalize follow-up task payloads into the planner's task shape."""
    planned: list[PlannedTask] = []
    for index, item in enumerate(items, start=1):
        metadata = dict(item.get("metadata", {}))
        planned.append(
            PlannedTask(
                local_id=item.get("local_id", f"followup-{index}"),
                subject=str(item.get("subject", "Follow-up task")),
                description=str(item.get("description", "Generated follow-up task")),
                activeForm=str(item.get("activeForm", "Following up on discovered work")),
                blockedBy=[],
                metadata=metadata,
            )
        )
    return planned
