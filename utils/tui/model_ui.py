"""TUI helpers for model selection and configuration editing."""

from __future__ import annotations

import asyncio
import os
import shlex
import shutil
import sys
from pathlib import Path
from typing import Protocol, Sequence

import aiofiles.os
from prompt_toolkit.application import Application, run_in_terminal
from prompt_toolkit.application.current import get_app_or_none
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style

from utils.tui.theme import Theme


class _Model(Protocol):
    model_id: str


class _ModelManager(Protocol):
    config_path: str

    def list_models(self) -> Sequence[_Model]: ...

    def get_current_model(self) -> _Model | None: ...


async def open_in_editor(path: str) -> tuple[bool, bool]:
    """Open a file in an editor (best-effort).

    Returns:
        (opened, waited): waited indicates we blocked until editing likely finished.
    """
    path = str(Path(path))

    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if editor:
        cmd = shlex.split(editor) + [path]
        try:
            proc = await asyncio.create_subprocess_exec(*cmd)
        except FileNotFoundError:
            return False, False
        return (await proc.wait()) == 0, True

    if shutil.which("vi"):
        proc = await asyncio.create_subprocess_exec("vi", path)
        return (await proc.wait()) == 0, True

    if shutil.which("code"):
        # Don't use `-w` here; we prefer to return to the TUI after the file is saved
        # (and auto-reloaded), without requiring the user to close the editor tab.
        proc = await asyncio.create_subprocess_exec("code", "--reuse-window", path)
        return (await proc.wait()) == 0, False

    if sys.platform == "darwin" and shutil.which("open"):
        # `open` returns immediately; we can't reliably wait for editing completion.
        proc = await asyncio.create_subprocess_exec("open", "-t", path)
        return (await proc.wait()) == 0, False

    if shutil.which("xdg-open"):
        # xdg-open returns immediately; we can't reliably wait for editing completion.
        proc = await asyncio.create_subprocess_exec("xdg-open", path)
        return (await proc.wait()) == 0, False

    return False, False


async def get_mtime(path: str) -> tuple[int, int] | None:
    try:
        stat = await aiofiles.os.stat(path)
        return stat.st_mtime_ns, stat.st_size
    except FileNotFoundError:
        return None


async def wait_for_file_change(path: str, old_mtime: tuple[int, int] | None) -> None:
    while True:
        new_mtime = await get_mtime(path)
        if old_mtime is None:
            if new_mtime is not None:
                return
        elif new_mtime is not None and new_mtime != old_mtime:
            return
        await asyncio.sleep(0.25)


async def open_config_and_wait_for_save(config_path: str) -> bool:
    """Open config file and return when it is likely saved at least once."""
    before = await get_mtime(config_path)
    ok, waited = await open_in_editor(config_path)
    if not ok:
        return False
    if not waited:
        await wait_for_file_change(config_path, before)
    return True


async def pick_model_id(model_manager: _ModelManager, title: str) -> str | None:
    """Pick a model_id using a keyboard-only list (Codex-style)."""
    models = list(model_manager.list_models())
    if not models:
        return None

    colors = Theme.get_colors()
    current = model_manager.get_current_model()
    current_id = current.model_id if current else None

    selected_index = 0
    if current_id:
        for i, m in enumerate(models):
            if m.model_id == current_id:
                selected_index = i
                break

    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    def _up(event) -> None:
        nonlocal selected_index
        selected_index = (selected_index - 1) % len(models)

    @kb.add("down")
    @kb.add("j")
    def _down(event) -> None:
        nonlocal selected_index
        selected_index = (selected_index + 1) % len(models)

    @kb.add("enter")
    def _enter(event) -> None:
        event.app.exit(result=models[selected_index].model_id)

    @kb.add("escape")
    @kb.add("c-c")
    def _cancel(event) -> None:
        event.app.exit(result=None)

    def _render() -> list[tuple[str, str]]:
        lines: list[tuple[str, str]] = []
        lines.append(("class:title", f"{title}\n"))
        lines.append(("class:hint", "Use ↑/↓ and Enter to select, Esc to cancel.\n\n"))

        for idx, m in enumerate(models, start=1):
            is_selected = (idx - 1) == selected_index
            is_current = m.model_id == current_id

            prefix = "› " if is_selected else "  "
            marker = "(current) " if is_current else ""
            text = f"{prefix}{idx}. {marker}{m.model_id}\n"
            style = "class:selected" if is_selected else "class:item"
            lines.append((style, text))

        return lines

    control = FormattedTextControl(_render, focusable=True)
    window = Window(content=control, dont_extend_height=True, always_hide_cursor=True)
    layout = Layout(HSplit([window]))

    style_dict = Theme.get_prompt_toolkit_style()
    style_dict.update(
        {
            "title": f"{colors.primary} bold",
            "hint": colors.text_muted,
            "item": colors.text_primary,
            "selected": f"bg:{colors.primary} {colors.bg_primary}",
        }
    )

    app = Application(
        layout=layout,
        key_bindings=kb,
        style=Style.from_dict(style_dict),
        full_screen=False,
        mouse_support=False,
    )
    # PTK2 runs a full-screen prompt_toolkit app already. In nested contexts,
    # run this picker in terminal mode with its own thread-backed event loop.
    current_app = get_app_or_none()
    if current_app is not None and current_app.is_running:
        return await run_in_terminal(lambda: app.run(in_thread=True), in_executor=False)

    return await app.run_async()


def mask_secret(value: str | None) -> str:
    if not value:
        return "(not set)"
    v = value.strip()
    if len(v) <= 8:
        return "*" * len(v)
    return f"{v[:4]}…{v[-4:]}"


def parse_kv_args(tokens: list[str]) -> tuple[dict[str, str], list[str]]:
    kv: dict[str, str] = {}
    rest: list[str] = []
    for token in tokens:
        if "=" in token:
            k, _, v = token.partition("=")
            kv[k.strip()] = v
        else:
            rest.append(token)
    return kv, rest
