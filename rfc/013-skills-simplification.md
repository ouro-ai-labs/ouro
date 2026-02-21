# RFC 013: Skills Simplification — Unified Directory + `/skills call`

- Status: Proposed
- Authors: ouro-dev
- Date: 2026-02-21
- Supersedes: RFC 011

## Summary

Simplify the skills system by using a single runtime directory (`~/.ouro/skills/`), removing the `$` prefix for explicit invocation, and adding `/skills call <name> [args]` for explicit skill invocation. Bundled skills are seeded into the user directory on first load. Dynamic install/uninstall updates the registry in-place and notifies the LLM via system messages (preserving KV cache).

## Problem

The current skills system loads from two directories (`~/.ouro/skills/` and `agent/skills/system/`), requires a `$SkillName` prefix for explicit invocation, and demands a restart after install/uninstall. This creates confusion about where skills live and adds unnecessary friction.

## Goals

- Single canonical directory for all skills at runtime (`~/.ouro/skills/`)
- Bundled skills auto-seeded on first load (without overwriting user customizations)
- Explicit invocation via `/skills call <name> [args]` command
- Dynamic registry updates on install/uninstall — no restart required
- LLM notified of changes via system messages (not by mutating the system prompt, preserving KV cache)

## Non-goals

- Changing skill file format (`SKILL.md` frontmatter)
- Changing the system prompt injection mechanism (progressive disclosure stays)
- Remote skill marketplace or versioning

## Proposed Behavior (User-Facing)

- CLI / UX changes:
  - Remove `$SkillName` prefix triggering
  - Add `/skills call <name> [args]` subcommand
  - Add "Call a skill" option to `/skills` menu
  - After install/uninstall, skills are immediately available without restart
- Config changes: None
- Output / logging changes:
  - Install/uninstall prints immediate confirmation (no "restart required" message)
  - LLM receives system message about skill availability changes

## Invariants (Must Not Regress)

- Implicit skill triggering via system prompt still works
- User skills override bundled skills of the same name
- Skill install from local path and git URL still works
- Skill uninstall still works
- System prompt skills section renders correctly

## Design Sketch (Minimal)

1. **Bootstrap**: On `load()`, copy bundled skills from `agent/skills/system/` to `~/.ouro/skills/` if not already present, then scan only `~/.ouro/skills/`.
2. **Remove `resolve_user_input()`**: No more `$` prefix handling.
3. **Add `call_skill(name, args)`**: Loads skill body and renders prompt for explicit invocation.
4. **Dynamic reload**: `install_skill()` / `uninstall_skill()` update `self.skills` dict immediately after success.
5. **System message notification**: After install/uninstall, caller injects a system message into memory to inform the LLM.

## Alternatives Considered

- Option A: Keep dual-directory scanning → rejected for simplicity
- Option B: Hot-reload system prompt on install → rejected to preserve KV cache

## Test Plan

- Unit tests: `test/test_skills_registry.py`, `test/test_skills_render.py`
- Targeted tests: `./scripts/dev.sh test -q test/test_skills_registry.py test/test_skills_render.py`
- Smoke run: `python main.py --mode interactive` → `/skills call skill-creator`

## Rollout / Migration

- Backward compatibility: Bundled skills auto-seed on first load; existing user skills are preserved
- Migration steps: None required — transparent upgrade

## Risks & Mitigations

- Risk: User has customized a bundled skill → Mitigation: bootstrap skips existing directories
- Risk: `call_skill` with unknown name → Returns None, caller handles gracefully

## Open Questions

- None
