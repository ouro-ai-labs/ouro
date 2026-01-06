"""ReAct (Reasoning + Acting) agent implementation."""
from llm import LLMMessage, ToolResult

from .base import BaseAgent


class ReActAgent(BaseAgent):
    """Agent using ReAct (Reasoning + Acting) pattern."""

    SYSTEM_PROMPT = """You are a helpful assistant that can use tools to accomplish tasks.

You should use the following loop:
1. Think about what to do next (reasoning)
2. Use a tool if needed (action)
3. Observe the result
4. Repeat until you can answer the user's question

When you have enough information, provide your final answer directly without using any more tools."""

    def run(self, task: str) -> str:
        """Execute ReAct loop until task is complete.

        Args:
            task: The task to complete

        Returns:
            Final answer as a string
        """
        # Initialize conversation with system message and user task
        messages = [
            LLMMessage(role="system", content=self.SYSTEM_PROMPT),
            LLMMessage(role="user", content=task)
        ]
        tools = self.tool_executor.get_tool_schemas()

        for iteration in range(self.max_iterations):
            print(f"\n--- Iteration {iteration + 1} ---")

            # Call LLM with tools
            response = self._call_llm(messages=messages, tools=tools)

            # Add assistant response to conversation
            messages.append(LLMMessage(role="assistant", content=response.content))

            # Check if we're done (no tool calls)
            if response.stop_reason == "end_turn":
                final_answer = self._extract_text(response)
                print(f"\nFinal answer received.")
                return final_answer

            # Execute tool calls and add results
            if response.stop_reason == "tool_use":
                # Extract tool calls using LLM abstraction
                tool_calls = self.llm.extract_tool_calls(response)

                if not tool_calls:
                    # No tool calls found, end loop
                    final_answer = self._extract_text(response)
                    return final_answer if final_answer else "No response generated."

                # Execute each tool call
                tool_results = []
                for tc in tool_calls:
                    print(f"Tool call: {tc.name}")
                    print(f"Input: {tc.arguments}")

                    result = self.tool_executor.execute_tool_call(tc.name, tc.arguments)
                    print(f"Result: {result[:200]}...")  # Print first 200 chars

                    tool_results.append(ToolResult(
                        tool_call_id=tc.id,
                        content=result
                    ))

                # Format tool results and add to conversation
                result_message = self.llm.format_tool_results(tool_results)
                messages.append(result_message)

        return "Max iterations reached without completion."
