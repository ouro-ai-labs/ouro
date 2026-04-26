"""Cron management tool for agents to schedule recurring tasks."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ouro.capabilities.tools.base import BaseTool

if TYPE_CHECKING:
    from ouro.interfaces.bot.proactive import CronScheduler


class CronTool(BaseTool):
    """Tool for managing cron-scheduled tasks during conversation."""

    def __init__(self, cron_scheduler: CronScheduler):
        self._scheduler = cron_scheduler

    @property
    def name(self) -> str:
        return "manage_cron"

    @property
    def description(self) -> str:
        return """Manage cron-scheduled tasks (recurring or one-time).

WHEN TO USE:
- User asks to schedule a recurring task (e.g. "send me a daily report every morning at 9am")
- User asks to schedule a one-time task (e.g. "remind me about the meeting tomorrow at 3pm")
- User wants to list, modify, or remove scheduled jobs

OPERATIONS:
- add: Create a new cron job (requires schedule and prompt)
- remove: Delete an existing job (requires job_id)
- list: View all scheduled jobs

SCHEDULE FORMAT:
- Cron expression: "0 9 * * *" (daily at 9am), "*/30 * * * *" (every 30 min)
- Interval in seconds: "3600" (every hour), "300" (every 5 min)
- One-time: ISO datetime "2026-02-22T15:00:00+08:00" (execute once then auto-remove)

SESSION MODE (optional, default "main"):
- main: run inside the most recently active IM session; reply goes back to that session. Best for reminders and personal recurring tasks.
- isolated: run in a throwaway agent (no conversation history) and broadcast the reply to every active session.

EXAMPLES:
- add recurring: {"schedule": "0 9 * * *", "prompt": "Generate today's work report", "name": "Daily report"}
- add one-time: {"schedule": "2026-02-23T15:00:00+08:00", "prompt": "Remind me about the meeting", "name": "Meeting reminder"}
- add broadcast: {"schedule": "0 * * * *", "prompt": "Hourly status ping", "session_mode": "isolated"}
- list: {} (no parameters needed)
- remove: {"job_id": "abc123def456"}"""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "operation": {
                "type": "string",
                "description": "Operation to perform: add, remove, or list",
            },
            "schedule": {
                "type": "string",
                "description": "Cron expression, interval in seconds, or ISO datetime for one-time (for add)",
                "default": "",
            },
            "prompt": {
                "type": "string",
                "description": "Task prompt that the agent will execute on each run (for add)",
                "default": "",
            },
            "name": {
                "type": "string",
                "description": "Optional human-readable name for the job (for add)",
                "default": "",
            },
            "job_id": {
                "type": "string",
                "description": "Job ID to remove (for remove)",
                "default": "",
            },
            "session_mode": {
                "type": "string",
                "description": (
                    "For add: 'main' (run in the most recently active IM session; "
                    "default) or 'isolated' (throwaway agent, broadcast reply to all sessions)."
                ),
                "default": "main",
            },
        }

    async def execute(
        self,
        operation: str,
        schedule: str = "",
        prompt: str = "",
        name: str = "",
        job_id: str = "",
        session_mode: str = "main",
        **kwargs: Any,
    ) -> str:
        try:
            if operation == "add":
                return self._add(schedule, prompt, name, session_mode)
            elif operation == "remove":
                return self._remove(job_id)
            elif operation == "list":
                return self._list()
            else:
                return f"Error: Unknown operation '{operation}'. Supported: add, remove, list"
        except Exception as e:
            return f"Error executing cron operation: {e}"

    def _add(self, schedule: str, prompt: str, name: str, session_mode: str) -> str:
        if not schedule:
            return "Error: 'schedule' is required for add operation"
        if not prompt:
            return "Error: 'prompt' is required for add operation"
        # The manage_cron tool cannot bind to the caller's chat session (no
        # conversation context passed in), so it only exposes 'main' and
        # 'isolated'. The /cron add slash command handles 'current'.
        mode = session_mode or "main"
        if mode not in ("main", "isolated"):
            return (
                f"Error: session_mode '{mode}' not supported by manage_cron; "
                "use 'main' or 'isolated'."
            )
        try:
            job = self._scheduler.add_job(schedule, prompt, name=name, session_mode=mode)
        except (ValueError, KeyError) as exc:
            return f"Error: Invalid schedule '{schedule}': {exc}"
        return (
            f"Created cron job {job.id}"
            f" (name={job.name!r},"
            f" schedule={job.schedule_type}={job.schedule_value},"
            f" session={job.session_mode},"
            f" next_run={job.next_run_at})"
        )

    def _remove(self, job_id: str) -> str:
        if not job_id:
            return "Error: 'job_id' is required for remove operation"
        if self._scheduler.remove_job(job_id):
            return f"Removed cron job {job_id}."
        return f"Error: No cron job with id '{job_id}'."

    def _list(self) -> str:
        jobs = self._scheduler.jobs
        if not jobs:
            return "No cron jobs scheduled."
        lines = []
        for j in jobs:
            status = "enabled" if j.enabled else "disabled"
            lines.append(
                f"- {j.id}: {j.name}"
                f" [{j.schedule_type}={j.schedule_value}]"
                f" ({status}, next_run={j.next_run_at})"
            )
        return "Cron jobs:\n" + "\n".join(lines)
