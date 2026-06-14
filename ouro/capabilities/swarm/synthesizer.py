"""Result synthesis for swarm task-graph execution."""

from __future__ import annotations

from ouro.capabilities.swarm.planner import TaskPlan
from ouro.capabilities.tasks.models import TaskStatus
from ouro.capabilities.tasks.store import TaskStore


class TaskGraphSynthesizer:
    """Build a concise final answer from Task V2 execution state."""

    async def summarize(self, *, task: str, plan: TaskPlan, store: TaskStore) -> str:
        tasks = store.list_all()
        completed = sum(1 for item in tasks if item.status == TaskStatus.COMPLETED)
        lines = [
            f"Completed task-graph execution for: {task}",
            f"Plan summary: {plan.summary}",
            f"Task completion: {completed}/{len(tasks)} completed",
            "Tasks:",
        ]
        for item in tasks:
            worker = item.metadata.get("worker_agent_id")
            worker_suffix = f" ({worker})" if worker else ""
            lines.append(f"- [{item.status.value}] {item.subject}{worker_suffix}")
            result = item.metadata.get("result")
            if isinstance(result, dict):
                summary = result.get("summary")
                if summary:
                    lines.append(f"  Result: {summary}")
                artifacts = result.get("artifacts") or []
                if artifacts:
                    lines.append(f"  Artifacts: {', '.join(artifacts)}")
            elif result:
                lines.append(f"  Result: {result}")
            error = item.metadata.get("error")
            if error:
                lines.append(f"  Error: {error}")
        return "\n".join(lines)
