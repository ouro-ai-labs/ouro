"""Example usage of WebFetchTool with ReAct Agent."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.react_agent import ReActAgent
from config import Config
from llm import LiteLLMAdapter
from tools.web_fetch import WebFetchTool


async def main():
    """Run WebFetchTool examples."""
    print("=" * 60)
    print("WebFetchTool Example")
    print("=" * 60)

    try:
        Config.validate()
    except ValueError as exc:
        print(f"Error: {exc}")
        print("Please set your API key in .aloop/config")
        return

    llm = LiteLLMAdapter(
        model=Config.LITELLM_MODEL,
        api_base=Config.LITELLM_API_BASE,
        drop_params=Config.LITELLM_DROP_PARAMS,
        timeout=Config.LITELLM_TIMEOUT,
    )

    agent = ReActAgent(
        llm=llm,
        tools=[WebFetchTool()],
        max_iterations=8,
    )

    print("\n--- Example 1: Fetch web page (raw tool output) ---")
    result1 = await agent.run(
        "Use the web_fetch tool to fetch https://github.com/luohaha/agentic-loop in markdown format with a 20s timeout. "
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
