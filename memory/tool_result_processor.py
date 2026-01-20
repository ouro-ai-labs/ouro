"""Tool result processing for intelligent summarization and truncation.

This module provides unified tool result processing with:
- Intelligent truncation strategies based on tool type
- Error-aware processing (preserves error messages)
- Bypass whitelist for tools that should never be truncated
- Automatic tracking of modifications for external storage
"""

import logging
import re
from typing import Dict, Set, Union

from config import Config
from memory.code_extractor import CodeExtractor

logger = logging.getLogger(__name__)


class ToolResultProcessor:
    """Unified tool result processor.

    All tool result truncation/processing should go through this class.

    Provides different strategies for different tool types:
    - extract_key_sections: For code files, extract imports, definitions, key logic
    - preserve_matches: For search results, keep all matches with minimal context
    - preserve_errors: For error outputs, preserve tail where errors usually appear
    - summarize_output: For complex outputs, use LLM to generate summary
    - smart_truncate: For general content, preserve head and tail
    """

    # Tool-specific processing strategies
    # If a tool is not listed here, DEFAULT_MAX_TOKENS will be used
    TOOL_STRATEGIES: Dict[str, Dict[str, Union[int, str]]] = {
        "read_file": {
            "max_tokens": 1000,
            "strategy": "extract_key_sections",
        },
        "grep_content": {
            "max_tokens": 800,
            "strategy": "preserve_matches",
        },
        "execute_shell": {
            "max_tokens": 500,
            "strategy": "smart_truncate",
        },
        "web_search": {
            "max_tokens": 1200,
            "strategy": "smart_truncate",
        },
        "web_fetch": {
            "max_tokens": 1500,
            "strategy": "summarize_output",
        },
        "glob_files": {
            "max_tokens": 600,
            "strategy": "smart_truncate",
        },
        # Internal: subtask result processing
        "_subtask_result": {
            "max_tokens": 800,
            "strategy": "smart_truncate",
        },
    }

    # Default max tokens for tools not in TOOL_STRATEGIES
    DEFAULT_MAX_TOKENS = 1000

    @classmethod
    def get_bypass_tools(cls) -> Set[str]:
        """Get tools that should never be truncated (from Config)."""
        return set(Config.TOOL_RESULT_BYPASS_TOOLS)

    # Default threshold for external storage (tokens)
    DEFAULT_STORAGE_THRESHOLD = 10000

    def __init__(
        self,
        storage_threshold: int = DEFAULT_STORAGE_THRESHOLD,
        summary_model: str = None,
    ):
        """Initialize processor.

        Args:
            storage_threshold: Token threshold for recommending external storage
            summary_model: Optional model name for LLM summarization (e.g., "openai/gpt-4o-mini")
                          If None, LLM summarization is disabled and falls back to smart_truncate.
        """
        self.storage_threshold = storage_threshold
        self.summary_model = summary_model
        self.code_extractor = CodeExtractor()

    def process_result(
        self,
        tool_name: str,
        result: str,
        context: str = "",
        filename: str = "",
    ) -> tuple[str, bool]:
        """Process tool result with appropriate strategy.

        This is the unified entry point for all tool result processing.

        Args:
            tool_name: Name of the tool that produced the result
            result: Raw tool result string
            context: Optional context about the task (for intelligent summarization)
            filename: Optional filename for language detection (used by extract_key_sections)

        Returns:
            Tuple of (processed_result, was_modified)
            - was_modified: True if result was truncated/processed, indicating original should be stored
        """
        # Bypass tools should never be truncated
        bypass_tools = self.get_bypass_tools()
        if tool_name in bypass_tools:
            logger.debug(f"Tool {tool_name} is in bypass list, returning as-is")
            return result, False

        # Get max tokens from tool config or use default
        tool_config = self.TOOL_STRATEGIES.get(tool_name, {})
        max_tokens = int(tool_config.get("max_tokens", self.DEFAULT_MAX_TOKENS))

        # Estimate tokens (rough: 3.5 chars per token)
        estimated_tokens = len(result) / 3.5

        # If result is small enough, return as-is (was_modified=False)
        if estimated_tokens <= max_tokens:
            return result, False

        # Result needs processing - was_modified will be True
        strategy = self._get_strategy(tool_name)

        # Check for error content - use error-preserving strategy
        if self._contains_error(result):
            processed = self._preserve_errors(result, max_tokens)
            strategy_used = "preserve_errors"
        elif strategy == "extract_key_sections":
            processed = self._extract_key_sections(result, max_tokens, filename)
            strategy_used = strategy
        elif strategy == "preserve_matches":
            processed = self._preserve_matches(result, max_tokens)
            strategy_used = strategy
        elif strategy == "summarize_output" and self.summary_model:
            processed = self._summarize_with_llm(result, max_tokens, context)
            strategy_used = strategy
        else:
            processed = self._smart_truncate(result, max_tokens)
            strategy_used = "smart_truncate"

        logger.info(
            f"Processed {tool_name}: {int(estimated_tokens)} -> "
            f"{int(len(processed) / 3.5)} tokens (strategy: {strategy_used}, was_modified=True)"
        )

        return processed, True

    def _get_strategy(self, tool_name: str) -> str:
        """Get processing strategy for tool.

        Args:
            tool_name: Name of the tool

        Returns:
            Strategy name
        """
        tool_config = self.TOOL_STRATEGIES.get(tool_name, {})
        return str(tool_config.get("strategy", "smart_truncate"))

    def _contains_error(self, content: str) -> bool:
        """Check if content contains error indicators.

        Args:
            content: Content to check

        Returns:
            True if content appears to contain errors
        """
        error_indicators = [
            "error:",
            "exception:",
            "traceback",
            "failed:",
            "Error:",
            "Exception:",
            "FAILED",
            "panic:",
            "fatal:",
            "Fatal:",
            "FATAL",
            "Errno",
            "TypeError:",
            "ValueError:",
            "KeyError:",
            "AttributeError:",
            "ImportError:",
            "ModuleNotFoundError:",
            "FileNotFoundError:",
            "PermissionError:",
            "ConnectionError:",
            "TimeoutError:",
        ]
        content_lower = content.lower()
        return any(ind.lower() in content_lower for ind in error_indicators)

    def _preserve_errors(self, content: str, max_tokens: int) -> str:
        """Preserve errors strategy - keeps more tail content where errors usually appear.

        Args:
            content: Content to process
            max_tokens: Token budget

        Returns:
            Processed content with errors preserved
        """
        max_chars = int(max_tokens * 3.5)

        if len(content) <= max_chars:
            return content

        # Error messages are usually at the tail, so preserve more tail
        head_chars = int(max_chars * 0.30)  # 30% head
        tail_chars = int(max_chars * 0.60)  # 60% tail (errors)

        head_part = content[:head_chars]
        tail_part = content[-tail_chars:]

        # Try to break at line boundaries
        last_newline = head_part.rfind("\n")
        if last_newline > head_chars * 0.7:
            head_part = head_part[:last_newline]

        first_newline = tail_part.find("\n")
        if 0 < first_newline < tail_chars * 0.2:
            tail_part = tail_part[first_newline + 1 :]

        omitted_chars = len(content) - len(head_part) - len(tail_part)

        return (
            head_part
            + f"\n\n[... {omitted_chars} characters omitted (error detected, tail preserved) ...]\n\n"
            + tail_part
        )

    def _extract_key_sections(self, content: str, max_tokens: int, filename: str = "") -> str:
        """Extract key sections from code files using CodeExtractor.

        Uses tree-sitter for accurate multi-language parsing when available,
        with regex fallback for unsupported languages.

        Preserves:
        - Import statements
        - Class and function definitions
        - Key structural elements (structs, interfaces, traits, etc.)

        Omits:
        - Long comments and docstrings
        - Repetitive code blocks

        Args:
            content: Source code content
            max_tokens: Maximum tokens to use
            filename: Optional filename for language detection
        """
        # Try to detect language from filename
        language = self.code_extractor.detect_language(filename, content) if filename else None

        # If we can detect the language, use CodeExtractor's format_extracted_code
        if language:
            return self.code_extractor.format_extracted_code(content, filename, max_tokens)

        # Fallback: try to detect language from content (e.g., shebang)
        language = self.code_extractor.detect_language("", content)
        if language:
            # Create a dummy filename with the right extension
            ext_map = {v: k for k, v in self.code_extractor.EXTENSION_TO_LANGUAGE.items()}
            dummy_ext = ext_map.get(language, ".py")
            return self.code_extractor.format_extracted_code(
                content, f"file{dummy_ext}", max_tokens
            )

        # Final fallback: use simple Python-focused regex extraction
        return self._extract_key_sections_regex(content, max_tokens)

    def _extract_key_sections_regex(self, content: str, max_tokens: int) -> str:
        """Fallback regex-based extraction for unknown languages.

        Uses simple Python-like patterns as a reasonable default.

        Args:
            content: Source code content
            max_tokens: Maximum tokens to use
        """
        max_chars = int(max_tokens * 3.5)
        lines = content.split("\n")

        # Patterns to identify important lines (Python-focused but catches common patterns)
        important_patterns = [
            r"^\s*import\s+",  # imports
            r"^\s*from\s+.*\s+import\s+",  # from imports
            r"^\s*class\s+\w+",  # class definitions
            r"^\s*def\s+\w+",  # function definitions
            r"^\s*async\s+def\s+\w+",  # async function definitions
            r"^\s*@\w+",  # decorators
            r"^\s*function\s+\w+",  # JS/TS functions
            r"^\s*const\s+\w+\s*=\s*\(.*\)\s*=>",  # arrow functions
            r"^\s*interface\s+\w+",  # TS interfaces
            r"^\s*type\s+\w+",  # TS type aliases
            r"^\s*fn\s+\w+",  # Rust functions
            r"^\s*struct\s+\w+",  # Rust/Go structs
            r"^\s*impl\s+",  # Rust impl blocks
            r"^\s*func\s+",  # Go functions
            r"^\s*#include\s+",  # C/C++ includes
        ]

        important_lines = []
        current_size = 0

        for i, line in enumerate(lines):
            # Check if line matches important patterns
            is_important = any(re.match(pattern, line) for pattern in important_patterns)

            if is_important:
                # Add line with line number
                line_with_num = f"{i+1:4d}: {line}"
                if current_size + len(line_with_num) < max_chars:
                    important_lines.append(line_with_num)
                    current_size += len(line_with_num) + 1
                else:
                    break

        if not important_lines:
            # Fallback to smart truncate if no important lines found
            return self._smart_truncate(content, max_tokens)

        result = "\n".join(important_lines)
        omitted_lines = len(lines) - len(important_lines)

        return (
            f"[Key sections extracted - {omitted_lines} lines omitted]\n\n"
            + result
            + "\n\n[Use read_file with specific line ranges for full content]"
        )

    def _preserve_matches(self, content: str, max_tokens: int) -> str:
        """Preserve search matches with minimal context.

        For grep/search results, keeps all matching lines with line numbers.
        """
        max_chars = int(max_tokens * 3.5)
        lines = content.split("\n")

        # Try to keep all lines if possible
        if len(content) <= max_chars:
            return content

        # If too large, keep first N matches
        preserved_lines = []
        current_size = 0
        match_count = 0

        for line in lines:
            if current_size + len(line) < max_chars:
                preserved_lines.append(line)
                current_size += len(line) + 1
                if ":" in line:  # Likely a match line (file:line:content)
                    match_count += 1
            else:
                break

        omitted = len(lines) - len(preserved_lines)
        result = "\n".join(preserved_lines)

        if omitted > 0:
            result += f"\n\n[... {omitted} more lines omitted. Use more specific search patterns.]"

        return result

    def _summarize_with_llm(self, content: str, max_tokens: int, context: str) -> str:
        """Use configured LLM model to generate intelligent summary.

        Args:
            content: Content to summarize
            max_tokens: Target token limit for summary
            context: Task context for relevance-aware summarization

        Returns:
            Summarized content or smart_truncate fallback on error
        """
        if not self.summary_model:
            return self._smart_truncate(content, max_tokens)

        try:
            import litellm

            # Limit input to avoid excessive costs (10k chars ~ 2.5k tokens)
            input_limit = 10000
            truncated_content = content[:input_limit]
            if len(content) > input_limit:
                truncated_content += f"\n\n[... {len(content) - input_limit} more characters]"

            prompt = f"""Summarize this tool output concisely, focusing on key information.
Context: {context if context else 'general task'}

Output to summarize:
{truncated_content}

Provide a concise summary (target: {max_tokens} tokens) that captures the essential information."""

            response = litellm.completion(
                model=self.summary_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens * 2,
            )
            summary = response.choices[0].message.content

            return f"[Summary by {self.summary_model}]\n\n{summary}"

        except Exception as e:
            logger.warning(
                f"LLM summarization failed ({self.summary_model}): {e}, falling back to truncation"
            )
            return self._smart_truncate(content, max_tokens)

    def _smart_truncate(self, content: str, max_tokens: int) -> str:
        """Smart truncation preserving head and tail.

        Keeps first 65% and last 30% of allowed content (was 60%/20%).
        This preserves context from both beginning and end, utilizing full budget.
        """
        max_chars = int(max_tokens * 3.5)

        if len(content) <= max_chars:
            return content

        # Calculate split points - use 65% + 30% = 95% of budget
        head_chars = int(max_chars * 0.65)
        tail_chars = int(max_chars * 0.30)

        # Try to break at line boundaries
        head_part = content[:head_chars]
        tail_part = content[-tail_chars:]

        # Find last newline in head
        last_newline = head_part.rfind("\n")
        if last_newline > head_chars * 0.8:  # If newline is reasonably close
            head_part = head_part[:last_newline]

        # Find first newline in tail
        first_newline = tail_part.find("\n")
        if first_newline > 0 and first_newline < tail_chars * 0.2:
            tail_part = tail_part[first_newline + 1 :]

        omitted_chars = len(content) - len(head_part) - len(tail_part)

        return head_part + f"\n\n[... {omitted_chars} characters omitted ...]\n\n" + tail_part

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count for text.

        Args:
            text: Text to estimate

        Returns:
            Estimated token count
        """
        return int(len(text) / 3.5)
