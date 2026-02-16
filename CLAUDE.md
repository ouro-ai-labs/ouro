# ouro — Agent Instructions

This file defines the **operational workflow** for making changes in this repo (how to set up, run, test, format, build, and publish). Keep it short, specific, and executable; link to docs for long explanations.

Note: `AGENTS.md` is a symlink to this file (`CLAUDE.md`) for compatibility with multiple agent/rules systems.

Prerequisites: Python 3.12+ and `uv` (https://github.com/astral-sh/uv).

## Command Discovery (No Guessing)

**IMPORTANT**: Never assume a CLI flag or dev command exists.

- For ouro CLI flags: run `python main.py -h` (and `python main.py --mode interactive -h` if relevant).
- For repo workflow commands: run `./scripts/dev.sh --help`.

## Core Workflow (Verify → Explore → Plan → Implement → Ship)

This repo expects a verification-driven workflow:

- **Verify**: always define how correctness will be checked (tests, expected output, smoke command).
- **Explore**: read/grep before editing; confirm where the behavior lives.
- **Plan**: for multi-file or unfamiliar areas, write a short step plan + test plan before changing code.
- **Implement**: make the smallest change that satisfies acceptance criteria; keep diffs reviewable.
- **Ship**: run self-review protocol + update PR summary/checklist.

Skip the explicit plan only when the change is truly tiny and local (e.g., typo, small refactor in one file).

## Quickstart (Local Dev)

```bash
./scripts/bootstrap.sh
source .venv/bin/activate
./scripts/dev.sh test
```

Optional (recommended): enable git hooks:

```bash
pre-commit install
```

## Scoped Instructions (Read When Touching These Areas)

This repo uses directory-scoped rule files for focus. If you modify code/docs under these paths, also read the matching file first:

- `agent/CLAUDE.md` (runtime/loop safety + verification)
- `tools/CLAUDE.md` (tool contracts + targeted tests)
- `llm/CLAUDE.md` (provider safety + timeouts)
- `memory/CLAUDE.md` (serialization invariants + memory suite)
- `utils/tui/CLAUDE.md` (TUI UX stability + autocomplete/skills tests)
- `rfc/CLAUDE.md` (RFC writing discipline + template)
- `docs/CLAUDE.md` (docs consistency/executable examples)
- `test/CLAUDE.md` (test strategy + integration gating)

## Prompting Template (Use This With Agents)

When asking an agent to make changes, prefer this structure:

- **Goal**: what user-visible behavior changes?
- **Non-goals**: what must *not* change?
- **Where**: file(s) / module(s) to inspect first.
- **Acceptance criteria**: concrete, testable statements.
- **Verification**: which targeted tests to run + one real smoke run when relevant.

## Branching Workflow

**IMPORTANT**: Every change must be developed on a new branch using a git worktree, then merged into `main` via pull request.

1. Create a worktree with a new branch: `git worktree add ../ouro-<branch-name> -b <branch-name>`
2. Work in the worktree directory, commit changes there.
3. Push the branch and open a PR to merge into `main`.
4. After the PR is merged, clean up: `git worktree remove ../ouro-<branch-name>`

Never commit directly to `main`. All changes go through PR review.

### Worktree Env (Recommended)

Worktrees don't automatically share `.venv`. To avoid re-running bootstrap for every worktree, create the env once in the main checkout, then symlink it in each worktree:

```bash
# main checkout
cd /path/to/ouro
./scripts/bootstrap.sh

# each worktree (example: ../ouro-my-branch)
cd /path/to/ouro-my-branch
ln -s ../ouro/.venv .venv
# Point the editable install at *this* worktree (fast; doesn't reinstall deps).
./scripts/dev.sh install
./scripts/dev.sh check
```

## Checkpoint Commits

Prefer small, reviewable commits:
- Before committing, run `./scripts/dev.sh check` (precommit + typecheck + tests).
- Keep mechanical changes (formatting, renames) in their own commit when possible.
- **Human-in-the-loop**: at key checkpoints, the agent should *ask* whether to `git commit` and/or `git push` (do not do it automatically).
- Before asking to commit, show a short change summary (e.g. `git diff --stat`) and the `./scripts/dev.sh check` result.

## Permissions / Approval Boundaries

Allowed without prompting:
- Read files, list directories, search (`rg`).
- Run targeted unit tests or formatting/lint via `./scripts/dev.sh …`.

Require explicit confirmation first:
- Publishing (`./scripts/dev.sh publish`) or release actions.
- Git operations that change remote history (`git push`, opening PRs).
- Running live-LLM integration tests (`RUN_INTEGRATION_TESTS=1`) due to cost.
- Deleting large amounts of files or doing broad refactors/renames.

## Ship / Self-Review (Prefer One Command)

- Run `./scripts/dev.sh self-review`.
- Note: `self-review` runs **tracked** tests by default; `git add` new tests before running it.
- If behavior changed, run one real smoke command: `python main.py --task "<...>" --verify` (or interactive).
- Update PR body: `./scripts/dev.sh pr-body > /tmp/pr.md` and fill the checklist in `.github/pull_request_template.md`.

## Context Hygiene (Avoid Token/Attention Waste)

- Prefer targeted file reads and `rg` over dumping large logs/blobs into chat.
- When you must include outputs, include only the relevant excerpt and point to the file/command used.
- If a task becomes long/debug-heavy, pause and re-state current hypothesis + next verification step.

## CI

GitHub Actions runs `./scripts/dev.sh precommit`, `./scripts/dev.sh test -q`, and strict typecheck on PRs.

## Commands (Golden Path)

Everything should be runnable via `./scripts/dev.sh` (see `./scripts/dev.sh --help`).

### Build / Publish

```bash
./scripts/dev.sh build
```

### Publish (Manual / Interactive)

`./scripts/dev.sh publish` defaults to an interactive confirmation and refuses to run without a TTY unless you pass `--yes`.

- TestPyPI: `./scripts/dev.sh publish --test`
- PyPI (manual): `./scripts/dev.sh publish`

## Docs Pointers

- Configuration & `~/.ouro/models.yaml`: `docs/configuration.md`
- Packaging & release checklist: `docs/packaging.md`
- Extending tools/agents: `docs/extending.md`
- Memory system: `docs/memory-management.md`
- Usage examples: `docs/examples.md`

## Safety & Secrets

- Never commit `~/.ouro/config` or API keys.
- Never commit generated artifacts: `.venv/`, `dist/`, `build/`, `*.egg-info/`.
- Avoid running destructive shell commands; keep file edits scoped and reversible.
- Publishing/releasing steps require explicit human intent (see `docs/packaging.md`).

## Gotchas (Common Rework Sources)

- **Async-first runtime**: avoid new blocking I/O in `agent/`, `llm/`, `memory/`, `tools/`; don't use `asyncio.run()` in library code.
- **Packaging**: `pyproject.toml` uses an explicit `[tool.setuptools] packages` list; add new subpackages there or PyPI installs can break.
- **Significant changes**: write/update an RFC first (see `rfc/README.md` and `rfc/TEMPLATE.md`).
