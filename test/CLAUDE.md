# Test Instructions (ouro/test)

Note: `AGENTS.md` is a symlink to this file for compatibility with agents that look for `AGENTS.md`.

## Test strategy

- Prefer deterministic unit tests; avoid network calls.
- Live LLM tests must be explicitly gated behind `RUN_INTEGRATION_TESTS=1` and marked `@pytest.mark.integration`.

## Async tests

- Use `async def test_…` when awaiting async code.
- Async fixtures must use `@pytest_asyncio.fixture`.

## What to run while iterating

- Run the smallest relevant slice first (single file/nodeid), then broaden.
- Before you say “done”, run `./scripts/dev.sh test -q` (or `./scripts/dev.sh check` for full gating).
