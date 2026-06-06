"""Unit tests for TaskEngine (dependency resolution and high-level ops)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from ouro.capabilities.tasks.engine import TaskEngine
from ouro.capabilities.tasks.models import TaskStatus
from ouro.capabilities.tasks.store import TaskStore


@pytest.fixture
def engine():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "tasks.db"
        store = TaskStore(db_path)
        yield TaskEngine(store)


class TestAddDependency:
    def test_add_dependency_bidirectional(self, engine: TaskEngine) -> None:
        t1 = engine.store.create(subject="Blocker", description="...")
        t2 = engine.store.create(subject="Blocked", description="...")

        result = engine.add_dependency(t2.id, t1.id)
        assert result is not None
        assert t1.id in result.blockedBy

        # Check blocker.blocks was updated
        blocker = engine.store.get(t1.id)
        assert blocker is not None
        assert t2.id in blocker.blocks

    def test_add_dependency_missing_task(self, engine: TaskEngine) -> None:
        t1 = engine.store.create(subject="Only", description="...")
        result = engine.add_dependency("999", t1.id)
        assert result is None


class TestRemoveDependency:
    def test_remove_dependency_bidirectional(self, engine: TaskEngine) -> None:
        t1 = engine.store.create(subject="Blocker", description="...")
        t2 = engine.store.create(subject="Blocked", description="...", blockedBy=[t1.id])
        # Manually update t1.blocks
        engine.store.update(t1.id, blocks=[t2.id])

        result = engine.remove_dependency(t2.id, t1.id)
        assert result is not None
        assert t1.id not in result.blockedBy

        blocker = engine.store.get(t1.id)
        assert blocker is not None
        assert t2.id not in blocker.blocks


class TestGetDependencyChain:
    def test_direct_dependency(self, engine: TaskEngine) -> None:
        t1 = engine.store.create(subject="A", description="...")
        t2 = engine.store.create(subject="B", description="...", blockedBy=[t1.id])
        chain = engine.get_dependency_chain(t2.id)
        assert t1.id in chain

    def test_transitive_dependency(self, engine: TaskEngine) -> None:
        t1 = engine.store.create(subject="A", description="...")
        t2 = engine.store.create(subject="B", description="...", blockedBy=[t1.id])
        t3 = engine.store.create(subject="C", description="...", blockedBy=[t2.id])
        chain = engine.get_dependency_chain(t3.id)
        assert t1.id in chain
        assert t2.id in chain

    def test_no_dependencies(self, engine: TaskEngine) -> None:
        t1 = engine.store.create(subject="A", description="...")
        chain = engine.get_dependency_chain(t1.id)
        assert chain == []


class TestCreateWithDependencies:
    def test_create_with_blocked_by(self, engine: TaskEngine) -> None:
        t1 = engine.store.create(subject="Blocker", description="...")
        t2 = engine.create_with_dependencies(
            subject="Blocked",
            description="...",
            blocked_by=[t1.id],
        )
        assert t2 is not None
        assert t1.id in t2.blockedBy

        blocker = engine.store.get(t1.id)
        assert blocker is not None
        assert t2.id in blocker.blocks

    def test_create_with_blocks(self, engine: TaskEngine) -> None:
        t1 = engine.store.create(subject="Blocked", description="...")
        t2 = engine.create_with_dependencies(
            subject="Blocker",
            description="...",
            blocks=[t1.id],
        )
        assert t2 is not None
        assert t1.id in t2.blocks

        blocked = engine.store.get(t1.id)
        assert blocked is not None
        assert t2.id in blocked.blockedBy


class TestCompleteTask:
    def test_complete_task(self, engine: TaskEngine) -> None:
        task = engine.store.create(subject="Test", description="...")
        result = engine.complete_task(task.id)
        assert result is not None
        assert result.status == TaskStatus.COMPLETED
        assert result.completed_at is not None


class TestGetAvailableTasks:
    def test_available_tasks(self, engine: TaskEngine) -> None:
        t1 = engine.store.create(subject="Free", description="...")
        engine.store.create(subject="Done", description="...", status=TaskStatus.COMPLETED)
        engine.store.create(subject="Claimed", description="...", owner="alice")

        available = engine.get_available_tasks()
        assert len(available) == 1
        assert available[0].id == t1.id


class TestGetBlockedTasks:
    def test_blocked_tasks(self, engine: TaskEngine) -> None:
        t1 = engine.store.create(subject="Blocker", description="...")
        t2 = engine.store.create(subject="Blocked", description="...", blockedBy=[t1.id])

        blocked = engine.get_blocked_tasks()
        assert len(blocked) == 1
        assert blocked[0].id == t2.id

    def test_no_blocked_tasks(self, engine: TaskEngine) -> None:
        engine.store.create(subject="Free", description="...")
        blocked = engine.get_blocked_tasks()
        assert blocked == []


class TestTaskListView:
    def test_view_empty(self, engine: TaskEngine) -> None:
        view = engine.get_task_list_view()
        assert view["task_lines"] == []
        assert view["summary"] == "No tasks in the list"

    def test_view_contains_counts_and_lines(self, engine: TaskEngine) -> None:
        blocker = engine.store.create(subject="Blocker", description="...")
        engine.store.create(subject="Blocked", description="...", blockedBy=[blocker.id])
        engine.store.create(subject="Running", description="...", status=TaskStatus.IN_PROGRESS)
        engine.store.create(subject="Done", description="...", status=TaskStatus.COMPLETED)

        view = engine.get_task_list_view()
        assert "[blocked] #2 Blocked [waiting for #1]" in view["task_lines"]
        assert view["counts"] == {"done": 1, "running": 1, "blocked": 1, "pending": 1}
        assert view["summary"] == "Summary: 1 done, 1 running, 1 blocked, 1 pending"

class TestFormatTaskList:
    def test_format_empty(self, engine: TaskEngine) -> None:
        assert engine.format_task_list() == "No tasks in the list"

    def test_format_with_tasks(self, engine: TaskEngine) -> None:
        engine.store.create(subject="Task A", description="...")
        engine.store.create(subject="Task B", description="...", owner="alice")
        formatted = engine.format_task_list()
        assert "Tasks:" in formatted
        assert "[pending] #1 Task A" in formatted
        assert "[pending] #2 (alice) Task B" in formatted
        assert "Summary:" in formatted

    def test_format_with_blocked_and_completed_states(self, engine: TaskEngine) -> None:
        blocker = engine.store.create(subject="Blocker", description="...")
        blocked = engine.store.create(subject="Blocked", description="...", blockedBy=[blocker.id])
        engine.store.create(
            subject="Running", description="...", owner="agent-1", status=TaskStatus.IN_PROGRESS
        )
        engine.store.create(subject="Done", description="...", status=TaskStatus.COMPLETED)

        formatted = engine.format_task_list()
        assert f"[blocked] #{blocked.id} Blocked [waiting for #{blocker.id}]" in formatted
        assert "[running] #3 (agent-1) Running" in formatted
        assert "[done] #4 Done" in formatted
        assert "1 done, 1 running, 1 blocked, 1 pending" in formatted
