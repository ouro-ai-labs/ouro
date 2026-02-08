# ouro — Agent Instructions

This file defines the **operational workflow** for making changes in this repo (how to set up, run, test, format, build, and publish). Keep it short, specific, and executable; link to docs for long explanations.

Prerequisites: Python 3.12+ and `uv` (https://github.com/astral-sh/uv).

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

## CI

GitHub Actions runs `./scripts/dev.sh precommit`, `./scripts/dev.sh test -q`, and strict typecheck on PRs.

## Review Checklist

Run these before concluding a change:

```bash
./scripts/dev.sh precommit
TYPECHECK_STRICT=1 ./scripts/dev.sh typecheck
./scripts/dev.sh test -q
```

Manual doc/workflow checks:
- README/AGENTS/docs: avoid legacy/removed commands or env-based config; use current docs only
- Docker examples use `--mode`/`--task`
- Python 3.12+ + uv-only prerequisites documented consistently

Change impact reminders:
- CLI changes → update `README.md`, `docs/examples.md`
- Config changes → update `docs/configuration.md`
- Workflow scripts → update `AGENTS.md`, `docs/packaging.md`

Run a quick smoke task (requires a configured provider in `~/.ouro/models.yaml`):

```bash
python main.py --task "Calculate 1+1"
```

## Repo Map

- `main.py`, `cli.py`, `interactive.py`: CLI entry points and UX
- `agent/`: agent loops (ReAct, Plan-Execute) and orchestration
- `tools/`: tool implementations (file ops, shell, web search, etc.)
- `llm/`: provider adapters + retry logic
- `memory/`: memory manager, compression, persistence
- `docs/`: user/developer documentation
- `scripts/`: packaging/publishing scripts
- `test/`: tests (some require API keys; memory tests are mostly mocked)
- `rfc/`: RFC design documents for significant changes

## Commands (Golden Path)

### Install

- Use `./scripts/bootstrap.sh` to create `.venv` and install dependencies.
- Use `./scripts/dev.sh install` to reinstall dev deps into an existing `.venv`.

### Tests

- All tests: `python -m pytest test/`
- Memory suite: `python -m pytest test/memory/ -v`
- Unified entrypoint: `./scripts/dev.sh test`
- Integration tests: set `RUN_INTEGRATION_TESTS=1` (live LLM; may incur cost)

### Format

This repo uses `black` + `isort` + `ruff` (see `pyproject.toml`).

**IMPORTANT**: Always run formatting before committing to avoid CI failures:

```bash
source .venv/bin/activate
python -m black .
python -m isort .
python -m ruff check --fix .
```

Unified entrypoint: `./scripts/dev.sh format`

### Lint / Typecheck

- Lint (format check): `./scripts/dev.sh lint`
- Ruff (linter with auto-fix): `python -m ruff check --fix .`
- Pre-commit (recommended): `./scripts/dev.sh precommit`
- Typecheck (best-effort): `./scripts/dev.sh typecheck` (set `TYPECHECK_STRICT=1` to fail on errors)

### Build (Packaging)

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
- Avoid running destructive shell commands; keep file edits scoped and reversible.
- Publishing/releasing steps require explicit human intent (see `docs/packaging.md`).

## RFC Design Documents

**IMPORTANT**: Before starting significant changes, check `rfc/` for existing design documents and create new ones when needed.

When to write an RFC:
- Adding new agent types or major agent behavior changes
- Significant architectural changes (new modules, major refactors)
- New tool categories or substantial tool modifications
- Changes to memory system, persistence, or compression strategies
- New LLM provider integrations or API changes
- Breaking changes to CLI or configuration

RFC file naming: `rfc/NNN-short-description.md` (e.g., `rfc/001-plan-execute-agent.md`)

RFC should focus on design thinking:
- Problem statement: what problem are we solving and why now?
- Design goals and constraints
- Proposed approach and alternatives considered (with trade-offs)
- Key design decisions and rationale
- Open questions and risks

Avoid over-specifying implementation details; focus on the "what" and "why", not the "how".

Review existing RFCs before implementation to understand design decisions and constraints.

## Async Runtime Rules

- **New runtime code must be async-first**: avoid introducing new blocking I/O in `agent/`, `llm/`, `memory/`, and `tools/`.
- **Do not use `asyncio.run()` in library code**. Only entrypoints (e.g., `main.py`) should own the event loop.
- If you must call a blocking library temporarily, ensure it’s executed behind an async boundary (e.g., `asyncio.to_thread`) and has a timeout/cancellation strategy.
- **Strict async rule**: use native async libs where available (e.g., `aiofiles`, `httpx`). Use `aiofiles.os.path.*` for metadata checks. Only use `asyncio.to_thread` when no async API exists (e.g., glob/rglob). Avoid sync file copy; use async streaming instead.

### Testing Async Code

- **Tests that call async code must be async**: use `async def test_xxx` for tests that await async functions or use async fixtures.
- **Async fixtures must use `@pytest_asyncio.fixture`**: fixtures that perform async setup/teardown or depend on async fixtures must be async.
- **Subprocess cleanup in tests**: when tests create subprocesses, ensure proper cleanup before the event loop closes:
  - Call `process.kill()` + `await process.communicate()` to consume pipes
  - Explicitly close transport with `proc._transport.close()` if needed
  - Use async fixtures with `try/finally` to guarantee cleanup
- **Avoid mixing sync and async fixtures**: if a fixture depends on an async fixture, it should also be async.

## When Changing Key Areas

- If you change CLI flags / behavior: update `README.md` and `docs/examples.md`.
- If you change configuration/env vars: update `docs/configuration.md`.
- If you change packaging/versioning: update `pyproject.toml` and `docs/packaging.md`.
- If you change memory/compression/persistence: add/adjust tests under `test/memory/` and update `docs/memory-management.md`.
- **Significant changes**: write an RFC in `rfc/` before implementation (see RFC Design Documents section above).
