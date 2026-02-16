# Tooling Instructions (ouro/tools)

Note: `AGENTS.md` is a symlink to this file for compatibility with agents that look for `AGENTS.md`.

## Contract

- Tools must be deterministic and side-effect-aware; avoid surprising writes/commands.
- Keep tool outputs bounded; prefer summaries + pointers over dumping huge blobs.

## Change checklist

- If you add/remove a tool: update `main.py:create_agent()` and adjust tool-related tests.
- If you change file/shell/web tools: run targeted tests first (examples):
  - `./scripts/dev.sh test -q test/test_shell.py`
  - `./scripts/dev.sh test -q test/test_web_fetch.py`
  - `./scripts/dev.sh test -q test/test_tool_size_limits.py`

## Implementation style

- Keep parsing/validation close to the tool boundary.
- Prefer small, composable helpers over large monolith methods.
