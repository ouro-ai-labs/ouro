"""PTK2 interactive mode using a single prompt_toolkit renderer."""

from __future__ import annotations

import asyncio
import contextlib
import io
import os
import re
import time
from collections.abc import Callable
from typing import IO, cast

from prompt_toolkit.application import Application
from prompt_toolkit.application.current import get_app
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.data_structures import Point
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.containers import ConditionalContainer
from prompt_toolkit.layout.controls import FormattedTextControl, UIContent
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.margins import ScrollbarMargin
from prompt_toolkit.layout.menus import CompletionsMenuControl
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import TextArea
from rich.console import Console

import agent.base as agent_base_module
from interactive import InteractiveSession
from utils import terminal_ui
from utils.tui.theme import Theme

_ANSI_CSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_ANSI_OSC_RE = re.compile(r"\x1b\].*?(?:\x07|\x1b\\)")
_ANSI_NON_SGR_CSI_RE = re.compile(r"\x1b\[(?![0-9;]*m)[0-9;?]*[ -/]*[@-~]")
_SGR_START = "\x1b["


def strip_ansi(text: str) -> str:
    """Strip ANSI escape sequences from text."""
    text = _ANSI_OSC_RE.sub("", text)
    return _ANSI_CSI_RE.sub("", text)


def normalize_output_chunk(text: str) -> str:
    """Normalize captured output for PTK rendering.

    Keep SGR color escapes (`...m`) so ANSI rendering can preserve colors,
    while removing OSC and non-SGR control CSI escapes.
    """
    cleaned = _ANSI_OSC_RE.sub("", text)
    cleaned = _ANSI_NON_SGR_CSI_RE.sub("", cleaned)
    cleaned = cleaned.replace("\r\n", "\n")
    cleaned = cleaned.replace("\r", "\n")
    cleaned = cleaned.replace("\x08", "")
    return cleaned


def split_incomplete_ansi_suffix(text: str) -> tuple[str, str]:
    """Split out a trailing *incomplete* ANSI escape (CSI/OSC).

    This is used to avoid leaking partial escape sequences into the output pane.
    It also allows `normalize_output_chunk()` to strip OSC/non-SGR CSI once the
    sequence is complete.
    """
    if not text:
        return "", ""

    esc = text.rfind("\x1b")
    if esc == -1:
        return text, ""

    suffix = text[esc:]
    if suffix == "\x1b":
        return text[:esc], suffix

    # OSC: ESC ] ... (BEL | ST)
    if suffix.startswith("\x1b]"):
        if "\x07" not in suffix and "\x1b\\" not in suffix:
            return text[:esc], suffix
        return text, ""

    # CSI: ESC [ ... final byte in '@'..'~'
    if suffix.startswith("\x1b["):
        for ch in suffix[2:]:
            if "@" <= ch <= "~":
                return text, ""
        return text[:esc], suffix

    # Other escape: if it ends right after ESC, carry.
    if len(suffix) == 1:
        return text[:esc], suffix

    return text, ""


def drop_visible_prefix_preserving_sgr(text: str, visible_chars: int) -> str:
    """Drop N visible characters from the start, skipping full SGR escapes.

    Visible characters include newlines; SGR escapes don't count.
    """
    if visible_chars <= 0 or not text:
        return text

    i = 0
    remaining = visible_chars
    n = len(text)

    while i < n and remaining > 0:
        if text.startswith(_SGR_START, i):
            end = text.find("m", i + 2)
            if end == -1:
                # Incomplete escape; treat the ESC as visible to guarantee progress.
                i += 1
                remaining -= 1
                continue
            i = end + 1
            continue

        i += 1
        remaining -= 1

    return text[i:]


def split_visible_prefix_preserving_sgr(text: str, visible_chars: int) -> tuple[str, str]:
    """Split text into (prefix, rest) where prefix contains N visible characters.

    SGR escapes don't count towards visible characters and are kept intact.
    """
    if visible_chars <= 0 or not text:
        return "", text

    i = 0
    remaining = visible_chars
    n = len(text)

    while i < n and remaining > 0:
        if text.startswith(_SGR_START, i):
            end = text.find("m", i + 2)
            if end == -1:
                i += 1
                remaining -= 1
                continue
            i = end + 1
            continue

        i += 1
        remaining -= 1

    return text[:i], text[i:]


