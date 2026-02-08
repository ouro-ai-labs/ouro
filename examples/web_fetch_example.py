"""Example usage of WebFetchTool with LoopAgent."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.agent import LoopAgent
from llm import LiteLLMAdapter, ModelManager
from tools.web_fetch import WebFetchTool


async def main():
    """Run WebFetchTool examples."""
    print("=" * 60)
    print("WebFetchTool Example")
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

    agent = LoopAgent(
        llm=llm,
        tools=[WebFetchTool()],
        max_iterations=8,
    )

    print("\n--- Example 1: Fetch web page (raw tool output) ---")
    result1 = await agent.run(
        "Use the web_fetch tool to fetch https://github.com/ouro-ai-labs/ouro in markdown format with a 20s timeout. "
        "Return the raw tool output JSON without extra commentary."
    )
    print(f"\nResult:\n{result1}")

    print("\n--- Example 2: Invalid URL error ---")
    result2 = await agent.run(
        "Call web_fetch with url 'example.com' and return the raw tool output JSON only."
    )
    print(f"\nResult:\n{result2}")

    print("\n" + "=" * 60)
    print("All examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
