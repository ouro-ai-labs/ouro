# TUI Instructions (ouro/utils/tui)

Note: `AGENTS.md` is a symlink to this file for compatibility with agents that look for `AGENTS.md`.

## UX stability

- Avoid breaking keybindings/commands; update docs/tests when behavior changes.
- Keep rendering responsive; avoid blocking work on the UI path.

## Tests

- Run targeted TUI/autocomplete/skills tests when relevant:
  - `./scripts/dev.sh test -q test/test_skills_render.py`
  - `./scripts/dev.sh test -q test/test_slash_autocomplete_engine.py`
  - `./scripts/dev.sh test -q test/test_slash_command_autocomplete.py`
