"""Todo list tool for agents to manage complex multi-step tasks."""

from typing import Any, Dict

from agent.todo import TodoList
from tools.base import BaseTool


class TodoTool(BaseTool):
    """Tool for managing todo lists during task execution."""

    def __init__(self, todo_list: TodoList):
        """Initialize with a TodoList instance.

        Args:
            todo_list: The TodoList instance to manage
        """
        self._todo_list = todo_list

    @property
    def name(self) -> str:
        return "manage_todo_list"

    @property
    def description(self) -> str:
        return """Manage your task list for complex multi-step work.

WHEN TO USE:
- Tasks with 3+ distinct steps
- Multi-file operations
- Complex workflows requiring planning
- Anytime you need to track progress

OPERATIONS:
- add: Create new tasks (requires content and activeForm)
- update: Change task status to pending, in_progress, or completed (requires index and status)
- list: View all current tasks
- remove: Delete a task (requires index)
- clear_completed: Remove all completed tasks

CRITICAL RULES:
- Exactly ONE task must be in_progress at any time
- Mark tasks completed IMMEDIATELY after finishing
- Use activeForm for present continuous (e.g., "Reading file" not "Read file")

EXAMPLES:
- add: {"content": "Read data.csv", "activeForm": "Reading data.csv"}
- update: {"index": 1, "status": "in_progress"}
- update: {"index": 1, "status": "completed"}
- list: {} (no parameters)"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "operation": {
                "type": "string",
                "description": "Operation to perform: add, update, list, remove, or clear_completed",
            },
            "content": {
                "type": "string",
                "description": "Todo content in imperative form (for add operation)",
            },
            "activeForm": {
                "type": "string",
                "description": "Todo content in present continuous form (for add operation)",
            },
            "index": {
                "type": "integer",
                "description": "1-indexed position of todo item (for update/remove operations)",
            },
            "status": {
                "type": "string",
                "description": "New status: pending, in_progress, or completed (for update operation)",
            },
        }

    def execute(
        self,
        operation: str,
        content: str = "",
        activeForm: str = "",
        index: int = 0,
        status: str = "",
        **kwargs,
    ) -> str:
        """Execute todo list operation.

        Args:
            operation: The operation to perform
            content: Todo content (for add)
            activeForm: Active form of content (for add)
            index: Item index (for update/remove)
            status: New status (for update)

        Returns:
            Result message
        """
        try:
            # Convert index to int if it's a float (LLM may pass 1.0 instead of 1)
            if isinstance(index, float):
                index = int(index)

            if operation == "add":
                if not content or not activeForm:
                    return "Error: Both 'content' and 'activeForm' are required for add operation"
                return self._todo_list.add(content, activeForm)

            elif operation == "update":
                if index <= 0:
                    return "Error: 'index' must be provided and positive for update operation"
                if not status:
                    return "Error: 'status' must be provided for update operation"
                return self._todo_list.update_status(index, status)

            elif operation == "list":
                return self._todo_list.format_list()

            elif operation == "remove":
                if index <= 0:
                    return "Error: 'index' must be provided and positive for remove operation"
                return self._todo_list.remove(index)

            elif operation == "clear_completed":
                return self._todo_list.clear_completed()

            else:
                return f"Error: Unknown operation '{operation}'. Supported: add, update, list, remove, clear_completed"

        except Exception as e:
            return f"Error executing todo operation: {str(e)}"
