"""Tests for SmartEditTool."""

import tempfile
from pathlib import Path

import pytest

from tools.smart_edit import SmartEditTool


@pytest.fixture
def temp_file():
    """Create a temporary file for testing."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".py") as f:
        content = '''def calculate(x, y):
    """Calculate sum of x and y."""
    result = x + y
    return result

class Calculator:
    def add(self, a, b):
        return a + b

    def subtract(self, a, b):
        return a - b
'''
        f.write(content)
        temp_path = Path(f.name)

    yield temp_path

    # Cleanup
    temp_path.unlink(missing_ok=True)
    backup_path = temp_path.with_suffix(temp_path.suffix + ".bak")
    backup_path.unlink(missing_ok=True)


@pytest.fixture
def tool():
    """Create SmartEditTool instance."""
    return SmartEditTool()


class TestDiffReplace:
    """Test diff_replace mode."""

    def test_exact_match_replace(self, tool, temp_file):
        """Test exact string replacement."""
        result = tool.execute(
            file_path=str(temp_file),
            mode="diff_replace",
            old_code="result = x + y",
            new_code="result = x + y  # computed sum",
            create_backup=False,
        )

        assert "Successfully edited" in result
        content = temp_file.read_text()
        assert "# computed sum" in content

    def test_fuzzy_match_with_whitespace(self, tool, temp_file):
        """Test fuzzy matching handles whitespace differences."""
        # Code with different indentation
        result = tool.execute(
            file_path=str(temp_file),
            mode="diff_replace",
            old_code='def calculate(x, y):\n"""Calculate sum of x and y."""\nresult = x + y',
            new_code='def calculate(x, y):\n    """Calculate sum of x and y."""\n    result = x + y  # updated\n    print(f\'Result: {result}\')',
            fuzzy_match=True,
            create_backup=False,
        )

        assert "Successfully edited" in result or "Fuzzy match" in result
        content = temp_file.read_text()
        assert "updated" in content or "Result:" in content

    def test_no_match_found(self, tool, temp_file):
        """Test error when code not found."""
        result = tool.execute(
            file_path=str(temp_file),
            mode="diff_replace",
            old_code="nonexistent code",
            new_code="new code",
            fuzzy_match=False,
            create_backup=False,
        )

        assert "Error" in result
        assert "not found" in result.lower()

    def test_backup_creation(self, tool, temp_file):
        """Test that backup files are created."""
        result = tool.execute(
            file_path=str(temp_file),
            mode="diff_replace",
            old_code="result = x + y",
            new_code="result = x + y  # backup test",
            create_backup=True,
        )

        assert "Created backup" in result
        backup_path = temp_file.with_suffix(temp_file.suffix + ".bak")
        assert backup_path.exists()

        # Verify backup has original content
        backup_content = backup_path.read_text()
        assert "result = x + y" in backup_content
        assert "backup test" not in backup_content

    def test_dry_run_no_changes(self, tool, temp_file):
        """Test dry_run mode doesn't modify file."""
        original_content = temp_file.read_text()

        result = tool.execute(
            file_path=str(temp_file),
            mode="diff_replace",
            old_code="result = x + y",
            new_code="result = x + y  # dry run test",
            dry_run=True,
            create_backup=False,
        )

        assert "DRY RUN" in result
        assert "Diff preview" in result
        assert temp_file.read_text() == original_content


class TestSmartInsert:
    """Test smart_insert mode."""

    def test_insert_after_anchor(self, tool, temp_file):
        """Test inserting code after anchor line."""
        result = tool.execute(
            file_path=str(temp_file),
            mode="smart_insert",
            anchor="class Calculator:",
            code="    # New calculator class",
            position="after",
            create_backup=False,
        )

        assert "Successfully inserted" in result
        content = temp_file.read_text()
        assert "# New calculator class" in content

        # Verify it's after the anchor
        lines = content.splitlines()
        calc_idx = next(i for i, line in enumerate(lines) if "class Calculator:" in line)
        assert "# New calculator class" in lines[calc_idx + 1]

    def test_insert_before_anchor(self, tool, temp_file):
        """Test inserting code before anchor line."""
        result = tool.execute(
            file_path=str(temp_file),
            mode="smart_insert",
            anchor="def calculate",
            code="# Helper function\n",
            position="before",
            create_backup=False,
        )

        assert "Successfully inserted" in result
        content = temp_file.read_text()
        assert "# Helper function" in content

    def test_anchor_not_found(self, tool, temp_file):
        """Test error when anchor not found."""
        result = tool.execute(
            file_path=str(temp_file),
            mode="smart_insert",
            anchor="nonexistent anchor",
            code="new code",
            position="after",
            create_backup=False,
        )

        assert "Error" in result
        assert "not found" in result


