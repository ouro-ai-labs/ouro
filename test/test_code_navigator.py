"""Tests for CodeNavigatorTool."""

import pytest

from tools.code_navigator import (
    HAS_TREE_SITTER,
    CodeNavigatorTool,
    detect_language,
    get_supported_languages,
)


@pytest.fixture
def sample_python_files(tmp_path):
    """Create sample Python files for testing."""
    # File 1: base.py with class and functions
    base_file = tmp_path / "base.py"
    base_file.write_text(
        '''"""Base module."""
import os
from typing import List, Dict

class BaseAgent:
    """Base class for all agents."""

    def __init__(self, name: str):
        """Initialize agent."""
        self.name = name

    def run(self, task: str) -> str:
        """Execute task."""
        return self._process(task)

    def _process(self, task: str) -> str:
        """Internal processing."""
        result = transform_task(task)
        return result

def transform_task(task: str) -> str:
    """Transform task input."""
    return task.upper()

def helper_function(x, y):
    """Helper for calculations."""
    return x + y
'''
    )

    # File 2: agent.py with subclass
    agent_file = tmp_path / "agent.py"
    agent_file.write_text(
        '''"""Agent implementation."""
from base import BaseAgent, transform_task

class ReActAgent(BaseAgent):
    """ReAct agent implementation."""

    def __init__(self, name: str, max_iter: int = 10):
        super().__init__(name)
        self.max_iter = max_iter

    def run(self, task: str) -> str:
        """Run ReAct loop."""
        processed = transform_task(task)
        return self._execute(processed)

    def _execute(self, task: str) -> str:
        """Execute with iterations."""
        return task
'''
    )

    # File 3: utils.py with utility functions
    utils_file = tmp_path / "utils.py"
    utils_file.write_text(
        '''"""Utility functions."""

def transform_task(text: str) -> str:
    """Transform text."""
    return text.lower()

def calculate(a: int, b: int) -> int:
    """Calculate sum."""
    return a + b
'''
    )

    return tmp_path


@pytest.fixture
def tool():
    """Create CodeNavigatorTool instance."""
    return CodeNavigatorTool()


class TestFindFunction:
    """Test find_function functionality."""

    async def test_find_single_function(self, tool, sample_python_files):
        """Test finding a function that exists once."""
        result = await tool.execute(
            target="helper_function", search_type="find_function", path=str(sample_python_files)
        )

        assert "helper_function" in result
        assert "base.py" in result
        assert "def helper_function(x, y)" in result
        assert "Helper for calculations" in result

    async def test_find_multiple_functions(self, tool, sample_python_files):
        """Test finding a function that exists in multiple files."""
        result = await tool.execute(
            target="transform_task", search_type="find_function", path=str(sample_python_files)
        )

        assert "Found 2 function(s)" in result
        assert "base.py" in result
        assert "utils.py" in result

    async def test_function_not_found(self, tool, sample_python_files):
        """Test searching for non-existent function."""
        result = await tool.execute(
            target="nonexistent_function",
            search_type="find_function",
            path=str(sample_python_files),
        )

        assert "No function named" in result
        assert "nonexistent_function" in result

    async def test_function_with_type_hints(self, tool, sample_python_files):
        """Test that type hints are captured in signature."""
        result = await tool.execute(
            target="run", search_type="find_function", path=str(sample_python_files)
        )

        assert "task: str" in result
        assert "-> str" in result


class TestFindClass:
    """Test find_class functionality."""

    async def test_find_class(self, tool, sample_python_files):
        """Test finding a class."""
        result = await tool.execute(
            target="BaseAgent", search_type="find_class", path=str(sample_python_files)
        )

        assert "BaseAgent" in result
        assert "base.py" in result
        assert "Methods" in result
        assert "__init__" in result
        assert "run" in result
        assert "_process" in result

    async def test_find_subclass(self, tool, sample_python_files):
        """Test finding a subclass shows inheritance."""
        result = await tool.execute(
            target="ReActAgent", search_type="find_class", path=str(sample_python_files)
        )

        assert "ReActAgent" in result
        assert "BaseAgent" in result  # Should show base class
        assert "agent.py" in result

    async def test_class_not_found(self, tool, sample_python_files):
        """Test searching for non-existent class."""
        result = await tool.execute(
            target="NonExistentClass", search_type="find_class", path=str(sample_python_files)
        )

        assert "No class named" in result


