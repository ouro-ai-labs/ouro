"""Plan-and-Execute agent implementation."""
from typing import List
import re

from llm import LLMMessage, ToolResult
from .base import BaseAgent


class PlanExecuteAgent(BaseAgent):
    """Agent using Plan-and-Execute pattern."""

    PLANNER_PROMPT = """You are a planning assistant. Given a task, create a step-by-step plan.

Output your plan as a numbered list of steps. Each step should be clear and actionable.
Do not execute the plan, just create it.

Task: {task}

Plan:"""

    EXECUTOR_PROMPT = """You are executing step {step_num} of a plan: {step}

Previous steps and results:
{history}

Use available tools to complete this specific step. When done, provide a brief summary of what you accomplished."""

    SYNTHESIZER_PROMPT = """You have completed a multi-step plan. Here are the results:

{results}

Original task: {task}

Provide a final answer to the user's original task based on these results."""

    def run(self, task: str) -> str:
        """Execute Plan-and-Execute loop.

        Args:
            task: The task to complete

        Returns:
            Final answer as a string
        """
        # Phase 1: Create plan
        print("\n" + "=" * 60)
        print("PHASE 1: PLANNING")
        print("=" * 60)
        plan = self._create_plan(task)
        print(f"\n{plan}")

        # Phase 2: Execute each step
        print("\n" + "=" * 60)
        print("PHASE 2: EXECUTION")
        print("=" * 60)
        step_results = []
        steps = self._parse_plan(plan)

        if not steps:
            return "Failed to parse plan into executable steps."

        for i, step in enumerate(steps, 1):
            print(f"\n--- Executing Step {i}/{len(steps)}: {step} ---")
            result = self._execute_step(step, i, step_results, task)
            step_results.append(f"Step {i}: {step}\nResult: {result}")
            print(f"✓ Step {i} completed")

        # Phase 3: Synthesize final answer
        print("\n" + "=" * 60)
        print("PHASE 3: SYNTHESIS")
        print("=" * 60)
        final_answer = self._synthesize_results(task, step_results)

        # Print memory statistics
        self._print_memory_stats()

        return final_answer

    def _print_memory_stats(self):
        """Print memory usage statistics."""
        stats = self.memory.get_stats()
        print("\n--- Memory Statistics ---")
        print(f"Total tokens: {stats['current_tokens']}")
        print(f"Compressions: {stats['compression_count']}")
        print(f"Net savings: {stats['net_savings']} tokens")
        print(f"Total cost: ${stats['total_cost']:.4f}")

    def _create_plan(self, task: str) -> str:
        """Generate a plan without using tools."""
        messages = [
            LLMMessage(role="system", content="You are a planning expert. Create clear, actionable plans."),
            LLMMessage(role="user", content=self.PLANNER_PROMPT.format(task=task))
        ]
        response = self._call_llm(messages=messages)
        return self._extract_text(response)

    def _parse_plan(self, plan: str) -> List[str]:
        """Parse plan into individual steps."""
        lines = plan.strip().split("\n")
        steps = []
        for line in lines:
            # Match numbered lists like "1. ", "1) ", etc.
            match = re.match(r"^\d+[\.)]\s+(.+)$", line.strip())
            if match:
                steps.append(match.group(1))
        return steps

    def _execute_step(
        self, step: str, step_num: int, previous_results: List[str], original_task: str
    ) -> str:
        """Execute a single step using tools (mini ReAct loop)."""
        history = "\n\n".join(previous_results) if previous_results else "None"

        # Initialize step-specific message list for mini-loop
        messages = [
            LLMMessage(
                role="user",
                content=self.EXECUTOR_PROMPT.format(
                    step_num=step_num, step=step, history=history
                )
            )
        ]

        tools = self.tool_executor.get_tool_schemas()

        # Mini ReAct loop for this step (limited iterations)
        for iteration in range(5):  # Limit iterations per step
            response = self._call_llm(messages=messages, tools=tools)

            messages.append(LLMMessage(role="assistant", content=response.content))

            if response.stop_reason == "end_turn":
                result = self._extract_text(response)
                # Save step result summary to main memory
                self.memory.add_message(
                    LLMMessage(role="assistant", content=f"Step {step_num} completed: {result}")
                )
                return result

            if response.stop_reason == "tool_use":
                # Extract tool calls
                tool_calls = self.llm.extract_tool_calls(response)

                if not tool_calls:
                    result = self._extract_text(response)
                    self.memory.add_message(
                        LLMMessage(role="assistant", content=f"Step {step_num} completed: {result}")
                    )
                    return result

                # Execute tool calls
                tool_results = []
                for tc in tool_calls:
                    print(f"  Tool: {tc.name}")
                    result = self.tool_executor.execute_tool_call(tc.name, tc.arguments)
                    tool_results.append(ToolResult(
                        tool_call_id=tc.id,
                        content=result
                    ))

                # Format and add results
                result_message = self.llm.format_tool_results(tool_results)
                messages.append(result_message)

        incomplete_msg = "Step execution incomplete (max iterations reached)"
        self.memory.add_message(LLMMessage(role="assistant", content=f"Step {step_num}: {incomplete_msg}"))
        return incomplete_msg

    def _synthesize_results(self, task: str, results: List[str]) -> str:
        """Combine step results into final answer."""
        messages = [
            LLMMessage(
                role="user",
                content=self.SYNTHESIZER_PROMPT.format(
                    results="\n\n".join(results), task=task
                )
            )
        ]
        response = self._call_llm(messages=messages)
        return self._extract_text(response)
