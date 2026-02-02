"""Main entry point for the agentic loop system."""

import argparse
import asyncio
import importlib.metadata
import warnings

from rich.console import Console

from agent.agent import LoopAgent
from config import Config
from interactive import run_interactive_mode, run_model_setup_mode
from llm import LiteLLMAdapter, ModelManager
from memory import MemoryManager
from tools.advanced_file_ops import EditTool, GlobTool, GrepTool
from tools.calculator import CalculatorTool
from tools.code_navigator import CodeNavigatorTool
from tools.explore import ExploreTool
from tools.file_ops import FileReadTool, FileSearchTool, FileWriteTool
from tools.notify import NotifyTool
from tools.parallel_execute import ParallelExecutionTool
from tools.shell import ShellTool
from tools.shell_background import BackgroundTaskManager, ShellTaskStatusTool
from tools.smart_edit import SmartEditTool
from tools.web_fetch import WebFetchTool
from tools.web_search import WebSearchTool
from utils import setup_logger, terminal_ui
from utils.runtime import ensure_runtime_dirs

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
        FileSearchTool(),
        CalculatorTool(),
        WebSearchTool(),
        WebFetchTool(),
        GlobTool(),
        GrepTool(),
        EditTool(),
        SmartEditTool(),
        CodeNavigatorTool(),
        ShellTool(task_manager=task_manager),
        ShellTaskStatusTool(task_manager=task_manager),
        NotifyTool(),
    ]

    # Initialize model manager
    model_manager = ModelManager()

    if not model_manager.is_configured():
        raise ValueError(
            "No models configured. Run `aloop` without --task and use /model edit, "
            "or edit `.aloop/models.yaml` to add at least one model and set `default`."
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
        raise ValueError("No model available. Please check `.aloop/models.yaml`.")

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


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="Run an AI agent with tool-calling capabilities")

    try:
        version = importlib.metadata.version("aloop")
    except importlib.metadata.PackageNotFoundError:
        version = "dev"
    parser.add_argument("--version", "-V", action="version", version=f"aloop {version}")

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
        help="Enable verbose logging to .aloop/logs/",
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

    args = parser.parse_args()

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
        agent = create_agent(model_id=args.model)
    except ValueError as e:
        if args.task:
            terminal_ui.print_error(str(e), title="Model Configuration Error")
            terminal_ui.console.print(
                "Edit `.aloop/models.yaml` to add models and set `default` (this file is gitignored). "
                "Tip: run `aloop` (interactive) and use /model edit."
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

        # Quiet mode: suppress all Rich UI output, print raw result only
        terminal_ui.console = Console(quiet=True)

        # Run agent
        result = await agent.run(task)

        print(result)

    asyncio.run(_run())


if __name__ == "__main__":
    main()
