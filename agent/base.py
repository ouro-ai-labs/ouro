"""Base agent class for all agent types."""
from abc import ABC, abstractmethod
from typing import List, Optional

from .tool_executor import ToolExecutor
from tools.base import BaseTool
from llm import BaseLLM, LLMMessage, LLMResponse


class BaseAgent(ABC):
    """Abstract base class for all agent types."""

    def __init__(
        self,
        llm: BaseLLM,
        max_iterations: int = 10,
        tools: List[BaseTool] = None,
    ):
        """Initialize the agent.

        Args:
            llm: LLM instance to use
            max_iterations: Maximum number of agent loop iterations
            tools: List of tools available to the agent
        """
        self.llm = llm
        self.max_iterations = max_iterations
        self.tool_executor = ToolExecutor(tools or [])

    @abstractmethod
    def run(self, task: str) -> str:
        """Execute the agent on a task and return final answer."""
        pass

    def _call_llm(
        self,
        messages: List[LLMMessage],
        tools: Optional[List] = None,
        **kwargs
    ) -> LLMResponse:
        """Helper to call LLM with consistent parameters.

        Args:
            messages: List of conversation messages
            tools: Optional list of tool schemas
            **kwargs: Additional LLM-specific parameters

        Returns:
            LLMResponse object
        """
        return self.llm.call(
            messages=messages,
            tools=tools,
            max_tokens=4096,
            **kwargs
        )

    def _extract_text(self, response: LLMResponse) -> str:
        """Extract text from LLM response.

        Args:
            response: LLMResponse object

        Returns:
            Extracted text
        """
        return self.llm.extract_text(response)
