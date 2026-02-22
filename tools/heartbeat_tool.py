"""Heartbeat checklist management tool for agents."""

from __future__ import annotations

import os
from typing import Any

from tools.base import BaseTool

# Default path — same file that HeartbeatScheduler reads via load_heartbeat().
_BOT_DIR = os.path.join(os.path.expanduser("~"), ".ouro", "bot")
_HEARTBEAT_FILE = os.path.join(_BOT_DIR, "heartbeat.md")

_HEADER = "# Heartbeat Checklist\n"


class HeartbeatTool(BaseTool):
    """Tool for managing the heartbeat checklist during conversation."""

    def __init__(self, heartbeat_file: str = _HEARTBEAT_FILE):
        self._file = heartbeat_file

    @property
    def name(self) -> str:
        return "manage_heartbeat"

    @property
    def description(self) -> str:
        return """Manage the heartbeat checklist (periodic self-check items).

WHEN TO USE:
- User asks to add/remove/view periodic check items
- User wants to customise what the bot checks on each heartbeat cycle

OPERATIONS:
- add: Append a new checklist item (requires item)
- remove: Delete an item by 1-based index (requires index)
- list: Show all current checklist items

EXAMPLES:
- add: {"operation": "add", "item": "Check if CI pipeline is green"}
- remove: {"operation": "remove", "index": 2}
- list: {"operation": "list"}"""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "operation": {
                "type": "string",
                "description": "Operation to perform: add, remove, or list",
            },
            "item": {
                "type": "string",
                "description": "Checklist item text (for add)",
                "default": "",
            },
            "index": {
                "type": "integer",
                "description": "1-based index of the item to remove (for remove)",
                "default": 0,
            },
        }

    async def execute(
        self,
        operation: str,
        item: str = "",
        index: int = 0,
        **kwargs: Any,
    ) -> str:
        try:
            if operation == "add":
                return self._add(item)
            elif operation == "remove":
                return self._remove(index)
            elif operation == "list":
                return self._list()
            else:
                return f"Error: Unknown operation '{operation}'. Supported: add, remove, list"
        except Exception as e:
            return f"Error executing heartbeat operation: {e}"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_items(self) -> list[str]:
        """Parse ``- [ ] ...`` lines from the heartbeat file."""
        if not os.path.isfile(self._file):
            return []
        with open(self._file, encoding="utf-8") as f:
            lines = f.readlines()
        items: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("- [ ] "):
                items.append(stripped[6:])
        return items

    def _save_items(self, items: list[str]) -> None:
        """Write items back to the heartbeat file, preserving the header."""
        os.makedirs(os.path.dirname(self._file), exist_ok=True)
        with open(self._file, "w", encoding="utf-8") as f:
            f.write(_HEADER)
            f.write("\n")
            for item in items:
                f.write(f"- [ ] {item}\n")

    def _add(self, item: str) -> str:
        if not item:
            return "Error: 'item' is required for add operation"
        items = self._load_items()
        items.append(item)
        self._save_items(items)
        return f"Added checklist item #{len(items)}: {item}"

    def _remove(self, index: int) -> str:
        if index < 1:
            return "Error: 'index' must be a positive integer (1-based)"
        items = self._load_items()
        if index > len(items):
            return f"Error: index {index} out of range (1–{len(items)})"
        removed = items.pop(index - 1)
        self._save_items(items)
        return f"Removed checklist item #{index}: {removed}"

    def _list(self) -> str:
        items = self._load_items()
        if not items:
            return "No checklist items."
        lines = [f"{i}. {item}" for i, item in enumerate(items, 1)]
        return "Heartbeat checklist:\n" + "\n".join(lines)
