"""Plan file tool for agents to manage persistent task plans."""

from typing import Any, Dict, List, Optional

from agent.plan_files import PlanFileManager, PlanStatus
from tools.base import BaseTool


class PlanFileTool(BaseTool):
    """Tool for managing persistent plan files during task execution."""

    def __init__(self, plan_manager: PlanFileManager):
        """Initialize with a PlanFileManager instance.

        Args:
            plan_manager: The PlanFileManager instance to manage
        """
        self._plan_manager = plan_manager

    @property
    def name(self) -> str:
        return "manage_plan_file"

    @property
    def description(self) -> str:
        return """Manage persistent task plans that survive across sessions.

USE PLAN FILES WHEN:
- Complex multi-phase tasks that may span multiple sessions
- Tasks requiring extensive research with findings to preserve
- Work that needs to be recoverable after interruption
- Projects with clear phases and milestones

Note: For simple single-session tasks with 3-5 steps, use manage_todo_list instead.

OPERATIONS:
- create_plan: Create a new task plan with phases
  Required: task (brief description), phases (list of {name, items})
  Optional: objective (detailed description)

- update_phase: Update a phase's status
  Required: phase_index (0-indexed), status (pending/in_progress/completed/failed)

- update_item: Mark an item as completed or pending
  Required: phase_index, item_index, completed (boolean)

- mark_complete: Mark the entire plan as completed

- add_progress: Log a progress entry
  Required: title, content

- save_finding: Save a research finding/note
  Required: topic, content

- load_finding: Load a saved finding
  Required: topic

- get_summary: Get current plan summary

- list_plans: List all available plan sessions

- recover: Recover a plan from a previous session
  Required: session_id

EXAMPLES:
- create_plan: {"task": "Build REST API", "phases": [{"name": "Setup", "items": ["Create project", "Install deps"]}, {"name": "Models", "items": ["User model", "Role model"]}]}
- update_phase: {"phase_index": 0, "status": "in_progress"}
- update_item: {"phase_index": 0, "item_index": 1, "completed": true}
- save_finding: {"topic": "FastAPI patterns", "content": "Use Pydantic for validation..."}
- get_summary: {} (no parameters)"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "operation": {
                "type": "string",
                "description": "Operation: create_plan, update_phase, update_item, mark_complete, add_progress, save_finding, load_finding, get_summary, list_plans, recover",
            },
            "task": {
                "type": "string",
                "description": "Brief task description (for create_plan)",
                "default": "",
            },
            "objective": {
                "type": "string",
                "description": "Detailed objective (for create_plan)",
                "default": "",
            },
            "phases": {
                "type": "array",
                "description": "List of phase objects with 'name' and 'items' (for create_plan)",
                "default": [],
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Phase name",
                        },
                        "items": {
                            "type": "array",
                            "description": "List of task items in this phase",
                            "items": {"type": "string"},
                        },
                    },
                },
            },
            "phase_index": {
                "type": "integer",
                "description": "0-indexed phase number (for update_phase, update_item)",
                "default": -1,
            },
            "item_index": {
                "type": "integer",
                "description": "0-indexed item number within phase (for update_item)",
                "default": -1,
            },
            "status": {
                "type": "string",
                "description": "New status: pending, in_progress, completed, failed (for update_phase)",
                "default": "",
            },
            "completed": {
                "type": "boolean",
                "description": "Whether item is completed (for update_item)",
                "default": False,
            },
            "title": {
                "type": "string",
                "description": "Entry title (for add_progress)",
                "default": "",
            },
            "content": {
                "type": "string",
                "description": "Content text (for add_progress, save_finding)",
                "default": "",
            },
            "topic": {
                "type": "string",
                "description": "Finding topic name (for save_finding, load_finding)",
                "default": "",
            },
            "session_id": {
                "type": "string",
                "description": "Session ID to recover (for recover operation)",
                "default": "",
            },
        }

    async def execute(
        self,
        operation: str,
        task: str = "",
        objective: str = "",
        phases: Optional[List[Dict[str, Any]]] = None,
        phase_index: int = -1,
        item_index: int = -1,
        status: str = "",
        completed: bool = False,
        title: str = "",
        content: str = "",
        topic: str = "",
        session_id: str = "",
        **kwargs,
    ) -> str:
        """Execute plan file operation.

        Args:
            operation: The operation to perform
            task: Task description (for create_plan)
            objective: Detailed objective (for create_plan)
            phases: Phase definitions (for create_plan)
            phase_index: Phase index (for update_phase, update_item)
            item_index: Item index (for update_item)
            status: New status (for update_phase)
            completed: Whether completed (for update_item)
            title: Entry title (for add_progress)
            content: Content text (for add_progress, save_finding)
            topic: Finding topic (for save_finding, load_finding)
            session_id: Session ID (for recover)

        Returns:
            Result message
        """
        try:
            if phases is None:
                phases = []

            # Convert indices to int if float
            if isinstance(phase_index, float):
                phase_index = int(phase_index)
            if isinstance(item_index, float):
                item_index = int(item_index)

            if operation == "create_plan":
                if not task:
                    return "Error: 'task' is required for create_plan"
                if not phases:
                    return "Error: 'phases' is required for create_plan"

                plan = await self._plan_manager.create_plan(
                    task=task, phases=phases, objective=objective
                )
                return f"Plan created: {plan.task}\n\n{self._plan_manager.get_plan_summary()}"

            elif operation == "update_phase":
                if phase_index < 0:
                    return "Error: 'phase_index' is required for update_phase"
                if not status:
                    return "Error: 'status' is required for update_phase"
                try:
                    plan_status = PlanStatus(status)
                except ValueError:
                    return f"Error: Invalid status '{status}'. Must be: pending, in_progress, completed, failed"
                return await self._plan_manager.update_phase_status(phase_index, plan_status)

            elif operation == "update_item":
                if phase_index < 0:
                    return "Error: 'phase_index' is required for update_item"
                if item_index < 0:
                    return "Error: 'item_index' is required for update_item"
                return await self._plan_manager.update_item_status(
                    phase_index, item_index, completed
                )

            elif operation == "mark_complete":
                return await self._plan_manager.mark_complete()

            elif operation == "add_progress":
                if not title:
                    return "Error: 'title' is required for add_progress"
                if not content:
                    return "Error: 'content' is required for add_progress"
                return await self._plan_manager.add_progress_entry(title, content)

            elif operation == "save_finding":
                if not topic:
                    return "Error: 'topic' is required for save_finding"
                if not content:
                    return "Error: 'content' is required for save_finding"
                return await self._plan_manager.save_finding(topic, content)

            elif operation == "load_finding":
                if not topic:
                    return "Error: 'topic' is required for load_finding"
                result = await self._plan_manager.load_finding(topic)
                if result is None:
                    return f"Finding not found: {topic}"
                return result

            elif operation == "get_summary":
                summary = self._plan_manager.get_plan_summary()
                if summary is None:
                    return "No plan loaded. Use create_plan to create a new plan."
                return summary

            elif operation == "list_plans":
                plan_list = await PlanFileManager.list_available_plans()
                if not plan_list:
                    return "No saved plans found."
                lines = ["Available Plans:", ""]
                for plan_info in plan_list:
                    lines.append(f"- Session: {plan_info['session_id']}")
                    lines.append(f"  Task: {plan_info['task']}")
                    lines.append(f"  Status: {plan_info['status']}")
                    lines.append(f"  Progress: {plan_info['progress']}")
                    lines.append(f"  Created: {plan_info['created_at']}")
                    lines.append("")
                return "\n".join(lines)

            elif operation == "recover":
                if not session_id:
                    return "Error: 'session_id' is required for recover"
                # Note: Recovery creates a new manager; caller should update reference
                recovered = await PlanFileManager.recover_plan(session_id)
                if recovered is None:
                    return f"No plan found for session: {session_id}"
                # Copy the plan to our manager
                self._plan_manager._plan = recovered._plan
                self._plan_manager._progress_entries = recovered._progress_entries
                summary = self._plan_manager.get_plan_summary()
                return f"Plan recovered from session {session_id}\n\n{summary}"

            else:
                return f"Error: Unknown operation '{operation}'. Supported: create_plan, update_phase, update_item, mark_complete, add_progress, save_finding, load_finding, get_summary, list_plans, recover"

        except Exception as e:
            return f"Error executing plan operation: {str(e)}"
