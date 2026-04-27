"""Agent factory for the CLI / TUI / bot entry points.

Builds a `ComposedAgent` from `~/.ouro/models.yaml` config + the standard
builtin tool set + a TUI-backed `ProgressSink`. Used by:

- `ouro/interfaces/cli/main.py` (one-shot --task and interactive modes)
- `ouro/interfaces/bot/server.py` (per-conversation agent factory)
"""

from __future__ import annotations

from ouro.capabilities import AgentBuilder, ComposedAgent
from ouro.capabilities.tools.builtins.advanced_file_ops import GlobTool, GrepTool
from ouro.capabilities.tools.builtins.file_ops import FileReadTool, FileWriteTool
from ouro.capabilities.tools.builtins.multi_task import MultiTaskTool
from ouro.capabilities.tools.builtins.shell import ShellTool
from ouro.capabilities.tools.builtins.smart_edit import SmartEditTool
from ouro.capabilities.tools.builtins.web_fetch import WebFetchTool
from ouro.capabilities.tools.builtins.web_search import WebSearchTool
from ouro.config import Config
from ouro.core.llm import LiteLLMAdapter, ModelManager
from ouro.interfaces.tui import terminal_ui
from ouro.interfaces.tui.tui_progress import TuiProgressSink


def create_agent(
    model_id: str | None = None,
    sessions_dir: str | None = None,
    memory_dir: str | None = None,
) -> ComposedAgent:
    """Factory function to create a fully wired ComposedAgent.

    Args:
        model_id: Optional LiteLLM model ID (defaults to current/default).
        sessions_dir: Optional custom sessions directory (bot-mode isolation).
        memory_dir: Optional custom long-term memory directory (bot-mode isolation).

    Returns:
        A ComposedAgent with the standard builtin toolset, memory, and a
        TUI-backed progress sink. Skills/soul are NOT loaded here — callers
        load them async after construction and assign to the agent.

    Raises:
        ValueError: If no models are configured or the chosen model is invalid.
    """
    model_manager = ModelManager()
    if not model_manager.is_configured():
        raise ValueError(
            "No models configured. Run `ouro` without --task and use /model edit, "
            "or edit `.ouro/models.yaml` to add at least one model and set `default`."
        )

    if model_id:
        profile = model_manager.get_model(model_id)
        if profile:
            model_manager.switch_model(model_id)
        else:
            available = ", ".join(model_manager.get_model_ids())
            terminal_ui.print_error(f"Model '{model_id}' not found, using default")
            if available:
                terminal_ui.console.print(f"Available: {available}")

    current_profile = model_manager.get_current_model()
    if not current_profile:
        raise ValueError("No model available. Please check `.ouro/models.yaml`.")

    is_valid, error_msg = model_manager.validate_model(current_profile)
    if not is_valid:
        raise ValueError(error_msg)

    llm = LiteLLMAdapter(
        model=current_profile.model_id,
        api_key=current_profile.api_key,
        api_base=current_profile.api_base,
        drop_params=current_profile.drop_params,
        timeout=current_profile.timeout,
    )

    builder = (
        AgentBuilder()
        .with_llm(llm, model_manager=model_manager)
        .with_max_iterations(Config.MAX_ITERATIONS)
        .with_progress_sink(TuiProgressSink())
        .with_memory(sessions_dir=sessions_dir, memory_dir=memory_dir)
        .with_tools(
            [
                FileReadTool(),
                FileWriteTool(),
                WebSearchTool(),
                WebFetchTool(),
                GlobTool(),
                GrepTool(),
                SmartEditTool(),
                ShellTool(),
            ]
        )
    )

    agent = builder.build()

    # MultiTaskTool needs the agent reference; add post-build to break
    # the construction-time circular dependency.
    multi = MultiTaskTool(agent)
    agent.tool_executor.add_tool(multi)

    return agent
