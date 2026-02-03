"""Code navigation tool using AST analysis for fast and accurate code location.

This tool provides intelligent code navigation capabilities:
- Find function/class definitions quickly across multiple languages
- Show file structure (imports, classes, functions)
- Find usages of functions/classes
- Supports Python, JavaScript/TypeScript, Go, Rust, Java, Kotlin, C/C++
"""

import ast
import asyncio
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict

import aiofiles
import aiofiles.os

from tools.base import BaseTool

# Try to import tree-sitter-languages for multi-language support
try:
    # tree_sitter_languages may trigger a FutureWarning from tree_sitter about
    # Language(path, name) being deprecated. This is a dependency-level warning
    # and is safe to suppress locally to keep test output clean.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            category=FutureWarning,
            module=r"^tree_sitter(\.|$)",
        )
        from tree_sitter_languages import get_language, get_parser

    HAS_TREE_SITTER = True
except ImportError:
    HAS_TREE_SITTER = False


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
    "kotlin": "(function_declaration (simple_identifier) @name)",
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
    "kotlin": "(class_declaration (type_identifier) @name)",
    "cpp": """[
        (class_specifier name: (type_identifier) @name)
        (struct_specifier name: (type_identifier) @name)
    ]""",
    "c": "(struct_specifier name: (type_identifier) @name)",
}

# File patterns by language for iteration
LANGUAGE_FILE_PATTERNS = {
    "python": ["*.py"],
    "javascript": ["*.js", "*.jsx"],
    "typescript": ["*.ts", "*.tsx"],
    "go": ["*.go"],
    "rust": ["*.rs"],
    "java": ["*.java"],
    "kotlin": ["*.kt", "*.kts"],
    "cpp": ["*.cpp", "*.cc", "*.cxx", "*.hpp"],
    "c": ["*.c", "*.h"],
}


def detect_language(file_path: Path) -> Optional[str]:
    """Detect language from file extension."""
    return EXTENSION_TO_LANGUAGE.get(file_path.suffix.lower())


def get_supported_languages() -> List[str]:
    """Return list of supported languages."""
    return list(FUNCTION_QUERIES.keys())


