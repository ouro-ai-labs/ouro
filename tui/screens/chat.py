"""Main chat screen for ouro TUI."""

import asyncio
from typing import TYPE_CHECKING, Any, List

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import LoadingIndicator, Static

from ..widgets import Header, InputArea, MessagePanel, StatusBar
from .help import HelpScreen

if TYPE_CHECKING:
    from agent.base import BaseAgent


class ChatScreen(Screen):
    """Main chat screen with message panel, input area, and status bar."""

    BINDINGS = [
        ("f1", "show_help", "Help"),
        ("ctrl+l", "clear_screen", "Clear"),
        ("ctrl+d", "quit_app", "Exit"),
        ("escape", "cancel", "Cancel"),
        ("pageup", "scroll_up", "Scroll Up"),
        ("pagedown", "scroll_down", "Scroll Down"),
        ("ctrl+u", "scroll_up", "Scroll Up"),
        ("ctrl+j", "scroll_down", "Scroll Down"),
    ]

    DEFAULT_CSS = """
    ChatScreen {
        layout: vertical;
        background: $surface;
    }

    ChatScreen #activity-bar {
        dock: bottom;
        height: 1;
        display: none;
        background: $surface-darken-1;
        layout: horizontal;
        padding: 0 1;
    }

    ChatScreen #activity-bar.visible {
        display: block;
    }

    ChatScreen #activity-bar LoadingIndicator {
        width: 3;
        height: 1;
        padding: 0;
        background: transparent;
    }

    ChatScreen #activity-bar .activity-text {
        color: $warning;
        padding-left: 1;
    }

    ChatScreen #input-section {
        dock: bottom;
        height: auto;
        margin-bottom: 1;
    }
    """

    def __init__(
        self,
        agent: "BaseAgent",
        mode: str = "react",
        model: str = "unknown",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.agent = agent
        self.mode = mode
        self.model = model
        self.turn_count = 0
        self._is_processing = False
        self._cancel_requested = False
        self._current_worker = None
        self._pending_events: List[Any] = []
        self._current_iteration = 0
        self._current_tool_id = ""

    def compose(self) -> ComposeResult:
        yield Header(model=self.model, mode=self.mode)
        yield MessagePanel(id="message-panel")
        with Horizontal(id="activity-bar"):
            yield LoadingIndicator()
            yield Static("", id="activity-text", classes="activity-text")
        with Vertical(id="input-section"):
            yield InputArea()
            yield StatusBar()

    def on_mount(self) -> None:
        """Initialize the screen."""
        # Register event handler with agent
        self.agent.add_event_handler(self._handle_agent_event)

        # Focus input area
        self.query_one(InputArea).focus_input()

        # Show welcome message
        self._add_welcome_message()

        # Set up a timer to process pending events
        self.set_interval(0.05, self._process_pending_events)

    def on_unmount(self) -> None:
        """Clean up when screen is removed."""
        self.agent.remove_event_handler(self._handle_agent_event)

    def _handle_agent_event(self, event: Any) -> None:
        """Handle events from agent (called from worker thread)."""
        self._pending_events.append(event)

    def _process_pending_events(self) -> None:
        """Process queued events on main thread."""
        while self._pending_events:
            event = self._pending_events.pop(0)
            self._dispatch_event(event)

    def _dispatch_event(self, event: Any) -> None:
        """Dispatch an event to the appropriate handler."""
        from agent.events import (
            AssistantResponse,
            IterationStarted,
            MemoryCompressed,
            ThinkingEvent,
            ToolCallCompleted,
            ToolCallStarted,
        )

        panel = self.query_one(MessagePanel)

        if isinstance(event, IterationStarted):
            self._current_iteration = event.iteration
            self._set_activity(f"Iteration {event.iteration}/{event.max_iterations}")
            panel.set_current_status(f"Thinking... (iteration {event.iteration})")

        elif isinstance(event, ThinkingEvent):
            # Show brief thinking in status
            preview = event.content[:50].replace("\n", " ")
            panel.set_current_status(f"Thinking: {preview}...")

        elif isinstance(event, ToolCallStarted):
            self._current_tool_id = event.tool_call_id
            self._set_activity(f"Running {event.tool_name}")
            panel.add_tool_call_to_current(
                tool_name=event.tool_name,
                arguments=event.arguments,
                tool_id=event.tool_call_id,
            )

        elif isinstance(event, ToolCallCompleted):
            self._set_activity(f"Completed {event.tool_name}")
            panel.complete_tool_call(event.tool_call_id, event.result)

        elif isinstance(event, MemoryCompressed):
            self._update_stats_from_memory()

        elif isinstance(event, AssistantResponse):
            if event.is_final:
                panel.update_streaming_content(event.content, is_complete=True)
            else:
                # Intermediate content alongside tool calls
                panel.update_streaming_content(event.content, is_complete=False)

    def _set_activity(self, text: str) -> None:
        """Set activity bar text."""
        try:
            activity_text = self.query_one("#activity-text", Static)
            activity_text.update(text)
        except Exception:
            pass

    def _add_welcome_message(self) -> None:
        """Add initial welcome message with ASCII banner and random tagline."""
        import random

        from utils.terminal_ui import OURO_LOGO, TAGLINES

        tagline = random.choice(TAGLINES)
        panel = self.query_one(MessagePanel)
        panel.add_assistant_message(
            content=(
                f"```\n{OURO_LOGO.strip()}\n```\n"
                f"*{tagline}*\n\n"
                "Tips: `@` for files, `/` for commands, `F1` for help."
            )
        )

    @on(InputArea.Submitted)
    def handle_input_submitted(self, event: InputArea.Submitted) -> None:
        """Handle user message submission."""
        if self._is_processing:
            return

        message = event.value.strip()
        if not message:
            return

        panel = self.query_one(MessagePanel)
        panel.add_user_message(message)
        self._start_processing(message)

    @on(InputArea.CommandSubmitted)
    def handle_command_submitted(self, event: InputArea.CommandSubmitted) -> None:
        """Handle command submission."""
        command = event.command
        args = event.args

        if command in ("/exit", "/quit"):
            self.app.exit()
        elif command == "/help":
            self.action_show_help()
        elif command in ("/clear", "/reset"):
            self._handle_clear_command()
        elif command == "/stats":
            self._handle_stats_command()
        elif command == "/compact":
            self._handle_compact_command()
        elif command == "/model":
            self._handle_model_command(args)
        elif command == "/verbose":
            self._handle_verbose_command()
        elif command == "/theme":
            self._handle_theme_command()
        elif command == "/resume":
            self._handle_resume_command(args)
        elif command == "/login":
            self._handle_login_command(args)
        elif command == "/logout":
            self._handle_logout_command(args)
        else:
            panel = self.query_one(MessagePanel)
            panel.add_assistant_message(
                content=f"Unknown command: `{command}`. Type `/help` for available commands."
            )

    def _start_processing(self, message: str) -> None:
        """Start processing a message."""
        self._is_processing = True
        self._cancel_requested = False
        self._current_iteration = 0
        self.turn_count += 1

        # Show activity bar
        activity_bar = self.query_one("#activity-bar")
        activity_bar.add_class("visible")
        self._set_activity("Starting...")

        # Update status bar
        status_bar = self.query_one(StatusBar)
        status_bar.update_stats(turn=self.turn_count)

        # Start streaming message
        panel = self.query_one(MessagePanel)
        panel.start_streaming_message()

        # Run agent
        self._current_worker = self._run_agent(message)

    @work(exclusive=True, thread=True, exit_on_error=False)
    def _run_agent(self, message: str) -> str:
        """Run agent in background thread."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result: str = loop.run_until_complete(self.agent.run(message))  # type: ignore[arg-type]
            return result
        finally:
            loop.close()

    def on_worker_state_changed(self, event) -> None:
        """Handle worker state changes."""
        if event.worker.name == "_run_agent":
            if event.worker.is_finished:
                self._on_agent_finished(event.worker)

    def _on_agent_finished(self, worker) -> None:
        """Called when agent worker finishes."""
        panel = self.query_one(MessagePanel)

        if worker.is_cancelled:
            panel.update_streaming_content("*Cancelled*", is_complete=True)
        elif worker.state.name == "ERROR":
            panel.update_streaming_content(f"**Error:** {worker.error}", is_complete=True)
        else:
            result = worker.result
            panel.update_streaming_content(result, is_complete=True)

        self._update_stats_from_memory()
        self._finish_processing()

    def _finish_processing(self) -> None:
        """Clean up after processing."""
        self._is_processing = False
        self._current_worker = None
        self._pending_events.clear()

        # Hide activity bar
        activity_bar = self.query_one("#activity-bar")
        activity_bar.remove_class("visible")

        self.query_one(InputArea).focus_input()

    def _update_stats_from_memory(self) -> None:
        """Update status bar and header from agent memory stats."""
        try:
            stats = self.agent.memory.get_stats()
            status_bar = self.query_one(StatusBar)
            status_bar.update_stats(
                input_tokens=stats.get("total_input_tokens", 0),
                output_tokens=stats.get("total_output_tokens", 0),
                cost=stats.get("total_cost", 0.0),
                compressions=stats.get("compression_count", 0),
            )
            header = self.query_one(Header)
            header.update_tokens(stats.get("current_tokens", 0))
        except Exception:
            pass

    def _handle_clear_command(self) -> None:
        """Handle /clear command."""
        self.agent.memory.reset()
        self.turn_count = 0

        panel = self.query_one(MessagePanel)
        panel.clear_messages()

        status_bar = self.query_one(StatusBar)
        status_bar.update_stats(turn=0, input_tokens=0, output_tokens=0, cost=0.0, compressions=0)

        header = self.query_one(Header)
        header.update_tokens(0)

        panel.add_assistant_message(content="Memory cleared.")

    def _handle_stats_command(self) -> None:
        """Handle /stats command."""
        try:
            stats = self.agent.memory.get_stats()
            panel = self.query_one(MessagePanel)
            total = stats.get("total_input_tokens", 0) + stats.get("total_output_tokens", 0)

            panel.add_assistant_message(content=f"""**Memory Statistics**

| Metric | Value |
|--------|------:|
| Total Tokens | {total:,} |
| Input | {stats.get('total_input_tokens', 0):,} |
| Output | {stats.get('total_output_tokens', 0):,} |
| Context | {stats.get('current_tokens', 0):,} |
| Compressions | {stats.get('compression_count', 0)} |
| Cost | ${stats.get('total_cost', 0):.4f} |
""")
        except Exception as e:
            self.query_one(MessagePanel).add_assistant_message(content=f"Error: {e}")

    def _handle_compact_command(self) -> None:
        """Handle /compact command - compress conversation memory."""
        panel = self.query_one(MessagePanel)

        @work(thread=True, exit_on_error=False)
        async def do_compact(self_ref: "ChatScreen") -> None:
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(self_ref.agent.memory.compress())
            finally:
                loop.close()
            if result is None:
                self_ref.app.call_from_thread(
                    panel.add_assistant_message, content="Nothing to compress."
                )
            else:
                self_ref.app.call_from_thread(
                    panel.add_assistant_message,
                    content=(
                        f"Compressed {result.original_message_count} messages: "
                        f"{result.original_tokens} -> {result.compressed_tokens} tokens "
                        f"({result.savings_percentage:.0f}% saved)"
                    ),
                )
            self_ref.app.call_from_thread(self_ref._update_stats_from_memory)

        do_compact(self)

    def _handle_model_command(self, args: List[str]) -> None:
        """Handle /model command - show current model or switch."""
        panel = self.query_one(MessagePanel)
        model_info = self.agent.get_current_model_info()

        if not args:
            # Show current model info and available models
            if not model_info:
                panel.add_assistant_message(content="No model configured.")
                return

            model_manager = getattr(self.agent, "model_manager", None)
            if not model_manager:
                panel.add_assistant_message(content=f"Current model: `{model_info['model_id']}`")
                return

            profiles = model_manager.list_models()
            current_id = model_info["model_id"]
            lines = ["**Available Models**\n"]
            for p in profiles:
                marker = " **(current)**" if p.model_id == current_id else ""
                lines.append(f"- `{p.model_id}`{marker}")
            lines.append("\nUsage: `/model <model_id>` to switch.")
            panel.add_assistant_message(content="\n".join(lines))
            return

        # Switch model
        target = " ".join(args)
        success = self.agent.switch_model(target)
        if success:
            new_info = self.agent.get_current_model_info()
            new_name = new_info["model_id"] if new_info else target
            panel.add_assistant_message(content=f"Switched to model: `{new_name}`")
            # Update header
            header = self.query_one(Header)
            header.model = new_name
        else:
            panel.add_assistant_message(
                content=f"Failed to switch to model `{target}`. Use `/model` to see available models."
            )

    def _handle_verbose_command(self) -> None:
        """Handle /verbose command - toggle thinking display."""
        from config import Config

        Config.TUI_SHOW_THINKING = not Config.TUI_SHOW_THINKING
        status = "enabled" if Config.TUI_SHOW_THINKING else "disabled"
        panel = self.query_one(MessagePanel)
        panel.add_assistant_message(content=f"Verbose thinking display **{status}**.")

    def _handle_theme_command(self) -> None:
        """Handle /theme command."""
        panel = self.query_one(MessagePanel)
        panel.add_assistant_message(
            content="Theme switching is handled by Textual. "
            "Use `textual` dark/light mode settings."
        )

    def _handle_resume_command(self, args: List[str]) -> None:
        """Handle /resume command - resume a previous session."""
        panel = self.query_one(MessagePanel)
        if not args:
            panel.add_assistant_message(content="Usage: `/resume <session_id>`")
            return

        session_id = args[0]

        @work(thread=True, exit_on_error=False)
        async def do_resume(self_ref: "ChatScreen") -> None:
            from memory import MemoryManager

            loop = asyncio.new_event_loop()
            try:
                resolved = loop.run_until_complete(MemoryManager.find_session_by_prefix(session_id))
                if not resolved:
                    self_ref.app.call_from_thread(
                        panel.add_assistant_message,
                        content=f"Session `{session_id}` not found.",
                    )
                    return
                loop.run_until_complete(self_ref.agent.load_session(resolved))
                msg_count = self_ref.agent.memory.short_term.count()
                self_ref.app.call_from_thread(
                    panel.add_assistant_message,
                    content=f"Resumed session `{resolved}` ({msg_count} messages).",
                )
                self_ref.app.call_from_thread(self_ref._update_stats_from_memory)
            finally:
                loop.close()

        do_resume(self)

    def _handle_login_command(self, args: List[str]) -> None:
        """Handle /login command - login to OAuth provider."""
        panel = self.query_one(MessagePanel)

        @work(thread=True, exit_on_error=False)
        async def do_login(self_ref: "ChatScreen") -> None:
            from llm.chatgpt_auth import (
                get_all_auth_provider_statuses,
                get_supported_auth_providers,
                is_auth_status_logged_in,
                login_auth_provider,
            )
            from llm.oauth_model_sync import sync_oauth_models

            loop = asyncio.new_event_loop()
            try:
                # Determine provider
                providers = get_supported_auth_providers()
                if args:
                    provider = args[0]
                    if provider not in providers:
                        self_ref.app.call_from_thread(
                            panel.add_assistant_message,
                            content=f"Unknown provider `{provider}`. Available: {', '.join(providers)}",
                        )
                        return
                else:
                    # Check status and pick first available
                    statuses = loop.run_until_complete(get_all_auth_provider_statuses())
                    available = [
                        p
                        for p in providers
                        if not (statuses.get(p) and is_auth_status_logged_in(statuses[p]))
                    ]
                    if not available:
                        self_ref.app.call_from_thread(
                            panel.add_assistant_message,
                            content="All OAuth providers already logged in.",
                        )
                        return
                    provider = available[0]

                self_ref.app.call_from_thread(
                    panel.add_assistant_message,
                    content=f"Starting **{provider}** login flow...",
                )

                status = loop.run_until_complete(login_auth_provider(provider))

                model_manager = getattr(self_ref.agent, "model_manager", None)
                added_msg = ""
                if model_manager:
                    added = sync_oauth_models(model_manager, provider)
                    if added:
                        added_msg = f" Added {len(added)} models."

                lines = [f"**{provider}** login completed.{added_msg}"]
                if status.auth_file:
                    lines.append(f"Auth file: `{status.auth_file}`")
                if status.account_id:
                    lines.append(f"Account: `{status.account_id}`")
                lines.append("Use `/model` to pick the active model.")
                self_ref.app.call_from_thread(
                    panel.add_assistant_message, content="\n\n".join(lines)
                )
            except Exception as e:
                self_ref.app.call_from_thread(
                    panel.add_assistant_message, content=f"**Login error:** {e}"
                )
            finally:
                loop.close()

        do_login(self)

    def _handle_logout_command(self, args: List[str]) -> None:
        """Handle /logout command - logout from OAuth provider."""
        panel = self.query_one(MessagePanel)

        @work(thread=True, exit_on_error=False)
        async def do_logout(self_ref: "ChatScreen") -> None:
            from llm.chatgpt_auth import (
                get_all_auth_provider_statuses,
                get_supported_auth_providers,
                is_auth_status_logged_in,
                logout_auth_provider,
            )
            from llm.oauth_model_sync import remove_oauth_models

            loop = asyncio.new_event_loop()
            try:
                providers = get_supported_auth_providers()
                if args:
                    provider = args[0]
                    if provider not in providers:
                        self_ref.app.call_from_thread(
                            panel.add_assistant_message,
                            content=f"Unknown provider `{provider}`. Available: {', '.join(providers)}",
                        )
                        return
                else:
                    # Pick first logged-in provider
                    statuses = loop.run_until_complete(get_all_auth_provider_statuses())
                    logged_in = [
                        p
                        for p in providers
                        if statuses.get(p) and is_auth_status_logged_in(statuses[p])
                    ]
                    if not logged_in:
                        self_ref.app.call_from_thread(
                            panel.add_assistant_message,
                            content="No OAuth providers currently logged in.",
                        )
                        return
                    provider = logged_in[0]

                removed = loop.run_until_complete(logout_auth_provider(provider))

                model_manager = getattr(self_ref.agent, "model_manager", None)
                removed_msg = ""
                if model_manager:
                    removed_models = remove_oauth_models(model_manager, provider)
                    if removed_models:
                        removed_msg = f" Removed {len(removed_models)} managed models."
                    current_after = model_manager.get_current_model()
                    if current_after:
                        self_ref.agent.switch_model(current_after.model_id)

                if removed:
                    self_ref.app.call_from_thread(
                        panel.add_assistant_message,
                        content=f"Logged out from **{provider}**.{removed_msg}",
                    )
                else:
                    self_ref.app.call_from_thread(
                        panel.add_assistant_message,
                        content=f"No **{provider}** login state found.",
                    )
            except Exception as e:
                self_ref.app.call_from_thread(
                    panel.add_assistant_message, content=f"**Logout error:** {e}"
                )
            finally:
                loop.close()

        do_logout(self)

    def action_show_help(self) -> None:
        self.app.push_screen(HelpScreen())

    def action_clear_screen(self) -> None:
        self.query_one(MessagePanel).clear_messages()

    def action_quit_app(self) -> None:
        self.app.exit()

    def action_cancel(self) -> None:
        if self._is_processing and self._current_worker:
            self._current_worker.cancel()

    def action_scroll_up(self) -> None:
        """Scroll message panel up."""
        panel = self.query_one(MessagePanel)
        panel.scroll_page_up()

    def action_scroll_down(self) -> None:
        """Scroll message panel down."""
        panel = self.query_one(MessagePanel)
        panel.scroll_page_down()
