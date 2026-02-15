"""Header widget displaying ouro branding and session info."""

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class Header(Widget):
    """Header bar with logo, model info, mode, and token count."""

    DEFAULT_CSS = """
    Header {
        dock: top;
        height: 1;
        background: $primary-background;
        layout: horizontal;
    }

    Header > .header-logo {
        width: auto;
        padding: 0 1;
        color: $success;
        text-style: bold;
    }

    Header > .header-sep {
        width: 1;
        color: $text-muted;
    }

    Header > .header-model {
        width: auto;
        padding: 0 1;
        color: $text;
    }

    Header > .header-mode {
        width: auto;
        padding: 0 1;
        color: $primary-lighten-2;
    }

    Header > .header-spacer {
        width: 1fr;
    }

    Header > .header-tokens {
        width: auto;
        padding: 0 1;
        color: $text-muted;
    }
    """

    model: reactive[str] = reactive("unknown")
    mode: reactive[str] = reactive("react")
    token_count: reactive[int] = reactive(0)

    def __init__(
        self,
        model: str = "unknown",
        mode: str = "react",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.model = model
        self.mode = mode

    def compose(self) -> ComposeResult:
        yield Static("\u25c9 ouro", classes="header-logo")
        yield Static("\u2502", classes="header-sep")
        yield Static(self._short_model(), id="header-model", classes="header-model")
        yield Static(f"[{self.mode}]", id="header-mode", classes="header-mode")
        yield Static("", classes="header-spacer")
        yield Static(self._format_tokens(), id="header-tokens", classes="header-tokens")

    def _short_model(self) -> str:
        """Get a shortened model name."""
        # e.g. "anthropic/claude-3-5-sonnet" -> "claude-3-5-sonnet"
        if "/" in self.model:
            return self.model.split("/", 1)[1]
        return self.model

    def _format_tokens(self) -> str:
        """Format token count for display."""
        if self.token_count == 0:
            return ""
        if self.token_count >= 1000:
            return f"{self.token_count / 1000:.1f}k tokens"
        return f"{self.token_count} tokens"

    def watch_model(self, value: str) -> None:
        """React to model changes."""
        try:
            self.query_one("#header-model", Static).update(self._short_model())
        except Exception:
            pass

    def watch_mode(self, value: str) -> None:
        """React to mode changes."""
        try:
            self.query_one("#header-mode", Static).update(f"[{value}]")
        except Exception:
            pass

    def watch_token_count(self, value: int) -> None:
        """React to token count changes."""
        try:
            self.query_one("#header-tokens", Static).update(self._format_tokens())
        except Exception:
            pass

    def update_tokens(self, count: int) -> None:
        """Update the token count display."""
        self.token_count = count
