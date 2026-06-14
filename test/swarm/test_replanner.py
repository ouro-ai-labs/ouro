"""Tests for dynamic swarm replanning."""

from __future__ import annotations

import tempfile
from pathlib import Path

from ouro.capabilities.swarm.replanner import SwarmReplanner
from ouro.capabilities.tasks.models import TaskStatus
from ouro.capabilities.tasks.store import TaskStore


def test_replanner_adds_followup_tasks_after_completion() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = TaskStore(Path(tmpdir) / "tasks.db")
        task = store.create(subject="Inspect", description="Inspect the repo")
        store.update(
            task.id,
            status=TaskStatus.COMPLETED,
            metadata={
                "result": {
                    "summary": "Found extra work",
                    "followup_tasks": [
                        {
                            "subject": "Implement follow-up",
                            "description": "Handle the newly discovered change",
                            "activeForm": "Implementing follow-up",
                        }
                    ],
                }
            },
        )

        outcome = SwarmReplanner().apply_followups(completed_task_id=task.id, store=store)
        tasks = store.list_all()

    assert len(outcome.created_task_ids) == 1
    assert len(tasks) == 2
    assert tasks[1].blockedBy == [task.id]
    assert tasks[1].subject == "Implement follow-up"
