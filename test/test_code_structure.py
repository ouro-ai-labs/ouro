"""Tests for tools/code_structure.py — every supported language."""

from pathlib import Path

import pytest

from tools.code_structure import (
    EXTENSION_TO_LANGUAGE,
    LANGUAGE_MODULES,
    detect_language,
    show_file_structure,
)

# ---------------------------------------------------------------------------
# detect_language
# ---------------------------------------------------------------------------


class TestDetectLanguage:
    @pytest.mark.parametrize(
        "ext, expected",
        [
            (".py", "python"),
            (".js", "javascript"),
            (".jsx", "javascript"),
            (".ts", "typescript"),
            (".tsx", "typescript"),
            (".go", "go"),
            (".rs", "rust"),
            (".java", "java"),
            (".kt", "kotlin"),
            (".kts", "kotlin"),
            (".cpp", "cpp"),
            (".cc", "cpp"),
            (".cxx", "cpp"),
            (".c", "c"),
            (".h", "c"),
            (".hpp", "cpp"),
        ],
    )
    def test_known_extensions(self, ext, expected):
        assert detect_language(Path(f"foo{ext}")) == expected

    def test_unknown_extension_returns_none(self):
        assert detect_language(Path("foo.txt")) is None
        assert detect_language(Path("foo.md")) is None
        assert detect_language(Path("Makefile")) is None

    def test_case_insensitive(self):
        assert detect_language(Path("Foo.PY")) == "python"
        assert detect_language(Path("Bar.JS")) == "javascript"


# ---------------------------------------------------------------------------
# LANGUAGE_MODULES covers every non-python language in EXTENSION_TO_LANGUAGE
# ---------------------------------------------------------------------------


def test_language_modules_cover_all_tree_sitter_languages():
    """Every non-python language used in EXTENSION_TO_LANGUAGE must appear in LANGUAGE_MODULES."""
    ts_languages = {lang for lang in EXTENSION_TO_LANGUAGE.values() if lang != "python"}
    assert ts_languages == set(LANGUAGE_MODULES.keys())


# ---------------------------------------------------------------------------
# Sample source snippets per language (function + class/struct/trait/interface)
# ---------------------------------------------------------------------------

PYTHON_CODE = '''\
import os
from pathlib import Path

class Greeter:
    """A greeter class."""
    def greet(self):
        pass

def hello(name: str) -> str:
    """Say hello."""
    return f"hello {name}"
'''

JAVASCRIPT_CODE = """\
function greet(name) {
  return "hello " + name;
}

class Animal {
  constructor(name) {
    this.name = name;
  }
  speak() {
    return this.name;
  }
}
"""

TYPESCRIPT_CODE = """\
function greet(name: string): string {
  return "hello " + name;
}

class Animal {
  name: string;
  constructor(name: string) {
    this.name = name;
  }
  speak(): string {
    return this.name;
  }
}

interface Serializable {
  serialize(): string;
}
"""

GO_CODE = """\
package main

func greet(name string) string {
    return "hello " + name
}

type Animal struct {
    Name string
}
"""

RUST_CODE = """\
fn greet(name: &str) -> String {
    format!("hello {}", name)
}

struct Animal {
    name: String,
}

trait Greeter {
    fn greet(&self) -> String;
}

impl Greeter for Animal {
    fn greet(&self) -> String {
        format!("hello {}", self.name)
    }
}
"""

JAVA_CODE = """\
public class Greeter {
    public String greet(String name) {
        return "hello " + name;
    }
}

interface Serializable {
    String serialize();
}
"""

KOTLIN_CODE = """\
fun greet(name: String): String {
    return "hello $name"
}

class Animal(val name: String)
"""

CPP_CODE = """\
#include <string>

class Animal {
public:
    std::string name;
};

struct Point {
    int x;
    int y;
};

std::string greet(const std::string& name) {
    return "hello " + name;
}
"""

