# Docs Instructions (ouro/docs)

Note: `AGENTS.md` is a symlink to this file for compatibility with agents that look for `AGENTS.md`.

## Keep docs executable

- Prefer repo scripts in examples (`./scripts/bootstrap.sh`, `./scripts/dev.sh …`) over ad-hoc commands.
- When documenting CLI flags/behavior, confirm against `main.py` and/or real runs.

## Consistency checks before finishing doc changes

- Search for outdated flags/paths and fix them (e.g. `rg -n -- \"--task|--mode|--verify\" docs`).
- If you changed CLI/config, update the relevant doc page and at least one example:
  - CLI: `README.md`, `docs/examples.md`
  - Config: `docs/configuration.md`
