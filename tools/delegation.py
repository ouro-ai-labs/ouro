"""Delegation tool for sub-agent task execution."""

from typing import Any, Dict

from .base import BaseTool


class DelegationTool(BaseTool):
    """Tool that allows main agent to delegate subtasks to isolated sub-agents.

    This enables the main agent to offload complex, multi-step subtasks to
    temporary execution contexts that don't pollute the main agent's memory.

    Key benefits:
    - Context isolation: Subtask details don't clutter main context
    - Memory efficiency: Only result summary is kept, not full execution trace
    - Focused execution: Sub-agent is optimized for single subtask completion
    """

    def __init__(self, agent):
        """Initialize delegation tool.

        Args:
            agent: The parent agent instance that will delegate tasks
        """
        self.agent = agent

    @property
    def name(self) -> str:
        return "delegate_subtask"

    @property
    def description(self) -> str:
        return """Delegate a complex subtask to an isolated sub-agent for focused execution.

Use this tool when you need to:
- Perform deep exploration or research that involves many steps
- Execute complex operations that would clutter your main context
- Isolate experimental or uncertain operations
- Handle subtasks that require their own multi-step planning

DO NOT use this for:
- Simple, single-step operations (use regular tools instead)
- Tasks that require frequent back-and-forth with you
- Tasks where you need fine-grained control of each step

The sub-agent will execute the task independently and return a summary.
You'll receive the result without your context being filled with execution details.

Input parameters:
- subtask_description (required): Clear, detailed description of what the subtask should accomplish
- include_context (optional, default=false): Whether to provide system context (git, env) to sub-agent"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "subtask_description": {
                "type": "string",
                "description": "Clear, detailed description of the subtask to execute",
            },
            "include_context": {
                "type": "boolean",
                "description": "Include system context (git, env info) for sub-agent (default: false)",
            },
        }

    def to_anthropic_schema(self) -> Dict[str, Any]:
        """Convert to Anthropic tool schema format with optional parameters."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": self.parameters,
                "required": ["subtask_description"],  # Only subtask_description is required
            },
        }

    async def execute(self, subtask_description: str, include_context: bool = False) -> str:
        """Execute subtask delegation.

        Args:
            subtask_description: Description of the subtask
            include_context: Whether to include system context

        Returns:
            Compressed summary of subtask execution result
        """
        return await self.agent.delegate_subtask(
            subtask_description=subtask_description,
            include_context=include_context,
        )
