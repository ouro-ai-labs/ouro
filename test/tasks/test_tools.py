"""Unit tests for Task V2 tool suite (TaskCreate/Update/List/Get/Delete)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from ouro.capabilities.tasks.store import TaskStore
from ouro.capabilities.tools.builtins.task_create import TaskCreateTool
from ouro.capabilities.tools.builtins.task_delete import TaskDeleteTool
from ouro.capabilities.tools.builtins.task_get import TaskGetTool
from ouro.capabilities.tools.builtins.task_list import TaskListTool
from ouro.capabilities.tools.builtins.task_update import TaskUpdateTool


@pytest.fixture
async def tools():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "tasks.db"
        store = TaskStore(db_path)
        yield {
            "create": TaskCreateTool(store),
            "update": TaskUpdateTool(store),
            "list": TaskListTool(store),
            "get": TaskGetTool(store),
            "delete": TaskDeleteTool(store),
            "store": store,
        }


class TestTaskCreateTool:
    async def test_create_basic(self, tools: dict) -> None:
        result = await tools["create"].execute(subject="Fix bug", description="Fix auth")
        assert "Created task #1" in result
        assert "Fix bug" in result

    async def test_create_missing_fields(self, tools: dict) -> None:
        result = await tools["create"].execute(subject="", description="")
        assert "Error" in result

    async def test_create_with_dependencies(self, tools: dict) -> None:
        t1 = tools["store"].create(subject="Blocker", description="...")
        result = await tools["create"].execute(
            subject="Blocked", description="...", blockedBy=[t1.id]
        )
        assert "Created task" in result

        # Check bidirectional wiring
        blocker = tools["store"].get(t1.id)
        assert blocker is not None
        assert any(t.id == "2" for t in tools["store"].list_all() if t.id in blocker.blocks)


class TestTaskUpdateTool:
    async def test_update_status(self, tools: dict) -> None:
        task = tools["store"].create(subject="Test", description="...")
        result = await tools["update"].execute(taskId=task.id, status="completed")
        assert "Updated" in result
        assert "completed" in result

    async def test_update_owner(self, tools: dict) -> None:
        task = tools["store"].create(subject="Test", description="...")
        result = await tools["update"].execute(taskId=task.id, owner="alice")
        assert "alice" in result

    async def test_delete_via_status(self, tools: dict) -> None:
        task = tools["store"].create(subject="Test", description="...")
        result = await tools["update"].execute(taskId=task.id, status="deleted")
        assert "Deleted" in result
        assert tools["store"].get(task.id) is None

    async def test_update_add_dependency(self, tools: dict) -> None:
        t1 = tools["store"].create(subject="Blocker", description="...")
        t2 = tools["store"].create(subject="Blocked", description="...")
        result = await tools["update"].execute(taskId=t2.id, addBlockedBy=[t1.id])
        assert "Updated" in result

        updated = tools["store"].get(t2.id)
        assert updated is not None
        assert t1.id in updated.blockedBy

    async def test_update_missing_task(self, tools: dict) -> None:
        result = await tools["update"].execute(taskId="999", status="completed")
        assert "Error" in result
        assert "not found" in result


class TestTaskListTool:
    async def test_list_empty(self, tools: dict) -> None:
        result = await tools["list"].execute()
        assert "No tasks" in result

    async def test_list_with_tasks(self, tools: dict) -> None:
        tools["store"].create(subject="Task A", description="...")
        tools["store"].create(subject="Task B", description="...")
        result = await tools["list"].execute()
        assert "Task A" in result
        assert "Task B" in result
        assert "Summary:" in result


class TestTaskGetTool:
    async def test_get_existing(self, tools: dict) -> None:
        task = tools["store"].create(subject="Test", description="Details here")
        result = await tools["get"].execute(taskId=task.id)
        assert "Test" in result
        assert "Details here" in result
        assert "pending" in result

    async def test_get_missing(self, tools: dict) -> None:
        result = await tools["get"].execute(taskId="999")
        assert "Error" in result
        assert "not found" in result


class TestTaskDeleteTool:
    async def test_delete_existing(self, tools: dict) -> None:
        task = tools["store"].create(subject="Test", description="...")
        result = await tools["delete"].execute(taskId=task.id)
        assert "Deleted" in result
        assert tools["store"].get(task.id) is None

    async def test_delete_missing(self, tools: dict) -> None:
        result = await tools["delete"].execute(taskId="999")
        assert "Error" in result
        assert "not found" in result
