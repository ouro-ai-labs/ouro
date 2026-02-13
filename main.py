"""Main entry point for the agentic loop system."""

import argparse
import asyncio
import importlib.metadata
import warnings

from rich.console import Console

from agent.agent import LoopAgent
from agent.skills import SkillsRegistry, render_skills_section
from config import Config
from interactive import run_interactive_mode, run_model_setup_mode
from llm import LiteLLMAdapter, ModelManager
from memory import MemoryManager
from roles import RoleManager
from tools.registry import AGENT_TOOL_NAMES, add_agent_tools, create_core_tools
from utils import setup_logger, terminal_ui
from utils.runtime import ensure_runtime_dirs

warnings.filterwarnings("ignore", message="Pydantic serializer warnings.*", category=UserWarning)


def create_agent(model_id: str | None = None, role_name: str | None = None):
    """Factory function to create agents with tools.

    Args:
        model_id: Optional LiteLLM model ID to use (defaults to current/default)
        role_name: Optional role name (defaults to "general")

    Returns:
        Configured LoopAgent instance with all tools
    """
    # Resolve role
    role_manager = RoleManager()
    role_name = role_name or "general"
    role = role_manager.get_role(role_name)
    if not role:
        available = ", ".join(role_manager.get_role_names())
        raise ValueError(f"Role '{role_name}' not found. Available: {available}")

    # Create tools filtered by role
    tool_names = role.tools  # None = all tools
    # Filter to only core tools when role specifies a whitelist
    core_tool_names = None
    if tool_names is not None:
        from tools.registry import CORE_TOOLS

        core_tool_names = [n for n in tool_names if n in CORE_TOOLS]
    tools = create_core_tools(names=core_tool_names)

    # Initialize model manager
    model_manager = ModelManager()

    if not model_manager.is_configured():
        raise ValueError(
            "No models configured. Run `ouro` without --task and use /model edit, "
            "or edit `.ouro/models.yaml` to add at least one model and set `default`."
        )

    # Get the model to use
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

    # Create LLM instance with the current profile
    llm = LiteLLMAdapter(
        model=current_profile.model_id,
        api_key=current_profile.api_key,
        api_base=current_profile.api_base,
        drop_params=current_profile.drop_params,
        timeout=current_profile.timeout,
    )

    agent = LoopAgent(
        llm=llm,
        tools=tools,
        max_iterations=Config.MAX_ITERATIONS,
        model_manager=model_manager,
        role=role,
    )

    # Add agent-reference tools (filtered by role)
    agent_tool_filter = None
    if tool_names is not None:
        agent_tool_filter = [n for n in tool_names if n in AGENT_TOOL_NAMES]
    add_agent_tools(agent, names=agent_tool_filter)

    return agent


async def _resolve_session_id(resume_arg: str) -> str:
    """Resolve --resume argument to a full session ID.

    Args:
        resume_arg: "latest" or a session ID / prefix

    Returns:
        Full session ID

    Raises:
        ValueError: If session cannot be found
    """
    if resume_arg == "latest":
        session_id = await MemoryManager.find_latest_session()
        if not session_id:
            raise ValueError("No sessions found to resume.")
        return session_id

    session_id = await MemoryManager.find_session_by_prefix(resume_arg)
    if not session_id:
        raise ValueError(f"Session '{resume_arg}' not found.")
    return session_id


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="Run an AI agent with tool-calling capabilities")

    try:
        version = importlib.metadata.version("ouro-ai")
    except importlib.metadata.PackageNotFoundError:
        version = "dev"
    parser.add_argument("--version", "-V", action="version", version=f"ouro {version}")

    parser.add_argument(
        "--task",
        "-t",
        type=str,
        help="Task for the agent to complete (if not provided, enters interactive mode)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging to .ouro/logs/",
    )
    parser.add_argument(
        "--model",
        "-m",
        type=str,
        help="Model to use (LiteLLM model ID, e.g. openai/gpt-4o)",
    )
    parser.add_argument(
        "--resume",
        "-r",
        nargs="?",
        const="latest",
        help="Resume a previous session (session ID prefix or 'latest')",
    )
    parser.add_argument(
        "--role",
        type=str,
        nargs="?",
        const="__list__",
        default=None,
        help="Agent role (e.g., searcher, debugger, coder). Omit value to list available roles.",
    )

    args = parser.parse_args()

    # --role without a value: list available roles and exit
    if args.role == "__list__":
        role_manager = RoleManager()
        terminal_ui.console.print("\n[bold]Available roles:[/bold]\n")
        for role in role_manager.list_roles():
            desc = f"  [dim]{role.description}[/dim]" if role.description else ""
            source = ""
            if role.source_path:
                source = f"  [dim italic]({role.source_path})[/dim italic]"
            terminal_ui.console.print(f"  [bold]{role.name}[/bold]{desc}{source}")
        terminal_ui.console.print()
        return

    # Initialize runtime directories (create logs dir only in verbose mode)
    ensure_runtime_dirs(create_logs=args.verbose)

    # Initialize logging only in verbose mode
    if args.verbose:
        setup_logger()

    # Validate config
    try:
        Config.validate()
    except ValueError as e:
        terminal_ui.print_error(str(e), title="Configuration Error")
        return

    # Resolve --resume session ID early (before agent creation) so we can fail fast
    resume_session_id = None
    if args.resume:
        try:
            resume_session_id = asyncio.run(_resolve_session_id(args.resume))
            terminal_ui.print_info(f"Resuming session: {resume_session_id}")
        except ValueError as e:
            terminal_ui.print_error(str(e), title="Resume Error")
            return

    # Create agent with optional model selection. If we're going into interactive mode and
    # models aren't configured yet, enter a setup session first.
    try:
        agent = create_agent(model_id=args.model, role_name=args.role)
    except ValueError as e:
        if args.task:
            terminal_ui.print_error(str(e), title="Model Configuration Error")
            terminal_ui.console.print(
                "Edit `.ouro/models.yaml` to add models and set `default` (this file is gitignored). "
                "Tip: run `ouro` (interactive) and use /model edit."
            )
            return

        terminal_ui.print_error(str(e), title="Model Setup Required")
        ready = asyncio.run(run_model_setup_mode())
        if not ready:
            return

        # Retry after setup.
        agent = create_agent(model_id=args.model, role_name=args.role)

    async def _run() -> None:
        # Load resumed session if requested
        if resume_session_id:
            await agent.load_session(resume_session_id)

        # If no task provided, enter interactive mode (default behavior)
        if not args.task:
            await run_interactive_mode(agent)
            return

        # Single-turn mode: execute one task and exit
        task = args.task

        # Load skills if the role allows it
        role = agent.role
        if role is None or role.skills.enabled:
            skills_registry = SkillsRegistry()
            try:
                await skills_registry.load()

                # Filter to allowed skills if role specifies a whitelist
                skills_list = list(skills_registry.skills.values())
                if role and role.skills.allowed is not None:
                    allowed = set(role.skills.allowed)
                    skills_list = [s for s in skills_list if s.name in allowed]

                skills_section = render_skills_section(skills_list)
                agent.set_skills_section(skills_section)
                # Resolve explicit skill/command invocations
                resolved = await skills_registry.resolve_user_input(task)
                task = resolved.rendered
            except Exception as e:
                terminal_ui.print_warning(f"Failed to load skills registry: {e}")

        # Quiet mode: suppress all Rich UI output, print raw result only
        terminal_ui.console = Console(quiet=True)

        # Run agent
        result = await agent.run(task)

        print(result)

    asyncio.run(_run())


if __name__ == "__main__":
    main()