class TestShowStructure:
    """Test show_structure functionality."""

    async def test_show_structure(self, tool, sample_python_files):
        """Test showing file structure."""
        base_file = sample_python_files / "base.py"
        result = await tool.execute(target=str(base_file), search_type="show_structure")

        # Check for imports section
        assert "IMPORTS" in result
        assert "import os" in result
        assert "from typing import" in result

        # Check for classes section
        assert "CLASSES" in result
        assert "BaseAgent" in result

        # Check for functions section
        assert "FUNCTIONS" in result
        assert "transform_task" in result
        assert "helper_function" in result

    async def test_show_structure_nonexistent_file(self, tool):
        """Test show_structure on non-existent file."""
        result = await tool.execute(target="/nonexistent/file.py", search_type="show_structure")

        assert "Error" in result
        assert "does not exist" in result

    async def test_show_structure_with_line_numbers(self, tool, sample_python_files):
        """Test that line numbers are included."""
        base_file = sample_python_files / "base.py"
        result = await tool.execute(target=str(base_file), search_type="show_structure")

        assert "Line" in result


class TestFindUsages:
    """Test find_usages functionality."""

    async def test_find_function_usages(self, tool, sample_python_files):
        """Test finding where a function is called."""
        result = await tool.execute(
            target="transform_task", search_type="find_usages", path=str(sample_python_files)
        )

        assert "transform_task" in result
        # Should find usages in both base.py and agent.py
        assert "usage" in result.lower()

    async def test_find_class_usages(self, tool, sample_python_files):
        """Test finding where a class is used."""
        result = await tool.execute(
            target="BaseAgent", search_type="find_usages", path=str(sample_python_files)
        )

        # Should find import and inheritance
        assert "BaseAgent" in result

    async def test_usages_not_found(self, tool, sample_python_files):
        """Test finding usages of something not used."""
        result = await tool.execute(
            target="never_used_function", search_type="find_usages", path=str(sample_python_files)
        )

        assert "No usages" in result


class TestErrorHandling:
    """Test error handling."""

    async def test_invalid_search_type(self, tool, sample_python_files):
        """Test invalid search type."""
        result = await tool.execute(
            target="something", search_type="invalid_type", path=str(sample_python_files)
        )

        assert "Error" in result
        assert "Unknown search_type" in result

    async def test_invalid_path(self, tool):
        """Test with invalid path."""
        result = await tool.execute(
            target="something", search_type="find_function", path="/nonexistent/path"
        )

        assert "Error" in result
        assert "does not exist" in result


class TestPerformance:
    """Test performance characteristics."""

    async def test_handles_syntax_errors_gracefully(self, tool, tmp_path):
        """Test that files with syntax errors are skipped."""
        # Create a file with syntax error
        bad_file = tmp_path / "bad.py"
        bad_file.write_text("def broken(\n  # Missing closing parenthesis")

        # Create a good file
        good_file = tmp_path / "good.py"
        good_file.write_text("def working():\n    pass")

        # Should still find the working function
        result = await tool.execute(
            target="working", search_type="find_function", path=str(tmp_path)
        )

        assert "working" in result
        assert "good.py" in result

    async def test_large_number_of_files(self, tool, tmp_path):
        """Test handling many files."""
        # Create 20 files with functions
        for i in range(20):
            file = tmp_path / f"file_{i}.py"
            file.write_text(f"def function_{i}():\n    pass")

        # Should find all functions quickly
        result = await tool.execute(
            target="function_10", search_type="find_function", path=str(tmp_path)
        )

        assert "function_10" in result


class TestRealWorldScenarios:
    """Test with real-world scenarios."""

    async def test_find_init_method(self, tool, sample_python_files):
        """Test finding __init__ methods."""
        result = await tool.execute(
            target="__init__", search_type="find_function", path=str(sample_python_files)
        )

        assert "__init__" in result
        assert "Found 2 function(s)" in result  # BaseAgent and ReActAgent

    async def test_private_methods(self, tool, sample_python_files):
        """Test finding private methods."""
        result = await tool.execute(
            target="_process", search_type="find_function", path=str(sample_python_files)
        )

        assert "_process" in result
        assert "BaseAgent" in result or "base.py" in result


