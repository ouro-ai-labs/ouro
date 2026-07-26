"""Agent factory for the CLI / TUI / bot entry points.

Builds a `ComposedAgent` from `~/.ouro/models.yaml` config + the standard
builtin tool set + a TUI-backed `ProgressSink`. Used by:

- `ouro/interfaces/cli/main.py` (one-shot --task and interactive modes)
- `ouro/interfaces/bot/server.py` (per-conversation agent factory)
"""

from __future__ import annotations

from ouro.capabilities import AgentBuilder, ComposedAgent
from ouro.capabilities.sandbox import SandboxManager
from ouro.capabilities.sandbox.adapters import create_sandbox_session
from ouro.capabilities.tools.builtins.advanced_file_ops import GlobTool, GrepTool
from ouro.capabilities.tools.builtins.conversation_search import ConversationSearchTool
from ouro.capabilities.tools.builtins.file_ops import FileReadTool, FileWriteTool
from ouro.capabilities.tools.builtins.memory_block_edit import MemoryBlockEditTool
from ouro.capabilities.tools.builtins.multi_task import MultiTaskTool
from ouro.capabilities.tools.builtins.sandbox import create_sandbox_tools
from ouro.capabilities.tools.builtins.shell import ShellTool
from ouro.capabilities.tools.builtins.smart_edit import SmartEditTool
from ouro.capabilities.tools.builtins.web_fetch import WebFetchTool
from ouro.capabilities.tools.builtins.web_search import WebSearchTool
from ouro.config import Config
from ouro.core.llm import ModelManager, create_llm_adapter
from ouro.core.tracing import Tracer
from ouro.interfaces.tui import terminal_ui
from ouro.interfaces.tui.json_progress import JsonProgressSink
from ouro.interfaces.tui.tui_progress import TuiProgressSink


def _base_tools(*, sandbox_enabled: bool, memory_dir: str | None):
    if sandbox_enabled:
        # Sandbox mode is sandbox-only for filesystem/search/command tools.
        # Keep host-independent agent capabilities (web + memory search), but do
        # not expose host shell/read/write/edit/glob/grep.
        return [
            WebSearchTool(),
            WebFetchTool(),
            ConversationSearchTool(memory_dir=memory_dir),
        ]
    return [
        FileReadTool(),
        FileWriteTool(),
        WebSearchTool(),
        WebFetchTool(),
        GlobTool(),
        GrepTool(),
        SmartEditTool(),
        ShellTool(attribution_enabled=Config.ATTRIBUTION_ENABLED),
        ConversationSearchTool(memory_dir=memory_dir),
    ]


def create_agent(
    model_id: str | None = None,
    sessions_dir: str | None = None,
    memory_dir: str | None = None,
    progress_format: str = "tui",
    progress_stream=None,
    tracer: Tracer | None = None,
    sandbox_id: str | None = None,
    sandbox_enabled: bool = False,
) -> ComposedAgent:
    """Factory function to create a fully wired ComposedAgent.

    Args:
        model_id: Optional LiteLLM model ID (defaults to current/default).
        sessions_dir: Optional custom sessions directory (bot-mode isolation).
        memory_dir: Optional custom long-term memory directory (bot-mode isolation).
        tracer: Optional tracer for run/LLM/tool instrumentation.

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

    llm = create_llm_adapter(
        model=current_profile.model_id,
        api_key=current_profile.api_key,
        api_base=current_profile.api_base,
        drop_params=current_profile.drop_params,
        timeout=current_profile.timeout,
    )

    progress_sink = (
        JsonProgressSink(stream=progress_stream) if progress_format == "json" else TuiProgressSink()
    )
    tools = _base_tools(sandbox_enabled=sandbox_enabled, memory_dir=memory_dir)

    if sandbox_enabled:
        sandbox_manager = SandboxManager()
        if sandbox_id:
            sandbox_profile = sandbox_manager.get_sandbox(sandbox_id)
            if sandbox_profile is None:
                available = ", ".join(sandbox_manager.get_sandbox_ids())
                raise ValueError(
                    f"Sandbox '{sandbox_id}' not found."
                    + (
                        f" Available: {available}"
                        if available
                        else " Add one to ~/.ouro/sandboxes.yaml."
                    )
                )
            sandbox_manager.switch_sandbox(sandbox_id)
        else:
            sandbox_profile = sandbox_manager.get_current_sandbox()
        if sandbox_profile is None:
            raise ValueError("No sandbox configured. Edit ~/.ouro/sandboxes.yaml.")
        is_valid_sandbox, sandbox_error = sandbox_manager.validate_sandbox(sandbox_profile)
        if not is_valid_sandbox:
            raise ValueError(sandbox_error)
        sandbox_session = create_sandbox_session(sandbox_profile)
        tools.extend(create_sandbox_tools(sandbox_session))

    builder = (
        AgentBuilder()
        .with_llm(llm, model_manager=model_manager)
        .with_max_iterations(Config.MAX_ITERATIONS)
        .with_progress_sink(progress_sink)
        .with_tracer(tracer)
        .with_progress_identity(
            agent_id="root",
            root_agent_id="root",
            role="root",
        )
        .with_memory(sessions_dir=sessions_dir, memory_dir=memory_dir)
        .with_tools(tools)
    )

    if sandbox_enabled:
        # The default read-before-write rule checks host filesystem paths. In
        # sandbox mode, the same tool names are backed by a remote sandbox, so
        # keep the host-aware rule out of the sandbox tool path.
        builder = builder.without_read_before_write()

    # Agent Swarm / Task V2: persistent task store + multi-agent coordination.
    # When enabled, replaces TodoTool and MultiTaskTool with task_create,
    # task_claim, task_update, task_list, task_get, task_delete tools.
    if Config.ENABLE_AGENT_SWARM:
        builder = builder.with_agent_swarm(enabled=True)

    agent = builder.build()

    # MultiTaskTool is only added when Agent Swarm is disabled (legacy mode).
    if not Config.ENABLE_AGENT_SWARM:
        multi = MultiTaskTool(agent)
        agent.tool_executor.add_tool(multi)

    # MemoryBlockEditTool needs the MemoryBlockManager owned by MemoryManager;
    # add post-build for the same reason.
    if agent.memory is not None:
        from ouro.capabilities.memory.blocks import MemoryBlockManager

        ltm = agent.memory.long_term
        if isinstance(ltm, MemoryBlockManager):
            agent.tool_executor.add_tool(MemoryBlockEditTool(ltm))

    return agent
