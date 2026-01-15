"""Basic tests to verify core tools and imports work.

These tests are intentionally offline and should not require any API keys.
"""

import os


def test_imports():
    from agent.react_agent import ReActAgent  # noqa: F401
    from config import Config  # noqa: F401
    from tools.calculator import CalculatorTool  # noqa: F401
    from tools.file_ops import FileReadTool, FileWriteTool  # noqa: F401


def test_tools_execute_and_cleanup(tmp_path):
    from tools.calculator import CalculatorTool
    from tools.file_ops import FileReadTool, FileWriteTool

    calc = CalculatorTool()
    file_read = FileReadTool()
    file_write = FileWriteTool()

    result = calc.execute(code="print(2 + 2)")
    assert result.strip() == "4"

    test_file = tmp_path / "test_temp.txt"
    write_result = file_write.execute(file_path=str(test_file), content="Hello, Agent!")
    assert "Successfully wrote" in write_result

    read_result = file_read.execute(file_path=str(test_file))
    assert "Hello, Agent!" in read_result

    assert test_file.exists()
    os.remove(test_file)
    assert not test_file.exists()


def test_tool_schema_generation():
    from tools.calculator import CalculatorTool

    schema = CalculatorTool().to_anthropic_schema()
    assert "name" in schema
    assert "description" in schema
    assert "input_schema" in schema
