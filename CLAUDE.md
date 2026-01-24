# AgenticLoop — Agent Instructions

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
- README/AGENTS/docs: avoid legacy/removed commands (`LLM_PROVIDER`, `pip install -e`, `requirements.txt`, `setup.py`)
- Docker examples use `--mode`/`--task`
- Python 3.12+ + uv-only prerequisites documented consistently

Change impact reminders:
- CLI changes → update `README.md`, `docs/examples.md`
- Config changes → update `.env.example`, `docs/configuration.md`
- Workflow scripts → update `AGENTS.md`, `docs/packaging.md`

Run a quick smoke task (requires a configured provider in `.env`):

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

## Commands (Golden Path)

### Install

- Use `./scripts/bootstrap.sh` to create `.venv` and install dependencies.
- Use `./scripts/dev.sh install` to reinstall dev deps into an existing `.venv`.

### Tests

- All tests: `python -m pytest test/`
- Memory suite: `python -m pytest test/memory/ -v`
- Script: `./scripts/test.sh`
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

Script: `./scripts/format.sh`
Unified entrypoint: `./scripts/dev.sh format`

### Lint / Typecheck

- Lint (format check): `./scripts/dev.sh lint`
- Ruff (linter with auto-fix): `python -m ruff check --fix .`
- Pre-commit (recommended): `./scripts/dev.sh precommit`
- Typecheck (best-effort): `./scripts/dev.sh typecheck` (set `TYPECHECK_STRICT=1` to fail on errors)

### Build (Packaging)

```bash
./scripts/build.sh
```
Unified entrypoint: `./scripts/dev.sh build`

### Publish (Manual / Interactive)

`./scripts/publish.sh` defaults to an interactive confirmation and refuses to run without a TTY unless you pass `--yes`.

- TestPyPI: `./scripts/publish.sh --test`
- PyPI (manual): `./scripts/publish.sh`
- Unified entrypoint: `./scripts/dev.sh publish`

## Docs Pointers

- Configuration & `.env`: `docs/configuration.md`
- Packaging & release checklist: `docs/packaging.md`
- Extending tools/agents: `docs/extending.md`
- Memory system: `docs/memory-management.md`, `docs/memory_persistence.md`
- Usage examples: `docs/examples.md`

## Safety & Secrets

- Never commit `.env` or API keys.
- Avoid running destructive shell commands; keep file edits scoped and reversible.
- Publishing/releasing steps require explicit human intent (see `docs/packaging.md`).

## When Changing Key Areas

- If you change CLI flags / behavior: update `README.md` and `docs/examples.md`.
- If you change configuration/env vars: update `docs/configuration.md` and `.env.example`.
- If you change packaging/versioning: update `pyproject.toml` and `docs/packaging.md`.
- If you change memory/compression/persistence: add/adjust tests under `test/memory/` and update `docs/memory-management.md` / `docs/memory_persistence.md`.
