"""Tests for plan file management system."""

import os
import shutil
import tempfile
from datetime import datetime
from unittest.mock import patch

import pytest

from agent.plan_files import (
    Phase,
    PhaseItem,
    PlanFileManager,
    PlanStatus,
    ProgressEntry,
    TaskPlan,
)
from tools.plan_files import PlanFileTool


class TestPlanStatus:
    """Tests for PlanStatus enum."""

    def test_status_values(self):
        """Test enum values are correct."""
        assert PlanStatus.PENDING.value == "pending"
        assert PlanStatus.IN_PROGRESS.value == "in_progress"
        assert PlanStatus.COMPLETED.value == "completed"
        assert PlanStatus.FAILED.value == "failed"


class TestPhaseItem:
    """Tests for PhaseItem dataclass."""

    def test_to_markdown_pending(self):
        """Test markdown conversion for pending item."""
        item = PhaseItem(content="Create project", status=PlanStatus.PENDING)
        assert item.to_markdown() == "- [ ] Create project"

    def test_to_markdown_completed(self):
        """Test markdown conversion for completed item."""
        item = PhaseItem(content="Install deps", status=PlanStatus.COMPLETED)
        assert item.to_markdown() == "- [x] Install deps"

    def test_from_markdown_unchecked(self):
        """Test parsing unchecked markdown item."""
        item = PhaseItem.from_markdown("- [ ] Create project")
        assert item is not None
        assert item.content == "Create project"
        assert item.status == PlanStatus.PENDING

    def test_from_markdown_checked(self):
        """Test parsing checked markdown item."""
        item = PhaseItem.from_markdown("- [x] Install deps")
        assert item is not None
        assert item.content == "Install deps"
        assert item.status == PlanStatus.COMPLETED

    def test_from_markdown_uppercase_x(self):
        """Test parsing with uppercase X."""
        item = PhaseItem.from_markdown("- [X] Task done")
        assert item is not None
        assert item.status == PlanStatus.COMPLETED

    def test_from_markdown_invalid(self):
        """Test parsing invalid line returns None."""
        assert PhaseItem.from_markdown("Not a checkbox") is None
        assert PhaseItem.from_markdown("") is None


class TestPhase:
    """Tests for Phase dataclass."""

    def test_to_markdown(self):
        """Test markdown conversion."""
        phase = Phase(
            name="Setup",
            items=[
                PhaseItem(content="Create project", status=PlanStatus.COMPLETED),
                PhaseItem(content="Install deps", status=PlanStatus.PENDING),
            ],
            status=PlanStatus.IN_PROGRESS,
        )
        md = phase.to_markdown()
        assert "### Setup" in md
        assert "- Status: in_progress" in md
        assert "- [x] Create project" in md
        assert "- [ ] Install deps" in md

    def test_completed_count(self):
        """Test completed count property."""
        phase = Phase(
            name="Test",
            items=[
                PhaseItem(content="A", status=PlanStatus.COMPLETED),
                PhaseItem(content="B", status=PlanStatus.COMPLETED),
                PhaseItem(content="C", status=PlanStatus.PENDING),
            ],
        )
        assert phase.completed_count == 2
        assert phase.total_count == 3

    def test_update_status_from_items_all_completed(self):
        """Test status update when all items completed."""
        phase = Phase(
            name="Test",
            items=[
                PhaseItem(content="A", status=PlanStatus.COMPLETED),
                PhaseItem(content="B", status=PlanStatus.COMPLETED),
            ],
        )
        phase.update_status_from_items()
        assert phase.status == PlanStatus.COMPLETED

    def test_update_status_from_items_some_in_progress(self):
        """Test status update when some items in progress."""
        phase = Phase(
            name="Test",
            items=[
                PhaseItem(content="A", status=PlanStatus.COMPLETED),
                PhaseItem(content="B", status=PlanStatus.PENDING),
            ],
        )
        phase.update_status_from_items()
        assert phase.status == PlanStatus.IN_PROGRESS

    def test_update_status_from_items_all_pending(self):
        """Test status update when all items pending."""
        phase = Phase(
            name="Test",
            items=[
                PhaseItem(content="A", status=PlanStatus.PENDING),
                PhaseItem(content="B", status=PlanStatus.PENDING),
            ],
        )
        phase.update_status_from_items()
        assert phase.status == PlanStatus.PENDING


