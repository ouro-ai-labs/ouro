"""Code structure extraction using tree-sitter for multiple languages."""

import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Try to import tree-sitter, but make it optional
try:
    from tree_sitter_language_pack import get_language, get_parser

    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False
    logger.warning(
        "tree-sitter-language-pack not available. "
        "Install with: pip install tree-sitter-language-pack"
    )


class CodeExtractor:
    """Extract key structures from code files using tree-sitter.

    Supports 160+ languages including Python, JavaScript, Java, C++, Rust, Go, etc.
    Falls back to regex-based extraction if tree-sitter is not available.
    """

    # Language detection by file extension
    EXTENSION_TO_LANGUAGE = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".java": "java",
        ".c": "c",
        ".h": "c",
        ".cpp": "cpp",
        ".cc": "cpp",
        ".cxx": "cpp",
        ".hpp": "cpp",
        ".rs": "rust",
        ".go": "go",
        ".rb": "ruby",
        ".php": "php",
        ".swift": "swift",
        ".kt": "kotlin",
        ".cs": "c_sharp",
        ".scala": "scala",
        ".sh": "bash",
        ".bash": "bash",
        ".zsh": "bash",
        ".lua": "lua",
        ".r": "r",
        ".R": "r",
        ".sql": "sql",
        ".html": "html",
        ".css": "css",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".toml": "toml",
        ".xml": "xml",
        ".md": "markdown",
    }

    # Tree-sitter queries for extracting definitions
    # These queries work across multiple languages with similar syntax
    QUERIES = {
        "python": """
            (function_definition
              name: (identifier) @name) @definition.function

            (class_definition
              name: (identifier) @name) @definition.class

            (import_statement) @import
            (import_from_statement) @import

            (decorated_definition) @decorator
        """,
        "javascript": """
            (function_declaration
              name: (identifier) @name) @definition.function

            (class_declaration
              name: (identifier) @name) @definition.class

            (method_definition
              name: (property_identifier) @name) @definition.method

            (import_statement) @import
            (export_statement) @export
        """,
        "typescript": """
            (function_declaration
              name: (identifier) @name) @definition.function

            (class_declaration
              name: (type_identifier) @name) @definition.class

            (method_definition
              name: (property_identifier) @name) @definition.method

            (interface_declaration
              name: (type_identifier) @name) @definition.interface

            (type_alias_declaration
              name: (type_identifier) @name) @definition.type

            (import_statement) @import
        """,
        "java": """
            (method_declaration
              name: (identifier) @name) @definition.method

            (class_declaration
              name: (identifier) @name) @definition.class

            (interface_declaration
              name: (identifier) @name) @definition.interface

            (import_declaration) @import
        """,
        "rust": """
            (function_item
              name: (identifier) @name) @definition.function

            (struct_item
              name: (type_identifier) @name) @definition.struct

            (enum_item
              name: (type_identifier) @name) @definition.enum

            (trait_item
              name: (type_identifier) @name) @definition.trait

            (impl_item) @definition.impl

            (use_declaration) @import
        """,
        "go": """
            (function_declaration
              name: (identifier) @name) @definition.function

            (method_declaration
              name: (field_identifier) @name) @definition.method

            (type_declaration) @definition.type

            (import_declaration) @import
        """,
        "cpp": """
            (function_definition
              declarator: (function_declarator
                declarator: (identifier) @name)) @definition.function

            (class_specifier
              name: (type_identifier) @name) @definition.class

            (struct_specifier
              name: (type_identifier) @name) @definition.struct

            (preproc_include) @import
        """,
    }

    def __init__(self):
        """Initialize code extractor."""
        self.parsers: Dict[str, any] = {}
        self.languages: Dict[str, any] = {}

    def detect_language(self, filename: str, content: str) -> Optional[str]:
        """Detect programming language from filename or content.

        Args:
            filename: Name of the file
            content: File content

        Returns:
            Language name or None if not detected
        """
        # Try extension first
        for ext, lang in self.EXTENSION_TO_LANGUAGE.items():
            if filename.endswith(ext):
                return lang

        # Try shebang for scripts
        if content.startswith("#!"):
            first_line = content.split("\n")[0].lower()
            if "python" in first_line:
                return "python"
            elif "node" in first_line or "javascript" in first_line:
                return "javascript"
            elif "bash" in first_line or "sh" in first_line:
                return "bash"
            elif "ruby" in first_line:
                return "ruby"

        return None

    def _get_parser(self, language: str):
        """Get or create parser for language.

        Args:
            language: Language name

        Returns:
            Parser instance or None if not available
        """
        if not TREE_SITTER_AVAILABLE:
            return None

        if language not in self.parsers:
            try:
                self.parsers[language] = get_parser(language)
                self.languages[language] = get_language(language)
                logger.debug(f"Loaded tree-sitter parser for {language}")
            except Exception as e:
                logger.warning(f"Failed to load parser for {language}: {e}")
                return None

        return self.parsers.get(language)

    def extract_definitions(
        self, content: str, language: str, max_items: int = 100
    ) -> List[Tuple[int, str, str]]:
        """Extract function/class definitions from code.

        Args:
            content: Source code content
            language: Programming language
            max_items: Maximum number of items to extract

        Returns:
            List of (line_number, type, line_content) tuples
        """
        if not TREE_SITTER_AVAILABLE:
            return self._extract_definitions_regex(content, language, max_items)

        parser = self._get_parser(language)
        if not parser:
            return self._extract_definitions_regex(content, language, max_items)

        try:
            # Parse the code
            tree = parser.parse(bytes(content, "utf8"))
            root_node = tree.root_node

            # Get query for this language
            query_text = self.QUERIES.get(language)
            if not query_text:
                # Fallback to regex for unsupported languages
                return self._extract_definitions_regex(content, language, max_items)

            # Execute query
            lang = self.languages[language]
            query = lang.query(query_text)
            captures = query.captures(root_node)

            # Extract definitions with line numbers
            definitions = []
            lines = content.split("\n")

            for node, capture_name in captures:
                if len(definitions) >= max_items:
                    break

                line_num = node.start_point[0]
                if line_num < len(lines):
                    line_content = lines[line_num].strip()

                    # Determine type from capture name
                    if "function" in capture_name:
                        def_type = "function"
                    elif "class" in capture_name:
                        def_type = "class"
                    elif "method" in capture_name:
                        def_type = "method"
                    elif "import" in capture_name:
                        def_type = "import"
                    elif "struct" in capture_name:
                        def_type = "struct"
                    elif "interface" in capture_name:
                        def_type = "interface"
                    elif "type" in capture_name:
                        def_type = "type"
                    else:
                        def_type = "definition"

                    definitions.append((line_num + 1, def_type, line_content))

            return definitions

        except Exception as e:
            logger.warning(f"Tree-sitter extraction failed for {language}: {e}")
            return self._extract_definitions_regex(content, language, max_items)

    def _extract_definitions_regex(
        self, content: str, language: str, max_items: int
    ) -> List[Tuple[int, str, str]]:
        """Fallback regex-based extraction for when tree-sitter is unavailable.

        Args:
            content: Source code content
            language: Programming language
            max_items: Maximum number of items to extract

        Returns:
            List of (line_number, type, line_content) tuples
        """
        import re

        lines = content.split("\n")
        definitions = []

        # Language-specific patterns
        patterns = {
            "python": [
                (r"^\s*def\s+\w+", "function"),
                (r"^\s*async\s+def\s+\w+", "function"),
                (r"^\s*class\s+\w+", "class"),
                (r"^\s*@\w+", "decorator"),
                (r"^\s*(import\s+|from\s+.*\s+import\s+)", "import"),
            ],
            "javascript": [
                (r"^\s*function\s+\w+", "function"),
                (r"^\s*class\s+\w+", "class"),
                (r"^\s*const\s+\w+\s*=\s*\(.*\)\s*=>", "function"),
                (r"^\s*(import\s+|export\s+)", "import"),
            ],
            "typescript": [
                (r"^\s*function\s+\w+", "function"),
                (r"^\s*class\s+\w+", "class"),
                (r"^\s*interface\s+\w+", "interface"),
                (r"^\s*type\s+\w+", "type"),
                (r"^\s*(import\s+|export\s+)", "import"),
            ],
            "java": [
                (r"^\s*(public|private|protected)?\s*(static)?\s*\w+\s+\w+\s*\(", "method"),
                (r"^\s*(public|private|protected)?\s*class\s+\w+", "class"),
                (r"^\s*(public|private|protected)?\s*interface\s+\w+", "interface"),
                (r"^\s*import\s+", "import"),
            ],
            "rust": [
                (r"^\s*fn\s+\w+", "function"),
                (r"^\s*struct\s+\w+", "struct"),
                (r"^\s*enum\s+\w+", "enum"),
                (r"^\s*trait\s+\w+", "trait"),
                (r"^\s*impl\s+", "impl"),
                (r"^\s*use\s+", "import"),
            ],
            "go": [
                (r"^\s*func\s+\w+", "function"),
                (r"^\s*func\s+\(.*\)\s+\w+", "method"),
                (r"^\s*type\s+\w+\s+struct", "struct"),
                (r"^\s*type\s+\w+\s+interface", "interface"),
                (r"^\s*import\s+", "import"),
            ],
            "cpp": [
                (r"^\s*\w+\s+\w+\s*\(.*\)\s*\{?", "function"),
                (r"^\s*class\s+\w+", "class"),
                (r"^\s*struct\s+\w+", "struct"),
                (r"^\s*#include\s+", "import"),
            ],
        }

        # Get patterns for this language, or use Python as default
        lang_patterns = patterns.get(language, patterns["python"])

        for i, line in enumerate(lines):
            if len(definitions) >= max_items:
                break

            for pattern, def_type in lang_patterns:
                if re.match(pattern, line):
                    definitions.append((i + 1, def_type, line.strip()))
                    break

        return definitions

    def format_extracted_code(self, content: str, filename: str, max_tokens: int) -> str:
        """Format extracted code with key definitions.

        Args:
            content: Source code content
            filename: Name of the file
            max_tokens: Maximum tokens to use

        Returns:
            Formatted string with key sections
        """
        max_chars = int(max_tokens * 3.5)

        # Detect language
        language = self.detect_language(filename, content)
        if not language:
            # Can't detect language, return truncated content
            return content[:max_chars]

        # Extract definitions
        definitions = self.extract_definitions(content, language, max_items=200)

        if not definitions:
            # No definitions found, return truncated content
            return content[:max_chars]

        # Format output
        lines = content.split("\n")
        output_lines = []
        current_size = 0

        header = f"[Key sections extracted from {language} code - {len(lines) - len(definitions)} lines omitted]\n\n"
        current_size += len(header)

        for line_num, def_type, line_content in definitions:
            formatted = f"{line_num:4d}: {line_content}"
            if current_size + len(formatted) < max_chars:
                output_lines.append(formatted)
                current_size += len(formatted) + 1
            else:
                break

        footer = f"\n\n[Extracted {len(output_lines)} {language} definitions. Use read_file with line ranges for full content]"

        return header + "\n".join(output_lines) + footer
