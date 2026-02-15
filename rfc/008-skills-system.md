# RFC 008: Skills System MVP

## Status

Draft

## Summary

Introduce a minimal skills system for ouro focused on one core object:

- **Skill**: reusable workflow package with progressive disclosure

This MVP intentionally excludes repo-scoped command templates (`/review`-style custom commands)
to reduce implementation complexity and rollout risk.

## Problem Statement

ouro needs a structured way to:

- Provide opt-in, reusable workflows without bloating context
- Let LLM automatically select skills based on task matching
- Make context assembly auditable and deterministic

## Scope (MVP)

### In Scope

- User-installed and system skills
- Skills metadata indexing at startup (`name` + `description`)
- Explicit skill invocation via `$skill-name`
- Implicit skill selection via description matching in system instructions
- Skill body lazy loading only on invocation
- Skills management UI (`/skills` list/install/uninstall)

### Out of Scope (Deferred)

- Repo-scoped custom command templates under `.ouro/commands/*.md`
- Command frontmatter (`requires-skills`, template expansion)
- Dynamic slash commands backed by local markdown files

## Design

### 1) Canonical Object

| Object | Description |
|--------|-------------|
| **Skill** | Reusable workflow package. Metadata indexed at startup; body loaded on invocation. |

### 2) File Layout

```text
# User-level (not in repo)
~/.ouro/skills/<skill-name>/SKILL.md  # Installed skills

# Bundled with app
agent/skills/system/<skill-name>/SKILL.md
```

MVP only discovers skills from user and bundled system locations.

### 3) Skill Format

Follows the [Agent Skills open format](https://agentskills.io/specification):

```yaml
---
name: code-review
description: Review code for style and correctness. Use when reviewing PRs, checking code quality, or when user mentions code review.
---

Instructions for the agent...
```

**Required**: `name`, `description`

**Optional**: `license`, `compatibility`, `metadata`

**Constraints**:
- `name`: 1–64 chars, lowercase + hyphens, must match directory name
- `description`: 1–1024 chars. This is the primary trigger mechanism; include both what and when.

Optional directories: `scripts/`, `references/`, `assets/` (read-only in MVP).

### 4) Progressive Disclosure

Skills use a three-level loading system to manage context efficiently:

1. **Metadata (~100 tokens)**: `name` + `description` loaded at startup for all skills
2. **System Prompt Injection**: available skills list injected into system prompt
3. **Full Body (on invocation)**: complete `SKILL.md` body loaded only when skill is triggered

### 5) Invocation

Skills can be invoked in two ways:

| Method | Trigger | Example |
|--------|---------|---------|
| **Explicit** | User types `$skill-name` | `$lint src/` |
| **Implicit** | LLM matches task to skill description | User: "check my code" → LLM selects `code-review` |

**Trigger rules** (injected into system prompt):
- If user names a skill (with `$SkillName` or plain text), use that skill
- If task clearly matches a skill's description, LLM must use that skill
- Multiple matches → use all matching skills
- Skills do not carry across turns unless re-mentioned

### 6) Context Assembly

1. At startup: render skills section into system prompt (name + description + path)
2. On invocation: load skill body and inject it into the user turn
3. Pass user arguments after `$skill` as `ARGUMENTS` context

### 7) Skill Management

`/skills` opens an interactive menu:

```text
Skills
Choose an action

> 1. List skills          Tip: press $ to open this list directly.
  2. Install skill        Install from local path or git URL.
  3. Uninstall skill      Remove an installed skill.
```

**MVP behavior**:
- List shows `name` + `description` for each installed skill
- Install copies skill directory to `~/.ouro/skills/`
- Uninstall removes directory from `~/.ouro/skills/`
- Restart required after install/uninstall to reload registry

### 8) Startup Flow

1. Scan `~/.ouro/skills/*/SKILL.md` and bundled system skills
2. Parse frontmatter (`name` + `description`)
3. Build skills registry (no body loading)
4. Render skills section and inject into system prompt

Malformed files are skipped with a warning.

## References

- [Agent Skills spec](https://agentskills.io/specification)
- [OpenAI Codex skills](https://developers.openai.com/codex/skills/)

## Future Work

- Re-introduce repo-scoped command templates (`.ouro/commands/*.md`) if needed
- Enable/disable state (`~/.ouro/skills.json`)
- Repo-scoped skills (`.ouro/skills/`)
- Autocomplete for `$` prefix
- Script execution with sandboxing
- Template variables: `$FILE`, `$SELECTION`, `$REPO_ROOT`

## Next Steps

1. ~~Implement skill indexer + loader~~
2. ~~Add `$skill` parsing to input handler~~
3. Add `render_skills_section()` for system prompt injection
4. Integrate skills into agent's system prompt
