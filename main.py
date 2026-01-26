"""Main entry point for the agentic loop system."""

import argparse
import asyncio
import warnings

from agent.react_agent import ReActAgent
from config import Config
from interactive import run_interactive_mode
from llm import LiteLLMAdapter
from tools.advanced_file_ops import EditTool, GlobTool, GrepTool
from tools.calculator import CalculatorTool
from tools.code_navigator import CodeNavigatorTool
from tools.explore import ExploreTool
from tools.file_ops import FileReadTool, FileSearchTool, FileWriteTool
from tools.parallel_execute import ParallelExecutionTool
from tools.shell import ShellTool
from tools.shell_background import BackgroundTaskManager, ShellTaskStatusTool
from tools.smart_edit import SmartEditTool
from tools.web_fetch import WebFetchTool
from tools.web_search import WebSearchTool
from utils import get_log_file_path, setup_logger, terminal_ui

warnings.filterwarnings("ignore", message="Pydantic serializer warnings.*", category=UserWarning)


def create_agent():
    """Factory function to create agents with tools.

    Returns:
        Configured ReActAgent instance with all tools
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
    ]

    # Create LLM instance with LiteLLM (retry config is read from Config directly)
    llm = LiteLLMAdapter(
        model=Config.LITELLM_MODEL,
        api_base=Config.LITELLM_API_BASE,
        drop_params=Config.LITELLM_DROP_PARAMS,
        timeout=Config.LITELLM_TIMEOUT,
    )

    agent = ReActAgent(
        llm=llm,
        tools=tools,
        max_iterations=Config.MAX_ITERATIONS,
    )

    # Add tools that require agent reference
    agent.tool_executor.add_tool(ExploreTool(agent))
    agent.tool_executor.add_tool(ParallelExecutionTool(agent))

    return agent


def main():
    """Main CLI entry point."""
    # Initialize logging
    setup_logger()

    parser = argparse.ArgumentParser(description="Run an AI agent with tool-calling capabilities")
    parser.add_argument(
        "--task",
        "-t",
        type=str,
        help="Task for the agent to complete (if not provided, enters interactive mode)",
    )

    args = parser.parse_args()

    # Validate config
    try:
        Config.validate()
    except ValueError as e:
        terminal_ui.print_error(str(e), title="Configuration Error")
        return

    # Create agent
    agent = create_agent()

    async def _run() -> None:
        # If no task provided, enter interactive mode (default behavior)
        if not args.task:
            await run_interactive_mode(agent)
            return

        # Single-turn mode: execute one task and exit
        task = args.task

        # Display header and config
        terminal_ui.print_header(
            "🤖 Agentic Loop System", subtitle="Intelligent AI Agent with Tool-Calling Capabilities"
        )

        config_dict = {
            "LLM Provider": (
                Config.LITELLM_MODEL.split("/")[0].upper()
                if "/" in Config.LITELLM_MODEL
                else "UNKNOWN"
            ),
            "Model": Config.LITELLM_MODEL,
            "Task": task if len(task) < 100 else task[:97] + "...",
        }
        terminal_ui.print_config(config_dict)

        # Run agent
        result = await agent.run(task)

        terminal_ui.print_final_answer(result)

        # Show log file location
        log_file = get_log_file_path()
        if log_file:
            terminal_ui.print_log_location(log_file)

    asyncio.run(_run())


if __name__ == "__main__":
    main()