class TestTaskPlan:
    """Tests for TaskPlan dataclass."""

    def test_to_markdown(self):
        """Test markdown conversion."""
        plan = TaskPlan(
            session_id="abc123",
            task="Build REST API",
            objective="Build a REST API for users",
            phases=[
                Phase(
                    name="Setup",
                    items=[PhaseItem(content="Create project")],
                    status=PlanStatus.COMPLETED,
                ),
            ],
        )
        md = plan.to_markdown()
        assert 'session_id: "abc123"' in md
        assert 'task: "Build REST API"' in md
        assert "# Task Plan" in md
        assert "## Objective" in md
        assert "Build a REST API for users" in md
        assert "### Setup" in md

    def test_from_markdown(self):
        """Test parsing from markdown."""
        content = """---
session_id: "abc123"
task: "Build REST API"
created_at: "2024-01-15T10:30:00"
status: "in_progress"
---

# Task Plan

## Objective
Build a REST API

## Phases

### Phase 1: Setup
- Status: completed
- [x] Create project
- [x] Install deps

### Phase 2: Models
- Status: in_progress
- [x] User model
- [ ] Role model
"""
        plan = TaskPlan.from_markdown(content)
        assert plan is not None
        assert plan.session_id == "abc123"
        assert plan.task == "Build REST API"
        assert plan.status == PlanStatus.IN_PROGRESS
        assert len(plan.phases) == 2
        assert plan.phases[0].name == "Phase 1: Setup"
        assert plan.phases[0].status == PlanStatus.COMPLETED
        assert len(plan.phases[0].items) == 2

    def test_progress_summary(self):
        """Test progress summary property."""
        plan = TaskPlan(
            session_id="test",
            task="Test task",
            phases=[
                Phase(
                    name="Phase 1",
                    items=[
                        PhaseItem(content="A", status=PlanStatus.COMPLETED),
                        PhaseItem(content="B", status=PlanStatus.COMPLETED),
                    ],
                    status=PlanStatus.COMPLETED,
                ),
                Phase(
                    name="Phase 2",
                    items=[
                        PhaseItem(content="C", status=PlanStatus.COMPLETED),
                        PhaseItem(content="D", status=PlanStatus.PENDING),
                    ],
                    status=PlanStatus.IN_PROGRESS,
                ),
            ],
            status=PlanStatus.IN_PROGRESS,
        )
        summary = plan.progress_summary
        assert "3/4" in summary
        assert "75%" in summary
        assert "in_progress" in summary


