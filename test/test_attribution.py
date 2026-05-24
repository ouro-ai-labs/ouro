"""Tests for commit/PR attribution in the shell tool description."""

from ouro.capabilities.prompts.attribution import (
    COMMIT_TRAILER,
    PR_FOOTER,
    get_commit_and_pr_instructions,
)
from ouro.capabilities.tools.builtins.shell import ShellTool


class TestAttributionInstructions:
    """The standalone instruction builder."""

    def test_enabled_contains_both_trailers_and_examples(self):
        text = get_commit_and_pr_instructions(enabled=True)
        assert COMMIT_TRAILER in text
        assert PR_FOOTER in text
        # The <example> blocks are what the model copies when building commands.
        assert text.count("<example>") == 2
        assert "git commit" in text
        assert "gh pr create" in text

    def test_disabled_collapses_to_empty(self):
        assert get_commit_and_pr_instructions(enabled=False) == ""

    def test_trailer_constants(self):
        assert (
            COMMIT_TRAILER == "Co-Authored-By: ouro <197364660+ahahoul007@users.noreply.github.com>"
        )
        assert PR_FOOTER == "🤖 Generated with ouro (https://github.com/ouro-ai-labs/ouro)"


class TestShellToolDescription:
    """ShellTool.description wires the instructions in/out by the flag."""

    def test_default_includes_attribution(self):
        # Default-on so the SDK path (not just the CLI factory) is attributed.
        desc = ShellTool().description
        assert COMMIT_TRAILER in desc
        assert PR_FOOTER in desc

    def test_enabled_includes_attribution(self):
        desc = ShellTool(attribution_enabled=True).description
        assert "Execute shell commands" in desc
        assert COMMIT_TRAILER in desc

    def test_disabled_omits_attribution(self):
        desc = ShellTool(attribution_enabled=False).description
        assert "Execute shell commands" in desc
        assert "Co-Authored-By" not in desc
        assert "Generated with ouro" not in desc
