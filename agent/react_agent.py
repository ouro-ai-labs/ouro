"""ReAct (Reasoning + Acting) agent implementation."""

import asyncio

from llm import LLMMessage
from utils import terminal_ui

from .base import BaseAgent
from .context import format_context_prompt


class ReActAgent(BaseAgent):
    """Agent using ReAct (Reasoning + Acting) pattern."""

    SYSTEM_PROMPT = """<role>
You are a helpful AI assistant that uses tools to accomplish tasks efficiently and reliably.
</role>

<critical_rules>
IMPORTANT: Always think before acting
IMPORTANT: Use the most efficient tool for each operation
IMPORTANT: Manage todo lists for complex multi-step tasks
IMPORTANT: Mark tasks completed IMMEDIATELY after finishing them
</critical_rules>

<task_management>
Use the manage_todo_list tool for complex tasks to prevent forgetting steps.

WHEN TO USE TODO LISTS:
- Tasks with 3+ distinct steps
- Multi-file operations
- Complex workflows requiring planning
- Any task where tracking progress helps

TODO LIST RULES:
- Create todos BEFORE starting complex work
- Exactly ONE task must be in_progress at any time
- Mark tasks completed IMMEDIATELY after finishing
- Update status as you work through the list

<good_example>
User: Create a data pipeline that reads CSV, processes it, and generates report
Assistant: I'll use the todo list to track this multi-step task.
[Calls manage_todo_list with operation="add" for each step]
[Marks first task as in_progress before starting]
[Uses read_file tool]
[Marks as completed, moves to next task]
</good_example>

<bad_example>
User: Create a data pipeline that reads CSV, processes it, and generates report
Assistant: [Immediately starts without planning, forgets steps halfway through]
</bad_example>
</task_management>

<tool_usage_guidelines>
For file operations:
- Use glob_files to find files by pattern (fast, efficient)
- Use code_navigator to find function/class definitions (10x faster than grep, AST-based)
- Use grep_content for text search only (not for finding code structure)
- Use read_file only when you need full contents (avoid reading multiple large files at once)
- Use smart_edit for code edits (fuzzy match, auto backup, diff preview)
- Use edit_file for simple append/insert operations only
- Use write_file only for creating new files or complete rewrites

CRITICAL: Never read multiple large files in a single iteration - this causes context overflow!
Instead: Use code_navigator or grep_content to find specific information, then read only what you need.

For complex tasks:
- Use manage_todo_list to track progress
- Break into smaller, manageable steps
- Mark tasks completed as you go
- Keep exactly ONE task in_progress at a time

<good_example>
Task: Find all Python files that import 'requests'
Approach:
1. Use glob_files with pattern "**/*.py" to find Python files
2. Use grep_content with pattern "^import requests|^from requests" to search
Result: Efficient, minimal tokens used
</good_example>

<bad_example>
Task: Find all Python files that import 'requests'
Approach:
1. Use read_file on every Python file one by one
2. Manually search through content
Result: Wasteful, uses 100x more tokens
</bad_example>
</tool_usage_guidelines>

<workflow>
For each user request, follow this ReAct pattern:
1. THINK: Analyze what's needed, choose best tools
2. ACT: Execute with appropriate tools
3. OBSERVE: Check results and learn from them
4. REPEAT or COMPLETE: Continue the loop or provide final answer

When you have enough information, provide your final answer directly without using more tools.
</workflow>

<available_tools>
You have access to various tools including:
- Code navigation: code_navigator (find functions/classes/structure/usages)
- Code editing: smart_edit (intelligent edits with preview), edit_file
- File operations: glob_files, grep_content, read_file, write_file, search_files
- Git operations: git_status, git_diff, git_add, git_commit, git_log, git_branch, git_checkout, git_push, git_pull, git_remote, git_stash, git_clean
- Task management: manage_todo_list
- Sub-agent delegation: delegate_subtask (for complex multi-step subtasks)
- Utilities: calculate, web_search, shell

Always choose the most efficient tool for the task at hand.
</available_tools>

<delegation_strategy>
Use delegate_subtask when:
- A subtask requires deep exploration (5+ iterations of searching/reading)
- Subtask details would clutter your context (e.g., exploring large codebases)
- You need to isolate experimental operations
- The subtask is self-contained and doesn't need frequent interaction

Example: "Research all Python files that use asyncio and analyze their patterns"
→ delegate_subtask(subtask_description="Find and analyze all asyncio usage patterns", max_iterations=8)

DO NOT delegate simple operations that can be done in 1-2 tool calls.
</delegation_strategy>"""

    async def run(self, task: str) -> str:
        """Execute ReAct loop until task is complete.

        Args:
            task: The task to complete

        Returns:
            Final answer as a string
        """
        # Build system message with context (only if not already in memory)
        # This allows multi-turn conversations to reuse the same system message
        if not self.memory.system_messages:
            system_content = self.SYSTEM_PROMPT
            try:
                context = await asyncio.to_thread(format_context_prompt)
                system_content = context + "\n" + system_content
            except Exception:
                # If context gathering fails, continue without it
                pass

            # Add system message only on first turn
            await self.memory.add_message(LLMMessage(role="system", content=system_content))

        # Add user task/message
        await self.memory.add_message(LLMMessage(role="user", content=task))

        tools = self.tool_executor.get_tool_schemas()

        # Use the generic ReAct loop implementation
        result = await self._react_loop(
            messages=[],  # Not used when use_memory=True
            tools=tools,
            max_iterations=self.max_iterations,
            use_memory=True,
            save_to_memory=True,
            verbose=True,
            task=task,
        )

        self._print_memory_stats()

        # Save memory state to database after task completion
        self.memory.save_memory()

        return result

    def _print_memory_stats(self):
        """Print memory usage statistics."""
        stats = self.memory.get_stats()
        terminal_ui.print_memory_stats(stats)
