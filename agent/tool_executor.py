"""Tool execution engine for managing and executing tools."""

import asyncio
from typing import Any, Dict, List

from config import Config
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
            timeout = Config.TOOL_TIMEOUT
            if "timeout" in tool_input and tool_input["timeout"] is not None:
                try:
                    timeout = float(tool_input["timeout"])
                except (TypeError, ValueError):
                    timeout = Config.TOOL_TIMEOUT

            if timeout is not None and timeout > 0:
                async with asyncio.timeout(timeout):
                    result = await self.tools[tool_name].execute(**tool_input)
            else:
                result = await self.tools[tool_name].execute(**tool_input)
            return str(result)
        except TimeoutError:
            return f"Error: Tool '{tool_name}' timed out after {timeout}s"
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
