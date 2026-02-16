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

<workflow>
For each user request, follow this ReAct pattern:
1. THINK: Analyze what's needed, choose best tools
2. ACT: Execute with appropriate tools
3. OBSERVE: Check results and learn from them
4. REPEAT or COMPLETE: Continue the loop or provide final answer

When you have enough information, provide your final answer directly without using more tools.
</workflow>

<tool_usage_guidelines>
- Use bash for file operations like ls, find, etc.
- Use glob_files to find files by pattern (fast, efficient)
- Use grep_content for text/code search in files
- Use read_file only when you need full contents (avoid reading multiple large files at once)
- Use smart_edit for precise changes (fuzzy match, auto backup, diff preview)
- Use write_file only for creating new files or complete rewrites
- Use multi_task for parallelizable tasks
- Use manage_todo_list to track progress for complex tasks
</tool_usage_guidelines>

<agents_md>
Project instructions may be defined in AGENTS.md files in the project directory structure.
Before modifying code, check for AGENTS.md: glob_files(pattern="AGENTS.md")
If found, read it with read_file and follow the project-specific instructions.
AGENTS.md is optional. If not found, proceed normally.
</agents_md>

"""

    async def run(self, task: str, verify: bool = False) -> str:
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
                system_content = system_content + "\n" + context
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
        self.memory.set_tool_schemas(tools)

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
