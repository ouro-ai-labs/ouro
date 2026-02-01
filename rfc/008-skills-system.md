# RFC 008: Skills System MVP

## Status

Draft

## Summary

Introduce a minimal skills system for aloop:

- **Skill**: reusable workflow package, loaded on explicit invocation
- **Command**: user entrypoint (`/review`) that may depend on skills

## Problem Statement

aloop needs a structured way to:

- Provide opt-in, reusable workflows without bloating context
- Make context assembly auditable and deterministic

## Design

### 1) Canonical Objects

| Object | Description |
|--------|-------------|
| **Skill** | Reusable workflow package. Indexed at startup; body loaded on invocation. |
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
description: Review code for style and correctness.
---

Instructions for the agent...
```

**Required**: `name`, `description`

**Optional**: `license`, `compatibility`, `metadata`

**Constraints**:
- `name`: 1–64 chars, lowercase + hyphens, must match directory name
- `description`: 1–1024 chars

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

### 5) Invocation

| Syntax | Action |
|--------|--------|
| `/<command> <args>` | Invoke command, load its `requires-skills` |
| `$skill-name <args>` | Invoke skill directly |

### 6) Context Assembly

1. **On invocation**: command template + skill bodies from `requires-skills`
2. **Template variable**: `$ARGUMENTS` expands to user input

Skills follow **progressive disclosure**: only `name` + `description` are indexed at startup; full body is loaded when invoked.

### 7) Skill Management

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

### 8) Startup Flow

1. Scan `.aloop/commands/*.md` → parse frontmatter
2. Scan `~/.aloop/skills/*/SKILL.md` → parse frontmatter (`name` + `description`)
3. Build registry (no body loading)

**Error handling**: Malformed files are skipped with a warning.

## References

- [Agent Skills spec](https://agentskills.io/specification)
- [OpenAI Codex skills](https://developers.openai.com/codex/skills/)

## Future Work

- Implicit skill selection (auto-match by description)
- Enable/disable state (`~/.aloop/skills.json`)
- Repo-scoped skills (`.aloop/skills/`)
- Autocomplete for `$` prefix
- Script execution with sandboxing
- Template variables: `$FILE`, `$SELECTION`, `$REPO_ROOT`

## Next Steps

1. Implement skill indexer + loader
2. Add `/command` and `$skill` parsing to input handler
3. Integrate context assembly into agent loop
