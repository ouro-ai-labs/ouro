"""Standalone utility for extracting file structure (imports, classes, functions).

Extracted from CodeNavigatorTool's show_structure functionality. Used by
FileReadTool to show code structure when a file is too large to read fully.
"""

import ast
import importlib
from pathlib import Path
from typing import Dict, List, Optional

import aiofiles

# Try to import tree-sitter for multi-language support
try:
    from tree_sitter import Language, Parser, Query, QueryCursor

    HAS_TREE_SITTER = True
except ImportError:
    HAS_TREE_SITTER = False

# Map language names to (module_name, entry_function_name)
LANGUAGE_MODULES = {
    "javascript": ("tree_sitter_javascript", "language"),
    "typescript": ("tree_sitter_typescript", "language_typescript"),
    "go": ("tree_sitter_go", "language"),
    "rust": ("tree_sitter_rust", "language"),
    "java": ("tree_sitter_java", "language"),
    "kotlin": ("tree_sitter_kotlin", "language"),
    "cpp": ("tree_sitter_cpp", "language"),
    "c": ("tree_sitter_c", "language"),
}


# Language extension mapping
EXTENSION_TO_LANGUAGE = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
}

# Tree-sitter query patterns for function definitions by language
FUNCTION_QUERIES = {
    "python": "(function_definition name: (identifier) @name)",
    "javascript": """[
        (function_declaration name: (identifier) @name)
        (method_definition name: (property_identifier) @name)
        (arrow_function) @arrow
    ]""",
    "typescript": """[
        (function_declaration name: (identifier) @name)
        (method_definition name: (property_identifier) @name)
        (arrow_function) @arrow
    ]""",
    "go": "(function_declaration name: (identifier) @name)",
    "rust": "(function_item name: (identifier) @name)",
    "java": "(method_declaration name: (identifier) @name)",
    "kotlin": "(function_declaration (identifier) @name)",
    "cpp": "(function_definition declarator: (function_declarator declarator: (_) @name))",
    "c": "(function_definition declarator: (function_declarator declarator: (_) @name))",
}

# Tree-sitter query patterns for class definitions by language
CLASS_QUERIES = {
    "python": "(class_definition name: (identifier) @name)",
    "javascript": "(class_declaration name: (identifier) @name)",
    "typescript": """[
        (class_declaration name: (type_identifier) @name)
        (interface_declaration name: (type_identifier) @name)
    ]""",
    "go": "(type_declaration (type_spec name: (type_identifier) @name))",
    "rust": """[
        (struct_item name: (type_identifier) @name)
        (impl_item type: (type_identifier) @name)
        (trait_item name: (type_identifier) @name)
    ]""",
    "java": """[
        (class_declaration name: (identifier) @name)
        (interface_declaration name: (identifier) @name)
    ]""",
    "kotlin": "(class_declaration (identifier) @name)",
    "cpp": """[
        (class_specifier name: (type_identifier) @name)
        (struct_specifier name: (type_identifier) @name)
    ]""",
    "c": "(struct_specifier name: (type_identifier) @name)",
}


def detect_language(file_path: Path) -> Optional[str]:
    """Detect language from file extension."""
    return EXTENSION_TO_LANGUAGE.get(file_path.suffix.lower())


def _get_tree_sitter_parser_and_language(lang: str):
    """Get a tree-sitter parser and language via individual language packages."""
    module_name, func_name = LANGUAGE_MODULES[lang]
    mod = importlib.import_module(module_name)
    language = Language(getattr(mod, func_name)())
    parser = Parser(language)
    return parser, language


def _format_base_class(node: ast.expr) -> str:
    """Format a base class node as string."""
    try:
        return ast.unparse(node)
    except Exception:
        return "?"


def _format_function_args(args: ast.arguments) -> str:
    """Format function arguments as string."""
    arg_strs = []

    for arg in args.args:
        arg_str = arg.arg
        if arg.annotation:
            arg_str += f": {ast.unparse(arg.annotation)}"
        arg_strs.append(arg_str)

    if args.vararg:
        arg_str = f"*{args.vararg.arg}"
        if args.vararg.annotation:
            arg_str += f": {ast.unparse(args.vararg.annotation)}"
        arg_strs.append(arg_str)

    if args.kwarg:
        arg_str = f"**{args.kwarg.arg}"
        if args.kwarg.annotation:
            arg_str += f": {ast.unparse(args.kwarg.annotation)}"
        arg_strs.append(arg_str)

    return ", ".join(arg_strs)


