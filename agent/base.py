"""Base agent class for all agent types."""
from abc import ABC, abstractmethod
from typing import List, Optional

from .tool_executor import ToolExecutor
from tools.base import BaseTool
from llm import BaseLLM, LLMMessage, LLMResponse, ToolResult
from memory import MemoryManager, MemoryConfig
from utils import get_logger

logger = get_logger(__name__)


class BaseAgent(ABC):
    """Abstract base class for all agent types."""

    def __init__(
        self,
        llm: BaseLLM,
        max_iterations: int = 10,
        tools: List[BaseTool] = None,
        memory_config: Optional[MemoryConfig] = None,
    ):
        """Initialize the agent.

        Args:
            llm: LLM instance to use
            max_iterations: Maximum number of agent loop iterations
            tools: List of tools available to the agent
            memory_config: Optional memory configuration (None = use defaults)
        """
        self.llm = llm
        self.max_iterations = max_iterations
        self.tool_executor = ToolExecutor(tools or [])

        # Initialize memory manager
        if memory_config is None:
            memory_config = MemoryConfig()
        self.memory = MemoryManager(memory_config, llm)

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

    def _react_loop(
        self,
        messages: List[LLMMessage],
        tools: List,
        max_iterations: int,
        use_memory: bool = True,
        save_to_memory: bool = True,
        verbose: bool = True
    ) -> str:
        """Execute a ReAct (Reasoning + Acting) loop.

        This is a generic ReAct loop implementation that can be used by different agent types.
        It supports both global memory-based context (for main agent loop) and local message
        lists (for mini-loops within plan execution).

        Args:
            messages: Initial message list (ignored if use_memory=True)
            tools: List of available tool schemas
            max_iterations: Maximum number of loop iterations
            use_memory: If True, use self.memory for context; if False, use local messages list
            save_to_memory: If True, save messages to self.memory (only when use_memory=True)
            verbose: If True, print iteration and tool call information

        Returns:
            Final answer as a string
        """
        for iteration in range(max_iterations):
            if verbose:
                print(f"\n--- Iteration {iteration + 1} ---")

            # Get context (either from memory or local messages)
            if use_memory:
                context = self.memory.get_context_for_llm()
            else:
                context = messages

            # Call LLM with tools
            response = self._call_llm(messages=context, tools=tools)

            # Save assistant response
            assistant_msg = LLMMessage(role="assistant", content=response.content)
            if use_memory:
                if save_to_memory:
                    # Extract actual token usage from response
                    actual_tokens = None
                    if response.usage:
                        actual_tokens = {
                            "input": response.usage.get("input_tokens", 0),
                            "output": response.usage.get("output_tokens", 0)
                        }
                    self.memory.add_message(assistant_msg, actual_tokens=actual_tokens)

                    # Log compression info if it happened
                    if self.memory.was_compressed_last_iteration:
                        logger.debug(f"Memory compressed: saved {self.memory.last_compression_savings} tokens")
            else:
                # For local messages (mini-loop), still track token usage
                if response.usage:
                    self.memory.token_tracker.add_input_tokens(response.usage.get("input_tokens", 0))
                    self.memory.token_tracker.add_output_tokens(response.usage.get("output_tokens", 0))
                messages.append(assistant_msg)

            # Check if we're done (no tool calls)
            if response.stop_reason == "end_turn":
                final_answer = self._extract_text(response)
                if verbose:
                    print(f"\nFinal answer received.")
                return final_answer

            # Execute tool calls
            if response.stop_reason == "tool_use":
                tool_calls = self.llm.extract_tool_calls(response)

                if not tool_calls:
                    # No tool calls found, return response
                    final_answer = self._extract_text(response)
                    return final_answer if final_answer else "No response generated."

                # Execute each tool call
                tool_results = []
                for tc in tool_calls:
                    if verbose:
                        print(f"Tool call: {tc.name}")
                        print(f"Input: {tc.arguments}")

                    result = self.tool_executor.execute_tool_call(tc.name, tc.arguments)

                    # Log result (truncated)
                    logger.debug(f"Tool result: {result[:200]}{'...' if len(result) > 200 else ''}")

                    tool_results.append(ToolResult(
                        tool_call_id=tc.id,
                        content=result
                    ))

                # Format tool results and add to context
                result_message = self.llm.format_tool_results(tool_results)
                if use_memory and save_to_memory:
                    self.memory.add_message(result_message)
                else:
                    messages.append(result_message)

        return "Max iterations reached without completion."
