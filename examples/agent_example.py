"""Example usage of ComposedAgent via AgentBuilder."""

import asyncio
import os
import sys

# Add parent directory to path to import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ouro.capabilities import AgentBuilder
from ouro.capabilities.tools.builtins.file_ops import FileReadTool, FileWriteTool
from ouro.capabilities.tools.builtins.shell import ShellTool
from ouro.capabilities.tools.builtins.web_search import WebSearchTool
from ouro.core.llm import LiteLLMAdapter, ModelManager


async def main():
    """Run ComposedAgent example."""
    print("=" * 60)
    print("ComposedAgent Example")
    print("=" * 60)

    mm = ModelManager()
    profile = mm.get_current_model()
    if not profile:
        print("No models configured. Edit .ouro/models.yaml and set `default`.")
        return

    llm = LiteLLMAdapter(
        model=profile.model_id,
        api_key=profile.api_key,
        api_base=profile.api_base,
        drop_params=profile.drop_params,
        timeout=profile.timeout,
    )

    # Build a memoryless agent for the example.
    agent = (
        AgentBuilder()
        .with_llm(llm, model_manager=mm)
        .with_max_iterations(10)
        .without_memory()
        .with_tools(
            [
                FileReadTool(),
                FileWriteTool(),
                ShellTool(),
                WebSearchTool(),
            ]
        )
        .build()
    )

    # Example 1: Simple calculation using shell
    print("\n--- Example 1: Simple Calculation ---")
    result1 = await agent.run("What is 12345 multiplied by 67890? Use python to calculate.")
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
