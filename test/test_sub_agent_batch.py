"""Tests for the sub_agent_batch tool."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass

import pytest

from agent.tasks import TaskStore
from agent.tool_executor import ToolExecutor
from tools.sub_agent_batch import SubAgentBatchTool
from tools.task_tools import TaskCreateTool, TaskGetTool, TaskListTool, TaskUpdateTool


@dataclass
class _ConcurrencyProbe:
    lock: asyncio.Lock
    active: int = 0
    max_active: int = 0

    async def enter(self) -> None:
        async with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)

    async def exit(self) -> None:
        async with self.lock:
            self.active -= 1


class _FakeAgent:
    def __init__(self, tool_executor: ToolExecutor, probe: _ConcurrencyProbe | None = None):
        self.tool_executor = tool_executor
        self._probe = probe

    async def _react_loop(self, messages, tools, use_memory, save_to_memory, task: str = "") -> str:
        content = messages[0].content
        match = re.search(r"<task_id>(.*?)</task_id>", content, re.DOTALL)
        assert match is not None
        task_id = match.group(1).strip()

        if self._probe is not None:
            await self._probe.enter()
            await asyncio.sleep(0.05)

        if self._probe is not None:
            await self._probe.exit()

        return f"result for {task_id}"


@pytest.mark.asyncio
async def test_sub_agent_batch_runs_workers_and_updates_task_status():
    store = TaskStore()
    create = TaskCreateTool(store)
    update = TaskUpdateTool(store)
    tget = TaskGetTool(store)
    tlist = TaskListTool(store)

    executor = ToolExecutor([create, update, tget, tlist])
    agent = _FakeAgent(executor)
    tool = SubAgentBatchTool(agent)

    a = json.loads(await create.execute(content="Do A", activeForm="Doing A"))
    b = json.loads(await create.execute(content="Do B", activeForm="Doing B"))
    a_id = a["task"]["id"]
    b_id = b["task"]["id"]

    result = json.loads(await tool.execute(runs=[{"taskId": a_id}, {"taskId": b_id}], maxParallel=2))
    assert result["ok"] is True
    assert {r["taskId"] for r in result["results"]} == {a_id, b_id}
    assert all(r["ok"] is True for r in result["results"])
    # sub_agent_batch does not update task state; the main agent applies results via TaskUpdate.
    got_a = json.loads(await TaskGetTool(store).execute(id=a_id))
    got_b = json.loads(await TaskGetTool(store).execute(id=b_id))
    assert got_a["task"]["status"] == "pending"
    assert got_b["task"]["status"] == "pending"


@pytest.mark.asyncio
async def test_sub_agent_batch_respects_max_parallel():
    store = TaskStore()
    create = TaskCreateTool(store)
    update = TaskUpdateTool(store)
    tget = TaskGetTool(store)
    tlist = TaskListTool(store)

    probe = _ConcurrencyProbe(lock=asyncio.Lock())
    executor = ToolExecutor([create, update, tget, tlist])
    agent = _FakeAgent(executor, probe=probe)
    tool = SubAgentBatchTool(agent)

    ids = []
    for _ in range(3):
        created = json.loads(await create.execute(content="Do X", activeForm="Doing X"))
        ids.append(created["task"]["id"])

    await tool.execute(runs=[{"taskId": tid} for tid in ids], maxParallel=2)
    assert probe.max_active <= 2
    assert probe.max_active >= 2


@pytest.mark.asyncio
async def test_sub_agent_batch_rejects_duplicate_task_ids():
    store = TaskStore()
    create = TaskCreateTool(store)
    update = TaskUpdateTool(store)
    tget = TaskGetTool(store)
    tlist = TaskListTool(store)

    executor = ToolExecutor([create, update, tget, tlist])
    agent = _FakeAgent(executor)
    tool = SubAgentBatchTool(agent)

    created = json.loads(await create.execute(content="Do A", activeForm="Doing A"))
    tid = created["task"]["id"]

    result = json.loads(await tool.execute(runs=[{"taskId": tid}, {"taskId": tid}]))
    assert result["ok"] is False
    assert "duplicate" in result["error"].lower()
