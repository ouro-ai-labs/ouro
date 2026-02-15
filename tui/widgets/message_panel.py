"""Message panel widget for displaying conversation history."""

from typing import Any, Dict, List, Optional

from textual.app import ComposeResult
from textual.containers import ScrollableContainer, Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Markdown, Static


class ToolCallBlock(Widget):
    """A collapsible tool call display."""

    DEFAULT_CSS = """
    ToolCallBlock {
        height: auto;
        margin: 0;
        padding: 0;
    }

    ToolCallBlock > .tool-row {
        height: 1;
        padding: 0 1;
    }

    ToolCallBlock > .tool-row.running {
        color: $warning;
    }

    ToolCallBlock > .tool-row.completed {
        color: $success-darken-1;
    }

    ToolCallBlock > .tool-details {
        padding: 0 3;
        color: $text-muted;
        display: none;
        height: auto;
        background: $surface-darken-1;
    }

    ToolCallBlock.expanded > .tool-details {
        display: block;
    }
    """

    expanded: reactive[bool] = reactive(False)
    is_running: reactive[bool] = reactive(True)

    def __init__(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        result: str = "",
        is_running: bool = True,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.tool_name = tool_name
        self.arguments = arguments
        self.result = result
        self.is_running = is_running

    def compose(self) -> ComposeResult:
        status = "\u25cf" if self.is_running else "\u2713"  # ● or ✓
        cls = "running" if self.is_running else "completed"
        yield Static(f"  \u25b8 {status} {self.tool_name}", classes=f"tool-row {cls}")
        yield Static(self._format_details(), classes="tool-details")

    def _format_details(self) -> str:
        """Format tool call details."""
        lines = []
        if self.arguments:
            for key, value in self.arguments.items():
                value_str = str(value)
                if len(value_str) > 80:
                    value_str = value_str[:77] + "..."
                lines.append(f"{key}: {value_str}")
        if self.result and not self.is_running:
            result_preview = self.result[:150] + "..." if len(self.result) > 150 else self.result
            lines.append(f"Result: {result_preview}")
        return "\n".join(lines) if lines else "No details"

    def on_click(self) -> None:
        """Toggle expansion on click."""
        self.expanded = not self.expanded
        if self.expanded:
            self.add_class("expanded")
            row = self.query_one(".tool-row", Static)
            status = "\u25cf" if self.is_running else "\u2713"
            row.update(f"  \u25be {status} {self.tool_name}")
        else:
            self.remove_class("expanded")
            row = self.query_one(".tool-row", Static)
            status = "\u25cf" if self.is_running else "\u2713"
            row.update(f"  \u25b8 {status} {self.tool_name}")

    def mark_completed(self, result: str) -> None:
        """Mark the tool call as completed."""
        self.result = result
        self.is_running = False
        try:
            row = self.query_one(".tool-row", Static)
            row.remove_class("running")
            row.add_class("completed")
            arrow = "\u25be" if self.expanded else "\u25b8"
            row.update(f"  {arrow} \u2713 {self.tool_name}")
            details = self.query_one(".tool-details", Static)
            details.update(self._format_details())
        except Exception:
            pass


class ThinkingBlock(Widget):
    """A collapsible thinking/reasoning display."""

    DEFAULT_CSS = """
    ThinkingBlock {
        height: auto;
        margin: 0;
        padding: 0;
    }

    ThinkingBlock > .thinking-row {
        height: 1;
        padding: 0 1;
        color: $primary-lighten-1;
    }

    ThinkingBlock > .thinking-details {
        padding: 0 3;
        color: $text-muted;
        display: none;
        height: auto;
        background: $surface-darken-1;
    }

    ThinkingBlock.expanded > .thinking-details {
        display: block;
    }
    """

    expanded: reactive[bool] = reactive(False)

    def __init__(self, content: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.content = content

    def compose(self) -> ComposeResult:
        preview = self.content[:60] + "..." if len(self.content) > 60 else self.content
        preview = preview.replace("\n", " ")
        yield Static(f"  \u25b8 Thinking: {preview}", classes="thinking-row")
        yield Static(self.content[:800], classes="thinking-details")

    def on_click(self) -> None:
        """Toggle expansion on click."""
        self.expanded = not self.expanded
        if self.expanded:
            self.add_class("expanded")
            row = self.query_one(".thinking-row", Static)
            row.update("  \u25be Thinking")
        else:
            self.remove_class("expanded")
            preview = self.content[:60] + "..." if len(self.content) > 60 else self.content
            preview = preview.replace("\n", " ")
            row = self.query_one(".thinking-row", Static)
            row.update(f"  \u25b8 Thinking: {preview}")


class UserMessage(Widget):
    """User message display."""

    DEFAULT_CSS = """
    UserMessage {
        height: auto;
        margin: 1 0 0 0;
        padding: 0;
    }

    UserMessage > .user-label {
        color: $secondary;
        text-style: bold;
        padding: 0 1;
    }

    UserMessage > .user-content {
        color: $text;
        padding: 0 1 0 3;
    }
    """

    def __init__(self, content: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.content = content

    def compose(self) -> ComposeResult:
        yield Static("\u276f You", classes="user-label")
        yield Static(self.content, classes="user-content")


class AssistantMessage(Widget):
    """Assistant message display with collapsible tool calls and thinking."""

    DEFAULT_CSS = """
    AssistantMessage {
        height: auto;
        margin: 1 0 0 0;
        padding: 0;
    }

    AssistantMessage > .assistant-label {
        color: $primary;
        text-style: bold;
        padding: 0 1;
    }

    AssistantMessage > .assistant-status {
        color: $warning;
        padding: 0 1;
        text-style: italic;
    }

    AssistantMessage > #assistant-content {
        color: $text;
        padding: 0 1 0 3;
        height: auto;
    }

    AssistantMessage > .tool-section {
        padding: 0 1;
        height: auto;
    }
    """

    streaming: reactive[bool] = reactive(False)

    def __init__(
        self,
        content: str = "",
        thinking: str = "",
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        is_streaming: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.content = content
        self.thinking = thinking
        self.tool_calls = tool_calls or []
        self.streaming = is_streaming
        self._tool_blocks: Dict[str, ToolCallBlock] = {}

    def compose(self) -> ComposeResult:
        yield Static("\u25c9 ouro", classes="assistant-label")

        # Thinking block (collapsed by default)
        if self.thinking:
            yield ThinkingBlock(self.thinking)

        # Tool calls section
        yield Vertical(id="tool-section", classes="tool-section")

        # Status indicator for streaming
        if self.streaming and not self.content:
            yield Static("Thinking...", classes="assistant-status", id="status-indicator")

        # Message content - only render if we have content
        if self.content:
            yield Markdown(self.content, id="assistant-content")

    def update_content(self, content: str, is_complete: bool = False) -> None:
        """Update the message content (for streaming)."""
        self.content = content
        self.streaming = not is_complete

        try:
            # Remove status indicator when we have content
            if content:
                indicators = self.query("#status-indicator")
                if indicators:
                    indicators.remove()

            # Try to update existing content widget
            try:
                content_widget = self.query_one("#assistant-content", Markdown)
                content_widget.update(content)
            except Exception:
                # Content widget doesn't exist yet, mount it
                if content:
                    self.mount(Markdown(content, id="assistant-content"))
        except Exception:
            pass

    def add_tool_call(
        self, tool_name: str, arguments: Dict[str, Any], result: str = "", tool_id: str = ""
    ) -> None:
        """Add a tool call to the message."""
        self.tool_calls.append(
            {"name": tool_name, "arguments": arguments, "result": result, "id": tool_id}
        )
        block = ToolCallBlock(tool_name, arguments, result, is_running=True)
        self._tool_blocks[tool_id or tool_name] = block
        try:
            section = self.query_one("#tool-section", Vertical)
            section.mount(block)
        except Exception:
            pass

    def complete_tool_call(self, tool_id: str, result: str) -> None:
        """Mark a tool call as completed."""
        if tool_id in self._tool_blocks:
            self._tool_blocks[tool_id].mark_completed(result)

    def set_status(self, status: str) -> None:
        """Set the status message."""
        try:
            indicator = self.query_one("#status-indicator", Static)
            indicator.update(status)
        except Exception:
            # No indicator exists yet, add one if needed
            if status and not self.content:
                try:
                    content = self.query_one("#assistant-content", Markdown)
                    self.mount(
                        Static(status, classes="assistant-status", id="status-indicator"),
                        before=content,
                    )
                except Exception:
                    pass


class MessagePanel(ScrollableContainer):
    """Scrollable panel containing conversation messages."""

    DEFAULT_CSS = """
    MessagePanel {
        height: 1fr;
        scrollbar-gutter: stable;
        background: $surface;
    }

    MessagePanel > #message-container {
        height: auto;
        min-height: 100%;
        align: left bottom;
        padding: 0 0 1 0;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._current_assistant_message: Optional[AssistantMessage] = None

    def compose(self) -> ComposeResult:
        """Create the inner container for messages."""
        yield Vertical(id="message-container")

    def _scroll_to_end(self) -> None:
        """Scroll to end after layout refresh."""
        self.scroll_end(animate=False)

    def _get_container(self) -> Vertical:
        """Get the message container."""
        return self.query_one("#message-container", Vertical)

    def add_user_message(self, content: str) -> UserMessage:
        """Add a user message to the panel."""
        msg = UserMessage(content)
        self._get_container().mount(msg)
        self.call_after_refresh(self._scroll_to_end)
        return msg

    def add_assistant_message(
        self,
        content: str = "",
        thinking: str = "",
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        is_streaming: bool = False,
    ) -> AssistantMessage:
        """Add an assistant message to the panel."""
        msg = AssistantMessage(
            content=content,
            thinking=thinking,
            tool_calls=tool_calls,
            is_streaming=is_streaming,
        )
        self._get_container().mount(msg)
        self._current_assistant_message = msg
        self.call_after_refresh(self._scroll_to_end)
        return msg

    def start_streaming_message(self) -> AssistantMessage:
        """Start a new streaming assistant message."""
        return self.add_assistant_message(content="", is_streaming=True)

    def update_streaming_content(self, content: str, is_complete: bool = False) -> None:
        """Update the current streaming message."""
        if self._current_assistant_message:
            self._current_assistant_message.update_content(content, is_complete)
            self.call_after_refresh(self._scroll_to_end)

    def add_tool_call_to_current(
        self, tool_name: str, arguments: Dict[str, Any], result: str = "", tool_id: str = ""
    ) -> None:
        """Add a tool call to the current assistant message."""
        if self._current_assistant_message:
            self._current_assistant_message.add_tool_call(tool_name, arguments, result, tool_id)
            self.call_after_refresh(self._scroll_to_end)

    def complete_tool_call(self, tool_id: str, result: str) -> None:
        """Mark a tool call as completed."""
        if self._current_assistant_message:
            self._current_assistant_message.complete_tool_call(tool_id, result)

    def set_current_status(self, status: str) -> None:
        """Set status on current message."""
        if self._current_assistant_message:
            self._current_assistant_message.set_status(status)
            self.call_after_refresh(self._scroll_to_end)

    def clear_messages(self) -> None:
        """Clear all messages from the panel."""
        self.query("UserMessage, AssistantMessage").remove()
        self._current_assistant_message = None