def next_follow_tail_state(current_follow_tail: bool, scroll_delta: int, at_bottom: bool) -> bool:
    """Compute whether output app should keep following tail after a scroll event."""
    if scroll_delta < 0:
        return False
    if scroll_delta > 0 and at_bottom:
        return True
    return current_follow_tail


class _OutputStream(io.TextIOBase):
    """Text stream that forwards writes to a callback."""

    def __init__(self, on_text: Callable[[str], None]) -> None:
        self._on_text = on_text

    def writable(self) -> bool:
        return True

    def write(self, s: str) -> int:
        if not s:
            return 0
        self._on_text(s)
        return len(s)

    def flush(self) -> None:  # pragma: no cover - no-op by design
        return None


class _OutputAnsiControl(FormattedTextControl):
    def __init__(self, get_text, on_scroll, get_cursor_pos):  # noqa: ANN001
        # Keep output unfocusable so we don't steal focus from the input buffer.
        # (The completion menu logic depends on the current buffer.)
        super().__init__(text=get_text, focusable=False, show_cursor=False)
        self._on_scroll = on_scroll
        self._get_cursor_pos = get_cursor_pos

    def mouse_handler(self, mouse_event: MouseEvent):  # noqa: ANN001
        if mouse_event.event_type == MouseEventType.SCROLL_UP:
            self._on_scroll(-4, "mouse")
            return None
        if mouse_event.event_type == MouseEventType.SCROLL_DOWN:
            self._on_scroll(4, "mouse")
            return None
        return NotImplemented

    def create_content(self, width: int, height: int | None) -> UIContent:
        # Default FormattedTextControl has cursor at (0,0), which makes `Window`
        # with `wrap_lines=True` clamp the scroll position to the top.
        #
        # We provide a dynamic cursor:
        # - LIVE mode: last line, so the viewport follows tail naturally.
        # - SCROLL mode: current vertical_scroll, so manual scrolling sticks.
        content = super().create_content(width, height)
        if content.line_count <= 0:
            return content

        pos = self._get_cursor_pos(content.line_count)
        y = max(0, min(pos.y, content.line_count - 1))
        x = max(0, pos.x)
        return UIContent(
            get_line=content.get_line,
            line_count=content.line_count,
            cursor_position=Point(x=x, y=y),
            menu_position=content.menu_position,
            show_cursor=False,
        )


