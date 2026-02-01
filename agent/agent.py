"""Loop agent implementation."""

import logging
from typing import Optional

from config import Config
from llm import LLMMessage
from utils import terminal_ui

from .base import BaseAgent
from .context import format_context_prompt

logger = logging.getLogger(__name__)


class LoopAgent(BaseAgent):
    """Primary agent implementation — one unified loop for all tasks."""

    # Skills section to inject into system prompt (set by caller)
    _skills_section: Optional[str] = None

    def set_skills_section(self, skills_section: Optional[str]) -> None:
        """Set the skills section to inject into system prompt.

        Args:
            skills_section: Rendered skills section from render_skills_section(),
                           or None to disable skills injection.
        """
        self._skills_section = skills_section

    SYSTEM_PROMPT = """<role>
You are a helpful AI assistant that uses tools to accomplish tasks efficiently and reliably.
</role>

<critical_rules>
IMPORTANT: Always think before acting
IMPORTANT: Use the most efficient tool for each operation
IMPORTANT: Manage todo lists for complex multi-step tasks
IMPORTANT: Mark tasks completed IMMEDIATELY after finishing them
</critical_rules>

<agents_md>
Project instructions may be defined in AGENTS.md files in the project directory structure.

WHEN TO READ AGENTS.MD:
- Before modifying code or making significant changes
- Before exploring an unfamiliar codebase
- When the user mentions project-specific workflows or conventions
- At the start of complex multi-step tasks

HOW TO FIND AGENTS.MD:
- Look for AGENTS.md in the current working directory first
- If not found, check parent directories up to the git root
- Use the NEAREST AGENTS.md file (more specific wins)
- Use glob_files tool to search: glob_files(pattern="AGENTS.md")

WORKFLOW:
1. Use glob_files to find AGENTS.md files: glob_files(pattern="AGENTS.md")
2. If multiple found, choose the one closest to current working directory
3. Read it with read_file tool
4. Follow the instructions in AGENTS.md for project-specific requirements

<good_example>
User: Update the authentication module
Assistant: Let me first check for project instructions.
[Calls glob_files with pattern="AGENTS.md"]
[Reads the nearest AGENTS.md with read_file]
[Follows instructions: runs tests before commit, uses specific code style, etc.]
</good_example>

<bad_example>
User: Update the authentication module
Assistant: [Immediately starts modifying code without checking AGENTS.md]
</bad_example>

NOTE: AGENTS.md is optional. If not found, proceed normally with general best practices.
</agents_md>

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
- Use grep_content for text/code search in files
- Use read_file only when you need full contents (avoid reading multiple large files at once)
- Use smart_edit for code edits (fuzzy match, auto backup, diff preview)
- Use edit_file for simple append/insert operations only
- Use write_file only for creating new files or complete rewrites

CRITICAL: Never read multiple large files in a single iteration - this causes context overflow!
Instead: Use grep_content to find specific information, then read only what you need.

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

<complex_task_strategy>
For complex tasks, combine tools to achieve an explore-plan-execute workflow:

1. **EXPLORE**: Gather context before acting
   - Use explore_context for parallel information gathering (code structure, web research)

2. **PLAN**: Structure your approach
   - Use manage_todo_list to break down the task into trackable steps
   - Identify dependencies between steps

3. **EXECUTE**: Carry out the plan
   - Use parallel_execute for multiple independent/semi-dependent tasks
   - Use regular tools for simple sequential operations

When to use each approach:
- Simple task (1-2 steps) → Use tools directly
- Medium task (3-5 steps) → Use todo list + sequential execution
- Complex task (needs research) → Explore → Plan → Execute
- Parallel workload → parallel_execute
</complex_task_strategy>"""

    async def run(self, task: str, verify: bool = True) -> str:
        """Execute ReAct loop until task is complete.

        Args:
            task: The task to complete
            verify: If True, use ralph loop (outer verification). If False, use
                    plain react loop (suitable for interactive multi-turn sessions).

        Returns:
            Final answer as a string
        """
        # Build system message with context (only if not already in memory)
        # This allows multi-turn conversations to reuse the same system message
        if not self.memory.system_messages:
            system_content = self.SYSTEM_PROMPT
            try:
                context = await format_context_prompt()
                system_content = context + "\n" + system_content
            except Exception:
                # If context gathering fails, continue without it
                pass

            # Inject long-term memory instructions + current memories
            if self.memory.long_term:
                try:
                    ltm_section = await self.memory.long_term.load_and_format()
                    if ltm_section:
                        system_content = system_content + "\n" + ltm_section
                except Exception:
                    logger.warning("Failed to load long-term memory", exc_info=True)

            # Inject skills section if available
            if self._skills_section:
                system_content = system_content + "\n\n" + self._skills_section

            # Add system message only on first turn
            await self.memory.add_message(LLMMessage(role="system", content=system_content))

        # Add user task/message
        await self.memory.add_message(LLMMessage(role="user", content=task))

        tools = self.tool_executor.get_tool_schemas()

        if verify:
            # Use ralph loop (outer verification wrapping the inner ReAct loop)
            result = await self._ralph_loop(
                messages=[],  # Not used when use_memory=True
                tools=tools,
                use_memory=True,
                save_to_memory=True,
                task=task,
                max_iterations=Config.RALPH_LOOP_MAX_ITERATIONS,
            )
        else:
            # Plain react loop without verification
            result = await self._react_loop(
                messages=[],
                tools=tools,
                use_memory=True,
                save_to_memory=True,
                task=task,
            )

        self._print_memory_stats()

        # Save memory state to database after task completion
        await self.memory.save_memory()

        return result

    def _print_memory_stats(self):
        """Print memory usage statistics."""
        stats = self.memory.get_stats()
        terminal_ui.print_memory_stats(stats)
