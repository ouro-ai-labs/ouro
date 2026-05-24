# RFC: Deterministic AGENTS.md auto-loading

- Status: Proposed
- Authors: Yixin Luo
- Date: 2026-05-24

## Summary

Replace ouro's on-demand AGENTS.md strategy (the LLM decides whether to
`glob_files` + `read_file`) with deterministic auto-loading at agent startup:
walk from the working directory up to the filesystem root, merge every
`AGENTS.md` found (nearest wins), and inject the result into the system prompt
as a `<project_instructions>` block. Borrows the core idea from Claude Code's
CLAUDE.md handling, scoped down to a minimal project tier.

## Problem

Today the agent is only *told* to look for AGENTS.md
(`ouro/capabilities/prompts/system_prompt.py` `<agents_md>` block). Whether the
project instructions are ever loaded depends on the model's judgement, so the
same project can behave differently run to run, and simple tasks silently skip
the rules entirely. Claude Code instead loads its instruction files
deterministically, which is what users actually expect from a project rules
file.

## Goals

- Project AGENTS.md instructions are loaded every run, with no reliance on LLM
  judgement.
- Upward walk from CWD to `/`, collecting every `AGENTS.md`; the nearest file
  takes precedence (appended last).
- Merged content is injected into the system prompt next to `<environment>`.

## Non-goals

- No `@import` directives.
- No size caps / truncation.
- No user-global (`~/.ouro/AGENTS.md`) or machine-wide tier.
- No new disable env var or exclude globs.
- No change to how the file is injected (system prompt, not a first user
  message).

## Proposed Behavior (User-Facing)

- On every agent build, ouro discovers `AGENTS.md` from the CWD upward and
  injects them. No tool calls, no spinner gating on it.
- Subdirectory AGENTS.md still wins over parent (nearest last in the merge).
- If no `AGENTS.md` exists, nothing is injected (no error, no empty block).
- The old "check for AGENTS.md with glob_files" guidance is removed from the
  system prompt (redundant + risks double-reading).

## Invariants (Must Not Regress)

- System prompt assembly order stays stable: base → `<environment>` →
  `<project_instructions>` → `<long_term_memory>` → skills → soul.
- A run with no AGENTS.md produces no `<project_instructions>` block.
- File-read / discovery failures never crash agent startup (logged, skipped).
- No blocking I/O on the loop hot path (discovery runs once at startup via
  `asyncio.to_thread`).

## Design Sketch (Minimal)

New leaf module `ouro/capabilities/context/agents_md.py`:

- `_discover_agents_md(start_dir)` → list[Path], parent-first / nearest-last.
- `_read_and_merge(paths)` → merged text with a `# <path>` header per file.
- `load_agents_md(start_dir=None)` → formatted `<project_instructions>` block
  (or `""`), file I/O wrapped in `asyncio.to_thread`.

`ComposedAgent._add_system_prompt()` calls `load_agents_md()` right after
`format_context_prompt()` and appends the block when non-empty. The
`<agents_md>` block is deleted from `DEFAULT_SYSTEM_PROMPT`.

## Alternatives Considered

- Keep on-demand (status quo): non-deterministic; the reported problem.
- First-user-message `<system-reminder>` injection (full Claude Code parity):
  better cache locality but a larger structural change to ouro's message flow;
  deferred.

## Test Plan

- Unit tests (`test/test_agents_md.py`): no file → `""`; single file; upward
  walk merge order (nearest last); empty/whitespace file skipped; default CWD.
- Targeted: `./scripts/dev.sh test -q test/test_agents_md.py`.
- Smoke: `python main.py --task "what project instructions apply here?"` from a
  dir containing an AGENTS.md.

## Rollout / Migration

- Backward compatible: existing AGENTS.md files keep working; they are now
  always loaded instead of sometimes. `docs/agents-md-guide.md` updated to drop
  the "on-demand only" framing.

## Risks & Mitigations

- Large/many AGENTS.md inflate the prompt: accepted for MVP (no caps); revisit
  if it bites.
- Symlinked AGENTS.md (this repo's own setup) resolve normally via `is_file()`
  / `read_text`; covered implicitly.

## Open Questions

- Whether to add a user-global tier and a disable switch later (out of scope).
