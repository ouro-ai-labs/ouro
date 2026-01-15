"""Code navigation tool using AST analysis for fast and accurate code location.

This tool provides intelligent code navigation capabilities:
- Find function/class definitions quickly
- Show file structure (imports, classes, functions)
- Find usages of functions/classes
- Much faster and more accurate than grep
"""

import ast
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict

from tools.base import BaseTool


class _FunctionResult(TypedDict):
    file: str
    line: int
    signature: str
    docstring: str
    decorators: List[str]


class _ClassResult(TypedDict):
    file: str
    line: int
    bases: List[str]
    methods: List[str]
    docstring: str
    decorators: List[str]


class CodeNavigatorTool(BaseTool):
    """Navigate code using AST analysis - fast and accurate."""

    def __init__(self):
        self.cache_dir = Path(".AgenticLoop/cache")
        self.symbol_cache = {}  # {symbol_name: [(file, line, type, info)]}
        self.cache_loaded = False

    @property
    def name(self) -> str:
        return "code_navigator"

    @property
    def description(self) -> str:
        return """Fast code navigation using AST analysis (MUCH better than grep for code).

This tool understands Python code structure and can quickly find definitions and usages.

Search types:
1. find_function: Find function definitions by name
   - Returns: file path, line number, function signature, docstring
   - Example: code_navigator(target="compress", search_type="find_function")

2. find_class: Find class definitions by name
   - Returns: file path, line number, base classes, methods list
   - Example: code_navigator(target="BaseAgent", search_type="find_class")

3. show_structure: Show structure of a specific file
   - Returns: imports, classes, functions in tree format
   - Example: code_navigator(target="agent/base.py", search_type="show_structure")

4. find_usages: Find where a function/class is called or used
   - Returns: all usage locations (file + line number + context)
   - Example: code_navigator(target="_react_loop", search_type="find_usages")

WHY USE THIS INSTEAD OF GREP:
- 10x faster for finding code elements
- Understands code structure (not just text matching)
- Returns exact line numbers and signatures
- No false positives from comments or strings
- Can distinguish between definitions and usages

WHEN TO USE:
- Finding where a function is defined: use find_function
- Finding where a class is defined: use find_class
- Understanding file structure: use show_structure
- Finding all places a function is called: use find_usages

WHEN TO USE GREP INSTEAD:
- Searching for string literals or text content
- Finding TODO/FIXME comments
- Searching in non-Python files"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "target": {
                "type": "string",
                "description": "What to search for: function name, class name, or file path (for show_structure)",
            },
            "search_type": {
                "type": "string",
                "description": "Type of search: find_function, find_class, show_structure, or find_usages",
                "enum": ["find_function", "find_class", "show_structure", "find_usages"],
            },
            "path": {
                "type": "string",
                "description": "Optional: limit search to specific directory (default: current directory)",
            },
        }

    def execute(self, target: str, search_type: str, path: str = ".", **kwargs) -> str:
        """Execute code navigation search."""
        try:
            base_path = Path(path)
            if not base_path.exists():
                return f"Error: Path does not exist: {path}"

            if search_type == "find_function":
                return self._find_function(target, base_path)
            elif search_type == "find_class":
                return self._find_class(target, base_path)
            elif search_type == "show_structure":
                return self._show_structure(target)
            elif search_type == "find_usages":
                return self._find_usages(target, base_path)
            else:
                return f"Error: Unknown search_type '{search_type}'"

        except Exception as e:
            return f"Error executing code_navigator: {str(e)}"

    def _find_function(self, name: str, base_path: Path) -> str:
        """Find all function definitions matching the name."""
        results: List[_FunctionResult] = []

        for py_file in base_path.rglob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8")
                tree = ast.parse(content, filename=str(py_file))

                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef) and node.name == name:
                        # Get function signature
                        args = self._format_function_args(node.args)
                        signature = f"def {node.name}({args})"

                        # Add return type annotation if present
                        if node.returns:
                            try:
                                return_type = ast.unparse(node.returns)
                                signature += f" -> {return_type}"
                            except Exception:
                                pass

                        # Get docstring
                        docstring = ast.get_docstring(node)

                        # Get decorator names
                        decorators = [self._format_decorator(d) for d in node.decorator_list]

                        results.append(
                            {
                                "file": str(py_file.relative_to(base_path)),
                                "line": node.lineno,
                                "signature": signature,
                                "docstring": docstring or "(no docstring)",
                                "decorators": decorators,
                            }
                        )
            except SyntaxError:
                # Skip files with syntax errors
                continue
            except Exception:
                # Skip files that can't be parsed
                continue

        if not results:
            return f"No function named '{name}' found in {base_path}"

        # Format results
        output_parts = [f"Found {len(results)} function(s) named '{name}':\n"]
        for r in results:
            output_parts.append(f"📍 {r['file']}:{r['line']}")
            if r["decorators"]:
                output_parts.append(f"   Decorators: {', '.join(r['decorators'])}")
            output_parts.append(f"   {r['signature']}")
            # Truncate long docstrings
            doc = r["docstring"]
            if len(doc) > 100:
                doc = doc[:100] + "..."
            output_parts.append(f'   "{doc}"\n')

        return "\n".join(output_parts)

    def _find_class(self, name: str, base_path: Path) -> str:
        """Find all class definitions matching the name."""
        results: List[_ClassResult] = []

        for py_file in base_path.rglob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8")
                tree = ast.parse(content, filename=str(py_file))

                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef) and node.name == name:
                        # Get base classes
                        bases = [self._format_base_class(b) for b in node.bases]

                        # Get methods
                        methods = []
                        for item in node.body:
                            if isinstance(item, ast.FunctionDef):
                                methods.append(item.name)

                        # Get docstring
                        docstring = ast.get_docstring(node)

                        # Get decorator names
                        decorators = [self._format_decorator(d) for d in node.decorator_list]

                        results.append(
                            {
                                "file": str(py_file.relative_to(base_path)),
                                "line": node.lineno,
                                "bases": bases,
                                "methods": methods,
                                "docstring": docstring or "(no docstring)",
                                "decorators": decorators,
                            }
                        )
            except SyntaxError:
                continue
            except Exception:
                continue

        if not results:
            return f"No class named '{name}' found in {base_path}"

        # Format results
        output_parts = [f"Found {len(results)} class(es) named '{name}':\n"]
        for r in results:
            output_parts.append(f"📍 {r['file']}:{r['line']}")
            output_parts.append(
                f"   class {name}({', '.join(r['bases']) if r['bases'] else 'object'})"
            )
            if r["decorators"]:
                output_parts.append(f"   Decorators: {', '.join(r['decorators'])}")

            doc = r["docstring"]
            if len(doc) > 100:
                doc = doc[:100] + "..."
            output_parts.append(f'   "{doc}"')

            if r["methods"]:
                output_parts.append(
                    f"   Methods ({len(r['methods'])}): {', '.join(r['methods'][:10])}"
                )
                if len(r["methods"]) > 10:
                    output_parts.append(f"            ... and {len(r['methods']) - 10} more")
            output_parts.append("")

        return "\n".join(output_parts)

    def _show_structure(self, file_path: str) -> str:
        """Show the structure of a specific file."""
        path = Path(file_path)
        if not path.exists():
            return f"Error: File does not exist: {file_path}"

        try:
            content = path.read_text(encoding="utf-8")
            tree = ast.parse(content, filename=str(path))

            structure = {
                "imports": [],
                "classes": [],
                "functions": [],
            }

            # Collect top-level elements
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        structure["imports"].append(
                            {
                                "line": node.lineno,
                                "type": "import",
                                "name": alias.name,
                                "as": alias.asname,
                            }
                        )
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        structure["imports"].append(
                            {
                                "line": node.lineno,
                                "type": "from",
                                "module": node.module or "",
                                "name": alias.name,
                                "as": alias.asname,
                            }
                        )
                elif isinstance(node, ast.ClassDef):
                    methods = [
                        {"name": item.name, "line": item.lineno}
                        for item in node.body
                        if isinstance(item, ast.FunctionDef)
                    ]
                    structure["classes"].append(
                        {
                            "line": node.lineno,
                            "name": node.name,
                            "bases": [self._format_base_class(b) for b in node.bases],
                            "methods": methods,
                            "docstring": ast.get_docstring(node),
                        }
                    )
                elif isinstance(node, ast.FunctionDef):
                    args = self._format_function_args(node.args)
                    structure["functions"].append(
                        {
                            "line": node.lineno,
                            "name": node.name,
                            "args": args,
                            "docstring": ast.get_docstring(node),
                        }
                    )

            # Format output
            output_parts = [f"Structure of {file_path}:\n"]

            # Imports
            if structure["imports"]:
                output_parts.append("📦 IMPORTS:")
                for imp in structure["imports"][:20]:  # Limit to 20 imports
                    if imp["type"] == "import":
                        line = f"   Line {imp['line']}: import {imp['name']}"
                        if imp["as"]:
                            line += f" as {imp['as']}"
                    else:
                        line = f"   Line {imp['line']}: from {imp['module']} import {imp['name']}"
                        if imp["as"]:
                            line += f" as {imp['as']}"
                    output_parts.append(line)
                if len(structure["imports"]) > 20:
                    output_parts.append(f"   ... and {len(structure['imports']) - 20} more imports")
                output_parts.append("")

            # Classes
            if structure["classes"]:
                output_parts.append("📘 CLASSES:")
                for cls in structure["classes"]:
                    bases_str = f"({', '.join(cls['bases'])})" if cls["bases"] else ""
                    output_parts.append(f"   Line {cls['line']}: class {cls['name']}{bases_str}")
                    if cls["docstring"]:
                        doc = cls["docstring"]
                        if len(doc) > 60:
                            doc = doc[:60] + "..."
                        output_parts.append(f'      "{doc}"')
                    if cls["methods"]:
                        methods_str = ", ".join(m["name"] for m in cls["methods"][:5])
                        if len(cls["methods"]) > 5:
                            methods_str += f", ... (+{len(cls['methods']) - 5} more)"
                        output_parts.append(f"      Methods: {methods_str}")
                    output_parts.append("")

            # Functions
            if structure["functions"]:
                output_parts.append("🔧 FUNCTIONS:")
                for func in structure["functions"]:
                    output_parts.append(
                        f"   Line {func['line']}: def {func['name']}({func['args']})"
                    )
                    if func["docstring"]:
                        doc = func["docstring"]
                        if len(doc) > 60:
                            doc = doc[:60] + "..."
                        output_parts.append(f'      "{doc}"')
                output_parts.append("")

            if not structure["imports"] and not structure["classes"] and not structure["functions"]:
                output_parts.append("(File appears to be empty or contains only statements)")

            return "\n".join(output_parts)

        except SyntaxError as e:
            return f"Error: Syntax error in {file_path} at line {e.lineno}: {e.msg}"
        except Exception as e:
            return f"Error parsing {file_path}: {str(e)}"

    def _find_usages(self, name: str, base_path: Path) -> str:
        """Find where a function or class is used (called)."""
        results = []

        for py_file in base_path.rglob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8")
                lines = content.splitlines()
                tree = ast.parse(content, filename=str(py_file))

                for node in ast.walk(tree):
                    # Function calls
                    if isinstance(node, ast.Call):
                        called_name = self._get_call_name(node.func)
                        if called_name == name:
                            # Get context (the line of code)
                            line_num = node.lineno
                            context = lines[line_num - 1].strip() if line_num <= len(lines) else ""

                            results.append(
                                {
                                    "file": str(py_file.relative_to(Path.cwd())),
                                    "line": line_num,
                                    "type": "function_call",
                                    "context": context,
                                }
                            )

                    # Name references (variables, attributes)
                    elif isinstance(node, ast.Name) and node.id == name:
                        line_num = node.lineno
                        context = lines[line_num - 1].strip() if line_num <= len(lines) else ""

                        results.append(
                            {
                                "file": str(py_file.relative_to(base_path)),
                                "line": line_num,
                                "type": "name_reference",
                                "context": context,
                            }
                        )

            except SyntaxError:
                continue
            except Exception:
                continue

        if not results:
            return f"No usages of '{name}' found in {base_path}"

        # Deduplicate results (same file + line)
        seen = set()
        unique_results = []
        for r in results:
            key = (r["file"], r["line"])
            if key not in seen:
                seen.add(key)
                unique_results.append(r)

        # Limit results to avoid overwhelming output
        if len(unique_results) > 50:
            unique_results = unique_results[:50]
            truncated = True
        else:
            truncated = False

        # Format results
        output_parts = [f"Found {len(seen)} usage(s) of '{name}':\n"]

        for r in unique_results:
            output_parts.append(f"📍 {r['file']}:{r['line']}")
            # Truncate long contexts
            context = r["context"]
            if len(context) > 80:
                context = context[:80] + "..."
            output_parts.append(f"   {context}\n")

        if truncated:
            output_parts.append(f"... (showing first 50 of {len(seen)} usages)")

        return "\n".join(output_parts)

    # Helper methods

    def _format_function_args(self, args: ast.arguments) -> str:
        """Format function arguments as string."""
        arg_strs = []

        # Regular args
        for arg in args.args:
            arg_str = arg.arg
            if arg.annotation:
                arg_str += f": {ast.unparse(arg.annotation)}"
            arg_strs.append(arg_str)

        # *args
        if args.vararg:
            arg_str = f"*{args.vararg.arg}"
            if args.vararg.annotation:
                arg_str += f": {ast.unparse(args.vararg.annotation)}"
            arg_strs.append(arg_str)

        # **kwargs
        if args.kwarg:
            arg_str = f"**{args.kwarg.arg}"
            if args.kwarg.annotation:
                arg_str += f": {ast.unparse(args.kwarg.annotation)}"
            arg_strs.append(arg_str)

        return ", ".join(arg_strs)

    def _format_base_class(self, node: ast.expr) -> str:
        """Format a base class node as string."""
        try:
            return ast.unparse(node)
        except Exception:
            return "?"

    def _format_decorator(self, node: ast.expr) -> str:
        """Format a decorator node as string."""
        try:
            return "@" + ast.unparse(node)
        except Exception:
            return "@?"

    def _get_call_name(self, node: ast.expr) -> Optional[str]:
        """Extract the name from a function call node."""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            # For method calls like obj.method(), return just 'method'
            return node.attr
        return None