class TestPlanFileManager:
    """Tests for PlanFileManager class."""

    @pytest.fixture
    def temp_plans_dir(self):
        """Create a temporary plans directory."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def manager(self, temp_plans_dir):
        """Create a PlanFileManager with temp directory."""
        with patch("agent.plan_files.get_plans_dir", return_value=temp_plans_dir):
            return PlanFileManager("test-session-123")

    @pytest.mark.asyncio
    async def test_initialize(self, manager, temp_plans_dir):
        """Test directory initialization."""
        await manager.initialize()
        assert os.path.exists(manager.plan_dir)
        assert os.path.exists(manager.findings_dir_path)

    @pytest.mark.asyncio
    async def test_create_plan(self, manager, temp_plans_dir):
        """Test creating a plan."""
        with patch("agent.plan_files.get_plans_dir", return_value=temp_plans_dir):
            plan = await manager.create_plan(
                task="Build API",
                phases=[
                    {"name": "Setup", "items": ["Create project", "Install deps"]},
                    {"name": "Models", "items": ["User model"]},
                ],
                objective="Build a REST API",
            )
            # Check file exists within the patch context
            plan_file = os.path.join(temp_plans_dir, manager.session_id, "task_plan.md")
            assert os.path.exists(plan_file)

        assert plan is not None
        assert plan.task == "Build API"
        assert plan.objective == "Build a REST API"
        assert len(plan.phases) == 2
        assert len(plan.phases[0].items) == 2

    @pytest.mark.asyncio
    async def test_load_plan(self, manager, temp_plans_dir):
        """Test loading a plan from disk."""
        with patch("agent.plan_files.get_plans_dir", return_value=temp_plans_dir):
            # Create a plan first
            await manager.create_plan(
                task="Test Task",
                phases=[{"name": "Phase 1", "items": ["Item 1"]}],
            )

            # Create new manager and load
            new_manager = PlanFileManager("test-session-123")
            plan = await new_manager.load_plan()

        assert plan is not None
        assert plan.task == "Test Task"

    @pytest.mark.asyncio
    async def test_update_phase_status(self, manager, temp_plans_dir):
        """Test updating phase status."""
        with patch("agent.plan_files.get_plans_dir", return_value=temp_plans_dir):
            await manager.create_plan(
                task="Test",
                phases=[{"name": "Phase 1", "items": ["Item"]}],
            )

            result = await manager.update_phase_status(0, PlanStatus.IN_PROGRESS)

        assert "in_progress" in result
        assert manager._plan.phases[0].status == PlanStatus.IN_PROGRESS

    @pytest.mark.asyncio
    async def test_update_item_status(self, manager, temp_plans_dir):
        """Test updating item status."""
        with patch("agent.plan_files.get_plans_dir", return_value=temp_plans_dir):
            await manager.create_plan(
                task="Test",
                phases=[{"name": "Phase 1", "items": ["Item 1", "Item 2"]}],
            )

            result = await manager.update_item_status(0, 0, True)

        assert "completed" in result
        assert manager._plan.phases[0].items[0].status == PlanStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_mark_complete(self, manager, temp_plans_dir):
        """Test marking plan complete."""
        with patch("agent.plan_files.get_plans_dir", return_value=temp_plans_dir):
            await manager.create_plan(
                task="Test",
                phases=[{"name": "Phase 1", "items": ["Item"]}],
            )

            result = await manager.mark_complete()

        assert "completed" in result
        assert manager._plan.status == PlanStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_save_and_load_finding(self, manager, temp_plans_dir):
        """Test saving and loading findings."""
        with patch("agent.plan_files.get_plans_dir", return_value=temp_plans_dir):
            await manager.initialize()

            await manager.save_finding("API Design", "Use REST with JSON responses")

            content = await manager.load_finding("API Design")

        assert content is not None
        assert "API Design" in content
        assert "REST with JSON" in content

    @pytest.mark.asyncio
    async def test_list_findings(self, manager, temp_plans_dir):
        """Test listing findings."""
        with patch("agent.plan_files.get_plans_dir", return_value=temp_plans_dir):
            await manager.initialize()
            await manager.save_finding("Topic A", "Content A")
            await manager.save_finding("Topic B", "Content B")

            findings = await manager.list_findings()

        assert len(findings) == 2

    def test_get_plan_summary_no_plan(self, manager):
        """Test getting summary with no plan."""
        assert manager.get_plan_summary() is None

    @pytest.mark.asyncio
    async def test_get_plan_summary(self, manager, temp_plans_dir):
        """Test getting plan summary."""
        with patch("agent.plan_files.get_plans_dir", return_value=temp_plans_dir):
            await manager.create_plan(
                task="Build API",
                phases=[{"name": "Setup", "items": ["Create project"]}],
            )

            summary = manager.get_plan_summary()

        assert summary is not None
        assert "[Current Plan]" in summary
        assert "Build API" in summary
        assert "Setup" in summary

    @pytest.mark.asyncio
    async def test_list_available_plans(self, temp_plans_dir):
        """Test listing all available plans."""
        with patch("agent.plan_files.get_plans_dir", return_value=temp_plans_dir):
            # Create multiple plans
            manager1 = PlanFileManager("session-1")
            await manager1.create_plan(
                task="Task 1",
                phases=[{"name": "Phase", "items": ["Item"]}],
            )

            manager2 = PlanFileManager("session-2")
            await manager2.create_plan(
                task="Task 2",
                phases=[{"name": "Phase", "items": ["Item"]}],
            )

            plans = await PlanFileManager.list_available_plans()

        assert len(plans) == 2
        tasks = [p["task"] for p in plans]
        assert "Task 1" in tasks
        assert "Task 2" in tasks

    @pytest.mark.asyncio
    async def test_recover_plan(self, temp_plans_dir):
        """Test recovering a plan from a previous session."""
        with patch("agent.plan_files.get_plans_dir", return_value=temp_plans_dir):
            # Create a plan
            original = PlanFileManager("session-to-recover")
            await original.create_plan(
                task="Recoverable Task",
                phases=[{"name": "Phase", "items": ["Item"]}],
            )

            # Recover it
            recovered = await PlanFileManager.recover_plan("session-to-recover")

        assert recovered is not None
        assert recovered.get_current_plan().task == "Recoverable Task"

    @pytest.mark.asyncio
    async def test_recover_plan_not_found(self, temp_plans_dir):
        """Test recovering a non-existent plan."""
        with patch("agent.plan_files.get_plans_dir", return_value=temp_plans_dir):
            recovered = await PlanFileManager.recover_plan("nonexistent")

        assert recovered is None


class TestPlanFileTool:
    """Tests for PlanFileTool class."""

    @pytest.fixture
    def temp_plans_dir(self):
        """Create a temporary plans directory."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def tool(self, temp_plans_dir):
        """Create a PlanFileTool with mocked manager."""
        with patch("agent.plan_files.get_plans_dir", return_value=temp_plans_dir):
            manager = PlanFileManager("test-session")
            return PlanFileTool(manager)

    def test_tool_name(self, tool):
        """Test tool name."""
        assert tool.name == "manage_plan_file"

    def test_tool_description(self, tool):
        """Test tool has description."""
        assert len(tool.description) > 0
        assert "create_plan" in tool.description

    def test_tool_parameters(self, tool):
        """Test tool has parameters."""
        params = tool.parameters
        assert "operation" in params
        assert "task" in params
        assert "phases" in params

    @pytest.mark.asyncio
    async def test_create_plan_operation(self, tool, temp_plans_dir):
        """Test create_plan operation."""
        with patch("agent.plan_files.get_plans_dir", return_value=temp_plans_dir):
            result = await tool.execute(
                operation="create_plan",
                task="Test Task",
                phases=[{"name": "Phase 1", "items": ["Item 1"]}],
            )

        assert "Plan created" in result
        assert "Test Task" in result

    @pytest.mark.asyncio
    async def test_create_plan_missing_task(self, tool):
        """Test create_plan with missing task."""
        result = await tool.execute(
            operation="create_plan",
            phases=[{"name": "Phase 1", "items": ["Item 1"]}],
        )
        assert "Error" in result
        assert "task" in result

    @pytest.mark.asyncio
    async def test_create_plan_missing_phases(self, tool):
        """Test create_plan with missing phases."""
        result = await tool.execute(
            operation="create_plan",
            task="Test Task",
        )
        assert "Error" in result
        assert "phases" in result

    @pytest.mark.asyncio
    async def test_get_summary_no_plan(self, tool):
        """Test get_summary with no plan."""
        result = await tool.execute(operation="get_summary")
        assert "No plan loaded" in result

    @pytest.mark.asyncio
    async def test_get_summary_with_plan(self, tool, temp_plans_dir):
        """Test get_summary with plan."""
        with patch("agent.plan_files.get_plans_dir", return_value=temp_plans_dir):
            await tool.execute(
                operation="create_plan",
                task="Test",
                phases=[{"name": "Phase", "items": ["Item"]}],
            )
            result = await tool.execute(operation="get_summary")

        assert "[Current Plan]" in result

    @pytest.mark.asyncio
    async def test_update_phase_operation(self, tool, temp_plans_dir):
        """Test update_phase operation."""
        with patch("agent.plan_files.get_plans_dir", return_value=temp_plans_dir):
            await tool.execute(
                operation="create_plan",
                task="Test",
                phases=[{"name": "Phase", "items": ["Item"]}],
            )
            result = await tool.execute(
                operation="update_phase",
                phase_index=0,
                status="in_progress",
            )

        assert "in_progress" in result

    @pytest.mark.asyncio
    async def test_update_item_operation(self, tool, temp_plans_dir):
        """Test update_item operation."""
        with patch("agent.plan_files.get_plans_dir", return_value=temp_plans_dir):
            await tool.execute(
                operation="create_plan",
                task="Test",
                phases=[{"name": "Phase", "items": ["Item"]}],
            )
            result = await tool.execute(
                operation="update_item",
                phase_index=0,
                item_index=0,
                completed=True,
            )

        assert "completed" in result

    @pytest.mark.asyncio
    async def test_save_finding_operation(self, tool, temp_plans_dir):
        """Test save_finding operation."""
        with patch("agent.plan_files.get_plans_dir", return_value=temp_plans_dir):
            await tool._plan_manager.initialize()
            result = await tool.execute(
                operation="save_finding",
                topic="Research",
                content="Found useful info",
            )

        assert "Finding saved" in result

    @pytest.mark.asyncio
    async def test_load_finding_operation(self, tool, temp_plans_dir):
        """Test load_finding operation."""
        with patch("agent.plan_files.get_plans_dir", return_value=temp_plans_dir):
            await tool._plan_manager.initialize()
            await tool.execute(
                operation="save_finding",
                topic="Research",
                content="Important content",
            )
            result = await tool.execute(
                operation="load_finding",
                topic="Research",
            )

        assert "Important content" in result

    @pytest.mark.asyncio
    async def test_load_finding_not_found(self, tool, temp_plans_dir):
        """Test load_finding for non-existent topic."""
        with patch("agent.plan_files.get_plans_dir", return_value=temp_plans_dir):
            await tool._plan_manager.initialize()
            result = await tool.execute(
                operation="load_finding",
                topic="Nonexistent",
            )

        assert "not found" in result

    @pytest.mark.asyncio
    async def test_list_plans_operation(self, tool, temp_plans_dir):
        """Test list_plans operation."""
        with patch("agent.plan_files.get_plans_dir", return_value=temp_plans_dir):
            result = await tool.execute(operation="list_plans")

        assert "No saved plans" in result or "Available Plans" in result

    @pytest.mark.asyncio
    async def test_unknown_operation(self, tool):
        """Test unknown operation returns error."""
        result = await tool.execute(operation="unknown_op")
        assert "Error" in result
        assert "Unknown operation" in result


class TestProgressEntry:
    """Tests for ProgressEntry dataclass."""

    def test_to_markdown(self):
        """Test markdown conversion."""
        entry = ProgressEntry(
            timestamp=datetime(2024, 1, 15, 10, 30),
            title="Phase Complete",
            content="Finished setup phase",
        )
        md = entry.to_markdown()
        assert "2024-01-15 10:30" in md
        assert "Phase Complete" in md
        assert "Finished setup phase" in md
