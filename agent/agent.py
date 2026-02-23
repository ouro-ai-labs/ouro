"""Loop agent implementation."""

import logging
from typing import Optional

from config import Config
from llm import LLMMessage
from utils import terminal_ui
from utils.tui.progress import AsyncSpinner

from .base import BaseAgent
from .context import format_context_prompt
from .task_policy import TaskPolicy

logger = logging.getLogger(__name__)


class LoopAgent(BaseAgent):
    """Primary agent implementation — one unified loop for all tasks."""

    # Optional sections injected into system prompt (set by caller)
    _skills_section: Optional[str] = None
    _soul_section: Optional[str] = None

    def set_skills_section(self, skills_section: Optional[str]) -> None:
        """Set the skills section to inject into system prompt.

        Args:
            skills_section: Rendered skills section from render_skills_section(),
                           or None to disable skills injection.
        """
        self._skills_section = skills_section

    def set_soul_section(self, soul_section: Optional[str]) -> None:
        """Set the soul/personality section to prepend to the system prompt.

        Args:
            soul_section: Content from ~/.ouro/bot/soul.md, or None to skip.
        """
        self._soul_section = soul_section

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
- Tasks + sub_agent_batch are experimental graph-orchestration tools. Use them when dependency-aware planning is beneficial or explicitly requested.
- multi_task remains available for legacy/simple parallel subtasks.
- Use TaskCreate/TaskUpdate/TaskList/TaskGet/TaskFanout/TaskDumpMd for task graphs (see each tool's description for the full contract).
- Use manage_todo_list only for a simple linear checklist or if Tasks tools are unavailable.
</tool_usage_guidelines>

<agents_md>
Project instructions may be defined in AGENTS.md files in the project directory structure.
Before modifying code, check for AGENTS.md: glob_files(pattern="AGENTS.md")
If found, read it with read_file and follow the project-specific instructions.
AGENTS.md is optional. If not found, proceed normally.
</agents_md>

"""

    def _task_policy(self) -> TaskPolicy:
        policy = getattr(self, "_task_policy_impl", None)
        if policy is None:
            policy = TaskPolicy(self)
            self._task_policy_impl = policy
        return policy

    # Backward-compatible wrappers (also used by existing tests).
    def _extract_task_dump_md_request(self, task: str) -> tuple[str, bool] | None:
        return self._task_policy().extract_task_dump_md_request(task)

    async def _auto_dump_tasks_md_if_requested(self, task: str) -> None:
        await self._task_policy().auto_dump_tasks_md_if_requested(task)

    async def _task_incomplete_summary(self) -> str | None:
        return await self._task_policy().task_incomplete_summary()

    async def _enforce_tasks_completed(self, *, tools: list, task: str, result: str) -> str:
        return await self._task_policy().enforce_tasks_completed(
            tools=tools, task=task, result=result
        )

    async def _prefer_terminal_task_detail_result(self, result: str) -> str:
        return await self._task_policy().prefer_terminal_task_detail_result(result)

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
                    async with AsyncSpinner(
                        terminal_ui.console, "Loading memory...", title="Working"
                    ):
                        ltm_section = await self.memory.long_term.load_and_format()
                    if ltm_section:
                        system_content = system_content + "\n" + ltm_section
                except Exception:
                    logger.warning("Failed to load long-term memory", exc_info=True)

            # Inject skills section if available
            if self._skills_section:
                system_content = system_content + "\n\n" + self._skills_section

            # Append soul/personality section at the end (bot mode only).
            # Placed last so it benefits from recency bias for style influence
            # while core instructions (tools, safety) retain higher priority.
            if self._soul_section:
                system_content = (
                    system_content
                    + "\n\n<soul>\n"
                    + "Embody the persona and tone defined below. "
                    + "Follow its guidance unless higher-priority instructions override it.\n\n"
                    + self._soul_section
                    + "\n</soul>"
                )

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

        result = await self._enforce_tasks_completed(tools=tools, task=task, result=result)
        preferred_result = await self._prefer_terminal_task_detail_result(result)
        if preferred_result != result:
            # Keep persisted conversation consistent with the returned final output.
            await self.memory.add_message(LLMMessage(role="assistant", content=preferred_result))
            result = preferred_result

        # Best-effort: if the user explicitly asked to call TaskDumpMd(path=..., includeDebug=...),
        # ensure we produce a final on-disk snapshot even if the LLM forgot or dumped too early.
        await self._auto_dump_tasks_md_if_requested(task)

        self._print_memory_stats()

        # Save memory state to database after task completion
        await self.memory.save_memory()

        return result

    def _print_memory_stats(self):
        """Print memory usage statistics."""
        stats = self.memory.get_stats()
        terminal_ui.print_memory_stats(stats)