class TestLanguageDetection:
    """Test language detection functionality."""

    async def test_python_extension(self, tmp_path):
        """Test Python file detection."""
        from pathlib import Path

        assert detect_language(Path("test.py")) == "python"

    async def test_javascript_extensions(self, tmp_path):
        """Test JavaScript file detection."""
        from pathlib import Path

        assert detect_language(Path("test.js")) == "javascript"
        assert detect_language(Path("test.jsx")) == "javascript"

    async def test_typescript_extensions(self, tmp_path):
        """Test TypeScript file detection."""
        from pathlib import Path

        assert detect_language(Path("test.ts")) == "typescript"
        assert detect_language(Path("test.tsx")) == "typescript"

    async def test_go_extension(self, tmp_path):
        """Test Go file detection."""
        from pathlib import Path

        assert detect_language(Path("test.go")) == "go"

    async def test_rust_extension(self, tmp_path):
        """Test Rust file detection."""
        from pathlib import Path

        assert detect_language(Path("test.rs")) == "rust"

    async def test_java_extension(self, tmp_path):
        """Test Java file detection."""
        from pathlib import Path

        assert detect_language(Path("test.java")) == "java"

    async def test_cpp_extensions(self, tmp_path):
        """Test C++ file detection."""
        from pathlib import Path

        assert detect_language(Path("test.cpp")) == "cpp"
        assert detect_language(Path("test.cc")) == "cpp"
        assert detect_language(Path("test.hpp")) == "cpp"

    async def test_c_extension(self, tmp_path):
        """Test C file detection."""
        from pathlib import Path

        assert detect_language(Path("test.c")) == "c"

    async def test_supported_languages(self):
        """Test that supported languages list is correct."""
        langs = get_supported_languages()
        assert "python" in langs
        assert "javascript" in langs
        assert "typescript" in langs
        assert "go" in langs
        assert "rust" in langs
        assert "java" in langs


