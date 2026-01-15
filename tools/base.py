"""Base tool interface for all agent tools."""

from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseTool(ABC):
    """Abstract base class for all tools."""

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
    def execute(self, **kwargs) -> str:
        """Execute the tool and return result as string."""
        pass

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
