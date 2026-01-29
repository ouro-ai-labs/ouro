"""Example usage of ReAct Agent."""

import asyncio
import os
import sys

# Add parent directory to path to import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.react_agent import ReActAgent
from config import Config
from llm import LiteLLMAdapter
from tools.calculator import CalculatorTool
from tools.file_ops import FileReadTool, FileWriteTool
from tools.web_search import WebSearchTool


async def main():
    """Run ReAct Agent example."""
    print("=" * 60)
    print("ReAct Agent Example")
    print("=" * 60)

    # Validate configuration
    try:
        Config.validate()
    except ValueError as e:
        print(f"Error: {e}")
        print("Please configure .aloop/config (see README.md)")
        return

    llm = LiteLLMAdapter(
        model=Config.LITELLM_MODEL,
        api_base=Config.LITELLM_API_BASE,
        drop_params=Config.LITELLM_DROP_PARAMS,
        timeout=Config.LITELLM_TIMEOUT,
    )

    # Initialize agent with tools
    agent = ReActAgent(
        llm=llm,
        tools=[
            CalculatorTool(),
            FileReadTool(),
            FileWriteTool(),
            WebSearchTool(),
        ],
        max_iterations=10,
    )

    # Example 1: Simple calculation
    print("\n--- Example 1: Simple Calculation ---")
    result1 = await agent.run("What is 12345 multiplied by 67890?")
    print(f"\nResult: {result1}")

    # Example 2: File operations
    print("\n\n--- Example 2: File Operations ---")
    result2 = await agent.run(
        "Create a file called 'test_output.txt' with the content 'Hello from ReAct Agent!', "
        "then read it back to verify."
    )
    print(f"\nResult: {result2}")

    # Example 3: Web search
    print("\n\n--- Example 3: Web Search ---")
    result3 = await agent.run(
        "Search for 'Python agentic frameworks' and tell me the top 3 results"
    )
    print(f"\nResult: {result3}")

    print("\n" + "=" * 60)
    print("All examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
