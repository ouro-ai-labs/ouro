"""Experimental PTK2 interactive mode (single renderer spike)."""

from __future__ import annotations

import asyncio
import contextlib
import io
import re
from collections.abc import Callable
from typing import IO, cast

from prompt_toolkit.application import Application
import agent.base as agent_base_module
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.document import Document
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import TextArea
from rich.console import Console

from interactive import InteractiveSession
from utils import terminal_ui
from utils.tui.theme import Theme

_ANSI_CSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_ANSI_OSC_RE = re.compile(r"\x1b\].*?(?:\x07|\x1b\\)")


def strip_ansi(text: str) -> str:
    """Strip ANSI escape sequences from text."""
    text = _ANSI_OSC_RE.sub("", text)
    return _ANSI_CSI_RE.sub("", text)


def normalize_output_chunk(text: str) -> str:
    """Normalize captured terminal output before rendering in PTK output pane."""
    cleaned = strip_ansi(text)
    cleaned = cleaned.replace("\r\n", "\n")
    cleaned = cleaned.replace("\r", "\n")
    # Backspace control chars from prompt redraws are noise in the output pane.
    cleaned = cleaned.replace("\x08", "")
    return cleaned


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


class _PTK2AsyncSpinner:
    """Non-live spinner shim for PTK2 output capture.

    Rich Live spinner frames don't map well into a text output pane. This shim keeps
    the same context-manager API, but emits a single thinking block instead of
    continuously repainting frames.
    """

    def __init__(self, console: Console, message: str = "Processing...") -> None:
        self.console = console
        self.message = message

    async def __aenter__(self) -> "_PTK2AsyncSpinner":
        if not self.console.quiet:
            terminal_ui.print_thinking(self.message)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # noqa: ANN001
        return None

    def update_message(self, message: str) -> None:
        self.message = message