@pytest.mark.skipif(not HAS_TREE_SITTER, reason="tree-sitter-languages not installed")
class TestMultiLanguageSupport:
    """Test multi-language code navigation with tree-sitter."""

    @pytest.fixture
    def multi_lang_files(self, tmp_path):
        """Create sample files in multiple languages."""
        # JavaScript file
        js_file = tmp_path / "app.js"
        js_file.write_text(
            """
function greet(name) {
    return "Hello, " + name;
}

class UserService {
    constructor() {
        this.users = [];
    }

    getUser(id) {
        return this.users.find(u => u.id === id);
    }
}

const helper = () => console.log("helper");
"""
        )

        # TypeScript file
        ts_file = tmp_path / "service.ts"
        ts_file.write_text(
            """
interface User {
    id: number;
    name: string;
}

class ApiService {
    private baseUrl: string;

    constructor(url: string) {
        this.baseUrl = url;
    }

    fetchData(endpoint: string): Promise<any> {
        return fetch(this.baseUrl + endpoint);
    }
}

function processData(data: User[]): void {
    console.log(data);
}
"""
        )

        # Go file
        go_file = tmp_path / "main.go"
        go_file.write_text(
            """
package main

import "fmt"

func main() {
    fmt.Println("Hello, World!")
}

func greet(name string) string {
    return "Hello, " + name
}

type Server struct {
    Port int
    Host string
}

func (s *Server) Start() {
    fmt.Printf("Starting server on %s:%d", s.Host, s.Port)
}
"""
        )

        # Rust file
        rs_file = tmp_path / "lib.rs"
        rs_file.write_text(
            """
pub fn calculate(a: i32, b: i32) -> i32 {
    a + b
}

struct Calculator {
    value: i32,
}

impl Calculator {
    fn new() -> Self {
        Calculator { value: 0 }
    }

    fn add(&mut self, n: i32) {
        self.value += n;
    }
}

trait Compute {
    fn compute(&self) -> i32;
}
"""
        )

        # Java file
        java_file = tmp_path / "Main.java"
        java_file.write_text(
            """
public class Main {
    public static void main(String[] args) {
        System.out.println("Hello, World!");
    }

    public int add(int a, int b) {
        return a + b;
    }
}

interface Processor {
    void process();
}

class Helper {
    private String name;

    public Helper(String name) {
        this.name = name;
    }

    public String getName() {
        return this.name;
    }
}
"""
        )

        # C++ file
        cpp_file = tmp_path / "app.cpp"
        cpp_file.write_text(
            """
#include <iostream>
#include <string>

class Engine {
public:
    void start() {
        std::cout << "Engine started" << std::endl;
    }

    void stop() {
        std::cout << "Engine stopped" << std::endl;
    }
};

int calculate(int a, int b) {
    return a + b;
}

void printMessage(const std::string& msg) {
    std::cout << msg << std::endl;
}
"""
        )

        return tmp_path

    async def test_find_javascript_function(self, tool, multi_lang_files):
        """Test finding JavaScript function."""
        result = await tool.execute(
            target="greet",
            search_type="find_function",
            path=str(multi_lang_files),
            language="javascript",
        )

        assert "greet" in result
        assert "app.js" in result
        assert "[javascript]" in result

    async def test_find_javascript_class(self, tool, multi_lang_files):
        """Test finding JavaScript class."""
        result = await tool.execute(
            target="UserService",
            search_type="find_class",
            path=str(multi_lang_files),
            language="javascript",
        )

        assert "UserService" in result
        assert "app.js" in result

    async def test_find_typescript_function(self, tool, multi_lang_files):
        """Test finding TypeScript function."""
        result = await tool.execute(
            target="processData",
            search_type="find_function",
            path=str(multi_lang_files),
            language="typescript",
        )

        assert "processData" in result
        assert "service.ts" in result

    async def test_find_typescript_class(self, tool, multi_lang_files):
        """Test finding TypeScript class and interface."""
        result = await tool.execute(
            target="ApiService",
            search_type="find_class",
            path=str(multi_lang_files),
            language="typescript",
        )

        assert "ApiService" in result
        assert "service.ts" in result

    async def test_find_go_function(self, tool, multi_lang_files):
        """Test finding Go function."""
        result = await tool.execute(
            target="greet",
            search_type="find_function",
            path=str(multi_lang_files),
            language="go",
        )

        assert "greet" in result
        assert "main.go" in result
        assert "[go]" in result

    async def test_find_go_struct(self, tool, multi_lang_files):
        """Test finding Go struct (treated as class)."""
        result = await tool.execute(
            target="Server",
            search_type="find_class",
            path=str(multi_lang_files),
            language="go",
        )

        assert "Server" in result
        assert "main.go" in result

    async def test_find_rust_function(self, tool, multi_lang_files):
        """Test finding Rust function."""
        result = await tool.execute(
            target="calculate",
            search_type="find_function",
            path=str(multi_lang_files),
            language="rust",
        )

        assert "calculate" in result
        assert "lib.rs" in result
        assert "[rust]" in result

    async def test_find_rust_struct(self, tool, multi_lang_files):
        """Test finding Rust struct."""
        result = await tool.execute(
            target="Calculator",
            search_type="find_class",
            path=str(multi_lang_files),
            language="rust",
        )

        assert "Calculator" in result
        assert "lib.rs" in result

    async def test_find_java_method(self, tool, multi_lang_files):
        """Test finding Java method."""
        result = await tool.execute(
            target="add",
            search_type="find_function",
            path=str(multi_lang_files),
            language="java",
        )

        assert "add" in result
        assert "Main.java" in result
        assert "[java]" in result

    async def test_find_java_class(self, tool, multi_lang_files):
        """Test finding Java class."""
        result = await tool.execute(
            target="Helper",
            search_type="find_class",
            path=str(multi_lang_files),
            language="java",
        )

        assert "Helper" in result
        assert "Main.java" in result

    async def test_find_cpp_function(self, tool, multi_lang_files):
        """Test finding C++ function."""
        result = await tool.execute(
            target="calculate",
            search_type="find_function",
            path=str(multi_lang_files),
            language="cpp",
        )

        assert "calculate" in result
        assert "app.cpp" in result
        assert "[cpp]" in result

    async def test_find_cpp_class(self, tool, multi_lang_files):
        """Test finding C++ class."""
        result = await tool.execute(
            target="Engine",
            search_type="find_class",
            path=str(multi_lang_files),
            language="cpp",
        )

        assert "Engine" in result
        assert "app.cpp" in result

    async def test_cross_language_search(self, tool, multi_lang_files):
        """Test finding function across multiple languages."""
        # 'greet' exists in both JS and Go
        result = await tool.execute(
            target="greet",
            search_type="find_function",
            path=str(multi_lang_files),
        )

        assert "greet" in result
        # Should find in both files
        assert "Found" in result

    async def test_show_structure_javascript(self, tool, multi_lang_files):
        """Test showing structure of JavaScript file."""
        js_file = multi_lang_files / "app.js"
        result = await tool.execute(target=str(js_file), search_type="show_structure")

        assert "[javascript]" in result
        assert "CLASSES" in result or "FUNCTIONS" in result
        assert "UserService" in result or "greet" in result

    async def test_show_structure_go(self, tool, multi_lang_files):
        """Test showing structure of Go file."""
        go_file = multi_lang_files / "main.go"
        result = await tool.execute(target=str(go_file), search_type="show_structure")

        assert "[go]" in result
        assert "FUNCTIONS" in result
        assert "main" in result or "greet" in result

    async def test_find_usages_cross_language(self, tool, multi_lang_files):
        """Test finding usages across languages."""
        result = await tool.execute(
            target="calculate",
            search_type="find_usages",
            path=str(multi_lang_files),
        )

        # Should find in Rust, Java, and C++
        assert "calculate" in result

    async def test_language_filter(self, tool, multi_lang_files):
        """Test that language filter works correctly."""
        # Search only in Python (should find nothing in multi_lang_files)
        result = await tool.execute(
            target="greet",
            search_type="find_function",
            path=str(multi_lang_files),
            language="python",
        )

        assert "No function named" in result


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
