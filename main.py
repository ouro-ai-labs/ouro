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
from llm.chatgpt_auth import (
    get_all_auth_provider_statuses,
    get_supported_auth_providers,
    is_auth_status_logged_in,
    login_auth_provider,
    logout_auth_provider,
)
from llm.oauth_model_sync import remove_oauth_models, sync_oauth_models
from memory import MemoryManager
from tools.advanced_file_ops import GlobTool, GrepTool
from tools.explore import ExploreTool
from tools.file_ops import FileReadTool, FileWriteTool
from tools.parallel_execute import ParallelExecutionTool
from tools.shell import ShellTool
from tools.shell_background import BackgroundTaskManager, ShellTaskStatusTool
from tools.smart_edit import SmartEditTool
from tools.web_fetch import WebFetchTool
from tools.web_search import WebSearchTool
from utils import setup_logger, terminal_ui
from utils.runtime import ensure_runtime_dirs
from utils.tui.oauth_ui import pick_oauth_provider

warnings.filterwarnings("ignore", message="Pydantic serializer warnings.*", category=UserWarning)


def create_agent(model_id: str | None = None):
    """Factory function to create agents with tools.

    Args:
        model_id: Optional LiteLLM model ID to use (defaults to current/default)

    Returns:
        Configured LoopAgent instance with all tools
    """
    # Initialize background task manager (shared between shell tools)
    task_manager = BackgroundTaskManager.get_instance()

    # Initialize base tools
    tools = [
        FileReadTool(),
        FileWriteTool(),
        WebSearchTool(),
        WebFetchTool(),
        GlobTool(),
        GrepTool(),
        SmartEditTool(),
        ShellTool(task_manager=task_manager),
        ShellTaskStatusTool(task_manager=task_manager),
    ]

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
    )

    # Add tools that require agent reference
    agent.tool_executor.add_tool(ExploreTool(agent))
    agent.tool_executor.add_tool(ParallelExecutionTool(agent))

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


async def _pick_auth_provider_cli(mode: str) -> str | None:
    statuses = await get_all_auth_provider_statuses()
    providers: list[tuple[str, str]] = []

    for provider in get_supported_auth_providers():
        status = statuses.get(provider)
        is_logged_in = bool(status and is_auth_status_logged_in(status))
        label = "logged in" if is_logged_in else "not logged in"

        if mode == "logout" and not is_logged_in:
            continue

        providers.append((provider, label))

    if not providers:
        if mode == "logout":
            terminal_ui.print_info("No OAuth providers logged in. Use --login first.")
        else:
            terminal_ui.print_error("No OAuth providers available.", title="Login Error")
        return None

    title = (
        "Select OAuth Provider to Login" if mode == "login" else "Select OAuth Provider to Logout"
    )
    hint = "Use ↑/↓ and Enter to select, Esc to cancel."
    return await pick_oauth_provider(providers=providers, title=title, hint=hint)


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
        "--login",
        action="store_true",
        help="Login to OAuth provider",
    )
    parser.add_argument(
        "--logout",
        action="store_true",
        help="Logout from OAuth provider",
    )

    args = parser.parse_args()

    # Initialize runtime directories (create logs dir only in verbose mode)
    ensure_runtime_dirs(create_logs=args.verbose)

    # Initialize logging only in verbose mode
    if args.verbose:
        setup_logger()

    if args.login and args.logout:
        terminal_ui.print_error("Use only one of --login or --logout.", title="Invalid Arguments")
        return

    if args.login:
        provider = asyncio.run(_pick_auth_provider_cli(mode="login"))
        if not provider:
            return

        terminal_ui.print_info(f"Starting {provider} login flow... (Ctrl+C to cancel)")
        try:
            status = asyncio.run(login_auth_provider(provider))
        except KeyboardInterrupt:
            terminal_ui.print_warning("Login cancelled by user.")
            return
        except Exception as e:
            terminal_ui.print_error(str(e), title="Login Error")
            return

        model_manager = ModelManager()
        added = sync_oauth_models(model_manager, provider)

        terminal_ui.print_success(f"{provider} login completed.")
        terminal_ui.console.print(f"Auth file: {status.auth_file}")
        if status.account_id:
            terminal_ui.console.print(f"Account ID: {status.account_id}")
        if added:
            terminal_ui.console.print(
                f"Added {len(added)} {provider} models to `{model_manager.config_path}`."
            )
        terminal_ui.console.print("Use /model (interactive) to pick the active model.")
        return

    if args.logout:
        provider = asyncio.run(_pick_auth_provider_cli(mode="logout"))
        if not provider:
            return

        try:
            removed = asyncio.run(logout_auth_provider(provider))
        except KeyboardInterrupt:
            terminal_ui.print_warning("Logout cancelled by user.")
            return
        except Exception as e:
            terminal_ui.print_error(str(e), title="Logout Error")
            return

        model_manager = ModelManager()
        removed_models = remove_oauth_models(model_manager, provider)

        if removed:
            terminal_ui.print_success(f"Logged out from {provider}.")
        else:
            terminal_ui.print_info(f"No {provider} login state found.")

        if removed_models:
            terminal_ui.console.print(
                f"Removed {len(removed_models)} managed {provider} models from `{model_manager.config_path}`."
            )
        return

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
        agent = create_agent(model_id=args.model)
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
        agent = create_agent(model_id=args.model)

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

        skills_registry = SkillsRegistry()
        try:
            await skills_registry.load()
            # Inject skills section into agent's system prompt
            skills_section = render_skills_section(list(skills_registry.skills.values()))
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
