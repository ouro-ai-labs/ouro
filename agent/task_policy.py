"""Task-graph runtime policies used by LoopAgent.

This module keeps task-specific orchestration policies separate from the core
agent loop to reduce coupling and keep the main runtime easier to reason about.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from llm import LLMMessage

if TYPE_CHECKING:
    from .agent import LoopAgent

logger = logging.getLogger(__name__)


class TaskPolicy:
    """Runtime policies for task-graph workflows."""

    def __init__(self, agent: LoopAgent):
        self.agent = agent

    def extract_task_dump_md_request(self, task: str) -> tuple[str, bool] | None:
        """Parse explicit TaskDumpMd(path=..., includeDebug=...) user request."""
        if "TaskDumpMd" not in task:
            return None

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
            include_debug = debug_match.group(1).lower() in {"true", "1"}

        return (path_value, include_debug)

    async def auto_dump_tasks_md_if_requested(self, task: str) -> None:
        store = getattr(self.agent, "task_store", None)
        if store is None:
            return

        request = self.extract_task_dump_md_request(task)
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

    async def task_incomplete_summary(self) -> str | None:
        store = getattr(self.agent, "task_store", None)
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
        for task_item in incomplete:
            blocked_by = list(getattr(task_item, "blocked_by", []) or [])
            missing = []
            for dep_id in blocked_by:
                dep = tasks_by_id.get(dep_id)
                if not dep or getattr(dep, "status", None) != "completed":
                    missing.append(dep_id)
            missing_txt = f" missingDeps={','.join(missing)}" if missing else ""
            lines.append(
                f"- {task_item.id}: {task_item.status} :: {task_item.content}{missing_txt}"
            )
        return "\n".join(lines).rstrip()

    async def enforce_tasks_completed(self, *, tools: list, task: str, result: str) -> str:
        """If task graph is incomplete, force another react pass to finish it."""
        passes = 0
        while passes < 3:
            summary = await self.task_incomplete_summary()
            if not summary:
                return result
            passes += 1
            gate_msg = (
                "You created Tasks but some are still incomplete. Continue by using the Task* tools "
                "to complete ALL tasks, then provide the final answer. Incomplete tasks:\n"
                f"{summary}"
            )
            await self.agent.memory.add_message(LLMMessage(role="user", content=gate_msg))
            result = await self.agent._react_loop(
                messages=[],
                tools=tools,
                use_memory=True,
                save_to_memory=True,
                task=task,
            )
        return result

    async def prefer_terminal_task_detail_result(self, result: str) -> str:
        """Prefer terminal task detail as final output when graph is fully complete."""
        store = getattr(self.agent, "task_store", None)
        if store is None:
            return result

        try:
            tasks = await store.list_tasks()
        except Exception:
            return result
        if not tasks:
            return result
        if any(getattr(t, "status", None) != "completed" for t in tasks):
            return result

        blocks_map: dict[str, list[str]] = {t.id: [] for t in tasks}
        for task_item in tasks:
            for dep_id in list(getattr(task_item, "blocked_by", []) or []):
                if dep_id in blocks_map:
                    blocks_map[dep_id].append(task_item.id)

        terminal_with_detail = [
            task_item
            for task_item in tasks
            if not blocks_map.get(task_item.id)
            and str(getattr(task_item, "detail", "") or "").strip()
        ]
        if not terminal_with_detail:
            return result

        preferred_candidates = [
            task_item
            for task_item in terminal_with_detail
            if list(getattr(task_item, "blocked_by", []) or [])
        ]
        if preferred_candidates:
            terminal_with_detail = preferred_candidates
        elif not (len(tasks) == 1 and len(terminal_with_detail) == 1):
            return result

        def _rank(task_item) -> tuple[int, int]:
            detail_len = len(str(getattr(task_item, "detail", "") or ""))
            try:
                order = int(str(getattr(task_item, "id", "0")))
            except ValueError:
                order = 0
            return (detail_len, order)

        chosen = max(terminal_with_detail, key=_rank)
        chosen_detail = str(getattr(chosen, "detail", "") or "").strip()
        if not chosen_detail:
            return result
        return chosen_detail
