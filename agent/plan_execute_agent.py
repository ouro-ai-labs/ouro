"""Plan-and-Execute agent implementation."""

import re
from typing import List

from llm import LLMMessage
from utils import terminal_ui

from .base import BaseAgent
from .context import format_context_prompt


class PlanExecuteAgent(BaseAgent):
    """Agent using Plan-and-Execute pattern."""

    PLANNER_PROMPT = """<role>
You are a planning expert who creates clear, actionable step-by-step plans for complex tasks.
</role>

<instructions>
Given a task, create a detailed plan with numbered steps.

IMPORTANT RULES:
- Each step must be clear and actionable
- Break complex operations into smaller sub-steps
- Consider dependencies between steps
- Be specific about what tools or operations are needed
- Do NOT execute the plan, only create it

OUTPUT FORMAT:
Return ONLY a numbered list of steps (e.g., "1. Step description")
</instructions>

<task>
{task}
</task>

<good_example>
Task: Analyze Python codebase for security issues
Plan:
1. Use glob_files to find all Python files in the project
2. Use grep_content to search for common security patterns (eval, exec, pickle)
3. Read flagged files to analyze context
4. Compile findings into security report
</good_example>

Plan:"""

    EXECUTOR_PROMPT = """<role>
You are executing a specific step of a larger plan. Focus only on completing this step.
</role>

<current_step>
Step {step_num}: {step}
</current_step>

<previous_context>
{history}
</previous_context>

<instructions>
IMPORTANT RULES:
- Focus ONLY on completing the current step
- Use the most efficient tools available
- Use grep_content and glob_files for file operations when possible
- Provide a concise summary of what you accomplished when done

TOOL GUIDELINES:
- glob_files: Fast file pattern matching
- grep_content: Search file contents efficiently
- read_file: Only when you need full file contents
- edit_file: For targeted edits

When you complete the step, provide a brief summary of your results.
</instructions>"""

    SYNTHESIZER_PROMPT = """<role>
You are synthesizing results from a multi-step plan execution into a final answer.
</role>

<original_task>
{task}
</original_task>

<execution_results>
{results}
</execution_results>

<instructions>
IMPORTANT RULES:
- Review all step results carefully
- Provide a comprehensive answer to the original task
- Highlight key findings or outputs
- Be concise but complete
- If any steps failed, mention it in your answer

Provide your final answer to the user based on the execution results above.
</instructions>"""

    def run(self, task: str) -> str:
        """Execute Plan-and-Execute loop.

        Args:
            task: The task to complete

        Returns:
            Final answer as a string
        """
        # Phase 1: Create plan
        terminal_ui.console.print()
        terminal_ui.console.rule("[bold cyan]PHASE 1: PLANNING[/bold cyan]", style="cyan")
        plan = self._create_plan(task)
        terminal_ui.console.print()
        terminal_ui.console.print(plan, style="dim")

        # Phase 2: Execute each step
        terminal_ui.console.print()
        terminal_ui.console.rule("[bold yellow]PHASE 2: EXECUTION[/bold yellow]", style="yellow")
        step_results = []
        steps = self._parse_plan(plan)

        if not steps:
            return "Failed to parse plan into executable steps."

        for i, step in enumerate(steps, 1):
            terminal_ui.console.print()
            terminal_ui.console.print(
                f"[bold magenta]▶ Step {i}/{len(steps)}:[/bold magenta] [white]{step}[/white]"
            )
            result = self._execute_step(step, i, step_results, task)
            step_results.append(f"Step {i}: {step}\nResult: {result}")
            terminal_ui.print_success(f"Step {i} completed")

        # Phase 3: Synthesize final answer
        terminal_ui.console.print()
        terminal_ui.console.rule("[bold green]PHASE 3: SYNTHESIS[/bold green]", style="green")
        final_answer = self._synthesize_results(task, step_results)

        # Print memory statistics
        self._print_memory_stats()

        # Save memory state to database after task completion
        self.memory.save_memory()

        return final_answer

    def _print_memory_stats(self):
        """Print memory usage statistics."""
        stats = self.memory.get_stats()
        terminal_ui.print_memory_stats(stats)

    def _create_plan(self, task: str) -> str:
        """Generate a plan without using tools.

        Args:
            task: The task to plan

        Returns:
            Generated plan as string
        """
        # Build system message with context
        system_content = "You are a planning expert. Create clear, actionable plans."
        try:
            context = format_context_prompt()
            system_content = context + "\n" + system_content
        except Exception:
            # If context gathering fails, continue without it
            pass

        messages = [
            LLMMessage(role="system", content=system_content),
            LLMMessage(role="user", content=self.PLANNER_PROMPT.format(task=task)),
        ]
        response = self._call_llm(messages=messages)

        # Track token usage from planning phase
        if response.usage:
            self.memory.token_tracker.add_input_tokens(response.usage.get("input_tokens", 0))
            self.memory.token_tracker.add_output_tokens(response.usage.get("output_tokens", 0))

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
                content=self.EXECUTOR_PROMPT.format(step_num=step_num, step=step, history=history),
            )
        ]

        tools = self.tool_executor.get_tool_schemas()

        # Use the generic ReAct loop for this step (mini-loop)
        result = self._react_loop(
            messages=messages,
            tools=tools,
            max_iterations=self.max_iterations,  # Limited iterations for each step
            use_memory=False,  # Use local messages list, not global memory
            save_to_memory=False,  # Don't auto-save to memory
            verbose=False,  # Quieter output for sub-steps
        )

        # Save step result summary to main memory
        self.memory.add_message(
            LLMMessage(role="assistant", content=f"Step {step_num} completed: {result}")
        )

        return result

    def _synthesize_results(self, task: str, results: List[str]) -> str:
        """Combine step results into final answer."""
        messages = [
            LLMMessage(
                role="user",
                content=self.SYNTHESIZER_PROMPT.format(results="\n\n".join(results), task=task),
            )
        ]
        response = self._call_llm(messages=messages)

        # Track token usage from synthesis phase
        if response.usage:
            self.memory.token_tracker.add_input_tokens(response.usage.get("input_tokens", 0))
            self.memory.token_tracker.add_output_tokens(response.usage.get("output_tokens", 0))

        return self._extract_text(response)
