from ouro.core.llm import LLMMessage
from ouro.core.loop import MessageList


def test_message_list_append_extend_replace_range_snapshot_clear():
    m1 = LLMMessage(role="user", content="u1")
    m2 = LLMMessage(role="assistant", content="a1")
    m3 = LLMMessage(role="tool", content="t1", tool_call_id="id1", name="tool")
    ml = MessageList([m1])

    ml.append(m2)
    assert len(ml) == 2
    assert ml[1] == m2

    snap = ml.snapshot()
    snap.append(m3)
    assert len(ml) == 2

    ml.extend([m3])
    assert len(ml) == 3

    replacement = [LLMMessage(role="system", content="sys")]
    ml.replace_range(0, 2, replacement)
    assert len(ml) == 2
    assert ml[0].role == "system"
    assert ml[1] == m3

    ml.clear()
    assert len(ml) == 0
