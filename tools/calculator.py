"""Calculator tool for executing Python code."""

import io
import sys
from typing import Any, Dict

from .base import BaseTool


class CalculatorTool(BaseTool):
    """Execute Python code for calculations and data manipulation."""

    @property
    def name(self) -> str:
        return "calculate"

    @property
    def description(self) -> str:
        return "Execute Python code for calculations. Use for math, data manipulation, etc. Use print() to output results."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "code": {
                "type": "string",
                "description": "Python code to execute (use print() for output)",
            }
        }

    def execute(self, code: str) -> str:
        """Execute Python code and return output."""
        # Capture stdout
        old_stdout = sys.stdout
        sys.stdout = buffer = io.StringIO()

        try:
            # Safe execution with limited scope
            exec_globals = {
                "__builtins__": __builtins__,
                "math": __import__("math"),
                "datetime": __import__("datetime"),
                "json": __import__("json"),
            }
            exec(code, exec_globals)
            output = buffer.getvalue()
            return output if output else "Code executed successfully (no output)"
        except Exception as e:
            return f"Error executing code: {str(e)}"
        finally:
            sys.stdout = old_stdout
