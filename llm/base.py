"""Base LLM interface for supporting multiple LLM providers."""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class LLMMessage:
    """Unified message format across all LLM providers."""
    role: str  # "user", "assistant", "system"
    content: Any  # Can be string or list of content blocks


@dataclass
class LLMResponse:
    """Unified response format across all LLM providers."""
    content: Any  # Response content (text or content blocks)
    stop_reason: str  # "end_turn", "tool_use", "max_tokens", etc.
    raw_response: Any  # Original response object for provider-specific handling


@dataclass
class ToolCall:
    """Unified tool call format."""
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class ToolResult:
    """Unified tool result format."""
    tool_call_id: str
    content: str


class BaseLLM(ABC):
    """Abstract base class for LLM providers."""

    def __init__(self, api_key: str, model: str, **kwargs):
        """Initialize LLM provider.

        Args:
            api_key: API key for the provider
            model: Model identifier
            **kwargs: Additional provider-specific configuration
        """
        self.api_key = api_key
        self.model = model
        self.config = kwargs

    @abstractmethod
    def call(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: int = 4096,
        **kwargs
    ) -> LLMResponse:
        """Call the LLM with messages and optional tools.

        Args:
            messages: List of conversation messages
            tools: Optional list of tool schemas
            max_tokens: Maximum tokens to generate
            **kwargs: Additional provider-specific parameters

        Returns:
            LLMResponse with unified format
        """
        pass

    @abstractmethod
    def extract_text(self, response: LLMResponse) -> str:
        """Extract text content from response.

        Args:
            response: LLMResponse object

        Returns:
            Extracted text as string
        """
        pass

    @abstractmethod
    def extract_tool_calls(self, response: LLMResponse) -> List[ToolCall]:
        """Extract tool calls from response.

        Args:
            response: LLMResponse object

        Returns:
            List of ToolCall objects
        """
        pass

    @abstractmethod
    def format_tool_results(self, results: List[ToolResult]) -> LLMMessage:
        """Format tool results into a message for the LLM.

        Args:
            results: List of tool results

        Returns:
            LLMMessage containing formatted tool results
        """
        pass

    @property
    @abstractmethod
    def supports_tools(self) -> bool:
        """Whether this LLM provider supports tool calling."""
        pass

    @property
    def provider_name(self) -> str:
        """Name of the LLM provider."""
        return self.__class__.__name__.replace("LLM", "")
