# Memory Instructions (ouro/memory)

Note: `AGENTS.md` is a symlink to this file for compatibility with agents that look for `AGENTS.md`.

## Safety rails

- Treat serialization formats as public contracts; avoid breaking changes without migration notes.
- Keep token accounting deterministic and tested.

## Tests

- Prefer the memory suite for local validation:
  - `./scripts/dev.sh test -q test/memory/`
- If you change session recovery/persistence, add a regression test.
