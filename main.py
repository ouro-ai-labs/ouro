"""Main entry point for the agentic loop system."""
import argparse

from config import Config
from llm import create_llm
from agent.react_agent import ReActAgent
from agent.plan_execute_agent import PlanExecuteAgent
from tools.file_ops import FileReadTool, FileWriteTool, FileSearchTool
from tools.calculator import CalculatorTool
from tools.shell import ShellTool
from tools.web_search import WebSearchTool
from tools.advanced_file_ops import GlobTool, GrepTool, EditTool
from tools.todo import TodoTool
from agent.todo import TodoList
from utils import setup_logger, get_log_file_path, terminal_ui


def create_agent(mode: str = "react", enable_shell: bool = False):
    """Factory function to create agents with tools.

    Args:
        mode: Agent mode - 'react' or 'plan'
        enable_shell: Whether to enable shell command execution

    Returns:
        Configured agent instance
    """
    # Initialize base tools
    tools = [
        FileReadTool(),
        FileWriteTool(),
        FileSearchTool(),
        CalculatorTool(),
        WebSearchTool(),
    ]

    # Add advanced file operation tools if enabled
    if Config.ENABLE_ADVANCED_TOOLS:
        tools.extend([
            GlobTool(),
            GrepTool(),
            EditTool(),
        ])
        terminal_ui.print_success("Advanced file tools enabled (Glob, Grep, Edit)")

    if enable_shell or Config.ENABLE_SHELL:
        terminal_ui.print_warning("Shell tool enabled - use with caution!")
        tools.append(ShellTool())

    # Create LLM instance with retry configuration and base_url
    llm = create_llm(
        provider=Config.LLM_PROVIDER,
        api_key=Config.get_api_key(),
        model=Config.get_default_model(),
        retry_config=Config.get_retry_config(),
        base_url=Config.get_base_url()
    )

    # Phase 2: Create model router for cost optimization
    model_router = None
    if Config.ENABLE_MODEL_ROUTING:
        from llm.model_router import ModelRouter
        tier_config = Config.get_model_tier_config()
        model_router = ModelRouter(tier_config, enable_routing=True)
        terminal_ui.print_success(f"Smart model routing enabled (Phase 2 Cost Optimization)")
        terminal_ui.console.print(f"  [dim]Light: {tier_config.light_model}[/dim]")
        terminal_ui.console.print(f"  [dim]Medium: {tier_config.medium_model}[/dim]")
        terminal_ui.console.print(f"  [dim]Heavy: {tier_config.heavy_model}[/dim]")

    # Create agent based on mode
    if mode == "react":
        agent_class = ReActAgent
    elif mode == "plan":
        agent_class = PlanExecuteAgent
    else:
        raise ValueError(f"Unknown mode: {mode}")

    return agent_class(
        llm=llm,
        max_iterations=Config.MAX_ITERATIONS,
        tools=tools,
        enable_todo=Config.ENABLE_TODO_SYSTEM,
        model_router=model_router,
    )


def main():
    """Main CLI entry point."""
    # Initialize logging
    setup_logger()

    parser = argparse.ArgumentParser(
        description="Run an AI agent with tool-calling capabilities"
    )
    parser.add_argument(
        "--mode",
        choices=["react", "plan"],
        default="react",
        help="Agent mode: 'react' for ReAct loop, 'plan' for Plan-and-Execute",
    )
    parser.add_argument("--task", type=str, help="Task for the agent to complete")
    parser.add_argument(
        "--enable-shell",
        action="store_true",
        help="Enable shell command execution (use with caution)",
    )

    args = parser.parse_args()

    # Validate config
    try:
        Config.validate()
    except ValueError as e:
        terminal_ui.print_error(str(e), title="Configuration Error")
        return

    # Get task from CLI or prompt user
    task = args.task
    if not task:
        terminal_ui.console.print("[bold cyan]Enter your task (press Enter twice to submit):[/bold cyan]")
        lines = []
        while True:
            line = input()
            if line == "" and lines:
                break
            lines.append(line)
        task = "\n".join(lines)

    if not task.strip():
        terminal_ui.print_error("No task provided")
        return

    # Create and run agent
    terminal_ui.print_header(
        "🤖 Agentic Loop System",
        subtitle="Intelligent AI Agent with Tool-Calling Capabilities"
    )

    # Display configuration
    config_dict = {
        "LLM Provider": Config.LLM_PROVIDER.upper(),
        "Model": Config.get_default_model(),
        "Mode": args.mode.upper(),
        "Task": task if len(task) < 100 else task[:97] + "..."
    }
    terminal_ui.print_config(config_dict)

    agent = create_agent(args.mode, args.enable_shell)
    result = agent.run(task, enable_context=Config.ENABLE_CONTEXT_INJECTION)

    terminal_ui.print_final_answer(result)

    # Show log file location
    log_file = get_log_file_path()
    if log_file:
        terminal_ui.print_log_location(log_file)


if __name__ == "__main__":
    main()
