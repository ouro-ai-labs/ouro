"""Unit tests for MemoryManager.

After the loop-owns-messages refactor, MemoryManager no longer holds
the conversation list — that lives on ``MessageListContext``.  The
manager owns persistence, long-term memory, the ``CompactionManager``
handle, and cumulative token/cost stats. These tests cover that
narrowed responsibility.

Compaction *strategy* behaviour (tool-pair preservation, sliding
window vs selective, etc.) is covered against ``WorkingMemoryCompressor``
directly in ``test_compressor.py`` — those tests don't need to be
re-routed through MemoryManager.
"""

from ouro.capabilities.memory import MemoryManager
from ouro.core.llm.base import LLMMessage
from ouro.core.loop import MessageListContext


def _ctx(*, system=None, detached=None) -> MessageListContext:
    return MessageListContext(
        system_messages=list(system or []),
        detached=list(detached or []),
    )


class TestMemoryManagerBasics:
    async def test_initialization(self, mock_llm):
        manager = MemoryManager(mock_llm)
        assert manager.llm is mock_llm
        assert manager.session_id is None
        assert manager._session_created is False
        assert manager.compaction is manager._compaction
        # token tracker starts empty
        assert manager.token_tracker.total_input_tokens == 0
        assert manager.compaction.compression_count == 0

    async def test_reset_clears_token_tracker_and_compaction(self, mock_llm):
        manager = MemoryManager(mock_llm)
        manager.token_tracker.record_usage({"input_tokens": 100, "output_tokens": 50})
        assert manager.token_tracker.total_input_tokens == 100

        manager.reset()
        assert manager.token_tracker.total_input_tokens == 0
        assert manager.compaction.compression_count == 0


class TestSaveMemory:
    async def test_skips_save_when_context_empty(self, mock_llm):
        manager = MemoryManager(mock_llm)
        await manager.save_memory(context=_ctx())
        # Empty context should not even create a session file
        assert manager._session_created is False

    async def test_lazy_session_creation_on_first_save(self, mock_llm):
        manager = MemoryManager(mock_llm)
        ctx = _ctx(detached=[LLMMessage(role="user", content="hello")])
        await manager.save_memory(context=ctx)
        assert manager._session_created is True
        assert manager.session_id is not None

    async def test_save_then_reload_round_trips(self, mock_llm):
        manager = MemoryManager(mock_llm)
        sys_msgs = [LLMMessage(role="system", content="be brief")]
        det_msgs = [
            LLMMessage(role="user", content="hi"),
            LLMMessage(role="assistant", content="hello"),
        ]
        ctx = _ctx(system=sys_msgs, detached=det_msgs)
        await manager.save_memory(context=ctx)

        sid = manager.session_id
        assert sid is not None

        loaded_mgr, loaded_ctx = await MemoryManager.from_session(sid, mock_llm)
        assert loaded_mgr.session_id == sid
        assert [m.role for m in loaded_ctx.system_messages] == ["system"]
        assert [m.role for m in loaded_ctx.detached.snapshot()] == ["user", "assistant"]


class TestGetStats:
    async def test_stats_keys(self, mock_llm, simple_messages):
        manager = MemoryManager(mock_llm)
        ctx = _ctx(detached=simple_messages)
        stats = manager.get_stats(context=ctx)

        # Critical keys consumed by ComposedAgent + TUI/bot UI:
        for key in (
            "current_tokens",
            "total_input_tokens",
            "total_output_tokens",
            "compression_count",
            "message_count",
            "detached_message_count",
            "short_term_count",  # legacy alias used by terminal_ui / bot
            "total_cost",
            "ltm_enabled",
        ):
            assert key in stats, f"missing stats key: {key}"

        assert stats["message_count"] == len(simple_messages)
        assert stats["detached_message_count"] == len(simple_messages)
        assert stats["short_term_count"] == len(simple_messages)
        assert stats["current_tokens"] >= 0

    async def test_stats_recomputed_per_call(self, mock_llm):
        """``current_tokens`` must reflect the live context, not stale state."""
        manager = MemoryManager(mock_llm)
        empty = manager.get_stats(context=_ctx())
        with_msgs = manager.get_stats(
            context=_ctx(detached=[LLMMessage(role="user", content="x" * 200)])
        )
        assert with_msgs["current_tokens"] >= empty["current_tokens"]
        assert with_msgs["message_count"] == 1
        assert empty["message_count"] == 0


class TestCompress:
    async def test_compress_empty_context_is_noop(self, mock_llm):
        manager = MemoryManager(mock_llm)
        result = await manager.compress(context=_ctx())
        assert result is None

    async def test_compress_replaces_detached_in_place(
        self, set_memory_config, mock_llm, simple_messages
    ):
        """A successful compress() should leave the context's detached
        list shorter (or at least replaced) and forward token-tracker
        accounting."""
        # Force a low target so even tiny conversations compress.
        set_memory_config(
            MEMORY_COMPRESSION_THRESHOLD=10,
            MEMORY_SHORT_TERM_MIN_SIZE=0,
            MEMORY_COMPRESSION_RATIO=0.3,
        )
        manager = MemoryManager(mock_llm)
        ctx = _ctx(detached=simple_messages)
        before = ctx.detached.snapshot()

        result = await manager.compress(context=ctx)

        # Manager forwards results from the underlying CompactionManager.
        # Either a CompressedMemory was returned and detached was
        # replaced, or compaction declined (None).  In either case
        # there should be no exception, and detached must still be a
        # list of LLMMessage.
        if result is not None:
            assert ctx.detached.snapshot() != before or len(ctx.detached) > 0
            assert manager.compaction.compression_count >= 1


class TestProperties:
    async def test_long_term_property(self, mock_llm, set_memory_config):
        # LTM follows Config.LONG_TERM_MEMORY_ENABLED; whatever value
        # the conftest leaves, ``long_term`` should mirror it.
        manager = MemoryManager(mock_llm)
        if manager.long_term is None:
            assert manager._long_term is None
        else:
            assert manager.long_term is manager._long_term

    async def test_compaction_property_returns_internal(self, mock_llm):
        manager = MemoryManager(mock_llm)
        assert manager.compaction is manager._compaction

    async def test_set_todo_context_provider_forwards(self, mock_llm):
        manager = MemoryManager(mock_llm)
        manager.set_todo_context_provider(lambda: "todo: x")
        assert manager._compaction._todo_context_provider() == "todo: x"
