"""Unit tests for ConversationSearchTool."""

import pytest

from ouro.capabilities.memory.recall import RecallIndex
from ouro.capabilities.tools.builtins.conversation_search import ConversationSearchTool
from ouro.core.llm.message_types import LLMMessage


@pytest.fixture
def tool(tmp_path):
    return ConversationSearchTool(memory_dir=str(tmp_path / "memdir"))


@pytest.fixture
async def populated_tool(tmp_path):
    memdir = str(tmp_path / "memdir")
    idx = RecallIndex(memdir)
    await idx.reindex_session(
        "session-xxxxxxxx-1",
        [
            LLMMessage(role="user", content="I prefer rust over go"),
            LLMMessage(role="assistant", content="Noted. Rust offers memory safety."),
        ],
    )
    await idx.reindex_session(
        "session-yyyyyyyy-2",
        [LLMMessage(role="user", content="Tell me about kubernetes")],
    )
    return ConversationSearchTool(memory_dir=memdir)


class TestSchema:
    def test_name_and_readonly(self, tool):
        assert tool.name == "conversation_search"
        assert tool.readonly is True

    def test_parameters_have_query(self, tool):
        params = tool.parameters
        assert "query" in params
        assert "session_id" in params
        assert "limit" in params

    def test_anthropic_schema_required_only_query(self, tool):
        schema = tool.to_anthropic_schema()
        assert schema["input_schema"]["required"] == ["query"]


class TestExecute:
    async def test_empty_query(self, tool):
        out = await tool.execute(query="   ")
        assert "No query" in out

    async def test_no_index_yet(self, tool):
        out = await tool.execute(query="anything")
        assert "No matches" in out

    async def test_match(self, populated_tool):
        out = await populated_tool.execute(query="rust")
        assert "rust" in out.lower()
        assert "session=session-" in out

    async def test_scope_by_session_id(self, populated_tool):
        # Restrict to session 2 — "rust" only lives in session 1 so should be empty.
        out = await populated_tool.execute(query="rust", session_id="session-yyyyyyyy-2")
        assert "No matches" in out

    async def test_limit_clamped(self, populated_tool):
        # Bogus limit values must not crash.
        out = await populated_tool.execute(query="rust", limit=9999)
        assert "rust" in out.lower()
        out = await populated_tool.execute(query="rust", limit=-5)
        assert "rust" in out.lower()
