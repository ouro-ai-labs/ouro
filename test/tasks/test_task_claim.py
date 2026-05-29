"""Unit tests for TaskClaimTool."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from ouro.capabilities.tasks.models import TaskStatus
from ouro.capabilities.tasks.store import TaskStore
from ouro.capabilities.tools.builtins.task_claim import TaskClaimTool


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "tasks.db"
        yield TaskStore(db_path)


@pytest.fixture
def tool(store: TaskStore):
    return TaskClaimTool(store, agent_id="alice")


class TestTaskClaimTool:
    async def test_claim_success(self, tool: TaskClaimTool, store: TaskStore) -> None:
        task = store.create(subject="Fix bug", description="Fix auth bug")
        result = await tool.execute(taskId=task.id)
        assert "Claimed" in result
        assert task.id in result

        updated = store.get(task.id)
        assert updated is not None
        assert updated.owner == "alice"
        assert updated.status == TaskStatus.IN_PROGRESS

    async def test_claim_missing_agent_id(self, store: TaskStore) -> None:
        tool = TaskClaimTool(store, agent_id=None)
        task = store.create(subject="Fix bug", description="Fix auth bug")
        result = await tool.execute(taskId=task.id)
        assert "Error" in result
        assert "No agent identifier" in result

    async def test_claim_override_agent_id(self, tool: TaskClaimTool, store: TaskStore) -> None:
        task = store.create(subject="Fix bug", description="Fix auth bug")
        result = await tool.execute(taskId=task.id, agentId="bob")
        assert "Claimed" in result

        updated = store.get(task.id)
        assert updated is not None
        assert updated.owner == "bob"

    async def test_claim_already_claimed(self, tool: TaskClaimTool, store: TaskStore) -> None:
        task = store.create(subject="Fix bug", description="Fix auth bug")
        store.claim(task.id, "bob")

        result = await tool.execute(taskId=task.id)
        assert "Error" in result
        assert "already claimed" in result
        assert "bob" in result

    async def test_claim_completed_task(self, tool: TaskClaimTool, store: TaskStore) -> None:
        task = store.create(subject="Fix bug", description="Fix auth bug")
        store.update(task.id, status=TaskStatus.COMPLETED)

        result = await tool.execute(taskId=task.id)
        assert "Error" in result
        assert "already completed" in result

    async def test_claim_blocked_task(self, tool: TaskClaimTool, store: TaskStore) -> None:
        blocker = store.create(subject="Blocker", description="...")
        task = store.create(subject="Blocked", description="...", blockedBy=[blocker.id])

        result = await tool.execute(taskId=task.id)
        assert "Error" in result
        assert "blocked" in result
        assert blocker.id in result

    async def test_claim_agent_busy(self, tool: TaskClaimTool, store: TaskStore) -> None:
        t1 = store.create(subject="Task 1", description="...")
        t2 = store.create(subject="Task 2", description="...")
        store.claim(t1.id, "alice")

        result = await tool.execute(taskId=t2.id)
        assert "Error" in result
        assert "already working" in result
        assert t1.id in result

    async def test_claim_nonexistent_task(self, tool: TaskClaimTool) -> None:
        result = await tool.execute(taskId="999")
        assert "Error" in result
        assert "not found" in result
