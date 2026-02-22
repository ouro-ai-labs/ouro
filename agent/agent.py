"""Loop agent implementation."""

import logging
import re
from typing import Optional

from config import Config
from llm import LLMMessage
from utils import terminal_ui
from utils.tui.progress import AsyncSpinner

from .base import BaseAgent
from .context import format_context_prompt

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
- Prefer Tasks + sub_agent_batch for parallelizable work. Avoid multi_task (legacy) when Tasks tools are available.
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

    def _extract_task_dump_md_request(self, task: str) -> tuple[str, bool] | None:
        """Best-effort parse of a user request that explicitly asks to call TaskDumpMd(...).

        Only triggers when a path is provided, to avoid surprising writes to repo root.
        """
        if "TaskDumpMd" not in task:
            return None

        # Match TaskDumpMd(path="...") in a user prompt. Keep this conservative to avoid false positives.
        # NOTE: Use \(...\) (not \\(...\\)) so the regex matches a literal '(' and doesn't open a group.
        path_match = re.search(r"TaskDumpMd\([^)]*\bpath\s*=\s*(['\"])(.+?)\1", task)
        if not path_match:
            return None
        path_value = str(path_match.group(2)).strip()
        if not path_value:
            return None

        include_debug = False
        debug_match = re.search(
            r"TaskDumpMd\([^)]*\bincludeDebug\s*=\s*(true|false|1|0)\b",
            task,
            flags=re.IGNORECASE,
        )
        if debug_match:
            raw = debug_match.group(1).lower()
            include_debug = raw in {"true", "1"}

        return (path_value, include_debug)

    async def _auto_dump_tasks_md_if_requested(self, task: str) -> None:
        store = getattr(self, "task_store", None)
        if store is None:
            return

        request = self._extract_task_dump_md_request(task)
        if not request:
            return
        path_value, include_debug = request

        try:
            tasks = await store.list_tasks()
        except Exception:
            return
        if not tasks:
            return

        try:
            from tools.task_tools import TaskDumpMdTool

            dump = TaskDumpMdTool(store)
            await dump.execute(path=path_value, includeDebug=include_debug)
        except Exception:
            logger.warning("Auto TaskDumpMd failed", exc_info=True)

    async def _task_incomplete_summary(self) -> str | None:
        store = getattr(self, "task_store", None)
        if store is None:
            return None

        try:
            tasks = await store.list_tasks()
        except Exception:
            return None

        if not tasks:
            return None

        incomplete = [t for t in tasks if getattr(t, "status", None) != "completed"]
        if not incomplete:
            return None

        tasks_by_id = {t.id: t for t in tasks}
        lines: list[str] = []
        for t in incomplete:
            blocked_by = list(getattr(t, "blocked_by", []) or [])
            missing = []
            for dep_id in blocked_by:
                dep = tasks_by_id.get(dep_id)
                if not dep or getattr(dep, "status", None) != "completed":
                    missing.append(dep_id)
            missing_txt = f" missingDeps={','.join(missing)}" if missing else ""
            lines.append(f"- {t.id}: {t.status} :: {t.content}{missing_txt}")
        return "\n".join(lines).rstrip()

    async def _enforce_tasks_completed(self, *, tools: list, task: str, result: str) -> str:
        """Prevent returning a final answer while Tasks remain incomplete.

        This does not auto-complete tasks; it injects a user message instructing the model
        to continue using Task* tools until the task graph reaches all-completed.
        """
        passes = 0
        while passes < 3:
            summary = await self._task_incomplete_summary()
            if not summary:
                return result
            passes += 1
            gate_msg = (
                "You created Tasks but some are still incomplete. Continue by using the Task* tools "
                "to complete ALL tasks, then provide the final answer. Incomplete tasks:\n"
                f"{summary}"
            )
            await self.memory.add_message(LLMMessage(role="user", content=gate_msg))
            result = await self._react_loop(
                messages=[],
                tools=tools,
                use_memory=True,
                save_to_memory=True,
                task=task,
            )
        return result

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