class PTK2Driver:
    """Single-renderer PTK application that hosts the interactive session."""

    def __init__(self, session: InteractiveSession) -> None:
        self.session = session
        self._loop: asyncio.AbstractEventLoop | None = None
        self._input_queue: asyncio.Queue[str] = asyncio.Queue()
        self._prompt_text = "> "
        self._max_output_chars = 200_000
        self._manual_scroll_mode = False
        self._output_text = ""
        self._plain_tail_line_len = 0
        self._raw_ansi_carry = ""
        # Coalesce high-frequency output writes into periodic flushes to avoid
        # invalidating/redrawing the full PTK layout for every small chunk.
        #
        # This matters most for streaming output (many tiny writes).
        flush_ms = os.environ.get("PTK2_FLUSH_MS", "8")
        try:
            self._flush_interval_s = max(0.0, float(flush_ms) / 1000.0)
        except ValueError:
            self._flush_interval_s = 0.008
        # Optional: limit how many visible characters we append per flush tick.
        # Setting this too low can cause many full-layout redraws and hurt perf.
        max_flush_chars = os.environ.get("PTK2_FLUSH_MAX_CHARS", "0")
        try:
            raw_max = int(max_flush_chars)
            self._flush_max_visible_chars = max(256, raw_max) if raw_max > 0 else None
        except ValueError:
            self._flush_max_visible_chars = None
        self._pending_raw = ""
        self._pending_norm = ""
        self._flush_handle: asyncio.Handle | None = None
        self._last_flush_ts = 0.0

        # Thinking panel (animated) used as a replacement for Rich Live spinners.
        self._thinking_active = False
        self._thinking_message = ""
        self._thinking_frame = 0
        self._thinking_tick: asyncio.Handle | None = None
        self._thinking_frames = ["|", "/", "-", "\\"]
        self._capture_path = os.environ.get("PTK2_CAPTURE_PATH")
        self._capture_fp: IO[str] | None = None
        self._debug_path = os.environ.get("PTK2_DEBUG_PATH")
        self._debug_fp: IO[str] | None = None

        def _output_cursor_y(line_count: int) -> int:
            if line_count <= 0:
                return 0
            # In SCROLL mode, pin cursor to the current top line to prevent PTK
            # from snapping the viewport back to the bottom.
            if self._manual_scroll_mode:
                return min(self.output_window.vertical_scroll, line_count - 1)
            return line_count - 1

        def _output_cursor_pos(line_count: int) -> Point:
            y = _output_cursor_y(line_count)
            # In LIVE mode, put cursor at the end of the tail line. This makes
            # `wrap_lines=True` follow the true tail (including wrapped rows)
            # without relying on a huge `vertical_scroll` sentinel, which can
            # break scrolling responsiveness.
            x = 0 if self._manual_scroll_mode else max(0, self._plain_tail_line_len)
            return Point(x=x, y=y)

        # Hooks to restore after run.
        self._orig_status_update = session.status_bar.update
        self._orig_status_show = session.status_bar.show
        self._orig_prompt_async = session.input_handler.prompt_async
        self._orig_async_spinner = agent_base_module.AsyncSpinner

        self._output_control = _OutputAnsiControl(self._render_output, self._scroll_output, _output_cursor_pos)
        self.output_window = Window(
            content=self._output_control,
            wrap_lines=True,
            right_margins=[ScrollbarMargin(display_arrows=True)],
            style="class:output",
        )

        self.input_area = TextArea(
            multiline=False,
            completer=session.input_handler.completer,
            complete_while_typing=True,
            style="class:input",
            accept_handler=self._accept_input,
        )

        self._last_completion_sync_text: str | None = None
        self._wire_slash_completion_sync()

        self._status_control = FormattedTextControl(self._render_status_line)
        self._prompt_control = FormattedTextControl(self._render_prompt)

        input_row = VSplit(
            [
                Window(self._prompt_control, width=3, dont_extend_height=True),
                self.input_area,
            ]
        )

        # Drop-down completion menu that appears *below* the input row (not as a float),
        # preventing overlays on the output/status bar and matching legacy UX.
        self._completion_visible = Condition(
            lambda: (
                self.input_area.buffer.complete_state is not None
                and bool(self.input_area.buffer.complete_state.completions)
            )
        )

        completion_border_top = Window(height=1, char="─", style="class:completion.border")
        completion_border_bottom = Window(height=1, char="─", style="class:completion.border")

        self._completion_count_control = FormattedTextControl(self._render_completion_count)
        completion_count = Window(
            height=1,
            content=self._completion_count_control,
            style="class:completion.count",
        )

        completion_list = Window(
            content=CompletionsMenuControl(),
            # Keep the completion dropdown usable in small terminals: preserve
            # at least a few rows for output.
            height=lambda: Dimension(  # noqa: E731
                min=1,
                max=max(1, min(8, get_app().output.get_size().rows - 9)),
            ),
            right_margins=[ScrollbarMargin(display_arrows=True)],
            dont_extend_width=False,
            style="class:completion-menu",
        )

        completion_box = ConditionalContainer(
            content=HSplit(
                [
                    completion_border_top,
                    completion_list,
                    completion_count,
                    completion_border_bottom,
                ]
            ),
            filter=self._completion_visible,
        )

        thinking_box = ConditionalContainer(
            content=Window(
                height=3,
                content=FormattedTextControl(self._render_thinking_panel),
                style="class:thinking.panel",
                dont_extend_height=True,
            ),
            filter=Condition(lambda: self._thinking_active),
        )

        root = HSplit(
            [
                thinking_box,
                self.output_window,
                Window(height=1, char="─", style="class:divider"),
                input_row,
                completion_box,
                Window(height=1, content=self._status_control, style="class:status"),
            ]
        )

        self.app = Application(
            layout=Layout(root, focused_element=self.input_area),
            key_bindings=self._create_key_bindings(),
            style=self._get_style(),
            full_screen=True,
            mouse_support=True,
        )

        self._stream = _OutputStream(self._on_stream_text)

    def _create_key_bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("escape")
        def _escape(_event) -> None:
            buf = self.input_area.buffer
            if buf.complete_state is not None:
                buf.cancel_completion()

        @kb.add("c-l")
        def _clear(_event) -> None:
            self._manual_scroll_mode = False
            self._set_output_text("", follow_tail=True)

        @kb.add("c-c")
        def _interrupt(_event) -> None:
            current_task = self.session.current_task
            if current_task and not current_task.done():
                current_task.cancel()
                return
            self._input_queue.put_nowait("/exit")

        @kb.add("pageup")
        def _page_up(_event) -> None:
            self._scroll_output(-12, "key:pageup")

        @kb.add("pagedown")
        def _page_down(_event) -> None:
            self._scroll_output(12, "key:pagedown")

        @kb.add(Keys.ScrollUp)
        def _scroll_up(_event) -> None:
            self._scroll_output(-4, "key:scrollup")

        @kb.add(Keys.ScrollDown)
        def _scroll_down(_event) -> None:
            self._scroll_output(4, "key:scrolldown")

        @kb.add("end")
        def _jump_to_latest(_event) -> None:
            self._manual_scroll_mode = False
            self._set_output_text(self._output_text, follow_tail=True)

        @kb.add("c-e")
        def _jump_to_latest_ctrl(_event) -> None:
            self._manual_scroll_mode = False
            self._set_output_text(self._output_text, follow_tail=True)

        return kb

    def _get_style(self) -> Style:
        colors = Theme.get_colors()
        style_dict = Theme.get_prompt_toolkit_style()
        style_dict.update(
            {
                "output": colors.text_primary,
                "input": colors.text_primary,
                "status": f"bg:{colors.bg_secondary} {colors.text_secondary}",
                "prompt": f"{colors.user_input} bold",
                "divider": colors.text_muted,
                "toolbar.hint": colors.text_secondary,
                "toolbar.cmd": f"{colors.primary} bold",
                "thinking.panel": f"bg:{colors.bg_secondary} {colors.text_primary}",
                "thinking.border": colors.text_muted,
                "thinking.title": f"{colors.secondary} bold",
                "thinking.body": colors.text_secondary,
            }
        )
        return Style.from_dict(style_dict)

    def _render_output(self):
        return ANSI(self._output_text)

    def _render_prompt(self):
        return [("class:prompt", self._prompt_text)]

    def _render_status_line(self):
        state = self.session.status_bar.state
        marker = "●" if state.is_processing else "◉"
        model = state.model_name or "(none)"
        view = "SCROLL" if self._manual_scroll_mode else "LIVE"
        text = (
            f" TUI: PTK2 | Model: {model} | Mode: {state.mode} | "
            f"Total: {state.input_tokens}↓ {state.output_tokens}↑ | "
            f"Context: {state.context_tokens} | Cost: ${state.cost:.4f} | View: {view} | {marker}"
        )
        return [("class:status", text)]

    def _render_completion_count(self):
        state = self.input_area.buffer.complete_state
        if not state or not state.completions:
            return [("class:completion.count", "")]
        idx = state.complete_index
        if idx is None:
            idx = 0
        text = f"({idx + 1}/{len(state.completions)})"
        return [("class:completion.count", text)]

    def _render_thinking_panel(self):
        if not self._thinking_active:
            return [("", "")]
        cols = 80
        with contextlib.suppress(Exception):
            cols = get_app().output.get_size().columns
        cols = max(20, cols)

        title = " Thinking "
        frame = self._thinking_frames[self._thinking_frame % len(self._thinking_frames)]
        msg = (self._thinking_message or "Processing...").strip()
        inner_w = max(0, cols - 4)
        body = f"{frame} {msg}"
        body = body[:inner_w].ljust(inner_w)

        top = f"+{title}{'-' * max(0, cols - len(title) - 2)}+"
        mid = f"| {body} |"
        bot = f"+{'-' * (cols - 2)}+"

        return [
            ("class:thinking.border", top + "\n"),
            ("class:thinking.body", mid + "\n"),
            ("class:thinking.border", bot),
        ]

    def _start_thinking(self, message: str) -> None:
        self._thinking_active = True
        self._thinking_message = message
        if self._loop is None:
            self._invalidate()
            return
        if self._thinking_tick is None or self._thinking_tick.cancelled():
            self._thinking_tick = self._loop.call_later(0.10, self._thinking_step)
        self._invalidate()

    def _stop_thinking(self) -> None:
        self._thinking_active = False
        self._thinking_message = ""
        if self._thinking_tick is not None:
            with contextlib.suppress(Exception):
                self._thinking_tick.cancel()
        self._thinking_tick = None
        self._invalidate()

    def _thinking_step(self) -> None:
        self._thinking_tick = None
        if not self._thinking_active or self._loop is None:
            return
        self._thinking_frame = (self._thinking_frame + 1) % len(self._thinking_frames)
        self._invalidate()
        self._thinking_tick = self._loop.call_later(0.10, self._thinking_step)

    def _wire_slash_completion_sync(self) -> None:
        """Keep slash completion state in sync while typing/deleting."""
        buf = self.input_area.buffer

        def _on_text_changed(_buffer) -> None:
            new_text = buf.text

            # UX rule: after the user scrolls up to read history, any typing means
            # "I'm back to chatting" -> jump back to LIVE/tail.
            if self._manual_scroll_mode and new_text:
                self._manual_scroll_mode = False
                self._debug("scroll:exit reason=typing")
                self._set_output_text(self._output_text, follow_tail=True)

            if new_text.startswith("/"):
                if new_text == self._last_completion_sync_text:
                    return
                self._last_completion_sync_text = new_text
                self._debug(f"completion:start text={new_text!r}")
                buf.start_completion(
                    select_first=False,
                    complete_event=CompleteEvent(text_inserted=True),
                )
                return

            self._last_completion_sync_text = None
            self._debug("completion:cancel")
            buf.cancel_completion()

        buf.on_text_changed += _on_text_changed

    def _accept_input(self, buf) -> bool:
        """Submit input text to the InteractiveSession prompt bridge."""
        if buf.complete_state and buf.text.startswith("/"):
            state = buf.complete_state
            completion = state.current_completion
            if completion is None and state.completions:
                completion = state.completions[0]
            if completion is not None:
                buf.apply_completion(completion)
                buf.cancel_completion()

        user_text = buf.text.strip()
        buf.text = ""
        self._last_completion_sync_text = None
        # Align with the default TUI: submitting any command/message returns to LIVE,
        # so new output is always visible.
        if user_text:
            self._manual_scroll_mode = False
        self._input_queue.put_nowait(user_text)
        self._invalidate()
        return True

    async def _prompt_async(self, prompt_text: str = "> ") -> str:
        self._prompt_text = prompt_text
        self._invalidate()
        return await self._input_queue.get()

    def _truncate_output(self, text: str) -> str:
        plain_len = len(strip_ansi(text))
        if plain_len <= self._max_output_chars:
            return text

        drop = plain_len - self._max_output_chars
        truncated = drop_visible_prefix_preserving_sgr(text, drop)

        # Reset style so truncation never leaves the ANSI parser in an "active" style.
        # (This is zero-width in `strip_ansi` and won't affect capture-based tests.)
        return "\x1b[0m" + truncated

    def _set_output_text(
        self,
        text: str,
        *,
        follow_tail: bool,
        preserve_scroll: int | None = None,
    ) -> None:
        self._output_text = text
        # Keep a cheap heuristic for whether the tail line might wrap.
        # (Avoid `strip_ansi(text)` on the full buffer here.)
        tail = text.rsplit("\n", 1)[-1]
        self._plain_tail_line_len = len(strip_ansi(tail))
        if not follow_tail and preserve_scroll is not None:
            # Don't try to clamp here: with `wrap_lines=True`, `WindowRenderInfo.content_height`
            # is based on logical lines (not wrapped rows) and clamping can create "can't scroll"
            # regressions. Let prompt_toolkit clamp during render.
            self.output_window.vertical_scroll = max(0, preserve_scroll)
        self._invalidate()

    def _max_output_scroll(self) -> int | None:
        render_info = self.output_window.render_info
        if render_info is not None:
            return max(0, render_info.content_height - render_info.window_height)
        return None

    def _scroll_output(self, delta: int, source: str = "") -> None:
        window = self.output_window
        before = window.vertical_scroll
        window.vertical_scroll = max(0, window.vertical_scroll + delta)
        after = window.vertical_scroll
        max_scroll = self._max_output_scroll()
        at_bottom = max_scroll is not None and after >= max_scroll

        # State machine:
        # - Any upward scroll enters manual mode.
        # - While in manual mode, scrolling back down to the bottom exits it.
        if delta < 0:
            self._manual_scroll_mode = True
        elif delta > 0 and self._manual_scroll_mode and at_bottom:
            self._manual_scroll_mode = False
            self._debug("scroll:exit reason=bottom")
        self._debug(
            f"scroll src={source or 'unknown'} delta={delta} before={before} after={after} "
            f"manual={self._manual_scroll_mode} max_scroll={max_scroll} at_bottom={at_bottom}"
        )
        self._invalidate()

    def _schedule_flush(self) -> None:
        if self._loop is None:
            return
        if self._flush_handle is not None and not self._flush_handle.cancelled():
            return
        if self._flush_interval_s <= 0:
            # Flush synchronously when coalescing is disabled.
            self._flush_pending()
            return
        now = time.monotonic()
        due_in = self._flush_interval_s - (now - self._last_flush_ts)
        if due_in <= 0:
            self._flush_handle = self._loop.call_soon(self._flush_pending)
        else:
            self._flush_handle = self._loop.call_later(due_in, self._flush_pending)

    def _enqueue_output(self, chunk: str) -> None:
        if not chunk:
            return
        self._pending_raw += chunk
        self._schedule_flush()

    def _flush_pending(self) -> None:
        # This runs in the PTK event loop thread.
        self._flush_handle = None
        if not self._pending_raw and not self._raw_ansi_carry and not self._pending_norm:
            return
        self._last_flush_ts = time.monotonic()

        raw = self._raw_ansi_carry + self._pending_raw
        self._pending_raw = ""
        self._raw_ansi_carry = ""

        raw, carry = split_incomplete_ansi_suffix(raw)
        if carry:
            self._raw_ansi_carry = carry

        normalized = normalize_output_chunk(raw)
        to_flush = self._pending_norm + normalized
        if not to_flush:
            return
        if self._flush_max_visible_chars is None:
            chunk, rest = to_flush, ""
        else:
            chunk, rest = split_visible_prefix_preserving_sgr(
                to_flush, self._flush_max_visible_chars
            )
        self._pending_norm = rest
        if not chunk:
            return

        if self._capture_path and self._capture_fp is not None:
            with contextlib.suppress(Exception):
                self._capture_fp.write(strip_ansi(chunk))
                self._capture_fp.flush()

        combined = self._truncate_output(self._output_text + chunk)
        self._set_output_text(
            combined,
            follow_tail=not self._manual_scroll_mode,
            preserve_scroll=self.output_window.vertical_scroll,
        )
        self._debug(
            f"flush len={len(chunk)} total={len(self._output_text)} "
            f"manual={self._manual_scroll_mode} vscroll={self.output_window.vertical_scroll} "
            f"max_scroll={self._max_output_scroll()}"
        )
        # If more output arrived while we were flushing, schedule the next flush.
        if self._pending_raw or self._raw_ansi_carry or self._pending_norm:
            self._schedule_flush()

    def _on_stream_text(self, text: str) -> None:
        if not text or self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._append_output, text)

    def _append_output(self, chunk: str) -> None:
        # Keep the thread-safe entrypoint stable: older callbacks call this name.
        self._enqueue_output(chunk)

    def _invalidate(self) -> None:
        with contextlib.suppress(Exception):
            self.app.invalidate()

    def _install_session_hooks(self) -> None:
        driver = self

        class _DriverAsyncSpinner:
            def __init__(self, console: Console, message: str = "Processing...") -> None:
                self.console = console
                self.message = message

            async def __aenter__(self):  # noqa: ANN001
                driver._start_thinking(self.message)
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # noqa: ANN001
                driver._stop_thinking()
                return None

            def update_message(self, message: str) -> None:
                self.message = message
                driver._start_thinking(message)

        def _status_update_proxy(*args, **kwargs) -> None:
            self._orig_status_update(*args, **kwargs)
            self._invalidate()

        def _status_show_proxy() -> None:
            self._invalidate()

        self.session.status_bar.update = _status_update_proxy  # type: ignore[method-assign]
        self.session.status_bar.show = _status_show_proxy  # type: ignore[method-assign]
        self.session.input_handler.prompt_async = self._prompt_async  # type: ignore[assignment]
        agent_base_module.AsyncSpinner = _DriverAsyncSpinner

    def _restore_session_hooks(self) -> None:
        self.session.status_bar.update = self._orig_status_update  # type: ignore[method-assign]
        self.session.status_bar.show = self._orig_status_show  # type: ignore[method-assign]
        self.session.input_handler.prompt_async = self._orig_prompt_async  # type: ignore[assignment]
        agent_base_module.AsyncSpinner = self._orig_async_spinner

    async def _stop_app_when_done(self, task: asyncio.Task[None]) -> None:
        try:
            await task
        finally:
            with contextlib.suppress(Exception):
                self.app.exit()

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        old_console = terminal_ui.console
        terminal_ui.console = Console(
            file=cast(IO[str], self._stream),
            force_terminal=True,
            color_system="truecolor",
            theme=Theme.get_rich_theme(),
        )

        self._install_session_hooks()

        session_task: asyncio.Task[None] | None = None
        stop_task: asyncio.Task[None] | None = None
        session_error: Exception | None = None

        try:
            if self._capture_path:
                with contextlib.suppress(Exception):
                    # Async-friendly I/O isn't necessary here: this runs once at startup.
                    self._capture_fp = open(  # noqa: ASYNC230,SIM115
                        self._capture_path, "a", encoding="utf-8"
                    )
            if self._debug_path:
                with contextlib.suppress(Exception):
                    # Async-friendly I/O isn't necessary here: this runs once at startup.
                    self._debug_fp = open(  # noqa: ASYNC230,SIM115
                        self._debug_path, "a", encoding="utf-8"
                    )

            # Do not redirect global stdout/stderr: PTK renderer writes to terminal
            # output and redirecting would feed paint frames back into the output pane.
            session_task = asyncio.create_task(self.session.run())
            stop_task = asyncio.create_task(self._stop_app_when_done(session_task))

            await self.app.run_async()

            if session_task and not session_task.done():
                session_task.cancel()

            if session_task is not None:
                try:
                    await session_task
                except asyncio.CancelledError:
                    pass
                except Exception as exc:  # pragma: no cover - passthrough
                    session_error = exc

        finally:
            # Best-effort flush of any buffered output before teardown.
            with contextlib.suppress(Exception):
                self._flush_pending()
            if stop_task is not None:
                stop_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await stop_task
            if self._capture_fp is not None:
                with contextlib.suppress(Exception):
                    self._capture_fp.close()
                self._capture_fp = None
            if self._debug_fp is not None:
                with contextlib.suppress(Exception):
                    self._debug_fp.close()
                self._debug_fp = None

            terminal_ui.console = old_console
            self._restore_session_hooks()

        if session_error is not None:
            raise session_error

    def _debug(self, msg: str) -> None:
        if not self._debug_fp:
            return
        ts = time.monotonic()
        with contextlib.suppress(Exception):
            self._debug_fp.write(f"{ts:.6f} {msg}\n")
            self._debug_fp.flush()


def run_interactive_mode_ptk2(agent):
    """Run interactive mode in PTK2 mode."""
    session = InteractiveSession(agent)
    driver = PTK2Driver(session)
    return driver.run()
