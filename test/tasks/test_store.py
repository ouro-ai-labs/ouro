"""Unit tests for TaskStore (SQLite-backed persistent task store)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from ouro.capabilities.tasks.models import TaskStatus
from ouro.capabilities.tasks.store import TaskStore


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "tasks.db"
        yield TaskStore(db_path)


class TestCreate:
    def test_create_basic(self, store: TaskStore) -> None:
        task = store.create(subject="Fix bug", description="Fix the auth bug")
        assert task.id == "1"
        assert task.subject == "Fix bug"
        assert task.status == TaskStatus.PENDING
        assert task.owner is None

    def test_create_increments_id(self, store: TaskStore) -> None:
        t1 = store.create(subject="A", description="...")
        t2 = store.create(subject="B", description="...")
        assert t1.id == "1"
        assert t2.id == "2"

    def test_create_with_all_fields(self, store: TaskStore) -> None:
        # Pre-create blocker tasks so the ids exist for bidirectional wiring
        blocker = store.create(subject="Blocker", description="...")
        blocked = store.create(subject="Blocked", description="...")
        task = store.create(
            subject="Refactor DB",
            description="Refactor the database layer",
            activeForm="Refactoring DB",
            owner="alice",
            status=TaskStatus.IN_PROGRESS,
            blocks=[blocked.id],
            blockedBy=[blocker.id],
            metadata={"priority": "high"},
        )
        assert task.activeForm == "Refactoring DB"
        assert task.owner == "alice"
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.blocks == [blocked.id]
        assert task.blockedBy == [blocker.id]
        assert task.metadata == {"priority": "high"}


class TestGet:
    def test_get_existing(self, store: TaskStore) -> None:
        created = store.create(subject="Test", description="...")
        fetched = store.get(created.id)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.subject == "Test"

    def test_get_missing(self, store: TaskStore) -> None:
        assert store.get("999") is None


class TestUpdate:
    def test_update_subject(self, store: TaskStore) -> None:
        task = store.create(subject="Old", description="...")
        updated = store.update(task.id, subject="New")
        assert updated is not None
        assert updated.subject == "New"
        # Other fields unchanged
        assert updated.description == "..."

    def test_update_status_to_completed(self, store: TaskStore) -> None:
        task = store.create(subject="Test", description="...")
        updated = store.update(task.id, status=TaskStatus.COMPLETED)
        assert updated is not None
        assert updated.status == TaskStatus.COMPLETED
        assert updated.completed_at is not None

    def test_update_status_to_pending_clears_completed(self, store: TaskStore) -> None:
        task = store.create(subject="Test", description="...")
        store.update(task.id, status=TaskStatus.COMPLETED)
        updated = store.update(task.id, status=TaskStatus.PENDING)
        assert updated is not None
        assert updated.completed_at is None

    def test_update_owner(self, store: TaskStore) -> None:
        task = store.create(subject="Test", description="...")
        updated = store.update(task.id, owner="alice")
        assert updated is not None
        assert updated.owner == "alice"

    def test_update_unassign_owner(self, store: TaskStore) -> None:
        task = store.create(subject="Test", description="...", owner="alice")
        updated = store.update(task.id, owner=None)
        assert updated is not None
        assert updated.owner is None

    def test_update_missing_task(self, store: TaskStore) -> None:
        assert store.update("999", subject="X") is None


class TestDelete:
    def test_delete_existing(self, store: TaskStore) -> None:
        task = store.create(subject="Test", description="...")
        assert store.delete(task.id) is True
        assert store.get(task.id) is None

    def test_delete_missing(self, store: TaskStore) -> None:
        assert store.delete("999") is False

    def test_delete_cleans_up_references(self, store: TaskStore) -> None:
        t1 = store.create(subject="A", description="...")
        t2 = store.create(subject="B", description="...", blockedBy=[t1.id])
        # t1.blocks should reference t2
        t1_fresh = store.get(t1.id)
        assert t2.id in (t1_fresh.blocks if t1_fresh else [])

        store.delete(t2.id)
        t1_after = store.get(t1.id)
        assert t1_after is not None
        assert t2.id not in t1_after.blocks


class TestListAll:
    def test_list_all_empty(self, store: TaskStore) -> None:
        assert store.list_all() == []

    def test_list_all_ordered(self, store: TaskStore) -> None:
        t1 = store.create(subject="First", description="...")
        t2 = store.create(subject="Second", description="...")
        tasks = store.list_all()
        assert [t.id for t in tasks] == [t1.id, t2.id]


class TestListAvailable:
    def test_available_excludes_completed(self, store: TaskStore) -> None:
        t1 = store.create(subject="Done", description="...")
        store.update(t1.id, status=TaskStatus.COMPLETED)
        t2 = store.create(subject="Pending", description="...")
        available = store.list_available()
        assert len(available) == 1
        assert available[0].id == t2.id

    def test_available_excludes_owned(self, store: TaskStore) -> None:
        store.create(subject="Claimed", description="...", owner="alice")
        t2 = store.create(subject="Free", description="...")
        available = store.list_available()
        assert len(available) == 1
        assert available[0].id == t2.id

    def test_available_excludes_blocked(self, store: TaskStore) -> None:
        t1 = store.create(subject="Blocker", description="...")
        store.create(subject="Blocked", description="...", blockedBy=[t1.id])
        available = store.list_available()
        # Only t1 is available (pending, unowned, not blocked)
        assert len(available) == 1
        assert available[0].id == t1.id

    def test_available_includes_unblocked(self, store: TaskStore) -> None:
        t1 = store.create(subject="Blocker", description="...")
        t2 = store.create(subject="Blocked", description="...", blockedBy=[t1.id])
        store.update(t1.id, status=TaskStatus.COMPLETED)
        available = store.list_available()
        # Now t2 is unblocked
        assert len(available) == 1
        assert available[0].id == t2.id


class TestClaim:
    def test_claim_success(self, store: TaskStore) -> None:
        task = store.create(subject="Test", description="...")
        result = store.claim(task.id, "alice")
        assert result.success is True
        assert result.task is not None
        assert result.task.owner == "alice"
        assert result.task.status == TaskStatus.IN_PROGRESS

    def test_claim_task_not_found(self, store: TaskStore) -> None:
        result = store.claim("999", "alice")
        assert result.success is False
        assert result.reason == "task_not_found"

    def test_claim_already_claimed(self, store: TaskStore) -> None:
        task = store.create(subject="Test", description="...", owner="bob")
        result = store.claim(task.id, "alice")
        assert result.success is False
        assert result.reason == "already_claimed"

    def test_claim_already_resolved(self, store: TaskStore) -> None:
        task = store.create(subject="Test", description="...")
        store.update(task.id, status=TaskStatus.COMPLETED)
        result = store.claim(task.id, "alice")
        assert result.success is False
        assert result.reason == "already_resolved"

    def test_claim_blocked(self, store: TaskStore) -> None:
        t1 = store.create(subject="Blocker", description="...")
        t2 = store.create(subject="Blocked", description="...", blockedBy=[t1.id])
        result = store.claim(t2.id, "alice")
        assert result.success is False
        assert result.reason == "blocked"
        assert result.blocked_by_tasks == [t1.id]

    def test_claim_agent_busy(self, store: TaskStore) -> None:
        t1 = store.create(subject="First", description="...")
        t2 = store.create(subject="Second", description="...")
        store.claim(t1.id, "alice")
        result = store.claim(t2.id, "alice")
        assert result.success is False
        assert result.reason == "agent_busy"
        assert result.busy_with_tasks == [t1.id]

    def test_claim_same_task_again(self, store: TaskStore) -> None:
        """Re-claiming the same in-progress task should succeed."""
        task = store.create(subject="Test", description="...")
        store.claim(task.id, "alice")
        result = store.claim(task.id, "alice")
        assert result.success is True

    def test_claim_after_completion(self, store: TaskStore) -> None:
        task = store.create(subject="Test", description="...")
        store.claim(task.id, "alice")
        store.update(task.id, status=TaskStatus.COMPLETED)
        result = store.claim(task.id, "alice")
        assert result.success is False
        assert result.reason == "already_resolved"


class TestUnassign:
    def test_unassign(self, store: TaskStore) -> None:
        task = store.create(subject="Test", description="...", owner="alice")
        updated = store.unassign(task.id)
        assert updated is not None
        assert updated.owner is None
        assert updated.status == TaskStatus.PENDING


class TestGetAgentTasks:
    def test_get_agent_tasks(self, store: TaskStore) -> None:
        t1 = store.create(subject="Alice's task", description="...", owner="alice")
        store.create(subject="Bob's task", description="...", owner="bob")
        alice_tasks = store.get_agent_tasks("alice")
        assert len(alice_tasks) == 1
        assert alice_tasks[0].id == t1.id


class TestPersistence:
    def test_persistence_across_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tasks.db"
            store1 = TaskStore(db_path)
            task = store1.create(subject="Persistent", description="...")

            store2 = TaskStore(db_path)
            fetched = store2.get(task.id)
            assert fetched is not None
            assert fetched.subject == "Persistent"
