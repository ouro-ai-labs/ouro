"""Tests for TaskPlanner."""

from __future__ import annotations

from ouro.capabilities.swarm.planner import TaskPlanner


class FakeLLM:
    def __init__(self, response_text: str):
        self.response_text = response_text

    async def call_async(self, **kwargs):
        from ouro.core.llm import LLMResponse, StopReason

        return LLMResponse(content=self.response_text, stop_reason=StopReason.STOP)

    def extract_text(self, response):
        return response.content


class TestTaskPlanner:
    async def test_plan_with_dependencies_is_valid(self) -> None:
        response = """{
          "summary": "Implement feature safely",
          "tasks": [
            {
              "local_id": "inspect",
              "subject": "Inspect implementation",
              "description": "Read the current code",
              "blockedBy": []
            },
            {
              "local_id": "change",
              "subject": "Implement changes",
              "description": "Update the code after inspection",
              "blockedBy": ["inspect"]
            }
          ]
        }"""
        planner = TaskPlanner(FakeLLM(response))
        plan = await planner.plan("Implement feature")

        assert plan.summary == "Implement feature safely"
        assert len(plan.tasks) == 2
        assert plan.tasks[1].blockedBy == ["inspect"]

    async def test_invalid_plan_falls_back_to_single_task(self) -> None:
        response = "not valid json"
        planner = TaskPlanner(FakeLLM(response))
        plan = await planner.plan("Do the work")

        assert len(plan.tasks) == 1
        assert plan.tasks[0].local_id == "task-1"

    async def test_unknown_dependency_rejected_and_falls_back(self) -> None:
        response = """{
          "summary": "Bad plan",
          "tasks": [
            {
              "local_id": "implement",
              "subject": "Implement changes",
              "description": "Update the code",
              "blockedBy": ["missing"]
            }
          ]
        }"""
        planner = TaskPlanner(FakeLLM(response))
        plan = await planner.plan("Do the work")

        assert len(plan.tasks) == 1
        assert plan.tasks[0].subject == "Execute the requested task"

    async def test_too_many_tasks_fall_back_to_single_task(self) -> None:
        response = """{
          "summary": "Overplanned",
          "tasks": [
            {"local_id": "t1", "subject": "T1", "description": "..."},
            {"local_id": "t2", "subject": "T2", "description": "..."},
            {"local_id": "t3", "subject": "T3", "description": "..."},
            {"local_id": "t4", "subject": "T4", "description": "..."},
            {"local_id": "t5", "subject": "T5", "description": "..."},
            {"local_id": "t6", "subject": "T6", "description": "..."},
            {"local_id": "t7", "subject": "T7", "description": "..."},
            {"local_id": "t8", "subject": "T8", "description": "..."},
            {"local_id": "t9", "subject": "T9", "description": "..."}
          ]
        }"""
        planner = TaskPlanner(FakeLLM(response), max_tasks=8)
        plan = await planner.plan("Do the work")

        assert len(plan.tasks) == 1
        assert plan.tasks[0].local_id == "task-1"
