"""Base agent class for all agent types."""

import asyncio
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List, Optional

from llm import LLMMessage, LLMResponse, StopReason, ToolCall, ToolResult
from llm.reasoning import display_reasoning_effort, normalize_reasoning_effort
from memory import MemoryManager
from tools.base import BaseTool
from tools.todo import TodoTool
from utils import get_logger, terminal_ui
from utils.tui.progress import AsyncSpinner

from .todo import TodoList
from .tool_executor import ToolExecutor
from .verification import LLMVerifier, VerificationResult, Verifier

if TYPE_CHECKING:
    from llm import LiteLLMAdapter, ModelManager

logger = get_logger(__name__)


class BaseAgent(ABC):
    """Abstract base class for all agent types."""

    def __init__(
        self,
        llm: "LiteLLMAdapter",
        tools: List[BaseTool],
        max_iterations: int = 10,
        model_manager: Optional["ModelManager"] = None,
    ):
        """Initialize the agent.

        Args:
            llm: LLM instance to use
            max_iterations: Maximum number of agent loop iterations
            tools: List of tools available to the agent
            model_manager: Optional model manager for switching models
        """
        self.llm = llm
        self.max_iterations = max_iterations
        self.model_manager = model_manager

        # Initialize todo list system
        self.todo_list = TodoList()

        # Add todo tool to the tools list if enabled
        tools = [] if tools is None else list(tools)  # Make a copy to avoid modifying original

        todo_tool = TodoTool(self.todo_list)
        tools.append(todo_tool)

        self.tool_executor = ToolExecutor(tools)

        # Memory manager is fully owned by the agent
        self.memory = MemoryManager(llm)
        self.memory.set_todo_context_provider(self._get_todo_context)

        # Run-scoped reasoning control. None means "omit reasoning_effort" (provider defaults).
        self._reasoning_effort: Optional[str] = None

    def set_reasoning_effort(self, value: Optional[str]) -> None:
        """Set run-scoped reasoning effort for primary task calls.

        Args:
            value: One of {"default","off","none","minimal","low","medium","high","xhigh"} (case-insensitive),
                   or None to reset to default (omit).
        """
        self._reasoning_effort = normalize_reasoning_effort(value)

    def get_reasoning_effort(self) -> str:
        """Get the reasoning effort string for display."""
        return display_reasoning_effort(getattr(self, "_reasoning_effort", None))

    async def load_session(self, session_id: str) -> None:
        """Load a saved session into the agent's memory.

        Args:
            session_id: Session ID to load
        """
        self.memory = await MemoryManager.from_session(session_id, self.llm)
        self.memory.set_todo_context_provider(self._get_todo_context)

    def _set_llm_adapter(self, llm: "LiteLLMAdapter") -> None:
        self.llm = llm

        # Keep memory/compressor in sync with the active LLM.
        # Otherwise stats/compression might continue using the previous model.
        if hasattr(self, "memory") and self.memory:
            self.memory.llm = llm
            if hasattr(self.memory, "compressor") and self.memory.compressor:
                self.memory.compressor.llm = llm

    @abstractmethod
    def run(self, task: str) -> str:
        """Execute the agent on a task and return final answer."""
        pass

    async def _call_llm(
        self,
        messages: List[LLMMessage],
        tools: Optional[List] = None,
        spinner_message: str = "Thinking...",
        **kwargs,
    ) -> LLMResponse:
        """Helper to call LLM with consistent parameters.

        Args:
            messages: List of conversation messages
            tools: Optional list of tool schemas
            spinner_message: Message to display with spinner
            **kwargs: Additional LLM-specific parameters

        Returns:
            LLMResponse object
        """
        effort = getattr(self, "_reasoning_effort", None)
        if effort is not None and "reasoning_effort" not in kwargs:
            kwargs = {**kwargs, "reasoning_effort": effort}
        async with AsyncSpinner(terminal_ui.console, spinner_message):
            return await self.llm.call_async(
                messages=messages, tools=tools, max_tokens=4096, **kwargs
            )

    def _extract_text(self, response: LLMResponse) -> str:
        """Extract text from LLM response.

        Args:
            response: LLMResponse object

        Returns:
            Extracted text
        """
        return self.llm.extract_text(response)

    def _get_todo_context(self) -> Optional[str]:
        """Get current todo list state for memory compression.

        Returns formatted todo list if items exist, None otherwise.
        This is used by MemoryManager to inject todo state into summaries.
        """
        items = self.todo_list.get_current()
        if not items:
            return None
        return self.todo_list.format_list()

    async def _react_loop(
        self,
        messages: List[LLMMessage],
        tools: List,
        use_memory: bool = True,
        save_to_memory: bool = True,
        task: str = "",
    ) -> str:
        """Execute a ReAct (Reasoning + Acting) loop.

        This is a generic ReAct loop implementation that can be used by different agent types.
        It supports both global memory-based context (for main agent loop) and local message
        lists (for mini-loops within plan execution).

        Args:
            messages: Initial message list (ignored if use_memory=True)
            tools: List of available tool schemas
            use_memory: If True, use self.memory for context; if False, use local messages list
            save_to_memory: If True, save messages to self.memory (only when use_memory=True)
            task: Optional task description for context in tool result processing

        Returns:
            Final answer as a string
        """
        while True:
            # Get context (either from memory or local messages)
            context = self.memory.get_context_for_llm() if use_memory else messages

            # Call LLM with tools
            response = await self._call_llm(
                messages=context,
                tools=tools,
                spinner_message="Analyzing request...",
            )

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
                    await self.memory.add_message(assistant_msg, actual_tokens=actual_tokens)

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

            # Print thinking/reasoning if available (for all responses)
            if hasattr(self.llm, "extract_thinking"):
                thinking = self.llm.extract_thinking(response)
                if thinking:
                    terminal_ui.print_thinking(thinking)

            # Check if we're done (no tool calls)
            if response.stop_reason == StopReason.STOP:
                final_answer = self._extract_text(response)
                terminal_ui.console.print("\n[bold green]✓ Final answer received[/bold green]")
                return final_answer

            # Execute tool calls
            if response.stop_reason == StopReason.TOOL_CALLS:
                # Print assistant text content alongside tool calls
                if response.content:
                    terminal_ui.print_assistant_message(response.content)

                tool_calls = self.llm.extract_tool_calls(response)

                if not tool_calls:
                    # No tool calls found, return response
                    final_answer = self._extract_text(response)
                    return final_answer if final_answer else "No response generated."

                # Decide parallel vs sequential execution
                all_readonly = len(tool_calls) > 1 and all(
                    self.tool_executor.is_tool_readonly(tc.name) for tc in tool_calls
                )

                if all_readonly:
                    tool_results = await self._execute_tools_parallel(tool_calls)
                else:
                    tool_results = await self._execute_tools_sequential(tool_calls)

                # Format tool results and add to context
                # format_tool_results now returns a list of tool messages (OpenAI format)
                result_messages = self.llm.format_tool_results(tool_results)
                if isinstance(result_messages, list):
                    for msg in result_messages:
                        if use_memory and save_to_memory:
                            await self.memory.add_message(msg)
                        else:
                            messages.append(msg)
                else:
                    # Backward compatibility: single message
                    if use_memory and save_to_memory:
                        await self.memory.add_message(result_messages)
                    else:
                        messages.append(result_messages)

    async def _execute_tools_sequential(self, tool_calls: List[ToolCall]) -> List[ToolResult]:
        """Execute tool calls one at a time (default path)."""
        tool_results: List[ToolResult] = []
        for tc in tool_calls:
            terminal_ui.print_tool_call(tc.name, tc.arguments)

            async with AsyncSpinner(terminal_ui.console, f"Executing {tc.name}..."):
                result = await self.tool_executor.execute_tool_call(tc.name, tc.arguments)

            terminal_ui.print_tool_result(result)
            logger.debug(f"Tool result: {result[:200]}{'...' if len(result) > 200 else ''}")

            tool_results.append(ToolResult(tool_call_id=tc.id, content=result, name=tc.name))
        return tool_results

    async def _execute_tools_parallel(self, tool_calls: List[ToolCall]) -> List[ToolResult]:
        """Execute readonly tool calls concurrently."""
        results: List[str] = [None] * len(tool_calls)  # type: ignore[list-item]

        # Print all tool calls upfront
        for tc in tool_calls:
            terminal_ui.print_tool_call(tc.name, tc.arguments)

        async def _run(index: int, tc: ToolCall) -> None:
            results[index] = await self.tool_executor.execute_tool_call(tc.name, tc.arguments)

        tool_names = ", ".join(tc.name for tc in tool_calls)
        async with (
            AsyncSpinner(
                terminal_ui.console,
                f"Executing {len(tool_calls)} tools in parallel ({tool_names})...",
            ),
            asyncio.TaskGroup() as tg,
        ):
            for i, tc in enumerate(tool_calls):
                tg.create_task(_run(i, tc))

        # Print results in order after all complete
        tool_results: List[ToolResult] = []
        for i, tc in enumerate(tool_calls):
            terminal_ui.print_tool_result(results[i])
            logger.debug(f"Tool result: {results[i][:200]}{'...' if len(results[i]) > 200 else ''}")
            tool_results.append(ToolResult(tool_call_id=tc.id, content=results[i], name=tc.name))
        return tool_results

    def switch_model(self, model_id: str) -> bool:
        """Switch to a different model.

        Args:
            model_id: LiteLLM model ID to switch to

        Returns:
            True if switch was successful, False otherwise
        """
        if not self.model_manager:
            logger.warning("No model manager available for switching models")
            return False

        profile = self.model_manager.get_model(model_id)
        if not profile:
            logger.error(f"Model '{model_id}' not found")
            return False

        # Validate the model
        is_valid, error_msg = self.model_manager.validate_model(profile)
        if not is_valid:
            logger.error(f"Invalid model: {error_msg}")
            return False

        # Switch the model
        new_profile = self.model_manager.switch_model(model_id)
        if not new_profile:
            logger.error(f"Failed to switch to model '{model_id}'")
            return False

        # Reinitialize LLM adapter with new model
        from llm import LiteLLMAdapter

        new_llm = LiteLLMAdapter(
            model=new_profile.model_id,
            api_key=new_profile.api_key,
            api_base=new_profile.api_base,
            timeout=new_profile.timeout,
            drop_params=new_profile.drop_params,
        )
        self._set_llm_adapter(new_llm)

        logger.info(f"Switched to model: {new_profile.model_id}")
        return True

    def get_current_model_info(self) -> Optional[dict]:
        """Get information about the current model.

        Returns:
            Dictionary with model info or None if not available
        """
        if self.model_manager:
            profile = self.model_manager.get_current_model()
            if not profile:
                return None
            return {
                "name": profile.model_id,
                "model_id": profile.model_id,
                "provider": profile.provider,
            }
        return None

    async def _ralph_loop(
        self,
        messages: List[LLMMessage],
        tools: List,
        use_memory: bool = True,
        save_to_memory: bool = True,
        task: str = "",
        max_iterations: int = 3,
        verifier: Optional[Verifier] = None,
    ) -> str:
        """Outer verification loop that wraps _react_loop.

        After _react_loop returns a final answer, a verifier judges whether the
        original task is satisfied. If not, feedback is injected and the inner
        loop re-enters.

        Args:
            messages: Initial message list (passed through to _react_loop).
            tools: List of available tool schemas.
            use_memory: If True, use self.memory for context.
            save_to_memory: If True, save messages to self.memory.
            task: The original task description.
            max_iterations: Maximum number of outer verification iterations.
            verifier: Optional custom Verifier instance. Defaults to LLMVerifier.

        Returns:
            Final answer as a string.
        """
        if verifier is None:
            verifier = LLMVerifier(self.llm, terminal_ui)

        previous_results: List[VerificationResult] = []

        for iteration in range(1, max_iterations + 1):
            logger.debug(f"Ralph loop iteration {iteration}/{max_iterations}")

            result = await self._react_loop(
                messages=messages,
                tools=tools,
                use_memory=use_memory,
                save_to_memory=save_to_memory,
                task=task,
            )

            # Skip verification on last iteration — just return whatever we got
            if iteration == max_iterations:
                logger.debug("Ralph loop: max iterations reached, returning result")
                terminal_ui.console.print(
                    f"\n[bold dark_orange]⚠ Verification skipped "
                    f"(max iterations {max_iterations} reached), returning last result[/bold dark_orange]"
                )
                return result

            verification = await verifier.verify(
                task=task,
                result=result,
                iteration=iteration,
                previous_results=previous_results,
            )
            previous_results.append(verification)

            if verification.complete:
                logger.debug(f"Ralph loop: verified complete — {verification.reason}")
                terminal_ui.console.print(
                    f"\n[bold green]✓ Verification passed "
                    f"(attempt {iteration}/{max_iterations}): {verification.reason}[/bold green]"
                )
                return result

            # Inject feedback as a user message so the next _react_loop iteration
            # picks it up from memory.
            feedback = (
                f"Your previous answer was reviewed and found incomplete. "
                f"Feedback: {verification.reason}\n\n"
                f"Please address the feedback and provide a complete answer."
            )
            # Print the incomplete result so the user can see what the agent produced
            terminal_ui.print_unfinished_answer(result)

            logger.debug(f"Ralph loop: injecting feedback — {verification.reason}")
            terminal_ui.console.print(
                f"\n[bold yellow]⟳ Verification feedback (attempt {iteration}/{max_iterations}): "
                f"{verification.reason}[/bold yellow]"
            )

            if use_memory and save_to_memory:
                await self.memory.add_message(LLMMessage(role="user", content=feedback))
            else:
                messages.append(LLMMessage(role="user", content=feedback))

        # Should not reach here, but return last result as safety fallback
        return result  # type: ignore[possibly-undefined]
