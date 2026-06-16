"""Unit tests for SwarmCoordinator."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from ouro.capabilities.builder import AgentBuilder
from ouro.capabilities.swarm.coordinator import SwarmCoordinator
from ouro.capabilities.tasks.models import TaskStatus
from ouro.capabilities.tasks.store import TaskStore


class FakeLLM:
    """Fake LLM for testing that returns predictable responses."""

    def __init__(self, responses=None):
        self.responses = responses or ["Done"]
        self.call_count = 0

    async def call_async(self, **kwargs):
        from ouro.core.llm import LLMResponse, StopReason

        response_text = self.responses[self.call_count % len(self.responses)]
        self.call_count += 1
        return LLMResponse(
            content=response_text,
            stop_reason=StopReason.STOP,
        )

    def extract_text(self, response):
        return response.content

    def extract_tool_calls(self, response):
        return []

    def to_message(self, response):
        from ouro.core.llm import LLMMessage

        return LLMMessage(role="assistant", content=response.content)

    @property
    def supports_tools(self) -> bool:
        return True


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "tasks.db"
        yield TaskStore(db_path)


@pytest.fixture
def coordinator(store: TaskStore):
    def builder_factory(agent_id: str):
        fake_llm = FakeLLM()
        return (
            AgentBuilder()
            .with_llm(fake_llm)
            .with_agent_swarm(enabled=True, store_path=str(store._db_path), agent_id=agent_id)
            .without_memory()
        )

    return SwarmCoordinator(store, builder_factory, heartbeat_interval=5.0)


class TestSwarmCoordinator:
    async def test_spawn_agents(self, coordinator: SwarmCoordinator) -> None:
        ids = await coordinator.spawn_agents(n=3)
        assert len(ids) == 3
        assert len(coordinator.agents) == 3
        assert "agent-1" in ids

    async def test_remove_agent(self, coordinator: SwarmCoordinator) -> None:
        await coordinator.spawn_agents(n=1)
        assert "agent-1" in coordinator.agents

        result = await coordinator.remove_agent("agent-1")
        assert result is True
        assert "agent-1" not in coordinator.agents

    async def test_remove_agent_not_found(self, coordinator: SwarmCoordinator) -> None:
        result = await coordinator.remove_agent("nonexistent")
        assert result is False

    async def test_task_assignment(self, coordinator: SwarmCoordinator, store: TaskStore) -> None:
        store.create(subject="Test task", description="A simple test task")
        await coordinator.spawn_agents(n=1)
        await coordinator._assign_tasks()

        task = store.get("1")
        assert task is not None
        assert task.owner == "agent-1"
        assert task.status == TaskStatus.IN_PROGRESS

    async def test_task_completion(self, coordinator: SwarmCoordinator, store: TaskStore) -> None:
        store.create(subject="Test task", description="A simple test task")
        await coordinator.spawn_agents(n=1)
        await coordinator._assign_tasks()
        await asyncio.sleep(0.5)

        task = store.get("1")
        assert task is not None
        assert task.status == TaskStatus.COMPLETED

    async def test_task_completion_persists_structured_json_result(self, store: TaskStore) -> None:
        def builder_factory(agent_id: str):
            fake_llm = FakeLLM(
                responses=[
                    '{"summary": "Implemented the change", "artifacts": ["test/swarm/test_swarm.py"], "followup_tasks": []}'
                ]
            )
            return (
                AgentBuilder()
                .with_llm(fake_llm)
                .with_agent_swarm(enabled=True, store_path=str(store._db_path), agent_id=agent_id)
                .without_memory()
            )

        custom = SwarmCoordinator(store, builder_factory, heartbeat_interval=0.1)
        store.create(subject="Test task", description="A simple test task")
        await custom.spawn_agents(n=1)
        await custom._assign_tasks()
        await asyncio.sleep(0.5)

        task = store.get("1")
        assert task is not None
        assert task.metadata["result"]["summary"] == "Implemented the change"
        assert task.metadata["result"]["artifacts"] == ["test/swarm/test_swarm.py"]

    async def test_get_status(self, coordinator: SwarmCoordinator, store: TaskStore) -> None:
        store.create(subject="Task 1", description="...")
        store.create(subject="Task 2", description="...")
        store.create(subject="Task 3", description="...")

        await coordinator.spawn_agents(n=2)

        status = coordinator.get_status()
        assert status.total_tasks == 3
        assert status.pending == 3
        assert status.in_progress == 0
        assert status.completed == 0
        assert len(status.available_agents) == 2

    async def test_health_check_recovery(
        self, coordinator: SwarmCoordinator, store: TaskStore
    ) -> None:
        store.create(subject="Test task", description="...")
        await coordinator.spawn_agents(n=1)
        store.claim("1", "agent-1")
        coordinator.agents["agent-1"].task_ids.append("1")
        coordinator.agents["agent-1"].last_heartbeat = 0

        await coordinator._health_check()

        task = store.get("1")
        assert task is not None
        assert task.owner is None
        assert task.status == TaskStatus.PENDING
        assert "1" not in coordinator.agents["agent-1"].task_ids

    async def test_run_until_done(self, coordinator: SwarmCoordinator, store: TaskStore) -> None:
        store.create(subject="Task 1", description="...")
        store.create(subject="Task 2", description="...")

        await coordinator.spawn_agents(n=2)
        coordinator.heartbeat_interval = 0.1

        try:
            await asyncio.wait_for(coordinator.run_until_done(), timeout=5.0)
        except asyncio.TimeoutError:
            coordinator.shutdown()
            raise

        tasks = store.list_all()
        assert all(t.status == TaskStatus.COMPLETED for t in tasks)
