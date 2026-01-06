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


def create_agent(mode: str = "react", enable_shell: bool = False):
    """Factory function to create agents with tools.

    Args:
        mode: Agent mode - 'react' or 'plan'
        enable_shell: Whether to enable shell command execution

    Returns:
        Configured agent instance
    """
    # Initialize tools
    tools = [
        FileReadTool(),
        FileWriteTool(),
        FileSearchTool(),
        CalculatorTool(),
        WebSearchTool(),
    ]

    if enable_shell:
        print("⚠️  Warning: Shell tool enabled - use with caution!")
        tools.append(ShellTool())

    # Create LLM instance with retry configuration
    llm = create_llm(
        provider=Config.LLM_PROVIDER,
        api_key=Config.get_api_key(),
        model=Config.get_default_model(),
        retry_config=Config.get_retry_config()
    )

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
    )


def main():
    """Main CLI entry point."""
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
        print(f"Configuration error: {e}")
        return

    # Get task from CLI or prompt user
    task = args.task
    if not task:
        print("Enter your task (press Enter twice to submit):")
        lines = []
        while True:
            line = input()
            if line == "" and lines:
                break
            lines.append(line)
        task = "\n".join(lines)

    if not task.strip():
        print("Error: No task provided")
        return

    # Create and run agent
    print(f"\n{'=' * 60}")
    print(f"LLM Provider: {Config.LLM_PROVIDER.upper()}")
    print(f"Model: {Config.get_default_model()}")
    print(f"Mode: {args.mode.upper()}")
    print(f"Task: {task}")
    print(f"{'=' * 60}")

    agent = create_agent(args.mode, args.enable_shell)
    result = agent.run(task)

    print(f"\n{'=' * 60}")
    print("FINAL ANSWER:")
    print(f"{'=' * 60}")
    print(result)


if __name__ == "__main__":
    main()
