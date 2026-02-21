"""Tests for task graph tools."""

from __future__ import annotations

import json

import pytest

from agent.tasks import TaskStore
from tools.task_tools import TaskCreateTool, TaskGetTool, TaskListTool, TaskUpdateTool


@pytest.mark.asyncio
async def test_task_create_list_get_and_availability_gates_on_dependencies():
    store = TaskStore()
    create = TaskCreateTool(store)
    update = TaskUpdateTool(store)
    tlist = TaskListTool(store)
    tget = TaskGetTool(store)

    created_a = json.loads(await create.execute(content="Do A", activeForm="Doing A"))
    a_id = created_a["task"]["id"]

    created_b = json.loads(
        await create.execute(content="Do B", activeForm="Doing B", blockedBy=[a_id])
    )
    b_id = created_b["task"]["id"]

    listed = json.loads(await tlist.execute())
    assert listed["available"] == [a_id]
    assert "debugTasksMd" in listed
    assert "tasksMd" in listed
    assert f"- [ ] {b_id}: Do B" in listed["tasksMd"]
    assert "blockedBy:" in listed["tasksMd"]

    got_b = json.loads(await tget.execute(id=b_id))
    assert got_b["task"]["blockedBy"] == [a_id]

    # Completing A should make B available.
    await update.execute(id=a_id, status="completed")
    listed2 = json.loads(await tlist.execute())
    assert b_id in listed2["available"]


@pytest.mark.asyncio
async def test_task_update_add_blocks_and_remove_blocks_mutates_reverse_edges():
    store = TaskStore()
    create = TaskCreateTool(store)
    update = TaskUpdateTool(store)
    tget = TaskGetTool(store)

    a = json.loads(await create.execute(content="Do A", activeForm="Doing A"))
    b = json.loads(await create.execute(content="Do B", activeForm="Doing B"))
    a_id = a["task"]["id"]
    b_id = b["task"]["id"]

    await update.execute(id=a_id, addBlocks=[b_id])
    got_b = json.loads(await tget.execute(id=b_id))
    assert a_id in got_b["task"]["blockedBy"]

    await update.execute(id=a_id, removeBlocks=[b_id])
    got_b2 = json.loads(await tget.execute(id=b_id))
    assert a_id not in got_b2["task"]["blockedBy"]


@pytest.mark.asyncio
async def test_task_update_add_and_remove_blocked_by_edits_dependencies():
    store = TaskStore()
    create = TaskCreateTool(store)
    update = TaskUpdateTool(store)
    tget = TaskGetTool(store)

    a = json.loads(await create.execute(content="Do A", activeForm="Doing A"))
    b = json.loads(await create.execute(content="Do B", activeForm="Doing B"))
    a_id = a["task"]["id"]
    b_id = b["task"]["id"]

    await update.execute(id=b_id, addBlockedBy=[a_id])
    got_b = json.loads(await tget.execute(id=b_id))
    assert got_b["task"]["blockedBy"] == [a_id]

    await update.execute(id=b_id, removeBlockedBy=[a_id])
    got_b2 = json.loads(await tget.execute(id=b_id))
    assert got_b2["task"]["blockedBy"] == []
