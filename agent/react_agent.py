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
        # Initialize memory with system message and user task
        self.memory.add_message(LLMMessage(role="system", content=self.SYSTEM_PROMPT))
        self.memory.add_message(LLMMessage(role="user", content=task))

        tools = self.tool_executor.get_tool_schemas()

        for iteration in range(self.max_iterations):
            print(f"\n--- Iteration {iteration + 1} ---")

            # Get optimized context from memory
            messages = self.memory.get_context_for_llm()

            # Call LLM with tools
            response = self._call_llm(messages=messages, tools=tools)

            # Add assistant response to memory (auto-compression if needed)
            self.memory.add_message(LLMMessage(role="assistant", content=response.content))

            # Show compression info if it happened
            if self.memory.was_compressed_last_iteration:
                print(f"[Memory compressed: saved {self.memory.last_compression_savings} tokens]")

            # Check if we're done (no tool calls)
            if response.stop_reason == "end_turn":
                final_answer = self._extract_text(response)
                print(f"\nFinal answer received.")
                self._print_memory_stats()
                return final_answer

            # Execute tool calls and add results
            if response.stop_reason == "tool_use":
                # Extract tool calls using LLM abstraction
                tool_calls = self.llm.extract_tool_calls(response)

                if not tool_calls:
                    # No tool calls found, end loop
                    final_answer = self._extract_text(response)
                    self._print_memory_stats()
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

                # Format tool results and add to memory
                result_message = self.llm.format_tool_results(tool_results)
                self.memory.add_message(result_message)

        self._print_memory_stats()
        return "Max iterations reached without completion."

    def _print_memory_stats(self):
        """Print memory usage statistics."""
        stats = self.memory.get_stats()
        print("\n--- Memory Statistics ---")
        print(f"Total tokens: {stats['current_tokens']}")
        print(f"Compressions: {stats['compression_count']}")
        print(f"Net savings: {stats['net_savings']} tokens")
        print(f"Total cost: ${stats['total_cost']:.4f}")
        print(f"Messages: {stats['short_term_count']} in memory, {stats['summary_count']} summaries")
