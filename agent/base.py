"""Base agent class for all agent types."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List, Optional

from llm import LLMMessage, LLMResponse, StopReason, ToolResult
from memory import MemoryManager
from tools.base import BaseTool
from tools.todo import TodoTool
from utils import get_logger, terminal_ui

from .todo import TodoList
from .tool_executor import ToolExecutor

if TYPE_CHECKING:
    from llm import LiteLLMLLM

logger = get_logger(__name__)


class BaseAgent(ABC):
    """Abstract base class for all agent types."""

    def __init__(
        self,
        llm: "LiteLLMLLM",
        tools: List[BaseTool],
        max_iterations: int = 10,
    ):
        """Initialize the agent.

        Args:
            llm: LLM instance to use
            max_iterations: Maximum number of agent loop iterations
            tools: List of tools available to the agent
        """
        self.llm = llm
        self.max_iterations = max_iterations

        # Initialize todo list system
        self.todo_list = TodoList()

        # Add todo tool to the tools list if enabled
        if tools is None:
            tools = []
        else:
            tools = list(tools)  # Make a copy to avoid modifying original

        todo_tool = TodoTool(self.todo_list)
        tools.append(todo_tool)

        self.tool_executor = ToolExecutor(tools)

        # Initialize memory manager (uses Config directly)
        self.memory = MemoryManager(llm)

    @abstractmethod
    def run(self, task: str) -> str:
        """Execute the agent on a task and return final answer."""
        pass

    def _call_llm(
        self, messages: List[LLMMessage], tools: Optional[List] = None, **kwargs
    ) -> LLMResponse:
        """Helper to call LLM with consistent parameters.

        Args:
            messages: List of conversation messages
            tools: Optional list of tool schemas
            **kwargs: Additional LLM-specific parameters

        Returns:
            LLMResponse object
        """
        return self.llm.call(messages=messages, tools=tools, max_tokens=4096, **kwargs)

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
        verbose: bool = True,
        task: str = "",
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
            task: Optional task description for context in tool result processing

        Returns:
            Final answer as a string
        """
        for iteration in range(max_iterations):
            if verbose:
                terminal_ui.print_iteration(iteration + 1, max_iterations)

            # Get context (either from memory or local messages)
            if use_memory:
                context = self.memory.get_context_for_llm()
            else:
                context = messages

            # Call LLM with tools
            response = self._call_llm(messages=context, tools=tools)

            # Save assistant response using response.to_message() for proper format
            assistant_msg = response.to_message()
            if use_memory:
                if save_to_memory:
                    # Extract actual token usage from response
                    actual_tokens = None
                    if response.usage:
                        actual_tokens = {
                            "input": response.usage.get("input_tokens", 0),
                            "output": response.usage.get("output_tokens", 0),
                        }
                    self.memory.add_message(assistant_msg, actual_tokens=actual_tokens)

                    # Log compression info if it happened
                    if self.memory.was_compressed_last_iteration:
                        logger.debug(
                            f"Memory compressed: saved {self.memory.last_compression_savings} tokens"
                        )
            else:
                # For local messages (mini-loop), still track token usage
                if response.usage:
                    self.memory.token_tracker.add_input_tokens(
                        response.usage.get("input_tokens", 0)
                    )
                    self.memory.token_tracker.add_output_tokens(
                        response.usage.get("output_tokens", 0)
                    )
                messages.append(assistant_msg)

            # Check if we're done (no tool calls)
            if response.stop_reason == StopReason.STOP:
                final_answer = self._extract_text(response)
                if verbose:
                    terminal_ui.console.print("\n[bold green]✓ Final answer received[/bold green]")
                return final_answer

            # Execute tool calls
            if response.stop_reason == StopReason.TOOL_CALLS:
                tool_calls = self.llm.extract_tool_calls(response)

                if not tool_calls:
                    # No tool calls found, return response
                    final_answer = self._extract_text(response)
                    return final_answer if final_answer else "No response generated."

                # Print thinking/reasoning if available
                if verbose and hasattr(self.llm, "extract_thinking"):
                    thinking = self.llm.extract_thinking(response)
                    if thinking:
                        terminal_ui.print_thinking(thinking)

                # Execute each tool call
                tool_results = []
                for tc in tool_calls:
                    if verbose:
                        terminal_ui.print_tool_call(tc.name, tc.arguments)

                    result = self.tool_executor.execute_tool_call(tc.name, tc.arguments)
                    # Tool already handles size limits, no additional processing needed

                    if verbose:
                        terminal_ui.print_tool_result(result)

                    # Log result (truncated)
                    logger.debug(f"Tool result: {result[:200]}{'...' if len(result) > 200 else ''}")

                    tool_results.append(
                        ToolResult(tool_call_id=tc.id, content=result, name=tc.name)
                    )

                # Format tool results and add to context
                # format_tool_results now returns a list of tool messages (OpenAI format)
                result_messages = self.llm.format_tool_results(tool_results)
                if isinstance(result_messages, list):
                    for msg in result_messages:
                        if use_memory and save_to_memory:
                            self.memory.add_message(msg)
                        else:
                            messages.append(msg)
                else:
                    # Backward compatibility: single message
                    if use_memory and save_to_memory:
                        self.memory.add_message(result_messages)
                    else:
                        messages.append(result_messages)

        return "Max iterations reached without completion."

    def delegate_subtask(
        self, subtask_description: str, max_iterations: int = 5, include_context: bool = False
    ) -> str:
        """Delegate a complex subtask to an isolated execution context.

        This creates a temporary, isolated agent context to handle complex subtasks
        without polluting the main agent's memory. Useful for:
        - Deep exploration/research tasks
        - Complex multi-step operations that would clutter main context
        - Experimental operations where you want isolation

        Args:
            subtask_description: Clear description of the subtask
            max_iterations: Maximum iterations for subtask (default: 5)
            include_context: Whether to include system context in sub-agent

        Returns:
            Compressed summary of subtask execution result
        """
        logger.info(
            f"🔀 Delegating subtask (max {max_iterations} iterations): {subtask_description[:100]}..."
        )

        # Build sub-agent system prompt
        sub_system_prompt = """<role>
You are a specialized sub-agent executing a focused subtask for a parent agent.
</role>

<critical_rules>
- Focus ONLY on completing the assigned subtask
- Use tools IMMEDIATELY to get results
- Do NOT spend time planning - just execute
- Return clear, concrete results
- Do NOT ask questions - make reasonable assumptions
</critical_rules>

<execution_strategy>
IMPORTANT: You have limited iterations. Execute tools directly instead of planning:
- Use glob_files or grep_content immediately to find files
- Use read_file immediately to read content
- Provide results directly without excessive todo management

Only use manage_todo_list if the subtask explicitly requires tracking multiple complex steps.
For simple search/analysis tasks, execute tools directly.
</execution_strategy>

<subtask>
{subtask}
</subtask>

Execute this subtask NOW and provide concrete results."""

        # Add context if requested
        if include_context:
            try:
                from .context import format_context_prompt

                context = format_context_prompt()
                sub_system_prompt = context + "\n\n" + sub_system_prompt
            except Exception as e:
                logger.debug(f"Failed to add context: {e}")

        # Format subtask into system prompt
        sub_system_prompt = sub_system_prompt.format(subtask=subtask_description)

        # Create isolated message context
        sub_messages = [
            LLMMessage(role="system", content=sub_system_prompt),
            LLMMessage(role="user", content=f"Execute the subtask: {subtask_description}"),
        ]

        # Get tools (same as main agent, but sub-agent has its own todo list via tool)
        tools = self.tool_executor.get_tool_schemas()

        # Execute in isolated context (no memory persistence)
        try:
            result = self._react_loop(
                messages=sub_messages,
                tools=tools,
                max_iterations=max_iterations,
                use_memory=False,  # KEY: Don't use main memory
                save_to_memory=False,  # KEY: Don't save to main memory
                verbose=True,  # Still show progress
            )

            logger.info(f"✅ Subtask completed. Result length: {len(result)} chars")

            return f"Subtask execution result:\n{result}"

        except Exception as e:
            error_msg = f"Subtask failed with error: {str(e)}"
            logger.error(error_msg)
            return error_msg