class PTK2Driver:
    """Single-renderer PTK application that hosts the interactive session."""

    def __init__(self, session: InteractiveSession) -> None:
        self.session = session
        self._loop: asyncio.AbstractEventLoop | None = None
        self._input_queue: asyncio.Queue[str] = asyncio.Queue()
        self._prompt_text = "> "
        self._max_output_chars = 200_000
        self._follow_output_tail = True

        # Hooks to restore after run.
        self._orig_status_update = session.status_bar.update
        self._orig_status_show = session.status_bar.show
        self._orig_prompt_async = session.input_handler.prompt_async
        self._orig_async_spinner = agent_base_module.AsyncSpinner

        self.output_area = TextArea(
            text="",
            multiline=True,
            wrap_lines=True,
            read_only=True,
            scrollbar=True,
            focusable=True,
            focus_on_click=True,
            style="class:output",
        )

        self.input_area = TextArea(
            multiline=False,
            completer=session.input_handler.completer,
            # Keep menu responsive while typing slash commands.
            complete_while_typing=True,
            style="class:input",
            accept_handler=self._accept_input,
        )

        self._prev_input_text = ""
        self._last_completion_sync_text: str | None = None
        self._wire_slash_completion_sync()

        self._status_control = FormattedTextControl(self._render_status_line)
        self._prompt_control = FormattedTextControl(self._render_prompt)
        self._command_hint_control = FormattedTextControl(self._render_command_hint)

        input_row = VSplit(
            [
                Window(self._prompt_control, width=3, dont_extend_height=True),
                self.input_area,
            ]
        )

        root = HSplit(
            [
                self.output_area,
                Window(height=1, char="─", style="class:divider"),
                input_row,
                Window(height=1, content=self._command_hint_control, style="class:hint"),
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
        def _escape(event) -> None:
            buf = self.input_area.buffer
            if buf.complete_state is not None:
                buf.cancel_completion()

        @kb.add("c-l")
        def _clear(_event) -> None:
            self._follow_output_tail = True
            self._set_output_text("", follow_tail=True)

        @kb.add("c-c")
        def _interrupt(_event) -> None:
            # Match existing semantics: cancel running task, otherwise exit.
            current_task = self.session.current_task
            if current_task and not current_task.done():
                current_task.cancel()
                return
            self._input_queue.put_nowait("/exit")

        @kb.add("pageup")
        def _page_up(_event) -> None:
            self._scroll_output(-12)

        @kb.add("pagedown")
        def _page_down(_event) -> None:
            self._scroll_output(12)

        @kb.add("<scroll-up>")
        def _scroll_up(_event) -> None:
            self._scroll_output(-4)

        @kb.add("<scroll-down>")
        def _scroll_down(_event) -> None:
            self._scroll_output(4)

        @kb.add("end")
        def _jump_to_latest(_event) -> None:
            self._follow_output_tail = True
            self._set_output_text(self.output_area.text, follow_tail=True)

        @kb.add("c-e")
        def _jump_to_latest_ctrl(_event) -> None:
            self._follow_output_tail = True
            self._set_output_text(self.output_area.text, follow_tail=True)

        return kb

    def _get_style(self) -> Style:
        colors = Theme.get_colors()
        style_dict = Theme.get_prompt_toolkit_style()
        style_dict.update(
            {
                "output": colors.text_primary,
                "input": colors.text_primary,
                "status": f"bg:{colors.bg_secondary} {colors.text_secondary}",
                "hint": f"bg:{colors.bg_secondary} {colors.text_muted}",
                "prompt": f"{colors.user_input} bold",
                "divider": colors.text_muted,
            }
        )
        return Style.from_dict(style_dict)

    def _render_prompt(self):
        return [("class:prompt", self._prompt_text)]

    def _render_status_line(self):
        state = self.session.status_bar.state
        marker = "●" if state.is_processing else "◉"
        model = state.model_name or "(none)"
        view = "LIVE" if self._is_output_at_bottom() else "SCROLL"
        text = (
            f" Model: {model} | Mode: {state.mode} | "
            f"Total: {state.input_tokens}↓ {state.output_tokens}↑ | "
            f"Context: {state.context_tokens} | Cost: ${state.cost:.4f} | View: {view} | {marker}"
        )
        return [("class:status", text)]

    def _render_command_hint(self):
        text = self.input_area.text
        if not text.startswith("/"):
            return [("class:hint", "")]

        suggestions = self.session.input_handler._get_command_suggestions(text)
        if not suggestions:
            return [("class:hint", "")]

        hints = "  ".join(display for display, _ in suggestions[:6])
        return [("class:hint", f" Commands: {hints}")]

    def _wire_slash_completion_sync(self) -> None:
        """Keep slash completion menu in sync while typing/deleting."""
        buf = self.input_area.buffer

        def _on_text_insert(_buffer) -> None:
            if not buf.text.startswith("/"):
                return
            if buf.text == self._last_completion_sync_text:
                return
            self._last_completion_sync_text = buf.text
            buf.start_completion(
                select_first=False,
                complete_event=CompleteEvent(text_inserted=True),
            )

        def _on_text_changed(_buffer) -> None:
            new_text = buf.text
            prev_text = self._prev_input_text
            self._prev_input_text = new_text

            if new_text.startswith("/"):
                is_deletion = len(new_text) < len(prev_text)
                if not is_deletion:
                    return
                if new_text == self._last_completion_sync_text:
                    return
                self._last_completion_sync_text = new_text
                buf.start_completion(
                    select_first=False,
                    complete_event=CompleteEvent(text_inserted=True),
                )
                return

            self._last_completion_sync_text = None
            buf.cancel_completion()

        buf.on_text_insert += _on_text_insert
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
        self._input_queue.put_nowait(user_text)
        return True

    async def _prompt_async(self, prompt_text: str = "> ") -> str:
        self._prompt_text = prompt_text
        self._invalidate()
        return await self._input_queue.get()

    def _set_output_text(
        self,
        text: str,
        *,
        follow_tail: bool,
        preserve_scroll: int | None = None,
    ) -> None:
        cursor_position = len(text) if follow_tail else min(
            self.output_area.buffer.cursor_position,
            len(text),
        )
        self.output_area.buffer.set_document(
            Document(text=text, cursor_position=cursor_position),
            bypass_readonly=True,
        )
        if follow_tail:
            # Large value is clamped by PTK to the actual bottom.
            self.output_area.window.vertical_scroll = 10**9
        elif preserve_scroll is not None:
            self.output_area.window.vertical_scroll = max(0, preserve_scroll)
        self._invalidate()

    def _is_output_at_bottom(self) -> bool:
        render_info = self.output_area.window.render_info
        if render_info is None:
            return self.output_area.buffer.cursor_position >= len(self.output_area.text)
        return bool(render_info.bottom_visible)

    def _sync_follow_output_tail(self) -> None:
        at_bottom = self._is_output_at_bottom()
        if at_bottom:
            self._follow_output_tail = True
            return
        self._follow_output_tail = False

    def _scroll_output(self, delta: int) -> None:
        window = self.output_area.window
        window.vertical_scroll = max(0, window.vertical_scroll + delta)
        self._follow_output_tail = next_follow_tail_state(
            current_follow_tail=self._follow_output_tail,
            scroll_delta=delta,
            at_bottom=self._is_output_at_bottom(),
        )
        self._invalidate()

    def _append_output(self, chunk: str) -> None:
        normalized = normalize_output_chunk(chunk)
        if not normalized:
            return

        self._sync_follow_output_tail()
        combined = self.output_area.text + normalized
        if len(combined) > self._max_output_chars:
            combined = combined[-self._max_output_chars :]
        self._set_output_text(
            combined,
            follow_tail=self._follow_output_tail,
            preserve_scroll=self.output_area.window.vertical_scroll,
        )

    def _on_stream_text(self, text: str) -> None:
        if not text:
            return

        if self._loop is None:
            return

        self._loop.call_soon_threadsafe(self._append_output, text)

    def _invalidate(self) -> None:
        with contextlib.suppress(Exception):
            self.app.invalidate()

    def _install_session_hooks(self) -> None:
        def _status_update_proxy(*args, **kwargs) -> None:
            self._orig_status_update(*args, **kwargs)
            self._invalidate()

        def _status_show_proxy() -> None:
            # Status is rendered in a dedicated PTK footer; don't print Rich panel.
            self._invalidate()

        self.session.status_bar.update = _status_update_proxy  # type: ignore[method-assign]
        self.session.status_bar.show = _status_show_proxy  # type: ignore[method-assign]
        self.session.input_handler.prompt_async = self._prompt_async  # type: ignore[assignment]
        agent_base_module.AsyncSpinner = _PTK2AsyncSpinner

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
            # PTK2 output pane can render ANSI; keep Rich coloring enabled.
            force_terminal=True,
            color_system="truecolor",
            theme=Theme.get_rich_theme(),
        )

        self._install_session_hooks()

        session_task: asyncio.Task[None] | None = None
        stop_task: asyncio.Task[None] | None = None
        session_error: Exception | None = None

        try:
            with contextlib.redirect_stdout(self._stream), contextlib.redirect_stderr(self._stream):
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
            if stop_task is not None:
                stop_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await stop_task

            terminal_ui.console = old_console
            self._restore_session_hooks()

        if session_error is not None:
            raise session_error


def run_interactive_mode_ptk2(agent):
    """Run interactive mode in experimental single-renderer PTK2 mode."""
    session = InteractiveSession(agent)
    driver = PTK2Driver(session)
    return driver.run()
