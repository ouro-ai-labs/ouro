"""Plan file management for persistent task tracking across sessions.

This module provides Manus AI-style "Plan with Files" functionality,
persisting plans and progress to Markdown files under .aloop/plans/.
"""

import contextlib
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

import aiofiles
import aiofiles.os

from utils import get_logger
from utils.runtime import get_plans_dir

logger = get_logger(__name__)


class PlanStatus(Enum):
    """Status of a plan item (phase or task)."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class PhaseItem:
    """A single task item within a phase."""

    content: str
    status: PlanStatus = PlanStatus.PENDING

    def to_markdown(self) -> str:
        """Convert to markdown checkbox format."""
        checkbox = "[x]" if self.status == PlanStatus.COMPLETED else "[ ]"
        return f"- {checkbox} {self.content}"

    @classmethod
    def from_markdown(cls, line: str) -> Optional["PhaseItem"]:
        """Parse from markdown checkbox format."""
        # Match: - [x] content or - [ ] content
        match = re.match(r"^-\s*\[([ xX])\]\s*(.+)$", line.strip())
        if match:
            checked = match.group(1).lower() == "x"
            content = match.group(2).strip()
            status = PlanStatus.COMPLETED if checked else PlanStatus.PENDING
            return cls(content=content, status=status)
        return None


@dataclass
class Phase:
    """A phase in the task plan."""

    name: str
    items: List[PhaseItem] = field(default_factory=list)
    status: PlanStatus = PlanStatus.PENDING

    def to_markdown(self) -> str:
        """Convert to markdown format."""
        lines = [f"### {self.name}"]
        lines.append(f"- Status: {self.status.value}")
        lines.extend(item.to_markdown() for item in self.items)
        return "\n".join(lines)

    @property
    def completed_count(self) -> int:
        """Count of completed items."""
        return sum(1 for item in self.items if item.status == PlanStatus.COMPLETED)

    @property
    def total_count(self) -> int:
        """Total count of items."""
        return len(self.items)

    def update_status_from_items(self) -> None:
        """Update phase status based on item completion."""
        if not self.items:
            return
        if all(item.status == PlanStatus.COMPLETED for item in self.items):
            self.status = PlanStatus.COMPLETED
        elif any(
            item.status in (PlanStatus.IN_PROGRESS, PlanStatus.COMPLETED) for item in self.items
        ):
            self.status = PlanStatus.IN_PROGRESS
        else:
            self.status = PlanStatus.PENDING


@dataclass
class TaskPlan:
    """A complete task plan with multiple phases."""

    session_id: str
    task: str
    created_at: datetime = field(default_factory=datetime.now)
    status: PlanStatus = PlanStatus.PENDING
    phases: List[Phase] = field(default_factory=list)
    objective: str = ""

    def to_markdown(self) -> str:
        """Convert to full markdown document."""
        lines = [
            "---",
            f'session_id: "{self.session_id}"',
            f'task: "{self.task}"',
            f'created_at: "{self.created_at.isoformat()}"',
            f'status: "{self.status.value}"',
            "---",
            "",
            "# Task Plan",
            "",
            "## Objective",
            self.objective or self.task,
            "",
            "## Phases",
            "",
        ]

        for phase in self.phases:
            lines.append(phase.to_markdown())
            lines.append("")

        return "\n".join(lines)

    @classmethod
    def from_markdown(cls, content: str) -> Optional["TaskPlan"]:
        """Parse from markdown content."""
        # Parse YAML frontmatter
        frontmatter_match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        if not frontmatter_match:
            return None

        frontmatter = frontmatter_match.group(1)

        # Extract frontmatter values
        def extract_value(key: str) -> str:
            match = re.search(rf'^{key}:\s*"?([^"\n]+)"?', frontmatter, re.MULTILINE)
            return match.group(1).strip() if match else ""

        session_id = extract_value("session_id")
        task = extract_value("task")
        created_at_str = extract_value("created_at")
        status_str = extract_value("status")

        if not session_id or not task:
            return None

        # Parse created_at
        try:
            created_at = (
                datetime.fromisoformat(created_at_str) if created_at_str else datetime.now()
            )
        except ValueError:
            created_at = datetime.now()

        # Parse status
        try:
            status = PlanStatus(status_str) if status_str else PlanStatus.PENDING
        except ValueError:
            status = PlanStatus.PENDING

        # Parse body content
        body = content[frontmatter_match.end() :].strip()

        # Extract objective
        objective = ""
        objective_match = re.search(r"## Objective\n(.+?)(?=\n## |\Z)", body, re.DOTALL)
        if objective_match:
            objective = objective_match.group(1).strip()

        # Parse phases
        phases = []
        phase_pattern = r"### (.+?)\n(.*?)(?=\n### |\Z)"
        for phase_match in re.finditer(phase_pattern, body, re.DOTALL):
            phase_name = phase_match.group(1).strip()
            phase_content = phase_match.group(2).strip()

            # Parse phase status
            phase_status = PlanStatus.PENDING
            status_match = re.search(r"- Status:\s*(\w+)", phase_content)
            if status_match:
                with contextlib.suppress(ValueError):
                    phase_status = PlanStatus(status_match.group(1))

            # Parse items
            items = []
            for line in phase_content.split("\n"):
                item = PhaseItem.from_markdown(line)
                if item:
                    items.append(item)

            phase = Phase(name=phase_name, items=items, status=phase_status)
            phases.append(phase)

        return cls(
            session_id=session_id,
            task=task,
            created_at=created_at,
            status=status,
            phases=phases,
            objective=objective,
        )

    def update_status_from_phases(self) -> None:
        """Update plan status based on phase completion."""
        if not self.phases:
            return
        if all(phase.status == PlanStatus.COMPLETED for phase in self.phases):
            self.status = PlanStatus.COMPLETED
        elif any(phase.status == PlanStatus.FAILED for phase in self.phases):
            self.status = PlanStatus.FAILED
        elif any(
            phase.status in (PlanStatus.IN_PROGRESS, PlanStatus.COMPLETED) for phase in self.phases
        ):
            self.status = PlanStatus.IN_PROGRESS
        else:
            self.status = PlanStatus.PENDING

    @property
    def progress_summary(self) -> str:
        """Get a brief progress summary."""
        total_items = sum(phase.total_count for phase in self.phases)
        completed_items = sum(phase.completed_count for phase in self.phases)
        if total_items == 0:
            return f"Status: {self.status.value}"
        percentage = (completed_items / total_items) * 100
        return f"{completed_items}/{total_items} tasks ({percentage:.0f}%) - Status: {self.status.value}"


@dataclass
class ProgressEntry:
    """A single progress log entry."""

    timestamp: datetime
    title: str
    content: str

    def to_markdown(self) -> str:
        """Convert to markdown format."""
        time_str = self.timestamp.strftime("%Y-%m-%d %H:%M")
        return f"## {time_str} - {self.title}\n{self.content}\n"


class PlanFileManager:
    """Manages plan files for persistent task tracking."""

    PLAN_FILE = "task_plan.md"
    PROGRESS_FILE = "progress.md"
    FINDINGS_DIR = "findings"

    def __init__(self, session_id: str):
        """Initialize plan file manager.

        Args:
            session_id: Session identifier for the plan
        """
        self.session_id = session_id
        self._plan: Optional[TaskPlan] = None
        self._progress_entries: List[ProgressEntry] = []

    @property
    def plan_dir(self) -> str:
        """Get the directory for this session's plan files."""
        return os.path.join(get_plans_dir(), self.session_id)

    @property
    def plan_file_path(self) -> str:
        """Get path to the task plan file."""
        return os.path.join(self.plan_dir, self.PLAN_FILE)

    @property
    def progress_file_path(self) -> str:
        """Get path to the progress log file."""
        return os.path.join(self.plan_dir, self.PROGRESS_FILE)

    @property
    def findings_dir_path(self) -> str:
        """Get path to the findings directory."""
        return os.path.join(self.plan_dir, self.FINDINGS_DIR)

    async def initialize(self) -> None:
        """Create directory structure for plan files."""
        await aiofiles.os.makedirs(self.plan_dir, exist_ok=True)
        await aiofiles.os.makedirs(self.findings_dir_path, exist_ok=True)
        logger.debug(f"Initialized plan directory: {self.plan_dir}")

    async def create_plan(
        self, task: str, phases: List[Dict[str, Any]], objective: str = ""
    ) -> TaskPlan:
        """Create a new task plan.

        Args:
            task: Brief task description
            phases: List of phase definitions with name and items
            objective: Optional detailed objective

        Returns:
            Created TaskPlan
        """
        await self.initialize()

        # Convert phase dicts to Phase objects
        phase_objects = []
        for phase_dict in phases:
            items = [PhaseItem(content=item) for item in phase_dict.get("items", [])]
            phase = Phase(name=phase_dict["name"], items=items)
            phase_objects.append(phase)

        self._plan = TaskPlan(
            session_id=self.session_id,
            task=task,
            phases=phase_objects,
            objective=objective or task,
        )

        await self._save_plan()

        # Initialize progress file
        await self.add_progress_entry("Plan Created", f"Created plan: {task}")

        logger.info(f"Created plan for session {self.session_id}: {task}")
        return self._plan

    async def load_plan(self) -> Optional[TaskPlan]:
        """Load plan from disk.

        Returns:
            Loaded TaskPlan or None if not found
        """
        try:
            if not await aiofiles.os.path.exists(self.plan_file_path):
                return None

            async with aiofiles.open(self.plan_file_path, encoding="utf-8") as f:
                content = await f.read()

            self._plan = TaskPlan.from_markdown(content)
            if self._plan:
                logger.info(f"Loaded plan for session {self.session_id}")
            return self._plan
        except Exception as e:
            logger.error(f"Failed to load plan: {e}")
            return None

    async def _save_plan(self) -> None:
        """Save current plan to disk."""
        if not self._plan:
            return

        content = self._plan.to_markdown()
        async with aiofiles.open(self.plan_file_path, "w", encoding="utf-8") as f:
            await f.write(content)
        logger.debug(f"Saved plan to {self.plan_file_path}")

    async def update_phase_status(self, phase_index: int, status: PlanStatus) -> str:
        """Update the status of a phase.

        Args:
            phase_index: 0-indexed phase number
            status: New status

        Returns:
            Result message
        """
        if not self._plan:
            return "Error: No plan loaded"

        if phase_index < 0 or phase_index >= len(self._plan.phases):
            return f"Error: Invalid phase index {phase_index}"

        phase = self._plan.phases[phase_index]
        old_status = phase.status
        phase.status = status

        # Update overall plan status
        self._plan.update_status_from_phases()

        await self._save_plan()

        result = f"Phase '{phase.name}' status: {old_status.value} -> {status.value}"
        await self.add_progress_entry("Phase Update", result)
        return result

    async def update_item_status(self, phase_index: int, item_index: int, completed: bool) -> str:
        """Update the status of an item within a phase.

        Args:
            phase_index: 0-indexed phase number
            item_index: 0-indexed item number within phase
            completed: Whether the item is completed

        Returns:
            Result message
        """
        if not self._plan:
            return "Error: No plan loaded"

        if phase_index < 0 or phase_index >= len(self._plan.phases):
            return f"Error: Invalid phase index {phase_index}"

        phase = self._plan.phases[phase_index]
        if item_index < 0 or item_index >= len(phase.items):
            return f"Error: Invalid item index {item_index}"

        item = phase.items[item_index]
        item.status = PlanStatus.COMPLETED if completed else PlanStatus.PENDING

        # Update phase status based on items
        phase.update_status_from_items()

        # Update overall plan status
        self._plan.update_status_from_phases()

        await self._save_plan()

        status_str = "completed" if completed else "pending"
        result = f"Item '{item.content}' marked as {status_str}"
        return result

    async def mark_complete(self) -> str:
        """Mark the entire plan as completed.

        Returns:
            Result message
        """
        if not self._plan:
            return "Error: No plan loaded"

        self._plan.status = PlanStatus.COMPLETED
        for phase in self._plan.phases:
            phase.status = PlanStatus.COMPLETED
            for item in phase.items:
                item.status = PlanStatus.COMPLETED

        await self._save_plan()
        await self.add_progress_entry("Plan Complete", "All tasks marked as completed")
        return "Plan marked as completed"

    async def add_progress_entry(self, title: str, content: str) -> str:
        """Add a progress log entry.

        Args:
            title: Entry title
            content: Entry content

        Returns:
            Result message
        """
        entry = ProgressEntry(timestamp=datetime.now(), title=title, content=content)
        self._progress_entries.append(entry)

        # Append to progress file
        try:
            # Check if file exists and has content
            file_exists = await aiofiles.os.path.exists(self.progress_file_path)
            if not file_exists:
                # Create initial progress file
                header = f'---\nsession_id: "{self.session_id}"\n---\n\n# Progress Log\n\n'
                async with aiofiles.open(self.progress_file_path, "w", encoding="utf-8") as f:
                    await f.write(header + entry.to_markdown())
            else:
                async with aiofiles.open(self.progress_file_path, "a", encoding="utf-8") as f:
                    await f.write(entry.to_markdown())

            logger.debug(f"Added progress entry: {title}")
            return f"Progress logged: {title}"
        except Exception as e:
            logger.error(f"Failed to log progress: {e}")
            return f"Error logging progress: {e}"

    async def save_finding(self, topic: str, content: str) -> str:
        """Save a research finding/note.

        Args:
            topic: Topic name (used as filename)
            content: Finding content

        Returns:
            Result message
        """
        await self.initialize()

        # Sanitize topic for filename
        safe_topic = re.sub(r"[^\w\-_]", "_", topic.lower())
        finding_path = os.path.join(self.findings_dir_path, f"{safe_topic}.md")

        finding_content = f"# {topic}\n\nUpdated: {datetime.now().isoformat()}\n\n{content}"

        try:
            async with aiofiles.open(finding_path, "w", encoding="utf-8") as f:
                await f.write(finding_content)
            logger.debug(f"Saved finding: {topic}")
            await self.add_progress_entry("Research", f"Saved finding to findings/{safe_topic}.md")
            return f"Finding saved: {topic}"
        except Exception as e:
            logger.error(f"Failed to save finding: {e}")
            return f"Error saving finding: {e}"

    async def load_finding(self, topic: str) -> Optional[str]:
        """Load a research finding.

        Args:
            topic: Topic name

        Returns:
            Finding content or None if not found
        """
        safe_topic = re.sub(r"[^\w\-_]", "_", topic.lower())
        finding_path = os.path.join(self.findings_dir_path, f"{safe_topic}.md")

        try:
            if not await aiofiles.os.path.exists(finding_path):
                return None
            async with aiofiles.open(finding_path, encoding="utf-8") as f:
                return await f.read()
        except Exception as e:
            logger.error(f"Failed to load finding: {e}")
            return None

    async def list_findings(self) -> List[str]:
        """List all finding topics.

        Returns:
            List of finding topic names
        """
        try:
            if not await aiofiles.os.path.exists(self.findings_dir_path):
                return []
            findings = []
            for entry in os.listdir(self.findings_dir_path):
                if entry.endswith(".md"):
                    # Convert filename back to topic
                    topic = entry[:-3].replace("_", " ")
                    findings.append(topic)
            return findings
        except Exception as e:
            logger.error(f"Failed to list findings: {e}")
            return []

    def get_plan_summary(self) -> Optional[str]:
        """Get a compact summary of the current plan for context injection.

        Returns:
            Summary string or None if no plan
        """
        if not self._plan:
            return None

        lines = [
            "[Current Plan]",
            f"Task: {self._plan.task}",
            f"Progress: {self._plan.progress_summary}",
            "",
            "Phases:",
        ]

        for i, phase in enumerate(self._plan.phases):
            status_icon = {
                PlanStatus.PENDING: "-",
                PlanStatus.IN_PROGRESS: ">",
                PlanStatus.COMPLETED: "x",
                PlanStatus.FAILED: "!",
            }[phase.status]
            progress = f"({phase.completed_count}/{phase.total_count})" if phase.items else ""
            lines.append(f"  [{status_icon}] {i + 1}. {phase.name} {progress}")

        return "\n".join(lines)

    def get_current_plan(self) -> Optional[TaskPlan]:
        """Get the current loaded plan.

        Returns:
            Current TaskPlan or None
        """
        return self._plan

    @classmethod
    async def list_available_plans(cls) -> List[Dict[str, Any]]:
        """List all available plan sessions.

        Returns:
            List of plan info dicts with session_id, task, status, created_at
        """
        plans_dir = get_plans_dir()
        plans = []

        try:
            if not await aiofiles.os.path.exists(plans_dir):
                return plans

            for session_id in os.listdir(plans_dir):
                session_dir = os.path.join(plans_dir, session_id)
                if not os.path.isdir(session_dir):
                    continue

                plan_file = os.path.join(session_dir, cls.PLAN_FILE)
                if not await aiofiles.os.path.exists(plan_file):
                    continue

                try:
                    async with aiofiles.open(plan_file, encoding="utf-8") as f:
                        content = await f.read()
                    plan = TaskPlan.from_markdown(content)
                    if plan:
                        plans.append(
                            {
                                "session_id": session_id,
                                "task": plan.task,
                                "status": plan.status.value,
                                "created_at": plan.created_at.isoformat(),
                                "progress": plan.progress_summary,
                            }
                        )
                except Exception as e:
                    logger.warning(f"Failed to read plan {session_id}: {e}")
                    continue

            # Sort by created_at descending
            plans.sort(key=lambda x: x["created_at"], reverse=True)
            return plans
        except Exception as e:
            logger.error(f"Failed to list plans: {e}")
            return []

    @classmethod
    async def recover_plan(cls, session_id: str) -> Optional["PlanFileManager"]:
        """Recover a plan from a previous session.

        Args:
            session_id: Session ID to recover

        Returns:
            PlanFileManager instance with loaded plan, or None if not found
        """
        manager = cls(session_id)
        plan = await manager.load_plan()
        if plan:
            return manager
        return None
