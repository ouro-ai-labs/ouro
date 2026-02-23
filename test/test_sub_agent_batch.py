"""Tests for the sub_agent_batch tool."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass

import pytest

from agent.tasks import TaskStore
from agent.tool_executor import ToolExecutor
from llm import LLMMessage
from tools.sub_agent_batch import SubAgentBatchTool
from tools.task_tools import (
    TaskCreateTool,
    TaskGetManyTool,
    TaskGetTool,
    TaskListTool,
    TaskUpdateTool,
)


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
    def __init__(
        self,
        tool_executor: ToolExecutor,
        probe: _ConcurrencyProbe | None = None,
        task_store: TaskStore | None = None,
        output_text: str | None = None,
    ):
        self.tool_executor = tool_executor
        self._probe = probe
        self.last_prompt: str | None = None
        self.task_store = task_store
        self._output_text = output_text

        class _ShortTerm:
            def __init__(self):
                self._messages: list[LLMMessage] = []

            def add_message(self, message: LLMMessage) -> None:
                self._messages.append(message)

            def get_messages(self):
                return list(self._messages)

        class _Memory:
            def __init__(self):
                self.short_term = _ShortTerm()

        self.memory = _Memory()

    async def _react_loop(self, messages, tools, use_memory, save_to_memory, task: str = "") -> str:
        content = messages[0].content
        self.last_prompt = content
        match = re.search(r"<task_id>(.*?)</task_id>", content, re.DOTALL)
        assert match is not None
        task_id = match.group(1).strip()

        if self._probe is not None:
            await self._probe.enter()
            await asyncio.sleep(0.05)

        if self._probe is not None:
            await self._probe.exit()

        if self._output_text is not None:
            return self._output_text
        return f"result for {task_id}"


@pytest.mark.asyncio
async def test_sub_agent_batch_runs_workers_and_applies_task_updates():
    store = TaskStore()
    create = TaskCreateTool(store)
    update = TaskUpdateTool(store)
    tget = TaskGetTool(store)
    tlist = TaskListTool(store)

    executor = ToolExecutor([create, update, tget, TaskGetManyTool(store), tlist])
    agent = _FakeAgent(executor, task_store=store)
    tool = SubAgentBatchTool(agent)

    a = json.loads(await create.execute(content="Do A", activeForm="Doing A"))
    b = json.loads(await create.execute(content="Do B", activeForm="Doing B"))
    a_id = a["task"]["id"]
    b_id = b["task"]["id"]

    result = json.loads(
        await tool.execute(runs=[{"taskId": a_id}, {"taskId": b_id}], maxParallel=2)
    )
    assert result["ok"] is True
    assert {r["taskId"] for r in result["results"]} == {a_id, b_id}
    assert all(r["ok"] is True for r in result["results"])
    assert {u["id"] for u in result["updates"]} == {a_id, b_id}
    assert all(u["status"] == "completed" for u in result["updates"])
    assert all(u.get("replaceDetail") is True for u in result["updates"])
    assert all(isinstance(u.get("detail", ""), str) and u["detail"] for u in result["updates"])
    assert set(result["appliedUpdates"]) == {a_id, b_id}
    assert result["updateErrors"] == []

    got_a = json.loads(await TaskGetTool(store).execute(id=a_id))
    got_b = json.loads(await TaskGetTool(store).execute(id=b_id))
    assert got_a["task"]["status"] == "completed"
    assert got_b["task"]["status"] == "completed"
    assert "result for" in got_a["task"]["detail"]
    assert "result for" in got_b["task"]["detail"]

    # Replay should still be safe and idempotent.
    await update.execute(updates=result["updates"])
    got_a2 = json.loads(await TaskGetTool(store).execute(id=a_id))
    got_b2 = json.loads(await TaskGetTool(store).execute(id=b_id))
    assert got_a2["task"]["status"] == "completed"
    assert got_b2["task"]["status"] == "completed"


@pytest.mark.asyncio
async def test_sub_agent_batch_respects_max_parallel():
    store = TaskStore()
    create = TaskCreateTool(store)
    update = TaskUpdateTool(store)
    tget = TaskGetTool(store)
    tlist = TaskListTool(store)

    probe = _ConcurrencyProbe(lock=asyncio.Lock())
    executor = ToolExecutor([create, update, tget, TaskGetManyTool(store), tlist])
    agent = _FakeAgent(executor, probe=probe, task_store=store)
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

    executor = ToolExecutor([create, update, tget, TaskGetManyTool(store), tlist])
    agent = _FakeAgent(executor, task_store=store)
    tool = SubAgentBatchTool(agent)

    created = json.loads(await create.execute(content="Do A", activeForm="Doing A"))
    tid = created["task"]["id"]

    result = json.loads(await tool.execute(runs=[{"taskId": tid}, {"taskId": tid}]))
    assert result["ok"] is False
    assert "duplicate" in result["error"].lower()


@pytest.mark.asyncio
async def test_sub_agent_batch_includes_simplified_context_and_upstream_outputs():
    store = TaskStore()
    create = TaskCreateTool(store)
    update = TaskUpdateTool(store)
    tget = TaskGetTool(store)
    tlist = TaskListTool(store)

    executor = ToolExecutor([create, update, tget, TaskGetManyTool(store), tlist])
    agent = _FakeAgent(executor, task_store=store)
    agent.memory.short_term.add_message(
        LLMMessage(role="user", content="调研《海贼王》里最热门的 5 个角色并分析原因。")
    )
    agent.memory.short_term.add_message(
        LLMMessage(role="assistant", content="我会先识别Top5再分别分析。")
    )
    tool = SubAgentBatchTool(agent)

    upstream = json.loads(
        await create.execute(
            content="识别《海贼王》最热门的5个角色",
            activeForm="识别最热门的5个角色",
            status="completed",
            detail="Top5: 路飞, 索隆, 娜美, 山治, 罗（Trafalgar Law）",
        )
    )
    upstream_id = upstream["task"]["id"]

    created = json.loads(
        await create.execute(
            content="分析罗（Law）为什么受欢迎",
            activeForm="分析罗为什么受欢迎",
            blockedBy=[upstream_id],
        )
    )
    tid = created["task"]["id"]

    call_names: list[str] = []
    original_execute_tool_call = executor.execute_tool_call

    async def _record_execute_tool_call(tool_name: str, params: dict):
        call_names.append(tool_name)
        return await original_execute_tool_call(tool_name, params)

    executor.execute_tool_call = _record_execute_tool_call  # type: ignore[method-assign]

    result = json.loads(
        await tool.execute(runs=[{"taskId": tid, "notes": "只分析《海贼王》的角色"}])
    )
    assert result["ok"] is True
    assert result["results"][0]["usedUpstreamContext"] is True
    assert upstream_id in result["results"][0]["upstreamIncluded"]
    assert result["results"][0]["upstreamIncludedCount"] == 1
    assert result["results"][0]["sharedContextChars"] > 0
    assert "TaskGetMany" in call_names
    assert agent.last_prompt is not None
    assert "<shared_context>" in agent.last_prompt
    assert "<conversation>" in agent.last_prompt
    assert "<upstream_outputs>" in agent.last_prompt
    assert "调研《海贼王》里最热门的 5 个角色" in agent.last_prompt
    assert "Top5:" in agent.last_prompt
    assert "Trafalgar Law" in agent.last_prompt


@pytest.mark.asyncio
async def test_sub_agent_batch_stashes_output_when_auto_apply_is_blocked():
    store = TaskStore()
    create = TaskCreateTool(store)
    update = TaskUpdateTool(store)
    tget = TaskGetTool(store)
    tlist = TaskListTool(store)

    executor = ToolExecutor([create, update, tget, TaskGetManyTool(store), tlist])
    agent = _FakeAgent(executor, task_store=store)
    tool = SubAgentBatchTool(agent)

    dep = json.loads(await create.execute(content="Gate", activeForm="Gating"))
    dep_id = dep["task"]["id"]
    child = json.loads(
        await create.execute(content="Leaf", activeForm="Working leaf", blockedBy=[dep_id])
    )
    child_id = child["task"]["id"]

    result = json.loads(await tool.execute(runs=[{"taskId": child_id}]))
    assert result["ok"] is True
    assert result["appliedUpdates"] == []
    assert len(result["updateErrors"]) == 1
    assert result["updateErrors"][0]["id"] == child_id
    assert "blockedBy incomplete deps" in result["updateErrors"][0]["error"]

    got_child = json.loads(await tget.execute(id=child_id))
    assert got_child["task"]["status"] == "pending"
    assert got_child["task"]["detail"] == ""

    await update.execute(id=dep_id, status="completed", detail="gate done")
    await update.execute(id=child_id, status="completed")
    got_child2 = json.loads(await tget.execute(id=child_id))
    assert got_child2["task"]["status"] == "completed"
    assert "result for" in got_child2["task"]["detail"]


@pytest.mark.asyncio
async def test_sub_agent_batch_preserves_long_detail_without_truncation():
    store = TaskStore()
    create = TaskCreateTool(store)
    tget = TaskGetTool(store)
    tlist = TaskListTool(store)
    update = TaskUpdateTool(store)

    long_output = "L" * 9000
    executor = ToolExecutor([create, update, tget, TaskGetManyTool(store), tlist])
    agent = _FakeAgent(executor, task_store=store, output_text=long_output)
    tool = SubAgentBatchTool(agent)

    created = json.loads(await create.execute(content="Do long task", activeForm="Doing long task"))
    task_id = created["task"]["id"]

    result = json.loads(await tool.execute(runs=[{"taskId": task_id}]))
    assert result["ok"] is True
    assert result["results"][0]["detailChars"] == len(long_output)
    assert result["updates"][0]["detail"] == long_output
    assert result["results"][0]["outputDigest"]
    assert result["results"][0]["outputPreview"]

    got = json.loads(await tget.execute(id=task_id))
    assert got["task"]["status"] == "completed"
    assert got["task"]["detailChars"] == len(long_output)
