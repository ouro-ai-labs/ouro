"""Quick integration test for SmartEditTool with Agent."""

import asyncio
import os
import tempfile
from pathlib import Path

import pytest

from ouro.capabilities import AgentBuilder
from ouro.capabilities.tools.builtins.file_ops import FileReadTool, FileWriteTool
from ouro.capabilities.tools.builtins.smart_edit import SmartEditTool
from ouro.core.llm import LiteLLMAdapter, ModelManager


@pytest.mark.integration
def test_smart_edit_in_agent():
    """Test that SmartEditTool works when used by an agent."""
    if os.getenv("RUN_INTEGRATION_TESTS") != "1":
        pytest.skip("Set RUN_INTEGRATION_TESTS=1 to run live LLM integration tests")

    mm = ModelManager()
    profile = mm.get_current_model()
    if not profile:
        pytest.skip("No models configured. Edit .ouro/models.yaml and set `default`.")

    is_valid, error_msg = mm.validate_model(profile)
    if not is_valid:
        pytest.skip(error_msg)

    if profile.provider == "ollama" and not profile.api_base:
        pytest.skip(
            "Ollama model requires api_base in .ouro/models.yaml (e.g. http://localhost:11434)"
        )

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
            model=profile.model_id,
            api_key=profile.api_key,
            api_base=profile.api_base,
            drop_params=profile.drop_params,
            timeout=profile.timeout,
        )

        agent = (
            AgentBuilder()
            .with_llm(llm, model_manager=mm)
            .with_max_iterations(5)
            .without_memory()
            .with_tools([FileReadTool(), FileWriteTool(), SmartEditTool()])
            .build()
        )

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
