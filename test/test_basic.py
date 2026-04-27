"""Basic tests to verify core tools and imports work.

These tests are intentionally offline and should not require any API keys.
"""

import os


async def test_imports():
    from ouro.capabilities import AgentBuilder, ComposedAgent  # noqa: F401
    from ouro.capabilities.tools.builtins.file_ops import FileReadTool, FileWriteTool  # noqa: F401
    from ouro.config import Config  # noqa: F401
    from ouro.core import Agent, Hook, ToolRegistry  # noqa: F401


async def test_tools_execute_and_cleanup(tmp_path):
    from ouro.capabilities.tools.builtins.file_ops import FileReadTool, FileWriteTool

    file_read = FileReadTool()
    file_write = FileWriteTool()

    test_file = tmp_path / "test_temp.txt"
    write_result = await file_write.execute(file_path=str(test_file), content="Hello, Agent!")
    assert "Successfully wrote" in write_result

    read_result = await file_read.execute(file_path=str(test_file))
    assert "Hello, Agent!" in read_result

    assert test_file.exists()
    os.remove(test_file)
    assert not test_file.exists()
