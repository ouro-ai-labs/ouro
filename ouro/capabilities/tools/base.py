"""Base tool interface for all agent tools."""

from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseTool(ABC):
    """Abstract base class for all tools."""

    # Token limits for tool output size checking
    MAX_TOKENS = 25000
    CHARS_PER_TOKEN = 4  # Conservative estimate
    readonly: bool = False

    def conflict_keys(self, **kwargs: Any) -> set[str] | None:
        """Resource keys this call would touch, for parallel-dispatch grouping.

        - ``set()``: no conflicts (parallel-safe with anything).
        - non-empty: parallel-safe with calls whose keys are disjoint.
        - ``None``: unknown scope; runs alone.

        Default: ``set()`` if ``readonly`` else ``None``. Override to declare
        a narrower scope; normalize keys at the tool boundary
        (``os.path.abspath`` for paths) so disjointness is sound.
        """
        return set() if self.readonly else None

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