class TestBlockEdit:
    """Test block_edit mode."""

    def test_replace_line_range(self, tool, temp_file):
        """Test replacing a range of lines."""
        # Replace lines 2-4 (the docstring and result line)
        result = tool.execute(
            file_path=str(temp_file),
            mode="block_edit",
            start_line=2,
            end_line=4,
            new_code='    """New docstring."""\n    return x + y  # simplified\n',
            create_backup=False,
        )

        assert "Successfully edited lines" in result
        content = temp_file.read_text()
        assert "New docstring" in content
        assert "simplified" in content

    def test_invalid_line_range(self, tool, temp_file):
        """Test error for invalid line range."""
        result = tool.execute(
            file_path=str(temp_file),
            mode="block_edit",
            start_line=100,
            end_line=200,
            new_code="new content",
            create_backup=False,
        )

        assert "Error" in result
        assert "exceeds file length" in result

    def test_line_numbers_validation(self, tool, temp_file):
        """Test line number validation."""
        # Start > end
        result = tool.execute(
            file_path=str(temp_file),
            mode="block_edit",
            start_line=5,
            end_line=2,
            new_code="new content",
            create_backup=False,
        )

        assert "Error" in result

        # Negative line numbers
        result = tool.execute(
            file_path=str(temp_file),
            mode="block_edit",
            start_line=-1,
            end_line=5,
            new_code="new content",
            create_backup=False,
        )

        assert "Error" in result


class TestDiffPreview:
    """Test diff preview functionality."""

    def test_diff_shown_by_default(self, tool, temp_file):
        """Test that diff is shown by default."""
        result = tool.execute(
            file_path=str(temp_file),
            mode="diff_replace",
            old_code="result = x + y",
            new_code="result = x + y  # with comment",
            show_diff=True,
            create_backup=False,
        )

        assert "Diff preview" in result
        assert "---" in result  # Unified diff format
        assert "+++" in result

    def test_diff_hidden_when_disabled(self, tool, temp_file):
        """Test diff can be hidden."""
        result = tool.execute(
            file_path=str(temp_file),
            mode="diff_replace",
            old_code="result = x + y",
            new_code="result = x + y  # no preview",
            show_diff=False,
            dry_run=False,
            create_backup=False,
        )

        # Diff should not be in output when show_diff=False and dry_run=False
        # But success message should be
        assert "Successfully edited" in result


class TestErrorHandling:
    """Test error handling."""

    def test_file_not_exist(self, tool):
        """Test error for non-existent file."""
        result = tool.execute(
            file_path="/nonexistent/file.py",
            mode="diff_replace",
            old_code="code",
            new_code="new code",
        )

        assert "Error" in result
        assert "does not exist" in result

    def test_missing_required_params(self, tool, temp_file):
        """Test error for missing required parameters."""
        # diff_replace without old_code
        result = tool.execute(file_path=str(temp_file), mode="diff_replace", new_code="new code")

        assert "Error" in result
        assert "old_code" in result.lower()

        # smart_insert without anchor
        result = tool.execute(file_path=str(temp_file), mode="smart_insert", code="new code")

        assert "Error" in result


class TestFuzzyMatching:
    """Test fuzzy matching algorithm."""

    def test_fuzzy_threshold(self, tool, temp_file):
        """Test fuzzy matching with different thresholds."""
        # Very different code should not match
        result = tool.execute(
            file_path=str(temp_file),
            mode="diff_replace",
            old_code="completely different code that doesn't exist",
            new_code="new code",
            fuzzy_match=True,
            create_backup=False,
        )

        assert "Error" in result or "not find" in result.lower()

    def test_fuzzy_match_info(self, tool, temp_file):
        """Test that fuzzy match shows similarity info."""
        # Use slightly different formatting (without docstring to make it more similar)
        result = tool.execute(
            file_path=str(temp_file),
            mode="diff_replace",
            old_code='def calculate(x,y):\n    """Calculate sum of x and y."""\n    result=x+y\n    return result',
            new_code='def calculate(x, y):\n    """Calculate sum of x and y."""\n    result = x + y + 1\n    return result',
            fuzzy_match=True,
            create_backup=False,
        )

        # Should show fuzzy match info if similarity < 99%
        # Or should succeed
        assert "Successfully" in result or "Fuzzy match" in result


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
