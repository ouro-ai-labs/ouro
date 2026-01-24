"""Quick integration test for SmartEditTool with Agent."""

import asyncio
import os
import tempfile
from pathlib import Path

import pytest

from agent.react_agent import ReActAgent
from config import Config
from llm import LiteLLMAdapter
from tools.file_ops import FileReadTool, FileWriteTool
from tools.smart_edit import SmartEditTool


def _has_api_key_for_model(model: str) -> bool:
    provider = model.split("/")[0] if model else ""
    if provider == "anthropic":
        return bool(os.getenv("ANTHROPIC_API_KEY"))
    if provider == "openai":
        return bool(os.getenv("OPENAI_API_KEY"))
    if provider in {"gemini", "google"}:
        return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    if provider == "ollama":
        return bool(os.getenv("OLLAMA_HOST"))
    return False


@pytest.mark.integration
def test_smart_edit_in_agent():
    """Test that SmartEditTool works when used by an agent."""
    if os.getenv("RUN_INTEGRATION_TESTS") != "1":
        pytest.skip("Set RUN_INTEGRATION_TESTS=1 to run live LLM integration tests")
    if not _has_api_key_for_model(Config.LITELLM_MODEL):
        pytest.skip(f"Missing API key (or server) for model: {Config.LITELLM_MODEL}")

    # Create a temporary test file
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".py") as f:
        f.write(
            """def calculate(x, y):
    result = x + y
    return result
"""
        )
        temp_path = f.name

    try:
        # Create minimal agent with just SmartEditTool
        llm = LiteLLMAdapter(
            model=Config.LITELLM_MODEL,
            api_base=Config.LITELLM_API_BASE,
            drop_params=Config.LITELLM_DROP_PARAMS,
            timeout=Config.LITELLM_TIMEOUT,
        )

        tools = [
            FileReadTool(),
            FileWriteTool(),
            SmartEditTool(),
        ]

        agent = ReActAgent(llm=llm, tools=tools, max_iterations=5)

        # Task: use smart_edit to add a comment
        task = f"""Use the smart_edit tool to add a comment '# computed sum' after 'result = x + y' in {temp_path}.

Use mode="diff_replace", old_code="result = x + y", new_code="result = x + y  # computed sum"."""

        print("Testing SmartEditTool integration...")
        print(f"Temp file: {temp_path}")
        print(f"Task: {task}")
        print("-" * 60)

        result = asyncio.run(agent.run(task))

        print("-" * 60)
        print(f"Agent result: {result}")

        # Verify the edit was made
        content = Path(temp_path).read_text()
        print(f"\nFile content after edit:\n{content}")

        assert "# computed sum" in content, "Edit was not applied!"
        print("\n✅ Integration test PASSED!")

    finally:
        # Cleanup
        Path(temp_path).unlink(missing_ok=True)
        Path(temp_path + ".bak").unlink(missing_ok=True)


if __name__ == "__main__":
    test_smart_edit_in_agent()
