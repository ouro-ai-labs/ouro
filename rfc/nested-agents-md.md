# RFC: Lazy subdirectory AGENTS.md loading

- Status: Proposed
- Authors: Yixin Luo
- Date: 2026-05-24

## Summary

Surface subdirectory `AGENTS.md` files on demand: when the agent reads a file
inside a subdirectory of the working directory, load every `AGENTS.md` along the
path from the CWD down to that file's directory and append them to the read
result. Complements the eager startup load (RFC `agents-md-autoload`, PR #193),
which covers the CWD and everything above it but never descends into
subdirectories. Borrows Claude Code's nested-memory mechanism, scoped down.

## Problem

The eager load only walks *upward* from the CWD, so subdirectory rules in a
monorepo (`backend/AGENTS.md`, `services/api/AGENTS.md`, …) are invisible unless
you `cd` into them. Loading every subdirectory's AGENTS.md eagerly would bloat
the prompt and mix conflicting rules. We want subdirectory rules to appear only
when they become relevant — i.e. when the agent actually touches a file under
them.

## Goals

- When `read_file` targets a file in a subdirectory of the CWD, inject that
  subdirectory's `AGENTS.md` (and any on the path down from the CWD).
- Scan only the single path CWD → target's directory; never sibling subtrees.
- Parent-first / nearest-last ordering (nearest wins), matching the eager load.
- Dedup so the same subdirectory AGENTS.md isn't re-injected repeatedly.
- On by default, with an opt-out.

## Non-goals

- Triggers other than `read_file` (no `@file` mention / IDE-open hooks).
- `.claude/rules/*.md`, `globs:` conditional rules, `CLAUDE.local.md`.
- Re-evaluating CWD-level / above files per trigger (they're eagerly loaded).
- `@import`, size caps, user-global / managed tiers.
- Session-permanent dedup (we reset per run; see below).

## Proposed Behavior (User-Facing)

- Reading `repo/services/api/handler.py` (CWD `repo`) appends the merged
  contents of `repo/services/AGENTS.md` + `repo/services/api/AGENTS.md` (those
  that exist) to the read result, wrapped in `<project_instructions>`.
- Reading a file directly in the CWD, or outside the CWD, injects nothing.
- Reading a sibling (`repo/services/db/x.py`) does not pull
  `repo/services/api/AGENTS.md`.
- Each subdirectory's AGENTS.md is injected at most once per `Agent.run`.
- On by default; `AgentBuilder.without_nested_agents_md()` disables it.

## Invariants (Must Not Regress)

- Eager startup load (PR #193) is unchanged; nested load never touches CWD-level
  or higher directories.
- A read with no nested AGENTS.md returns the result unchanged (rule returns
  `None`).
- Sibling subtrees are never scanned.
- No LLM calls in the rule; only cheap local stat/read on the per-call path.
- Layer boundaries intact (rule lives in `ouro.capabilities.rules`).

## Design Sketch (Minimal)

`ouro/capabilities/context/agents_md.py` gains synchronous helpers:

- `_nested_agents_md_paths(cwd, file_path)` — existing AGENTS.md on the path
  CWD → target dir, parent-first; `[]` for cwd-level / outside-cwd files.
- `_format_nested(merged)` — `<project_instructions>` wrapper.
- `load_nested_instructions(cwd, file_path, already_injected)` — filter by the
  dedup set, read+merge fresh ones, mutate the set, return the block or `""`.

`ouro/capabilities/rules/nested_agents_md.py` — `NestedAgentsMdRule` implements
the core `Rule` contract. `after_toolcall` watches `read_file`, calls
`load_nested_instructions`, and appends the block to the result. Dedup set
self-resets on a new `RunStatistic` identity (like `ReadBeforeWriteRule`).

`AgentBuilder`: `nested_agents_md: bool = True`,
`without_nested_agents_md()`, wired after `ReadBeforeWriteRule` in `build()`.

### Why a Rule, appending to the read result

`after_toolcall` is purpose-built to "rewrite output and/or record state from
real results." Appending the subdirectory rules to the very read that triggered
them places the guidance next to the file the model just looked at — ouro's
native analog to Claude Code's `nested_memory` attachment. The rule path is
synchronous, so reads are synchronous; they are tiny, local, and deduped, in the
spirit of the contract's allowed `os.path.exists` check.

## Alternatives Considered

- Async `Hook.on_iteration_end` injecting a separate message: avoids sync file
  I/O but needs cross-component coordination and a bespoke message; heavier for
  no real benefit at this size.
- Session-permanent dedup (Claude Code's non-evicting set): injects each subdir
  once ever, but grows unbounded. We chose per-run reset for bounded state and
  consistency with `ReadBeforeWriteRule`.

## Test Plan

- Unit (`test/test_nested_agents_md.py`): path discovery (down-walk, excludes
  cwd-level/outside/siblings), load+dedup, rule appends block, ignores non-read
  tools, per-run dedup reset, no-op returns `None`.
- Targeted: `./scripts/dev.sh test -q test/test_nested_agents_md.py test/test_loop_rules.py`.
- Smoke: from a repo with a `sub/AGENTS.md`, `python main.py --task "read sub/x.py and tell me the project rules"`.

## Rollout / Migration

- Backward compatible. On by default; opt out with
  `without_nested_agents_md()`.

## Risks & Mitigations

- Many/large subdirectory AGENTS.md inflate read results: accepted for MVP (no
  caps); dedup limits repetition.
- Sync file reads on the rule path: tiny, local, deduped; negligible next to the
  `read_file` that triggered them.

## Open Questions

- Whether to later add session-permanent dedup or `@file`-mention triggers
  (out of scope).
