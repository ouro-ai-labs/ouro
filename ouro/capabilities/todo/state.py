"""Todo list management for agents to track complex multi-step tasks."""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List


class TodoStatus(Enum):
    """Status of a todo item."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


@dataclass
class TodoItem:
    """A single todo item."""

    content: str  # Imperative form: "Fix authentication bug"
    activeForm: str  # Present continuous form: "Fixing authentication bug"
    status: TodoStatus

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {"content": self.content, "activeForm": self.activeForm, "status": self.status.value}


class TodoList:
    """Manages a list of todo items for an agent."""

    def __init__(self) -> None:
        self._items: List[TodoItem] = []

    def add(self, content: str, activeForm: str) -> str:
        """Add a new todo item.

        Args:
            content: Imperative form (e.g., "Read CSV file")
            activeForm: Present continuous form (e.g., "Reading CSV file")

        Returns:
            Success message with item index
        """
        if not content or not activeForm:
            return "Error: Both content and activeForm are required"

        item = TodoItem(content=content, activeForm=activeForm, status=TodoStatus.PENDING)
        self._items.append(item)
        return f"Added todo #{len(self._items)}: {content}"

    def update_status(self, index: int, status: str) -> str:
        """Update the status of a todo item.

        Args:
            index: 1-indexed position of the todo item
            status: New status (pending, in_progress, or completed)

        Returns:
            Success or error message
        """
        if index < 1 or index > len(self._items):
            return f"Error: Invalid index {index}. Valid range: 1-{len(self._items)}"

        try:
            new_status = TodoStatus(status)
        except ValueError:
            return f"Error: Invalid status '{status}'. Must be: pending, in_progress, or completed"

        # Check the ONE in_progress rule
        if new_status == TodoStatus.IN_PROGRESS:
            in_progress_count = sum(
                1 for item in self._items if item.status == TodoStatus.IN_PROGRESS
            )
            if in_progress_count > 0:
                in_progress_items = [
                    i + 1
                    for i, item in enumerate(self._items)
                    if item.status == TodoStatus.IN_PROGRESS
                ]
                return f"Error: Task #{in_progress_items[0]} is already in_progress. Complete it first before starting another task."

        item = self._items[index - 1]
        old_status = item.status.value
        item.status = new_status

        return f"Updated todo #{index} status: {old_status} → {status}"

    def get_current(self) -> List[TodoItem]:
        """Get all current todo items."""
        return self._items.copy()

    def remove(self, index: int) -> str:
        """Remove a todo item.

        Args:
            index: 1-indexed position of the todo item

        Returns:
            Success or error message
        """
        if index < 1 or index > len(self._items):
            return f"Error: Invalid index {index}. Valid range: 1-{len(self._items)}"

        item = self._items.pop(index - 1)
        return f"Removed todo: {item.content}"

    def format_list(self) -> str:
        """Format the todo list for display."""
        if not self._items:
            return "No todos in the list"

        lines = ["Current Todo List:"]
        for i, item in enumerate(self._items, 1):
            status_symbol = {
                TodoStatus.PENDING: "⏳",
                TodoStatus.IN_PROGRESS: "🔄",
                TodoStatus.COMPLETED: "✅",
            }[item.status]

            status_text = item.activeForm if item.status == TodoStatus.IN_PROGRESS else item.content
            lines.append(f"{i}. {status_symbol} [{item.status.value}] {status_text}")

        # Summary
        pending = sum(1 for item in self._items if item.status == TodoStatus.PENDING)
        in_progress = sum(1 for item in self._items if item.status == TodoStatus.IN_PROGRESS)
        completed = sum(1 for item in self._items if item.status == TodoStatus.COMPLETED)

        lines.append(
            f"\nSummary: {completed} completed, {in_progress} in progress, {pending} pending"
        )

        return "\n".join(lines)

    def get_summary(self) -> Dict[str, int]:
        """Get summary statistics."""
        return {
            "total": len(self._items),
            "pending": sum(1 for item in self._items if item.status == TodoStatus.PENDING),
            "in_progress": sum(1 for item in self._items if item.status == TodoStatus.IN_PROGRESS),
            "completed": sum(1 for item in self._items if item.status == TodoStatus.COMPLETED),
        }

    def clear_completed(self) -> str:
        """Remove all completed items."""
        before_count = len(self._items)
        self._items = [item for item in self._items if item.status != TodoStatus.COMPLETED]
        removed = before_count - len(self._items)
        return f"Removed {removed} completed todo(s)"
