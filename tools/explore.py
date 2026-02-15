"""Exploration tool for parallel context gathering."""

import asyncio
from typing import TYPE_CHECKING, Any, Dict, List

from llm import LLMMessage

from .base import BaseTool

if TYPE_CHECKING:
    from agent.base import BaseAgent


# General exploration prompt supporting both code and web exploration
GENERAL_EXPLORER_PROMPT = """<role>
You are an exploration agent gathering information for a task.
Your job is to discover relevant information WITHOUT making any changes.
</role>

<exploration_focus>
Aspect: {aspect}
Description: {description}
</exploration_focus>

<instructions>
1. Use available information-gathering tools:
   - Code exploration: glob_files, grep_content, read_file
   - Web exploration: web_search, web_fetch

2. Focus ONLY on the specified exploration aspect
3. Report your findings concisely and specifically
4. Do NOT make any changes to files
5. Do NOT try to solve problems - just gather information

Your output should be a structured summary of what you discovered.
</instructions>

Explore and report your findings:"""


class ExploreTool(BaseTool):
    """Tool for parallel exploration of code and web resources.

    This tool enables the main agent to gather context through parallel
    exploration sub-agents. Each exploration task runs in isolation and
    returns a compressed summary.

    Key features:
    - Parallel execution of multiple exploration tasks
    - Code exploration: file structure, patterns, dependencies
    - Web exploration: search results, webpage content
    - Compressed summaries to preserve context space
    """

    # Configuration
    MAX_PARALLEL_EXPLORATIONS = 3
    MAX_RESULT_CHARS = 1500

    # Allowed tools for exploration (read-only + network)
    EXPLORATION_TOOLS = {
        "glob_files",
        "grep_content",
        "read_file",
        "web_search",
        "web_fetch",
    }

    def __init__(self, agent: "BaseAgent"):
        """Initialize exploration tool.

        Args:
            agent: The parent agent instance that will run explorations
        """
        self.agent = agent

    @property
    def name(self) -> str:
        return "explore_context"

    @property
    def description(self) -> str:
        return """Gather context through parallel exploration of code and web resources.

Use this tool when you need to:
- Explore code structure, patterns, or dependencies
- Search the web for documentation, APIs, or solutions
- Gather information from multiple sources in parallel
- Understand a codebase before making changes

DO NOT use this for:
- Making changes to files (use regular edit tools)
- Simple, single-file reads (use read_file directly)
- Tasks that don't require exploration

Input parameters:
- tasks (required): Array of exploration tasks, each with:
  - aspect: Brief name of what to explore (e.g., "file_structure", "api_docs")
  - description: Detailed description of what to find

The tool runs explorations in parallel and returns compressed summaries."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "tasks": {
                "type": "array",
                "description": "List of exploration tasks to run in parallel",
                "items": {
                    "type": "object",
                    "properties": {
                        "aspect": {
                            "type": "string",
                            "description": "Brief name of the exploration aspect",
                        },
                        "description": {
                            "type": "string",
                            "description": "Detailed description of what to explore",
                        },
                    },
                    "required": ["aspect", "description"],
                },
            }
        }

    def to_anthropic_schema(self) -> Dict[str, Any]:
        """Convert to Anthropic tool schema format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": self.parameters,
                "required": ["tasks"],
            },
        }

    async def execute(self, tasks: List[Dict[str, str]]) -> str:
        """Execute parallel exploration tasks.

        Args:
            tasks: List of exploration tasks with 'aspect' and 'description' keys

        Returns:
            Combined exploration results as a string
        """
        if not tasks:
            return "Error: No exploration tasks provided"

        # Limit the number of parallel explorations
        tasks = tasks[: self.MAX_PARALLEL_EXPLORATIONS]

        # Get exploration-only tools
        all_tools = self.agent.tool_executor.get_tool_schemas()
        exploration_tools = [
            t
            for t in all_tools
            if t.get("name") in self.EXPLORATION_TOOLS
            or t.get("function", {}).get("name") in self.EXPLORATION_TOOLS
        ]

        # Run explorations in parallel
        results = await self._run_parallel_explorations(tasks, exploration_tools)

        # Format and return results
        return self._format_results(results)

    async def _run_parallel_explorations(
        self, tasks: List[Dict[str, str]], tools: List[Dict[str, Any]]
    ) -> Dict[str, str]:
        """Run multiple exploration tasks in parallel.

        Args:
            tasks: List of exploration tasks
            tools: Available exploration tools

        Returns:
            Dict mapping aspect names to results
        """

        async def run_single(task: Dict[str, str]) -> tuple:
            aspect = task.get("aspect", "unknown")
            description = task.get("description", "")
            try:
                result = await self._run_exploration(aspect, description, tools)
                return aspect, result
            except asyncio.CancelledError:
                raise
            except Exception as e:
                return aspect, f"Exploration failed: {str(e)}"

        # Use TaskGroup for parallel execution
        # Since run_single catches all exceptions internally (except CancelledError),
        # any ExceptionGroup raised here indicates cancellation which should propagate
        results = {}
        async with asyncio.TaskGroup() as tg:
            task_list = [tg.create_task(run_single(t)) for t in tasks]

        for task in task_list:
            aspect, result = task.result()
            results[aspect] = result

        return results

    async def _run_exploration(
        self, aspect: str, description: str, tools: List[Dict[str, Any]]
    ) -> str:
        """Run a single exploration using isolated mini-loop.

        Args:
            aspect: The aspect being explored
            description: Description of the exploration focus
            tools: Available exploration tools

        Returns:
            Exploration result string
        """
        # Build exploration prompt
        prompt = GENERAL_EXPLORER_PROMPT.format(aspect=aspect, description=description)

        messages = [LLMMessage(role="user", content=prompt)]

        # Run exploration in isolated context
        result = await self.agent._react_loop(
            messages=messages,
            tools=tools,
            use_memory=False,  # Don't use main memory
            save_to_memory=False,  # Don't save to main memory
        )

        return result

    def _format_results(self, results: Dict[str, str]) -> str:
        """Format exploration results into a combined summary.

        Args:
            results: Dict mapping aspect names to result strings

        Returns:
            Formatted combined results
        """
        if not results:
            return "No exploration results."

        parts = ["# Exploration Results\n"]

        for aspect, result in results.items():
            # Truncate long results
            if len(result) > self.MAX_RESULT_CHARS:
                result = result[: self.MAX_RESULT_CHARS] + "... [truncated]"

            parts.append(f"## {aspect}\n{result}\n")

        return "\n".join(parts)