C_CODE = """\
#include <stdio.h>

struct Point {
    int x;
    int y;
};

void greet(const char* name) {
    printf("hello %s\\n", name);
}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_source(tmp_path):
    """Return a helper that writes source code to a temp file with a given extension."""

    def _write(code: str, ext: str) -> str:
        p = tmp_path / f"sample{ext}"
        p.write_text(code, encoding="utf-8")
        return str(p)

    return _write


# ---------------------------------------------------------------------------
# Python (AST path)
# ---------------------------------------------------------------------------


class TestPython:
    async def test_functions_and_classes(self, tmp_source):
        path = tmp_source(PYTHON_CODE, ".py")
        result = await show_file_structure(path)
        assert result is not None
        assert "[python]" in result
        assert "hello" in result
        assert "Greeter" in result
        assert "greet" in result

    async def test_imports(self, tmp_source):
        path = tmp_source(PYTHON_CODE, ".py")
        result = await show_file_structure(path)
        assert result is not None
        assert "import os" in result
        assert "from pathlib import Path" in result

    async def test_docstrings(self, tmp_source):
        path = tmp_source(PYTHON_CODE, ".py")
        result = await show_file_structure(path)
        assert result is not None
        assert "A greeter class" in result
        assert "Say hello" in result

    async def test_class_methods_listed(self, tmp_source):
        path = tmp_source(PYTHON_CODE, ".py")
        result = await show_file_structure(path)
        assert result is not None
        assert "Methods: greet" in result

    async def test_function_args(self, tmp_source):
        path = tmp_source(PYTHON_CODE, ".py")
        result = await show_file_structure(path)
        assert result is not None
        assert "name: str" in result


# ---------------------------------------------------------------------------
# JavaScript
# ---------------------------------------------------------------------------


class TestJavaScript:
    async def test_functions_and_classes(self, tmp_source):
        path = tmp_source(JAVASCRIPT_CODE, ".js")
        result = await show_file_structure(path)
        assert result is not None
        assert "[javascript]" in result
        assert "greet" in result
        assert "Animal" in result

    async def test_method_detected(self, tmp_source):
        path = tmp_source(JAVASCRIPT_CODE, ".js")
        result = await show_file_structure(path)
        assert result is not None
        assert "speak" in result

    async def test_jsx_extension(self, tmp_source):
        path = tmp_source(JAVASCRIPT_CODE, ".jsx")
        result = await show_file_structure(path)
        assert result is not None
        assert "[javascript]" in result


# ---------------------------------------------------------------------------
# TypeScript
# ---------------------------------------------------------------------------


class TestTypeScript:
    async def test_functions_and_classes(self, tmp_source):
        path = tmp_source(TYPESCRIPT_CODE, ".ts")
        result = await show_file_structure(path)
        assert result is not None
        assert "[typescript]" in result
        assert "greet" in result
        assert "Animal" in result

    async def test_interface_detected(self, tmp_source):
        path = tmp_source(TYPESCRIPT_CODE, ".ts")
        result = await show_file_structure(path)
        assert result is not None
        assert "Serializable" in result

    async def test_tsx_extension(self, tmp_source):
        path = tmp_source(TYPESCRIPT_CODE, ".tsx")
        result = await show_file_structure(path)
        assert result is not None
        assert "[typescript]" in result


# ---------------------------------------------------------------------------
# Go
# ---------------------------------------------------------------------------


class TestGo:
    async def test_functions_and_types(self, tmp_source):
        path = tmp_source(GO_CODE, ".go")
        result = await show_file_structure(path)
        assert result is not None
        assert "[go]" in result
        assert "greet" in result
        assert "Animal" in result


# ---------------------------------------------------------------------------
# Rust
# ---------------------------------------------------------------------------


class TestRust:
    async def test_functions_and_structs(self, tmp_source):
        path = tmp_source(RUST_CODE, ".rs")
        result = await show_file_structure(path)
        assert result is not None
        assert "[rust]" in result
        assert "greet" in result
        assert "Animal" in result

    async def test_trait_detected(self, tmp_source):
        path = tmp_source(RUST_CODE, ".rs")
        result = await show_file_structure(path)
        assert result is not None
        assert "Greeter" in result


# ---------------------------------------------------------------------------
# Java
# ---------------------------------------------------------------------------


class TestJava:
    async def test_methods_and_classes(self, tmp_source):
        path = tmp_source(JAVA_CODE, ".java")
        result = await show_file_structure(path)
        assert result is not None
        assert "[java]" in result
        assert "greet" in result
        assert "Greeter" in result

    async def test_interface_detected(self, tmp_source):
        path = tmp_source(JAVA_CODE, ".java")
        result = await show_file_structure(path)
        assert result is not None
        assert "Serializable" in result


# ---------------------------------------------------------------------------
# Kotlin
# ---------------------------------------------------------------------------


class TestKotlin:
    async def test_functions_and_classes(self, tmp_source):
        path = tmp_source(KOTLIN_CODE, ".kt")
        result = await show_file_structure(path)
        assert result is not None
        assert "[kotlin]" in result
        assert "greet" in result
        assert "Animal" in result

    async def test_kts_extension(self, tmp_source):
        path = tmp_source(KOTLIN_CODE, ".kts")
        result = await show_file_structure(path)
        assert result is not None
        assert "[kotlin]" in result


# ---------------------------------------------------------------------------
# C++
# ---------------------------------------------------------------------------


class TestCpp:
    async def test_functions_and_classes(self, tmp_source):
        path = tmp_source(CPP_CODE, ".cpp")
        result = await show_file_structure(path)
        assert result is not None
        assert "[cpp]" in result
        assert "greet" in result
        assert "Animal" in result

    async def test_struct_detected(self, tmp_source):
        path = tmp_source(CPP_CODE, ".cpp")
        result = await show_file_structure(path)
        assert result is not None
        assert "Point" in result

    async def test_cc_extension(self, tmp_source):
        path = tmp_source(CPP_CODE, ".cc")
        result = await show_file_structure(path)
        assert result is not None
        assert "[cpp]" in result

    async def test_hpp_extension(self, tmp_source):
        path = tmp_source(CPP_CODE, ".hpp")
        result = await show_file_structure(path)
        assert result is not None
        assert "[cpp]" in result


# ---------------------------------------------------------------------------
# C
# ---------------------------------------------------------------------------


class TestC:
    async def test_functions_and_structs(self, tmp_source):
        path = tmp_source(C_CODE, ".c")
        result = await show_file_structure(path)
        assert result is not None
        assert "[c]" in result
        assert "greet" in result
        assert "Point" in result

    async def test_h_extension(self, tmp_source):
        path = tmp_source(C_CODE, ".h")
        result = await show_file_structure(path)
        assert result is not None
        assert "[c]" in result


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    async def test_unsupported_extension_returns_none(self, tmp_source):
        path = tmp_source("hello world", ".txt")
        result = await show_file_structure(path)
        assert result is None

    async def test_empty_file(self, tmp_source):
        path = tmp_source("", ".py")
        result = await show_file_structure(path)
        assert result is not None
        assert "empty" in result.lower() or "statements" in result.lower()

    async def test_nonexistent_file_returns_none(self):
        result = await show_file_structure("/tmp/does_not_exist_12345.py")
        assert result is None

    async def test_empty_js_file(self, tmp_source):
        path = tmp_source("", ".js")
        result = await show_file_structure(path)
        assert result is not None
        assert "empty" in result.lower() or "statements" in result.lower()
