"""TUI helpers for skills management (MVP)."""

from __future__ import annotations

from typing import Sequence

from prompt_toolkit.application import Application, run_in_terminal
from prompt_toolkit.application.current import get_app_or_none
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style

from utils.tui.theme import Theme


class SkillsAction:
    LIST = "list"
    INSTALL = "install"
    UNINSTALL = "uninstall"


_ACTIONS: list[tuple[str, str]] = [
    (SkillsAction.LIST, "List skills"),
    (SkillsAction.INSTALL, "Install skill"),
    (SkillsAction.UNINSTALL, "Uninstall skill"),
]


async def pick_skills_action(title: str = "Skills") -> str | None:
    colors = Theme.get_colors()
    selected_index = 0

    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    def _up(event) -> None:
        nonlocal selected_index
        selected_index = (selected_index - 1) % len(_ACTIONS)

    @kb.add("down")
    @kb.add("j")
    def _down(event) -> None:
        nonlocal selected_index
        selected_index = (selected_index + 1) % len(_ACTIONS)

    @kb.add("enter")
    def _enter(event) -> None:
        event.app.exit(result=_ACTIONS[selected_index][0])

    @kb.add("escape")
    @kb.add("c-c")
    def _cancel(event) -> None:
        event.app.exit(result=None)

    def _render() -> list[tuple[str, str]]:
        lines: list[tuple[str, str]] = []
        lines.append(("class:title", f"{title}\n"))
        lines.append(("class:hint", "Choose an action\n\n"))

        for idx, (_, label) in enumerate(_ACTIONS, start=1):
            is_selected = (idx - 1) == selected_index
            prefix = "> " if is_selected else "  "
            hint = ""
            if idx == 1:
                hint = "  Tip: press $ to open this list directly."
            elif idx == 2:
                hint = "  Install from local path or git URL."
            elif idx == 3:
                hint = "  Remove an installed skill."

            text = f"{prefix}{idx}. {label}{hint}\n"
            style = "class:selected" if is_selected else "class:item"
            lines.append((style, text))

        lines.append(("class:hint", "\nPress enter to confirm or esc to go back\n"))
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

    # PTK2 mode keeps a full-screen Application running. Running another PTK app
    # directly can deadlock; run this picker in terminal mode when nested.
    current_app = get_app_or_none()
    if current_app is not None and current_app.is_running:
        return await run_in_terminal(lambda: app.run(in_thread=True), in_executor=False)

    return await app.run_async()


def format_skill_lines(names: Sequence[str]) -> str:
    if not names:
        return "(no skills installed)"
    return "\n".join(f"- {name}" for name in names)
