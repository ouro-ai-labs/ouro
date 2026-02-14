from utils.tui.ptk2_mode import next_follow_tail_state, normalize_output_chunk, strip_ansi


def test_strip_ansi_removes_escape_sequences() -> None:
    assert strip_ansi("\x1b[31mERR\x1b[0m") == "ERR"


def test_strip_ansi_removes_osc_sequences() -> None:
    assert strip_ansi("x\x1b]0;title\x07y") == "xy"


def test_normalize_output_chunk_normalizes_crlf_and_cr() -> None:
    raw = "a\r\nb\rc"
    assert normalize_output_chunk(raw) == "a\nb\nc"


def test_normalize_output_chunk_strips_control_noise() -> None:
    raw = "\x1b[31mA\x1b[0m\bB"
    assert normalize_output_chunk(raw) == "AB"


def test_next_follow_tail_state_from_scroll_events() -> None:
    assert next_follow_tail_state(current_follow_tail=True, scroll_delta=-1, at_bottom=False) is False
    assert next_follow_tail_state(current_follow_tail=False, scroll_delta=1, at_bottom=False) is False
    assert next_follow_tail_state(current_follow_tail=False, scroll_delta=1, at_bottom=True) is True
    assert next_follow_tail_state(current_follow_tail=True, scroll_delta=0, at_bottom=False) is True
