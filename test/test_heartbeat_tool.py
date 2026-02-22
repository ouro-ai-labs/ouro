"""Tests for the manage_heartbeat tool (HeartbeatTool)."""

from __future__ import annotations

import os

from tools.heartbeat_tool import HeartbeatTool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(tmp_path) -> HeartbeatTool:
    """Create a HeartbeatTool pointing at a temp file."""
    return HeartbeatTool(heartbeat_file=str(tmp_path / "heartbeat.md"))


def _seed_file(tmp_path, items: list[str]) -> None:
    """Write a heartbeat.md with the given checklist items."""
    path = tmp_path / "heartbeat.md"
    lines = ["# Heartbeat Checklist\n", "\n"]
    for item in items:
        lines.append(f"- [ ] {item}\n")
    path.write_text("".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


class TestHeartbeatToolList:
    async def test_list_empty(self, tmp_path):
        tool = _make_tool(tmp_path)

        result = await tool.execute(operation="list")

        assert "No checklist items" in result

    async def test_list_with_items(self, tmp_path):
        _seed_file(tmp_path, ["Check CI", "Review PRs"])
        tool = _make_tool(tmp_path)

        result = await tool.execute(operation="list")

        assert "Heartbeat checklist:" in result
        assert "1. Check CI" in result
        assert "2. Review PRs" in result


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------


class TestHeartbeatToolAdd:
    async def test_add_item(self, tmp_path):
        tool = _make_tool(tmp_path)

        result = await tool.execute(operation="add", item="Check disk usage")

        assert "Added checklist item #1" in result
        assert "Check disk usage" in result
        # Verify persisted
        list_result = await tool.execute(operation="list")
        assert "1. Check disk usage" in list_result

    async def test_add_appends(self, tmp_path):
        _seed_file(tmp_path, ["Existing item"])
        tool = _make_tool(tmp_path)

        result = await tool.execute(operation="add", item="New item")

        assert "Added checklist item #2" in result
        list_result = await tool.execute(operation="list")
        assert "1. Existing item" in list_result
        assert "2. New item" in list_result

    async def test_add_missing_item(self, tmp_path):
        tool = _make_tool(tmp_path)

        result = await tool.execute(operation="add")

        assert "Error" in result
        assert "item" in result

    async def test_add_creates_file(self, tmp_path):
        """Adding an item to a non-existent file should create it."""
        tool = _make_tool(tmp_path)

        await tool.execute(operation="add", item="First item")

        assert os.path.isfile(str(tmp_path / "heartbeat.md"))


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------


class TestHeartbeatToolRemove:
    async def test_remove_item(self, tmp_path):
        _seed_file(tmp_path, ["Alpha", "Beta", "Gamma"])
        tool = _make_tool(tmp_path)

        result = await tool.execute(operation="remove", index=2)

        assert "Removed checklist item #2" in result
        assert "Beta" in result
        list_result = await tool.execute(operation="list")
        assert "1. Alpha" in list_result
        assert "2. Gamma" in list_result
        assert "Beta" not in list_result

    async def test_remove_invalid_index_zero(self, tmp_path):
        _seed_file(tmp_path, ["Item"])
        tool = _make_tool(tmp_path)

        result = await tool.execute(operation="remove", index=0)

        assert "Error" in result
        assert "positive integer" in result

    async def test_remove_index_out_of_range(self, tmp_path):
        _seed_file(tmp_path, ["Only item"])
        tool = _make_tool(tmp_path)

        result = await tool.execute(operation="remove", index=5)

        assert "Error" in result
        assert "out of range" in result

    async def test_remove_from_empty(self, tmp_path):
        tool = _make_tool(tmp_path)

        result = await tool.execute(operation="remove", index=1)

        assert "Error" in result
        assert "out of range" in result


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestHeartbeatToolEdgeCases:
    async def test_unknown_operation(self, tmp_path):
        tool = _make_tool(tmp_path)

        result = await tool.execute(operation="unknown")

        assert "Error" in result
        assert "Unknown operation" in result

    def test_tool_name(self, tmp_path):
        tool = _make_tool(tmp_path)
        assert tool.name == "manage_heartbeat"

    def test_tool_schema(self, tmp_path):
        tool = _make_tool(tmp_path)
        schema = tool.to_anthropic_schema()
        assert schema["name"] == "manage_heartbeat"
        assert "operation" in schema["input_schema"]["properties"]
        assert "operation" in schema["input_schema"]["required"]
        # Optional params should NOT be in required
        assert "item" not in schema["input_schema"]["required"]
        assert "index" not in schema["input_schema"]["required"]
