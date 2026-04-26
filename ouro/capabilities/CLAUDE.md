# Agent Runtime Instructions (ouro/agent)

Note: `AGENTS.md` is a symlink to this file for compatibility with agents that look for `AGENTS.md`.

## Safety rails

- Keep changes incremental; avoid “big refactors” without characterization tests first.
- Preserve existing behavior unless the task explicitly changes it; list any intentional behavior changes in the PR summary.

## Async/runtime rules

- Do not introduce new blocking I/O in the runtime loop.
- Prefer native async libraries; if unavoidable, use `asyncio.to_thread` with timeouts/cancellation.

## When changing the loop/verification

- Update or add tests (usually start with `./scripts/dev.sh test -q test/test_ralph_loop.py`).
- If tool execution/parallelism changes, run `./scripts/dev.sh test -q test/test_parallel_tools.py`.
- Do at least one real smoke run on the changed path (`python main.py --task ...` and/or `--verify`).
