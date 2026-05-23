"""Unit tests for MemoryBlockEditTool."""

import pytest

from ouro.capabilities.memory.blocks import MemoryBlockManager
from ouro.capabilities.tools.builtins.memory_block_edit import MemoryBlockEditTool


@pytest.fixture
def manager(tmp_path):
    return MemoryBlockManager(
        llm=None,
        memory_dir=str(tmp_path),
        block_budgets={"user": 20, "project": 40, "scratch": 60},
    )


@pytest.fixture
def tool(manager):
    return MemoryBlockEditTool(manager)


class TestSchema:
    def test_name(self, tool):
        assert tool.name == "memory_block_edit"

    def test_required_only_block_and_operation(self, tool):
        schema = tool.to_anthropic_schema()
        required = set(schema["input_schema"]["required"])
        assert required == {"block", "operation"}

    def test_operation_enum(self, tool):
        params = tool.parameters
        assert params["operation"]["enum"] == ["read", "replace", "append"]

    def test_conflict_keys_scoped_by_block(self, tool):
        keys = tool.conflict_keys(operation="append", block="user")
        assert keys == {"memory_block:user"}

    def test_conflict_keys_read_is_freely_parallel(self, tool):
        assert tool.conflict_keys(operation="read", block="user") == set()


class TestExecute:
    async def test_missing_block_arg(self, tool):
        out = await tool.execute(block="", operation="read")
        assert "block" in out.lower() and "required" in out.lower()

    async def test_unknown_operation(self, tool):
        out = await tool.execute(block="user", operation="delete")
        assert "unknown operation" in out.lower()

    async def test_read_empty_block(self, tool):
        out = await tool.execute(block="user", operation="read")
        assert "empty" in out.lower()

    async def test_round_trip_replace_then_read(self, tool):
        upd = await tool.execute(block="user", operation="replace", content="name: alice")
        assert "updated" in upd
        out = await tool.execute(block="user", operation="read")
        assert "name: alice" in out

    async def test_targeted_replace(self, tool):
        await tool.execute(block="user", operation="replace", content="rust > go")
        out = await tool.execute(block="user", operation="replace", old="rust", content="RUST")
        assert "updated" in out
        assert "RUST > go" in await tool.execute(block="user", operation="read")

    async def test_targeted_replace_missing_old(self, tool):
        await tool.execute(block="user", operation="replace", content="hello")
        out = await tool.execute(block="user", operation="replace", old="nope", content="x")
        assert "not found" in out.lower()

    async def test_append_missing_content(self, tool):
        out = await tool.execute(block="project", operation="append")
        assert "required" in out.lower()

    async def test_replace_overflow_surfaces_actionable_error(self, tool):
        out = await tool.execute(block="user", operation="replace", content="x" * 500)
        assert "budget exceeded" in out.lower()
        assert "trim" in out.lower()

    async def test_scratch_overflow_silently_truncates(self, tool):
        # scratch is lenient — should always succeed.
        for i in range(20):
            out = await tool.execute(
                block="scratch", operation="append", content=f"entry-{i}: " + "x" * 30
            )
            assert "updated" in out
        body = await tool.execute(block="scratch", operation="read")
        # Newest must survive; oldest dropped via FIFO.
        assert "entry-19" in body
        assert "entry-0:" not in body