def _format_structure_output(file_path: str, structure: Dict, lang: str) -> str:
    """Format structure output."""
    output_parts = [f"Structure of {file_path} [{lang}]:\n"]

    # Imports
    if structure["imports"]:
        output_parts.append("IMPORTS:")
        for imp in structure["imports"][:20]:
            if imp.get("type") == "import":
                line = f"   Line {imp['line']}: import {imp['name']}"
                if imp.get("as"):
                    line += f" as {imp['as']}"
            else:
                line = f"   Line {imp['line']}: from {imp.get('module', '')} import {imp['name']}"
                if imp.get("as"):
                    line += f" as {imp['as']}"
            output_parts.append(line)
        if len(structure["imports"]) > 20:
            output_parts.append(f"   ... and {len(structure['imports']) - 20} more imports")
        output_parts.append("")

    # Classes
    if structure["classes"]:
        output_parts.append("CLASSES:")
        for cls in structure["classes"]:
            bases_str = f"({', '.join(cls['bases'])})" if cls.get("bases") else ""
            output_parts.append(f"   Line {cls['line']}: class {cls['name']}{bases_str}")
            if cls.get("docstring"):
                doc = cls["docstring"]
                if len(doc) > 60:
                    doc = doc[:60] + "..."
                output_parts.append(f'      "{doc}"')
            if cls.get("methods"):
                methods_str = ", ".join(m["name"] for m in cls["methods"][:5])
                if len(cls["methods"]) > 5:
                    methods_str += f", ... (+{len(cls['methods']) - 5} more)"
                output_parts.append(f"      Methods: {methods_str}")
            output_parts.append("")

    # Functions
    if structure["functions"]:
        output_parts.append("FUNCTIONS:")
        for func in structure["functions"]:
            if lang == "python":
                output_parts.append(f"   Line {func['line']}: def {func['name']}({func['args']})")
            else:
                output_parts.append(f"   Line {func['line']}: {func['name']}")
            if func.get("docstring"):
                doc = func["docstring"]
                if len(doc) > 60:
                    doc = doc[:60] + "..."
                output_parts.append(f'      "{doc}"')
        output_parts.append("")

    if not structure["imports"] and not structure["classes"] and not structure["functions"]:
        output_parts.append("(File appears to be empty or contains only statements)")

    return "\n".join(output_parts)


async def _show_structure_python(path: Path) -> str:
    """Show structure of Python file using AST."""
    async with aiofiles.open(path, encoding="utf-8") as f:
        content = await f.read()
    tree = ast.parse(content, filename=str(path))

    structure: Dict[str, List] = {
        "imports": [],
        "classes": [],
        "functions": [],
    }

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
                    "bases": [_format_base_class(b) for b in node.bases],
                    "methods": methods,
                    "docstring": ast.get_docstring(node),
                }
            )
        elif isinstance(node, ast.FunctionDef):
            args = _format_function_args(node.args)
            structure["functions"].append(
                {
                    "line": node.lineno,
                    "name": node.name,
                    "args": args,
                    "docstring": ast.get_docstring(node),
                }
            )

    return _format_structure_output(str(path), structure, "python")


async def _show_structure_tree_sitter(path: Path, lang: str) -> str:
    """Show structure of file using tree-sitter."""
    parser, language = _get_tree_sitter_parser_and_language(lang)

    async with aiofiles.open(path, "rb") as f:
        code = await f.read()
    tree = parser.parse(code)
    lines = code.decode("utf-8", errors="replace").splitlines()

    structure: Dict[str, List] = {
        "imports": [],
        "classes": [],
        "functions": [],
    }

    # Find classes
    if lang in CLASS_QUERIES:
        try:
            query = Query(language, CLASS_QUERIES[lang])
            captures = QueryCursor(query).captures(tree.root_node)
            for node in captures.get("name", []):
                class_name = node.text.decode("utf-8") if node.text else ""
                structure["classes"].append(
                    {
                        "line": node.start_point[0] + 1,
                        "name": class_name,
                        "bases": [],
                        "methods": [],
                        "docstring": None,
                    }
                )
        except Exception:
            pass

    # Find functions
    if lang in FUNCTION_QUERIES:
        try:
            query = Query(language, FUNCTION_QUERIES[lang])
            captures = QueryCursor(query).captures(tree.root_node)
            for node in captures.get("name", []):
                func_name = node.text.decode("utf-8") if node.text else ""
                line_num = node.start_point[0] + 1
                line_content = lines[line_num - 1].strip() if line_num <= len(lines) else ""
                structure["functions"].append(
                    {
                        "line": line_num,
                        "name": func_name,
                        "args": line_content,
                        "docstring": None,
                    }
                )
        except Exception:
            pass

    return _format_structure_output(str(path), structure, lang)


async def show_file_structure(file_path: str) -> Optional[str]:
    """Return the structure of a code file, or None if unsupported.

    Args:
        file_path: Path to the file to analyze.

    Returns:
        Structure string for supported code files, None for unsupported files.
    """
    path = Path(file_path)
    lang = detect_language(path)

    if lang == "python":
        try:
            return await _show_structure_python(path)
        except Exception:
            return None
    elif HAS_TREE_SITTER and lang:
        try:
            return await _show_structure_tree_sitter(path, lang)
        except Exception:
            return None
    else:
        return None