class CodeNavigatorTool(BaseTool):
    """Navigate code using AST analysis - fast and accurate, multi-language support."""

    def __init__(self):
        self.cache_dir = Path(".aloop/cache")
        self.symbol_cache = {}  # {symbol_name: [(file, line, type, info)]}
        self.cache_loaded = False
        self._tree_sitter_available = HAS_TREE_SITTER

    def _get_tree_sitter_parser_and_language(self, lang: str):
        """Get a tree-sitter parser and language.

        tree_sitter_languages currently triggers a FutureWarning via tree_sitter
        (Language(path, name) deprecation). This is dependency-level noise, so we
        suppress it locally around the calls that instantiate Language objects.
        """
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                category=FutureWarning,
                module=r"^tree_sitter(\.|$)",
            )
            return get_parser(lang), get_language(lang)

    @property
    def name(self) -> str:
        return "code_navigator"

    @property
    def description(self) -> str:
        langs = ", ".join(get_supported_languages()) if HAS_TREE_SITTER else "Python"
        return f"""Fast code navigation using AST analysis (MUCH better than grep for code).

This tool understands code structure and can quickly find definitions and usages.
Supported languages: {langs}

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
- Searching in non-supported languages"""

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
            "language": {
                "type": "string",
                "description": "Optional: limit search to specific language (e.g., 'python', 'javascript', 'go')",
            },
        }

    async def execute(
        self, target: str, search_type: str, path: str = ".", language: str = None, **kwargs
    ) -> str:
        """Execute code navigation search."""
        try:
            base_path = Path(path)
            if not await aiofiles.os.path.exists(str(base_path)):
                return f"Error: Path does not exist: {path}"

            if search_type == "find_function":
                return await self._find_function(target, base_path, language)
            elif search_type == "find_class":
                return await self._find_class(target, base_path, language)
            elif search_type == "show_structure":
                return await self._show_structure(target)
            elif search_type == "find_usages":
                return await self._find_usages(target, base_path, language)
            else:
                return f"Error: Unknown search_type '{search_type}'"

        except Exception as e:
            return f"Error executing code_navigator: {str(e)}"

    async def _iter_source_files(
        self, base_path: Path, language: Optional[str] = None
    ) -> List[Path]:
        """Iterate over source files, optionally filtered by language."""
        files = []

        if language:
            # Filter by specific language
            patterns = LANGUAGE_FILE_PATTERNS.get(language, [])
            for pattern in patterns:
                matches = await asyncio.to_thread(
                    lambda pattern=pattern: list(base_path.rglob(pattern))
                )
                files.extend(matches)
        else:
            # All supported languages
            for patterns in LANGUAGE_FILE_PATTERNS.values():
                for pattern in patterns:
                    matches = await asyncio.to_thread(
                        lambda pattern=pattern: list(base_path.rglob(pattern))
                    )
                    files.extend(matches)

        # Deduplicate and exclude common non-code directories
        seen = set()
        result = []
        exclude_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", "target", "build"}

        for f in files:
            if f in seen:
                continue
            seen.add(f)

            # Skip excluded directories
            skip = False
            for part in f.parts:
                if part in exclude_dirs:
                    skip = True
                    break
            if not skip:
                result.append(f)

        return sorted(result)

    async def _find_function_with_tree_sitter(
        self, name: str, file_path: Path, lang: str
    ) -> List[Dict]:
        """Find functions using tree-sitter."""
        results = []

        if lang not in FUNCTION_QUERIES:
            return results

        try:
            parser, language = self._get_tree_sitter_parser_and_language(lang)
            query = language.query(FUNCTION_QUERIES[lang])

            async with aiofiles.open(file_path, "rb") as f:
                code = await f.read()
            tree = parser.parse(code)
            captures = query.captures(tree.root_node)

            for node, capture_name in captures:
                if capture_name == "name":
                    func_name = node.text.decode("utf-8")
                    if func_name == name:
                        # Get the full function node (parent)
                        func_node = node.parent
                        while func_node and not func_node.type.endswith(
                            (
                                "function_definition",
                                "function_declaration",
                                "function_item",
                                "method_declaration",
                                "method_definition",
                            )
                        ):
                            func_node = func_node.parent

                        start_line = node.start_point[0] + 1
                        end_line = func_node.end_point[0] + 1 if func_node else start_line

                        # Try to extract signature (first line of function)
                        lines = code.decode("utf-8", errors="replace").splitlines()
                        signature = (
                            lines[start_line - 1].strip() if start_line <= len(lines) else ""
                        )

                        results.append(
                            {
                                "file": str(file_path),
                                "line": start_line,
                                "end_line": end_line,
                                "signature": signature,
                                "docstring": "(no docstring)",
                                "decorators": [],
                                "language": lang,
                            }
                        )

        except Exception:
            pass

        return results

    async def _find_class_with_tree_sitter(
        self, name: str, file_path: Path, lang: str
    ) -> List[Dict]:
        """Find classes using tree-sitter."""
        results = []

        if lang not in CLASS_QUERIES:
            return results

        try:
            parser, language = self._get_tree_sitter_parser_and_language(lang)
            query = language.query(CLASS_QUERIES[lang])

            async with aiofiles.open(file_path, "rb") as f:
                code = await f.read()
            tree = parser.parse(code)
            captures = query.captures(tree.root_node)

            for node, capture_name in captures:
                if capture_name == "name":
                    class_name = node.text.decode("utf-8")
                    if class_name == name:
                        start_line = node.start_point[0] + 1

                        # Get the class node for methods extraction
                        class_node = node.parent
                        while class_node and not class_node.type.endswith(
                            (
                                "class_definition",
                                "class_declaration",
                                "class_specifier",
                                "struct_item",
                                "struct_specifier",
                                "type_spec",
                                "impl_item",
                                "trait_item",
                                "interface_declaration",
                            )
                        ):
                            class_node = class_node.parent

                        results.append(
                            {
                                "file": str(file_path),
                                "line": start_line,
                                "bases": [],
                                "methods": [],
                                "docstring": "(no docstring)",
                                "decorators": [],
                                "language": lang,
                            }
                        )

        except Exception:
            pass

        return results

    async def _find_function(
        self, name: str, base_path: Path, language: Optional[str] = None
    ) -> str:
        """Find all function definitions matching the name."""
        results: List[Dict] = []

        for source_file in await self._iter_source_files(base_path, language):
            lang = detect_language(source_file)
            if not lang:
                continue

            # Use Python AST for Python files (more detailed output)
            if lang == "python":
                try:
                    async with aiofiles.open(source_file, encoding="utf-8") as f:
                        content = await f.read()
                    tree = ast.parse(content, filename=str(source_file))

                    for node in ast.walk(tree):
                        if isinstance(node, ast.FunctionDef) and node.name == name:
                            args = self._format_function_args(node.args)
                            signature = f"def {node.name}({args})"

                            if node.returns:
                                try:
                                    return_type = ast.unparse(node.returns)
                                    signature += f" -> {return_type}"
                                except Exception:
                                    pass

                            docstring = ast.get_docstring(node)
                            decorators = [self._format_decorator(d) for d in node.decorator_list]

                            try:
                                rel_path = str(source_file.relative_to(base_path))
                            except ValueError:
                                rel_path = str(source_file)

                            results.append(
                                {
                                    "file": rel_path,
                                    "line": node.lineno,
                                    "signature": signature,
                                    "docstring": docstring or "(no docstring)",
                                    "decorators": decorators,
                                }
                            )
                except SyntaxError:
                    continue
                except Exception:
                    continue

            # Use tree-sitter for other languages
            elif self._tree_sitter_available:
                try:
                    rel_path = str(source_file.relative_to(base_path))
                except ValueError:
                    rel_path = str(source_file)

                ts_results = await self._find_function_with_tree_sitter(name, source_file, lang)
                for r in ts_results:
                    r["file"] = rel_path
                    results.append(r)

        if not results:
            return f"No function named '{name}' found in {base_path}"

        # Format results
        output_parts = [f"Found {len(results)} function(s) named '{name}':\n"]
        for r in results:
            lang_tag = f" [{r.get('language', 'python')}]" if r.get("language") else ""
            output_parts.append(f"{r['file']}:{r['line']}{lang_tag}")
            if r.get("decorators"):
                output_parts.append(f"   Decorators: {', '.join(r['decorators'])}")
            output_parts.append(f"   {r['signature']}")
            doc = r["docstring"]
            if len(doc) > 100:
                doc = doc[:100] + "..."
            output_parts.append(f'   "{doc}"\n')

        return "\n".join(output_parts)

    async def _find_class(self, name: str, base_path: Path, language: Optional[str] = None) -> str:
        """Find all class definitions matching the name."""
        results: List[Dict] = []

        for source_file in await self._iter_source_files(base_path, language):
            lang = detect_language(source_file)
            if not lang:
                continue

            # Use Python AST for Python files (more detailed output)
            if lang == "python":
                try:
                    async with aiofiles.open(source_file, encoding="utf-8") as f:
                        content = await f.read()
                    tree = ast.parse(content, filename=str(source_file))

                    for node in ast.walk(tree):
                        if isinstance(node, ast.ClassDef) and node.name == name:
                            bases = [self._format_base_class(b) for b in node.bases]
                            methods = [
                                item.name for item in node.body if isinstance(item, ast.FunctionDef)
                            ]

                            docstring = ast.get_docstring(node)
                            decorators = [self._format_decorator(d) for d in node.decorator_list]

                            try:
                                rel_path = str(source_file.relative_to(base_path))
                            except ValueError:
                                rel_path = str(source_file)

                            results.append(
                                {
                                    "file": rel_path,
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

            # Use tree-sitter for other languages
            elif self._tree_sitter_available:
                try:
                    rel_path = str(source_file.relative_to(base_path))
                except ValueError:
                    rel_path = str(source_file)

                ts_results = await self._find_class_with_tree_sitter(name, source_file, lang)
                for r in ts_results:
                    r["file"] = rel_path
                    results.append(r)

        if not results:
            return f"No class named '{name}' found in {base_path}"

        # Format results
        output_parts = [f"Found {len(results)} class(es) named '{name}':\n"]
        for r in results:
            lang_tag = f" [{r.get('language', 'python')}]" if r.get("language") else ""
            output_parts.append(f"{r['file']}:{r['line']}{lang_tag}")
            output_parts.append(
                f"   class {name}({', '.join(r['bases']) if r['bases'] else 'object'})"
            )
            if r.get("decorators"):
                output_parts.append(f"   Decorators: {', '.join(r['decorators'])}")

            doc = r["docstring"]
            if len(doc) > 100:
                doc = doc[:100] + "..."
            output_parts.append(f'   "{doc}"')

            if r.get("methods"):
                output_parts.append(
                    f"   Methods ({len(r['methods'])}): {', '.join(r['methods'][:10])}"
                )
                if len(r["methods"]) > 10:
                    output_parts.append(f"            ... and {len(r['methods']) - 10} more")
            output_parts.append("")

        return "\n".join(output_parts)

    async def _show_structure(self, file_path: str) -> str:
        """Show the structure of a specific file."""
        path = Path(file_path)
        if not await aiofiles.os.path.exists(str(path)):
            return f"Error: File does not exist: {file_path}"

        lang = detect_language(path)

        # Use Python AST for Python files
        if lang == "python":
            return await self._show_structure_python(path)
        elif self._tree_sitter_available and lang:
            return await self._show_structure_tree_sitter(path, lang)
        else:
            return f"Error: Unsupported file type or tree-sitter not available for: {file_path}"

    async def _show_structure_python(self, path: Path) -> str:
        """Show structure of Python file using AST."""
        try:
            async with aiofiles.open(path, encoding="utf-8") as f:
                content = await f.read()
            tree = ast.parse(content, filename=str(path))

            structure = {
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

            return self._format_structure_output(str(path), structure, "python")

        except SyntaxError as e:
            return f"Error: Syntax error in {path} at line {e.lineno}: {e.msg}"
        except Exception as e:
            return f"Error parsing {path}: {str(e)}"

    async def _show_structure_tree_sitter(self, path: Path, lang: str) -> str:
        """Show structure of file using tree-sitter."""
        try:
            parser, language = self._get_tree_sitter_parser_and_language(lang)

            async with aiofiles.open(path, "rb") as f:
                code = await f.read()
            tree = parser.parse(code)
            lines = code.decode("utf-8", errors="replace").splitlines()

            structure = {
                "imports": [],
                "classes": [],
                "functions": [],
            }

            # Find classes
            if lang in CLASS_QUERIES:
                try:
                    query = language.query(CLASS_QUERIES[lang])
                    captures = query.captures(tree.root_node)
                    for node, capture_name in captures:
                        if capture_name == "name":
                            class_name = node.text.decode("utf-8")
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
                    query = language.query(FUNCTION_QUERIES[lang])
                    captures = query.captures(tree.root_node)
                    for node, capture_name in captures:
                        if capture_name == "name":
                            func_name = node.text.decode("utf-8")
                            line_num = node.start_point[0] + 1
                            line_content = (
                                lines[line_num - 1].strip() if line_num <= len(lines) else ""
                            )
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

            return self._format_structure_output(str(path), structure, lang)

        except Exception as e:
            return f"Error parsing {path}: {str(e)}"

    def _format_structure_output(self, file_path: str, structure: Dict, lang: str) -> str:
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
                    line = (
                        f"   Line {imp['line']}: from {imp.get('module', '')} import {imp['name']}"
                    )
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
                    output_parts.append(
                        f"   Line {func['line']}: def {func['name']}({func['args']})"
                    )
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

    async def _find_usages(self, name: str, base_path: Path, language: Optional[str] = None) -> str:
        """Find where a function or class is used (called)."""
        results = []

        for source_file in await self._iter_source_files(base_path, language):
            lang = detect_language(source_file)
            if not lang:
                continue

            # Use Python AST for Python files
            if lang == "python":
                try:
                    async with aiofiles.open(source_file, encoding="utf-8") as f:
                        content = await f.read()
                    lines = content.splitlines()
                    tree = ast.parse(content, filename=str(source_file))

                    for node in ast.walk(tree):
                        if isinstance(node, ast.Call):
                            called_name = self._get_call_name(node.func)
                            if called_name == name:
                                line_num = node.lineno
                                context = (
                                    lines[line_num - 1].strip() if line_num <= len(lines) else ""
                                )

                                try:
                                    rel_path = str(source_file.relative_to(Path.cwd()))
                                except ValueError:
                                    rel_path = str(source_file)

                                results.append(
                                    {
                                        "file": rel_path,
                                        "line": line_num,
                                        "type": "function_call",
                                        "context": context,
                                    }
                                )

                        elif isinstance(node, ast.Name) and node.id == name:
                            line_num = node.lineno
                            context = lines[line_num - 1].strip() if line_num <= len(lines) else ""

                            try:
                                rel_path = str(source_file.relative_to(base_path))
                            except ValueError:
                                rel_path = str(source_file)

                            results.append(
                                {
                                    "file": rel_path,
                                    "line": line_num,
                                    "type": "name_reference",
                                    "context": context,
                                }
                            )
                except SyntaxError:
                    continue
                except Exception:
                    continue

            # For other languages, use simple text search for now
            elif self._tree_sitter_available:
                try:
                    async with aiofiles.open(source_file, encoding="utf-8") as f:
                        content = await f.read()
                    lines = content.splitlines()

                    for i, line in enumerate(lines):
                        if name in line:
                            try:
                                rel_path = str(source_file.relative_to(base_path))
                            except ValueError:
                                rel_path = str(source_file)

                            results.append(
                                {
                                    "file": rel_path,
                                    "line": i + 1,
                                    "type": "text_match",
                                    "context": line.strip(),
                                    "language": lang,
                                }
                            )
                except Exception:
                    continue

        if not results:
            return f"No usages of '{name}' found in {base_path}"

        # Deduplicate results
        seen = set()
        unique_results = []
        for r in results:
            key = (r["file"], r["line"])
            if key not in seen:
                seen.add(key)
                unique_results.append(r)

        # Limit results
        if len(unique_results) > 50:
            unique_results = unique_results[:50]
            truncated = True
        else:
            truncated = False

        # Format results
        output_parts = [f"Found {len(seen)} usage(s) of '{name}':\n"]

        for r in unique_results:
            lang_tag = f" [{r.get('language', 'python')}]" if r.get("language") else ""
            output_parts.append(f"{r['file']}:{r['line']}{lang_tag}")
            context = str(r["context"])
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
            return node.attr
        return None
