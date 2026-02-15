"""Main TUI application for aloop."""

from typing import TYPE_CHECKING

from textual.app import App

from .screens import ChatScreen

if TYPE_CHECKING:
    from agent.base import BaseAgent


class AloopTUI(App):
    """AgenticLoop Terminal User Interface application."""

    TITLE = "aloop"
    CSS_PATH = "styles.tcss"

    # Disable mouse capture to allow terminal native text selection
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = [
        ("ctrl+d", "quit", "Exit"),
        ("ctrl+c", "quit", "Exit"),
    ]

    def __init__(
        self,
        agent: "BaseAgent",
        mode: str = "react",
        model: str = "unknown",
        **kwargs,
    ) -> None:
        """Initialize the TUI application.

        Args:
            agent: The agent instance to use
            mode: Agent mode (react or plan)
            model: Model identifier for display
        """
        super().__init__(**kwargs)
        self.agent = agent
        self.mode = mode
        self.model = model

    def on_mount(self) -> None:
        """Called when app is mounted."""
        # Push the chat screen
        chat_screen = ChatScreen(
            agent=self.agent,
            mode=self.mode,
            model=self.model,
        )
        self.push_screen(chat_screen)

    def action_quit(self) -> None:
        """Exit the application."""
        self.exit()


async def run_tui_mode(agent: "BaseAgent") -> None:
    """Run the TUI mode.

    Args:
        agent: The agent instance
    """
    # Extract model info for display
    model_info = agent.get_current_model_info()
    model = model_info["model_id"] if model_info else "unknown"

    app = AloopTUI(agent=agent, mode="react", model=model)
    await app.run_async()
