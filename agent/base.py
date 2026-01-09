"""Base agent class for all agent types."""
from abc import ABC, abstractmethod
from typing import List, Optional

from .tool_executor import ToolExecutor
from .todo import TodoList
from tools.base import BaseTool
from tools.todo import TodoTool
from llm import BaseLLM, LLMMessage, LLMResponse, ToolResult
from llm.model_router import ModelRouter, ModelTierConfig
from memory import MemoryManager, MemoryConfig
from utils import get_logger, terminal_ui

logger = get_logger(__name__)


class BaseAgent(ABC):
    """Abstract base class for all agent types."""

    def __init__(
        self,
        llm: BaseLLM,
        max_iterations: int = 10,
        tools: List[BaseTool] = None,
        memory_config: Optional[MemoryConfig] = None,
        enable_todo: bool = True,
        model_router: Optional[ModelRouter] = None,
    ):
        """Initialize the agent.

        Args:
            llm: LLM instance to use (will be primary model)
            max_iterations: Maximum number of agent loop iterations
            tools: List of tools available to the agent
            memory_config: Optional memory configuration (None = use defaults)
            enable_todo: Whether to enable todo list management (default: True)
            model_router: Optional model router for cost optimization (Phase 2)
        """
        self.llm = llm
        self.max_iterations = max_iterations
        self.model_router = model_router
        self._iteration_count = 0  # Track iteration for routing decisions

        # Initialize todo list system
        self.todo_list = TodoList()

        # Add todo tool to the tools list if enabled
        if tools is None:
            tools = []
        else:
            tools = list(tools)  # Make a copy to avoid modifying original

        if enable_todo:
            todo_tool = TodoTool(self.todo_list)
            tools.append(todo_tool)

        self.tool_executor = ToolExecutor(tools)

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
        operation_context: Optional[dict] = None,
        **kwargs
    ) -> LLMResponse:
        """Helper to call LLM with consistent parameters and smart model routing.

        Args:
            messages: List of conversation messages
            tools: Optional list of tool schemas
            operation_context: Optional context for model routing (e.g., tool_name, operation_type)
            **kwargs: Additional LLM-specific parameters

        Returns:
            LLMResponse object
        """
        # Save original model
        original_model = self.llm.model

        try:
            # Use model router if available
            if self.model_router:
                # Determine operation type and context
                op_context = operation_context or {}
                op_context['is_first_call'] = (self._iteration_count == 0)

                # Select appropriate model
                selected_model, tier = self.model_router.select_model(
                    operation_type=op_context.get('operation_type', 'tool_call'),
                    context=op_context
                )

                # Switch to selected model
                self.llm.model = selected_model
                logger.debug(f"Using {tier.value} tier model: {selected_model}")

            # Make the LLM call
            response = self.llm.call(
                messages=messages,
                tools=tools,
                max_tokens=4096,
                **kwargs
            )

            return response

        finally:
            # Restore original model
            self.llm.model = original_model

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
        # Track previous tool calls for routing context
        previous_tool_names = []
        has_tool_results = False

        for iteration in range(max_iterations):
            self._iteration_count = iteration  # Update iteration counter for routing

            if verbose:
                terminal_ui.print_iteration(iteration + 1, max_iterations)

            # Get context (either from memory or local messages)
            if use_memory:
                context = self.memory.get_context_for_llm()
            else:
                context = messages

            # Call LLM with tools and operation context for smart routing
            operation_ctx = {
                'operation_type': 'tool_call',
                'is_first_call': (iteration == 0),
                'has_tool_results': has_tool_results,
            }

            # Add tool name if processing results from a single tool
            if has_tool_results and len(previous_tool_names) == 1:
                operation_ctx['tool_name'] = previous_tool_names[0]

            response = self._call_llm(messages=context, tools=tools, operation_context=operation_ctx)

            # Reset tool tracking (will be set again if tools are called)
            previous_tool_names = []
            has_tool_results = False

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
                    terminal_ui.console.print("\n[bold green]✓ Final answer received[/bold green]")
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
                        terminal_ui.print_tool_call(tc.name, tc.arguments)

                    # Track tool name for next iteration's routing context
                    previous_tool_names.append(tc.name)

                    result = self.tool_executor.execute_tool_call(tc.name, tc.arguments)

                    # Truncate overly large results to prevent context overflow
                    MAX_TOOL_RESULT_LENGTH = 8000  # characters
                    truncated = False
                    if len(result) > MAX_TOOL_RESULT_LENGTH:
                        truncated = True
                        truncated_length = MAX_TOOL_RESULT_LENGTH
                        result = (
                            result[:truncated_length] +
                            f"\n\n[... Output truncated. Showing first {truncated_length} characters of {len(result)} total. "
                            f"Use grep_content or glob_files for more targeted searches instead of reading large files.]"
                        )
                        if verbose:
                            terminal_ui.print_tool_result(result, truncated=True)
                    elif verbose:
                        terminal_ui.print_tool_result(result, truncated=False)

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

                # Mark that we have tool results for next iteration
                has_tool_results = True

        return "Max iterations reached without completion."
