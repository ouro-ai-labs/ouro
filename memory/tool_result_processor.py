"""Tool result processing with intelligent truncation and recovery suggestions.

This module provides unified tool result processing with:
- Bypass whitelist for tools that should never be truncated
- Intelligent recovery suggestions for truncated content
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from config import Config
from memory.code_extractor import CodeExtractor

logger = logging.getLogger(__name__)


@dataclass
class RecoveryMetadata:
    """Metadata extracted from tool results for recovery suggestions.

    Contains tool-specific information to help generate actionable
    recovery commands when content is truncated.
    """

    tool_name: str
    char_count: int
    line_count: int = 0

    # Tool-specific fields
    filename: Optional[str] = None  # read_file
    content_type: Optional[str] = None  # read_file, web_fetch
    structure: List[Tuple[str, str, int]] = field(
        default_factory=list
    )  # (type, name, line) for code

    # grep_content specific
    match_count: int = 0
    file_distribution: Dict[str, int] = field(default_factory=dict)  # file -> match count
    pattern: Optional[str] = None

    # execute_shell specific
    command: Optional[str] = None

    # web_search specific
    query: Optional[str] = None
    result_count: int = 0

    # web_fetch specific
    url: Optional[str] = None
    title: Optional[str] = None

    # glob_files specific
    file_count: int = 0
    common_prefixes: List[str] = field(default_factory=list)


class ToolResultProcessor:
    """Unified tool result processor.

    All tool result truncation/processing should go through this class.

    When content exceeds thresholds, it is truncated and recovery suggestions
    are added to guide users to access the full content via existing tools.
    """

    # Maximum characters to keep when truncating (recovery section is added after this)
    MAX_TRUNCATED_CHARS = 2000

    # Thresholds for truncation and recovery (must be > MAX_TRUNCATED_CHARS)
    RECOVERY_THRESHOLDS: Dict[str, int] = {
        "read_file": 3500,  # chars
        "grep_content": 3500,  # chars
        "execute_shell": 3500,  # chars
        "web_fetch": 5000,  # chars
        "web_search": 4000,  # chars
        "glob_files": 3500,  # chars
    }
    DEFAULT_RECOVERY_THRESHOLD = 3500  # chars

    # Tools that should never be truncated by default
    DEFAULT_BYPASS_TOOLS = {"manage_todo_list"}

    @classmethod
    def get_bypass_tools(cls) -> Set[str]:
        """Get tools that should never be truncated (default + Config)."""
        return cls.DEFAULT_BYPASS_TOOLS | set(Config.TOOL_RESULT_BYPASS_TOOLS)

    def __init__(self):
        """Initialize processor."""
        self.code_extractor = CodeExtractor()

    def process_result(
        self,
        tool_name: str,
        result: str,
        tool_context: Optional[Dict[str, Any]] = None,
    ) -> tuple[str, bool]:
        """Process tool result with truncation and recovery suggestions.

        Args:
            tool_name: Name of the tool that produced the result
            result: Raw tool result string
            tool_context: Optional dict with tool-specific context for recovery suggestions
                         Keys depend on tool: filename, pattern, command, query, url, etc.

        Returns:
            Tuple of (processed_result, was_modified)
            - was_modified: True if result was truncated
        """
        if tool_context is None:
            tool_context = {}

        # Bypass tools should never be truncated
        bypass_tools = self.get_bypass_tools()
        if tool_name in bypass_tools:
            logger.debug(f"Tool {tool_name} is in bypass list, returning as-is")
            return result, False

        # Check if truncation and recovery is needed
        if not self._should_include_recovery(tool_name, result, tool_context):
            return result, False

        # Extract metadata for recovery suggestions
        metadata = self._extract_metadata(tool_name, result, tool_context)

        # Truncate content
        truncated = result[: self.MAX_TRUNCATED_CHARS]
        if len(result) > self.MAX_TRUNCATED_CHARS:
            truncated += (
                f"\n\n[... {len(result) - self.MAX_TRUNCATED_CHARS} characters truncated ...]"
            )

        # Add recovery section
        recovery_section = self._format_recovery_section(metadata, tool_context)
        if recovery_section:
            truncated = truncated + "\n\n" + recovery_section

        logger.info(
            f"Processed {tool_name}: {len(result)} -> {len(truncated)} chars (truncated with recovery)"
        )

        return truncated, True

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count for text.

        Args:
            text: Text to estimate

        Returns:
            Estimated token count
        """
        return int(len(text) / 3.5)

    # ========== Recovery Section Methods ==========

    def _should_include_recovery(
        self, tool_name: str, result: str, tool_context: Dict[str, Any]
    ) -> bool:
        """Determine if recovery section should be included.

        Args:
            tool_name: Name of the tool
            result: Original result content
            tool_context: Tool-specific context

        Returns:
            True if recovery section should be added (result exceeds char threshold)
        """
        threshold = self.RECOVERY_THRESHOLDS.get(tool_name, self.DEFAULT_RECOVERY_THRESHOLD)
        return len(result) > threshold

    def _extract_metadata(
        self, tool_name: str, result: str, tool_context: Dict[str, Any]
    ) -> RecoveryMetadata:
        """Extract metadata from tool result for recovery suggestions.

        Args:
            tool_name: Name of the tool
            result: Original result content
            tool_context: Tool-specific context

        Returns:
            RecoveryMetadata with tool-specific information
        """
        lines = result.split("\n")
        metadata = RecoveryMetadata(
            tool_name=tool_name,
            char_count=len(result),
            line_count=len(lines),
        )

        # Dispatch to tool-specific extraction
        if tool_name == "read_file":
            self._extract_read_file_metadata(metadata, result, tool_context)
        elif tool_name == "grep_content":
            self._extract_grep_metadata(metadata, result, tool_context)
        elif tool_name == "execute_shell":
            self._extract_shell_metadata(metadata, result, tool_context)
        elif tool_name == "web_search":
            self._extract_web_search_metadata(metadata, result, tool_context)
        elif tool_name == "web_fetch":
            self._extract_web_fetch_metadata(metadata, result, tool_context)
        elif tool_name == "glob_files":
            self._extract_glob_metadata(metadata, result, tool_context)

        return metadata

    def _format_recovery_section(
        self, metadata: RecoveryMetadata, tool_context: Dict[str, Any]
    ) -> str:
        """Format recovery section based on tool type.

        Args:
            metadata: Extracted metadata
            tool_context: Tool-specific context

        Returns:
            Formatted recovery section string
        """
        # Dispatch to tool-specific formatter
        if metadata.tool_name == "read_file":
            return self._format_recovery_read_file(metadata, tool_context)
        elif metadata.tool_name == "grep_content":
            return self._format_recovery_grep(metadata, tool_context)
        elif metadata.tool_name == "execute_shell":
            return self._format_recovery_shell(metadata, tool_context)
        elif metadata.tool_name == "web_search":
            return self._format_recovery_web_search(metadata, tool_context)
        elif metadata.tool_name == "web_fetch":
            return self._format_recovery_web_fetch(metadata, tool_context)
        elif metadata.tool_name == "glob_files":
            return self._format_recovery_glob(metadata, tool_context)
        else:
            return self._format_recovery_default(metadata, tool_context)

    # ========== read_file Recovery ==========

    def _extract_read_file_metadata(
        self, metadata: RecoveryMetadata, result: str, tool_context: Dict[str, Any]
    ) -> None:
        """Extract metadata for read_file results."""
        metadata.filename = tool_context.get("filename", "")

        # Detect content type using CodeExtractor
        if metadata.filename:
            lang = self.code_extractor.detect_language(metadata.filename, result)
            if lang:
                metadata.content_type = "code"
                # Extract code structure (functions/classes with line numbers)
                definitions = self.code_extractor.extract_definitions(result, lang, max_items=20)
                metadata.structure = definitions
                return

        # Fallback: simple content type detection based on patterns
        if re.search(r"\b(ERROR|WARNING|INFO|DEBUG)\b", result):
            metadata.content_type = "log"
        elif result.strip().startswith(("{", "[")):
            metadata.content_type = "json"
        else:
            metadata.content_type = "text"

    def _format_recovery_read_file(
        self, metadata: RecoveryMetadata, tool_context: Dict[str, Any]
    ) -> str:
        """Format recovery section for read_file."""
        lines = []
        lines.append("--- Recovery Options ---")

        # File info
        filename = metadata.filename or tool_context.get("filename", "unknown")
        size_str = (
            f"{metadata.char_count:,}" if metadata.char_count > 1000 else str(metadata.char_count)
        )
        lines.append(f"File: {filename} | {metadata.line_count} lines, {size_str} chars")
        lines.append("")

        # Structure for code files
        if metadata.content_type == "code" and metadata.structure:
            lines.append("Structure:")
            for def_type, name, line_num in metadata.structure[:10]:
                lines.append(f"  - {def_type} {name} (line {line_num})")
            if len(metadata.structure) > 10:
                lines.append(f"  ... and {len(metadata.structure) - 10} more")
            lines.append("")

        # Recovery commands
        lines.append("Commands:")
        if metadata.structure:
            # Suggest grep for a function name
            first_def = metadata.structure[0]
            lines.append(f'  • grep_content(pattern="{first_def[1]}", path="{filename}")')
        else:
            lines.append(f'  • grep_content(pattern="keyword", path="{filename}")')
        lines.append(f"  • shell(command=\"sed -n '1,50p' {filename}\")  # First 50 lines")
        lines.append(f"  • shell(command=\"sed -n '100,150p' {filename}\")  # Lines 100-150")

        return "\n".join(lines)

    # ========== grep_content Recovery ==========

    def _extract_grep_metadata(
        self, metadata: RecoveryMetadata, result: str, tool_context: Dict[str, Any]
    ) -> None:
        """Extract metadata for grep_content results."""
        metadata.pattern = tool_context.get("pattern", "")

        # Parse grep output to count matches per file
        # Format: filename:line_number:content
        file_counts: Dict[str, int] = {}
        for line in result.split("\n"):
            match = re.match(r"^([^:]+):(\d+):", line)
            if match:
                filepath = match.group(1)
                file_counts[filepath] = file_counts.get(filepath, 0) + 1
                metadata.match_count += 1

        # Sort by match count descending
        metadata.file_distribution = dict(
            sorted(file_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        )

    def _format_recovery_grep(
        self, metadata: RecoveryMetadata, tool_context: Dict[str, Any]
    ) -> str:
        """Format recovery section for grep_content."""
        lines = []
        lines.append("--- Recovery Options ---")

        # Match info
        file_count = len(metadata.file_distribution)
        shown = min(metadata.match_count, 50)  # Assuming we showed ~50 matches
        lines.append(
            f"Searched: {file_count}+ files | {metadata.match_count} total matches | Showing first ~{shown}"
        )
        lines.append("")

        # Top files by match count
        if metadata.file_distribution:
            lines.append("Top files by matches:")
            for filepath, count in list(metadata.file_distribution.items())[:5]:
                lines.append(f"  - {filepath}: {count} matches")
            lines.append("")

        # Recovery commands
        pattern = metadata.pattern or tool_context.get("pattern", "pattern")
        lines.append("Commands:")
        if metadata.file_distribution:
            top_file = list(metadata.file_distribution.keys())[0]
            lines.append(
                f'  • grep_content(pattern="{pattern}", file_pattern="{top_file}", mode="with_context")'
            )
        lines.append(f'  • grep_content(pattern="{pattern}", max_matches_per_file=3)')

        return "\n".join(lines)

    # ========== execute_shell Recovery ==========

    def _extract_shell_metadata(
        self, metadata: RecoveryMetadata, result: str, tool_context: Dict[str, Any]
    ) -> None:
        """Extract metadata for execute_shell results."""
        metadata.command = tool_context.get("command", "")

    def _format_recovery_shell(
        self, metadata: RecoveryMetadata, tool_context: Dict[str, Any]
    ) -> str:
        """Format recovery section for execute_shell."""
        lines = []
        lines.append("--- Recovery Options ---")

        # Output info
        lines.append(f"Output: {metadata.line_count} lines, {metadata.char_count:,} chars")
        lines.append("")

        # Recovery commands
        cmd = metadata.command or tool_context.get("command", "command")
        # Escape single quotes in command
        cmd_escaped = cmd.replace("'", "'\"'\"'")
        lines.append("Commands:")
        lines.append(f'  • shell(command="{cmd_escaped} | head -n 50")')
        lines.append(f'  • shell(command="{cmd_escaped} | tail -n 50")')
        lines.append(f"  • shell(command=\"{cmd_escaped} | grep 'pattern'\")")

        return "\n".join(lines)

    # ========== web_search Recovery ==========

    def _extract_web_search_metadata(
        self, metadata: RecoveryMetadata, result: str, tool_context: Dict[str, Any]
    ) -> None:
        """Extract metadata for web_search results."""
        metadata.query = tool_context.get("query", "")

        # Count results (separated by ---)
        metadata.result_count = result.count("---") + 1

    def _format_recovery_web_search(
        self, metadata: RecoveryMetadata, tool_context: Dict[str, Any]
    ) -> str:
        """Format recovery section for web_search."""
        lines = []
        lines.append("--- Recovery Options ---")

        # Result info
        lines.append(f"Results: {metadata.result_count} shown (truncated)")
        lines.append("")

        # Recovery commands
        query = metadata.query or tool_context.get("query", "query")
        lines.append("Commands:")
        lines.append(f'  • web_search(query="{query} site:specific-domain.com")')
        lines.append(f'  • web_search(query="{query} filetype:pdf")')
        lines.append('  • web_fetch(url="<specific-result-url>") for full content')

        return "\n".join(lines)

    # ========== web_fetch Recovery ==========

    def _extract_web_fetch_metadata(
        self, metadata: RecoveryMetadata, result: str, tool_context: Dict[str, Any]
    ) -> None:
        """Extract metadata for web_fetch results."""
        metadata.url = tool_context.get("url", "")

        # Try to parse JSON response format
        try:
            data = json.loads(result)
            if isinstance(data, dict):
                metadata.title = data.get("title", "")
                output = data.get("output", "")
                metadata.char_count = len(output)
        except json.JSONDecodeError:
            # Not JSON, treat as raw content
            # Try to extract title from content
            title_match = re.search(r"^#\s+(.+)$", result, re.MULTILINE)
            if title_match:
                metadata.title = title_match.group(1)

    def _format_recovery_web_fetch(
        self, metadata: RecoveryMetadata, tool_context: Dict[str, Any]
    ) -> str:
        """Format recovery section for web_fetch."""
        lines = []
        lines.append("--- Recovery Options ---")

        # Page info
        title = metadata.title or "Unknown Page"
        lines.append(f"Page: {title} | {metadata.char_count:,} chars")
        if metadata.url:
            lines.append(f"URL: {metadata.url}")
        lines.append("")

        # Recovery commands
        url = metadata.url or tool_context.get("url", "<url>")
        # Extract domain from URL
        domain_match = re.search(r"https?://([^/]+)", url)
        domain = domain_match.group(1) if domain_match else "domain.com"

        lines.append("Commands:")
        lines.append(
            f'  • web_fetch(url="{url}", save_to="/tmp/page.md") '
            f'then grep_content(pattern="keyword", path="/tmp/page.md")'
        )
        lines.append(f'  • web_search(query="site:{domain} specific topic")')

        return "\n".join(lines)

    # ========== glob_files Recovery ==========

    def _extract_glob_metadata(
        self, metadata: RecoveryMetadata, result: str, tool_context: Dict[str, Any]
    ) -> None:
        """Extract metadata for glob_files results."""
        metadata.pattern = tool_context.get("pattern", "")

        # Count files and find common prefixes
        files = [line.strip() for line in result.split("\n") if line.strip()]
        metadata.file_count = len(files)

        # Find common directory prefixes
        if files:
            prefix_counts: Dict[str, int] = {}
            for f in files:
                # Get directory part
                parts = f.rsplit("/", 1)
                if len(parts) > 1:
                    prefix = parts[0]
                    prefix_counts[prefix] = prefix_counts.get(prefix, 0) + 1

            # Get top 3 prefixes
            sorted_prefixes = sorted(prefix_counts.items(), key=lambda x: x[1], reverse=True)
            metadata.common_prefixes = [p for p, _ in sorted_prefixes[:3]]

    def _format_recovery_glob(
        self, metadata: RecoveryMetadata, tool_context: Dict[str, Any]
    ) -> str:
        """Format recovery section for glob_files."""
        lines = []
        lines.append("--- Recovery Options ---")

        # File count
        shown = min(metadata.file_count, 50)  # Assuming we showed ~50 files
        lines.append(f"Found: {metadata.file_count} files | Showing first ~{shown}")
        lines.append("")

        # Common prefixes
        if metadata.common_prefixes:
            lines.append("Common directories:")
            for prefix in metadata.common_prefixes[:3]:
                lines.append(f"  - {prefix}/")
            lines.append("")

        # Recovery commands
        pattern = metadata.pattern or tool_context.get("pattern", "*.py")
        lines.append("Commands:")
        if metadata.common_prefixes:
            top_prefix = metadata.common_prefixes[0]
            lines.append(f'  • glob_files(pattern="{pattern}", path="{top_prefix}")')
        lines.append(f'  • glob_files(pattern="more_specific_{pattern}")')

        return "\n".join(lines)

    # ========== Default Recovery ==========

    def _format_recovery_default(
        self, metadata: RecoveryMetadata, tool_context: Dict[str, Any]
    ) -> str:
        """Format default recovery section for unknown tools."""
        lines = []
        lines.append("--- Recovery Options ---")
        lines.append(f"Output: {metadata.line_count} lines, {metadata.char_count:,} chars")
        lines.append("")
        lines.append("The output was truncated. Consider using more specific parameters")
        lines.append("or filtering the output with shell pipes (| head, | tail, | grep).")

        return "\n".join(lines)
