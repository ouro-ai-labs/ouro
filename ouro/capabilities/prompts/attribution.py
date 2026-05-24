"""Commit / PR attribution trailers for the shell tool description.

ouro identifies itself as the commit co-author and PR generator so the code
it ships stays traceable. Mirroring Claude Code's BashTool approach, the
trailers are interpolated into the shell tool's *description* rather than
applied via a git hook or post-processing step: the model copies the
``<example>`` blocks when it builds ``git commit`` / ``gh pr create``
commands, so the trailers land on every commit and PR it authors.

The attribution can be disabled (``ATTRIBUTION_ENABLED=false`` in
``~/.ouro/config``); when off, the whole section collapses out and the model
has no template prompting it to add the trailers.
"""

COMMIT_TRAILER = "Co-Authored-By: ouro <197364660+ouro-ai-lab@users.noreply.github.com>"
PR_FOOTER = "🤖 Generated with ouro (https://github.com/ouro-ai-labs/ouro)"


def get_commit_and_pr_instructions(enabled: bool = True) -> str:
    """Return the git-commit / PR attribution section for a tool description.

    Args:
        enabled: When False, return an empty string so the trailers (and the
            entire section) disappear cleanly.

    Returns:
        The instruction block, or ``""`` when attribution is disabled.
    """
    if not enabled:
        return ""

    return f"""# Committing changes with git

When you create a git commit, end the commit message with:

{COMMIT_TRAILER}

<example>
git commit -m "$(cat <<'EOF'
Commit message here.

{COMMIT_TRAILER}
EOF
)"
</example>

# Creating pull requests

When you create a pull request (e.g. with the gh CLI), end the PR body with:

{PR_FOOTER}

<example>
gh pr create --title "the pr title" --body "$(cat <<'EOF'
## Summary
<1-3 bullet points>

## Test plan
[Checklist of TODOs for testing the pull request...]

{PR_FOOTER}
EOF
)"
</example>"""
