"""Main entry point for the agentic loop system."""

import argparse
import asyncio
import warnings
from typing import List, Union

from agent.plan_execute_agent import PlanExecuteAgent
from agent.react_agent import ReActAgent
from agent.runtime import AgentRuntime, RuntimeConfig
from config import Config
from interactive import run_interactive_mode
from llm import LiteLLMAdapter
from tools.advanced_file_ops import EditTool, GlobTool, GrepTool
from tools.base import BaseTool
from tools.calculator import CalculatorTool
from tools.code_navigator import CodeNavigatorTool
from tools.delegation import DelegationTool
from tools.file_ops import FileReadTool, FileSearchTool, FileWriteTool
from tools.shell import ShellTool
from tools.shell_background import BackgroundTaskManager, ShellTaskStatusTool
from tools.smart_edit import SmartEditTool
from tools.web_fetch import WebFetchTool
from tools.web_search import WebSearchTool
from utils import get_log_file_path, setup_logger, terminal_ui

warnings.filterwarnings("ignore", message="Pydantic serializer warnings.*", category=UserWarning)


def create_tools() -> List[BaseTool]:
    """Create the standard set of tools.

    Returns:
        List of tool instances
    """
    # Initialize background task manager (shared between shell tools)
    task_manager = BackgroundTaskManager.get_instance()

    return [
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


def create_llm() -> LiteLLMAdapter:
    """Create the LLM adapter with configured settings.

    Returns:
        Configured LiteLLMAdapter instance
    """
    return LiteLLMAdapter(
        model=Config.LITELLM_MODEL,
        api_base=Config.LITELLM_API_BASE,
        drop_params=Config.LITELLM_DROP_PARAMS,
        timeout=Config.LITELLM_TIMEOUT,
    )


def create_agent(mode: str = "react") -> Union[ReActAgent, PlanExecuteAgent]:
    """Factory function to create agents with tools.

    Args:
        mode: Agent mode - 'react' or 'plan'

    Returns:
        Configured agent instance
    """
    tools = create_tools()
    llm = create_llm()

    # Create agent based on mode
    if mode == "react":
        agent_class = ReActAgent
    elif mode == "plan":
        agent_class = PlanExecuteAgent
    else:
        raise ValueError(f"Unknown mode: {mode}")

    agent = agent_class(
        llm=llm,
        tools=tools,
    )

    # Add delegation tool (requires agent instance)
    delegation_tool = DelegationTool(agent)
    agent.tool_executor.add_tool(delegation_tool)

    return agent


def create_runtime(config: RuntimeConfig = None) -> AgentRuntime:
    """Factory function to create an AgentRuntime.

    Args:
        config: Optional runtime configuration

    Returns:
        Configured AgentRuntime instance
    """
    tools = create_tools()
    llm = create_llm()

    return AgentRuntime(
        llm=llm,
        tools=tools,
        config=config or RuntimeConfig(),
    )


def main():
    """Main CLI entry point."""
    # Initialize logging
    setup_logger()

    parser = argparse.ArgumentParser(description="Run an AI agent with tool-calling capabilities")
    parser.add_argument(
        "--mode",
        "-m",
        choices=["react", "plan", "compose"],
        default="react",
        help="Agent mode: 'react' for ReAct loop, 'plan' for Plan-and-Execute, 'compose' for auto-composition",
    )
    parser.add_argument(
        "--task",
        "-t",
        type=str,
        help="Task for the agent to complete (if not provided, enters interactive mode)",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=5,
        help="Maximum agent nesting depth for compose mode (default: 5)",
    )
    parser.add_argument(
        "--max-agents",
        type=int,
        default=10,
        help="Maximum total agents per task for compose mode (default: 10)",
    )

    args = parser.parse_args()

    # Validate config
    try:
        Config.validate()
    except ValueError as e:
        terminal_ui.print_error(str(e), title="Configuration Error")
        return

    # Create agent or runtime based on mode
    if args.mode == "compose":
        runtime_config = RuntimeConfig(
            max_depth=args.max_depth,
            max_agents=args.max_agents,
        )
        runtime = create_runtime(runtime_config)
        agent = None
    else:
        agent = create_agent(args.mode)
        runtime = None

    async def _run() -> None:
        # If no task provided, enter interactive mode (default behavior)
        if not args.task:
            if agent:
                await run_interactive_mode(agent, args.mode)
            else:
                # For compose mode, create a react agent with composition enabled
                react_agent = create_agent("react")
                await run_interactive_mode(react_agent, args.mode, use_composition=True)
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
            "Mode": args.mode.upper(),
            "Task": task if len(task) < 100 else task[:97] + "...",
        }
        if args.mode == "compose":
            config_dict["Max Depth"] = args.max_depth
            config_dict["Max Agents"] = args.max_agents
        terminal_ui.print_config(config_dict)

        # Run agent or runtime
        if runtime:
            result = await runtime.run(task)
        else:
            result = await agent.run(task)

        terminal_ui.print_final_answer(result)

        # Show log file location
        log_file = get_log_file_path()
        if log_file:
            terminal_ui.print_log_location(log_file)

    asyncio.run(_run())


if __name__ == "__main__":
    main()
