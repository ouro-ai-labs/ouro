"""Base tool interface for all agent tools."""

from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseTool(ABC):
    """Abstract base class for all tools."""

    # Token limits for tool output size checking
    MAX_TOKENS = 25000
    CHARS_PER_TOKEN = 4  # Conservative estimate
    readonly: bool = False

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique tool identifier."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description for the LLM."""
        pass

    @property
    @abstractmethod
    def parameters(self) -> Dict[str, Any]:
        """JSON Schema for tool parameters."""
        pass

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        """Execute the tool and return result as string."""
        raise NotImplementedError

    def to_anthropic_schema(self) -> Dict[str, Any]:
        """Convert to Anthropic tool schema format."""
        params = self.parameters
        # Parameters without a 'default' value are required
        required = [key for key, value in params.items() if "default" not in value]

        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": params,
                "required": required,
            },
        }
