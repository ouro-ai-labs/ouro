"""Timer tool for scheduling delayed or periodic agent tasks."""

import asyncio
import time
from typing import Any, Dict

from croniter import croniter

from tools.base import BaseTool


class TimerTool(BaseTool):
    """Wait until a specified time or duration, then return the task description."""

    @property
    def name(self) -> str:
        return "timer"

    @property
    def description(self) -> str:
        return (
            "Set a timer to trigger after a delay or at a cron-scheduled time. "
            "Modes: 'delay' (wait N seconds), 'interval' (wait N seconds, agent loops), "
            "'cron' (wait until next cron match). Returns the task description when triggered."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "mode": {
                "type": "string",
                "description": (
                    "Timer mode: 'delay' (one-shot, fire once after N seconds), "
                    "'interval' (recurring, fire every N seconds — you must call timer again after each task), "
                    "'cron' (recurring, fire on cron schedule — you must call timer again after each task)"
                ),
                "enum": ["delay", "interval", "cron"],
            },
            "value": {
                "type": "string",
                "description": (
                    "For delay/interval: number of seconds (e.g. '60'). "
                    "For cron: a cron expression (e.g. '0 9 * * *' for daily at 9 AM)."
                ),
            },
            "task": {
                "type": "string",
                "description": "Task description to return when the timer triggers.",
            },
        }

    async def execute(self, mode: str, value: str, task: str) -> str:
        if mode == "delay":
            try:
                seconds = float(value)
            except ValueError:
                return f"Error: value must be a number for delay mode, got '{value}'"
            if seconds < 0:
                return f"Error: value must be non-negative, got {seconds}"
            await asyncio.sleep(seconds)
            return f"Timer triggered. Task to execute: {task}"

        if mode == "interval":
            try:
                seconds = float(value)
            except ValueError:
                return f"Error: value must be a number for interval mode, got '{value}'"
            if seconds < 0:
                return f"Error: value must be non-negative, got {seconds}"
            await asyncio.sleep(seconds)
            return (
                f"Timer triggered. Task to execute: {task}\n\n"
                f"[IMPORTANT: This is a recurring interval timer. "
                f"After completing the task above, you MUST call the timer tool again "
                f'with the same parameters (mode="interval", value="{value}", '
                f'task="{task}") to continue the cycle.]'
            )

        if mode == "cron":
            if not croniter.is_valid(value):
                return f"Error: invalid cron expression '{value}'"
            now = time.time()
            cron = croniter(value, now)
            next_fire = cron.get_next(float)
            wait_seconds = max(0, next_fire - now)
            await asyncio.sleep(wait_seconds)
            return (
                f"Timer triggered. Task to execute: {task}\n\n"
                f"[IMPORTANT: This is a recurring cron timer. "
                f"After completing the task above, you MUST call the timer tool again "
                f'with the same parameters (mode="cron", value="{value}", '
                f'task="{task}") to continue the schedule.]'
            )

        return f"Error: unknown mode '{mode}'. Use 'delay', 'interval', or 'cron'."
