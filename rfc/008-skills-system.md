# RFC 008: Skills System MVP

## Status

Draft

## Summary

Introduce a minimal skills system for aloop:

- **Skill**: reusable workflow package with progressive disclosure
- **Command**: user entrypoint (`/review`) that may depend on skills

## Problem Statement

aloop needs a structured way to:

- Provide opt-in, reusable workflows without bloating context
- Let LLM automatically select skills based on task matching
- Make context assembly auditable and deterministic

## Design

### 1) Canonical Objects

| Object | Description |
|--------|-------------|
| **Skill** | Reusable workflow package. Metadata indexed at startup; body loaded on invocation. |
| **Command** | Explicit entrypoint (e.g. `/review`). May declare `requires-skills`. |

### 2) File Layout

```
# Project files (checked into repo)
.aloop/commands/<name>.md              # Repo-specific commands

# User-level (not in repo)
~/.aloop/skills/<skill-name>/SKILL.md  # Installed skills
```

MVP only discovers skills from `~/.aloop/skills/`.

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
- `description`: 1–1024 chars. **Critical**: This is the primary trigger mechanism. Include both what the skill does AND when to use it.

Optional directories: `scripts/`, `references/`, `assets/` (read-only in MVP).

### 4) Command Format

```yaml
---
description: Perform code review.
requires-skills:
  - code-review
---

Review the changes: $ARGUMENTS
```

`name` is derived from filename (`.aloop/commands/review.md` → `/review`).

### 5) Progressive Disclosure

Skills use a three-level loading system to manage context efficiently:

1. **Metadata (~100 tokens)**: `name` + `description` loaded at startup for ALL skills
2. **System Prompt Injection**: Available skills list injected into system prompt so LLM knows what's available
3. **Full Body (on invocation)**: Complete `SKILL.md` body loaded only when skill is triggered

### 6) Invocation

Skills can be invoked in two ways:

| Method | Trigger | Example |
|--------|---------|---------|
| **Explicit** | User types `$skill-name` or `/<command>` | `$lint src/` or `/review` |
| **Implicit** | LLM matches task to skill description | User: "check my code" → LLM selects `code-review` |

**Trigger rules** (injected into system prompt):
- If user names a skill (with `$SkillName` or plain text), use that skill
- If task clearly matches a skill's description, LLM must use that skill
- Multiple matches → use all matching skills
- Skills do not carry across turns unless re-mentioned

### 7) Context Assembly

1. **At startup**: Render skills section into system prompt (name + description + path for each skill)
2. **On invocation**: Load skill body, inject as user message with `<skill>` tags
3. **Template variable**: `$ARGUMENTS` expands to user input

### 8) Skill Management

`/skills` opens an interactive menu:

```
Skills
Choose an action

> 1. List skills          Tip: press $ to open this list directly.
  2. Install skill        Install from local path or git URL.
  3. Uninstall skill      Remove an installed skill.

Press enter to confirm or esc to go back
```

**MVP scope**:
- List shows `name` + `description` for each installed skill
- Install copies skill directory to `~/.aloop/skills/`
- Uninstall removes directory from `~/.aloop/skills/`
- Restart required after install/uninstall to reload registry

### 9) Startup Flow

1. Scan `.aloop/commands/*.md` → parse frontmatter
2. Scan `~/.aloop/skills/*/SKILL.md` → parse frontmatter (`name` + `description`)
3. Build registry (no body loading)
4. **Render skills section** → inject into system prompt

**Error handling**: Malformed files are skipped with a warning.

### 10) System Prompt Injection

At startup, render available skills into the system prompt:

```markdown
## Skills
A skill is a set of local instructions stored in a `SKILL.md` file.

### Available skills
- code-review: Review code for style and correctness. (file: ~/.aloop/skills/code-review/SKILL.md)
- lint: Run linters on source files. (file: ~/.aloop/skills/lint/SKILL.md)

### How to use skills
- If user names a skill (with `$SkillName` or plain text) OR task matches a skill's description, use that skill
- After deciding to use a skill, open its `SKILL.md` and follow the workflow
- Announce which skill(s) you're using and why
```

This enables LLM to:
1. See all available skills and their descriptions
2. Automatically select matching skills based on user intent
3. Load full instructions only when needed

## References

- [Agent Skills spec](https://agentskills.io/specification)
- [OpenAI Codex skills](https://developers.openai.com/codex/skills/)

## Future Work

- Enable/disable state (`~/.aloop/skills.json`)
- Repo-scoped skills (`.aloop/skills/`)
- Autocomplete for `$` prefix
- Script execution with sandboxing
- Template variables: `$FILE`, `$SELECTION`, `$REPO_ROOT`

## Next Steps

1. ~~Implement skill indexer + loader~~
2. ~~Add `/command` and `$skill` parsing to input handler~~
3. **Add `render_skills_section()` for system prompt injection**
4. **Integrate skills into agent's system prompt**
