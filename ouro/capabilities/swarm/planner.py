"""Task graph planner for swarm execution.

Converts a complex user request into a Task V2-compatible plan with
explicit dependencies. The first slice focuses on producing a valid DAG
that can be persisted into ``TaskStore`` before runtime scheduling.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ouro.core.llm import LLMMessage
from ouro.core.log import get_logger

logger = get_logger(__name__)


@dataclass
class PlannedTask:
    """A task produced by the planner before persistence."""

    local_id: str
    subject: str
    description: str
    activeForm: str | None = None
    blockedBy: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskPlan:
    """A Task V2-compatible plan for a complex request."""

    summary: str
    tasks: list[PlannedTask]


PLANNER_PROMPT = """You are a task planner for a multi-agent coding system.

Your job is to convert a complex user request into a small Task V2-style task graph.
Return valid JSON matching this schema:

```json
{
  "summary": "Short summary of the plan",
  "tasks": [
    {
      "local_id": "short-stable-id",
      "subject": "Short imperative title",
      "description": "Detailed description of the task",
      "activeForm": "Present continuous form (optional)",
      "blockedBy": ["local-id-of-prerequisite-task"],
      "metadata": {}
    }
  ]
}
```

Rules:
- Create 3 to 6 tasks for genuinely complex requests; use 1 task only if the request is truly atomic.
- Prefer high-level phases or responsibilities over atomic implementation steps.
- Do not exceed 8 tasks under any circumstance.
- Use dependencies whenever one task must wait for another.
- Prefer partially ordered work over pretending tasks are independent.
- Every `local_id` must be unique.
- `blockedBy` may only reference earlier or later task `local_id` values that exist in the same response.
- Keep titles concrete and execution-oriented.
- Do not include cycles.
- If the task is not actually complex, still return a minimal 1-task plan.

Task: {task}
Response:"""


class TaskPlanner:
    """Plan a complex task as a dependency graph for Task V2 execution."""

    def __init__(self, llm, max_tasks: int = 8) -> None:
        self.llm = llm
        self.max_tasks = max_tasks

    async def plan(self, task: str) -> TaskPlan:
        """Return a validated task graph for the given request."""
        prompt = PLANNER_PROMPT.replace("{task}", task)
        messages = [LLMMessage(role="user", content=prompt)]
        response = await self.llm.call_async(messages=messages, max_tokens=2500)

        try:
            content = self.llm.extract_text(response)
            json_start = content.find("{")
            json_end = content.rfind("}") + 1
            if json_start == -1 or json_end == 0:
                raise ValueError("No JSON object found in planner response")

            result = json.loads(content[json_start:json_end])
            plan = TaskPlan(
                summary=result.get("summary", task),
                tasks=[
                    PlannedTask(
                        local_id=item["local_id"],
                        subject=item["subject"],
                        description=item["description"],
                        activeForm=item.get("activeForm"),
                        blockedBy=list(item.get("blockedBy", [])),
                        metadata=dict(item.get("metadata", {})),
                    )
                    for item in result.get("tasks", [])
                ],
            )
            self._validate(plan)
            return plan
        except Exception as e:
            logger.warning(f"TaskPlanner: Failed to parse plan: {e}")
            return TaskPlan(
                summary=task,
                tasks=[
                    PlannedTask(
                        local_id="task-1",
                        subject="Execute the requested task",
                        description=task,
                        activeForm="Executing the requested task",
                    )
                ],
            )

    def _validate(self, plan: TaskPlan) -> None:
        if not plan.tasks:
            raise ValueError("Planner returned no tasks")
        if len(plan.tasks) > self.max_tasks:
            raise ValueError(
                f"Planner returned too many tasks: {len(plan.tasks)} > {self.max_tasks}"
            )

        ids = [task.local_id for task in plan.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("Planner returned duplicate local_id values")

        known = set(ids)
        for task in plan.tasks:
            missing = [dep for dep in task.blockedBy if dep not in known]
            if missing:
                raise ValueError(f"Task {task.local_id} references unknown deps: {missing}")

        visiting: set[str] = set()
        visited: set[str] = set()
        by_id = {task.local_id: task for task in plan.tasks}

        def visit(task_id: str) -> None:
            if task_id in visited:
                return
            if task_id in visiting:
                raise ValueError("Planner returned cyclic dependencies")
            visiting.add(task_id)
            for dep in by_id[task_id].blockedBy:
                visit(dep)
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in ids:
            visit(task_id)
