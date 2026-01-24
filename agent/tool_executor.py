"""Tool execution engine for managing and executing tools."""

import asyncio
import inspect
from typing import Any, Dict, List

from tools.base import BaseTool


class ToolExecutor:
    """Executes tools called by the LLM."""

    def __init__(self, tools: List[BaseTool]):
        """Initialize with a list of tools."""
        self.tools = {tool.name: tool for tool in tools}

    async def execute_tool_call(self, tool_name: str, tool_input: Dict[str, Any]) -> str:
        """Execute a single tool call and return result."""
        if tool_name not in self.tools:
            return f"Error: Tool '{tool_name}' not found"

        try:
            execute = self.tools[tool_name].execute
            if inspect.iscoroutinefunction(execute):
                result = await execute(**tool_input)
            else:
                result = await asyncio.to_thread(execute, **tool_input)
            return str(result)
        except Exception as e:
            return f"Error executing {tool_name}: {str(e)}"

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """Get Anthropic-formatted schemas for all tools."""
        return [tool.to_anthropic_schema() for tool in self.tools.values()]

    def add_tool(self, tool: BaseTool):
        """Add a tool to the executor.

        Args:
            tool: Tool instance to add
        """
        self.tools[tool.name] = tool
