# AGENTS.md Guide

## Overview

ouro supports project-specific instructions via AGENTS.md files. They are auto-loaded into the system prompt at the start of every run, so the instructions apply deterministically regardless of the task.

## How It Works

- **Location**: Place AGENTS.md in your project directory (or any parent directory)
- **Discovery**: ouro walks from the working directory up to the filesystem root and collects every AGENTS.md found
- **Loading**: All discovered files are merged and injected at startup, parent-first so the nearest AGENTS.md wins (subdirectory overrides parent)
- **Format**: Plain markdown, no special syntax required

## What Gets Loaded

On every run, ouro discovers and merges AGENTS.md files from the working
directory upward. No tool calls or LLM judgement are involved — if an
AGENTS.md exists on the path from the CWD to `/`, its instructions are present
in context. If none exist, nothing is injected.

## Example AGENTS.md

```markdown
# Project Instructions

## Workflow
- Always run `./scripts/dev.sh check` before commits
- Use git worktrees for branches

## Code Style
- Python 3.12+ with type hints
- Use async/await patterns
- Format with black + isort + ruff

## Testing
- Write tests for new features
- Run `./scripts/dev.sh test` before PR

## Boundaries
- Never commit secrets (.env, credentials.json)
- Never modify vendor/ directory
- Never touch production configs
```

## Subdirectory Support

You can have multiple AGENTS.md files in different directories:

```
project/            # working directory
├── AGENTS.md          # General project rules — eager-loaded at startup
└── backend/
    ├── AGENTS.md      # Backend rules — loaded when a file under backend/ is read
    └── api/
        └── AGENTS.md  # API rules — loaded when a file under api/ is read
```

There are two complementary mechanisms:

- **Eager (startup)**: AGENTS.md in the working directory and *above* it are loaded once at the start of every run (see "What Gets Loaded").
- **Lazy (subdirectory)**: AGENTS.md in *subdirectories* of the working directory are loaded on demand — when the agent reads a file under that subdirectory, every AGENTS.md on the path from the working directory down to that file is appended to the read result. Sibling subtrees are never scanned, and each subdirectory's AGENTS.md is injected at most once per run.

This lets you:
- Define general rules at the project root (always present)
- Add subdirectory rules that surface only while working in that subtree
- Keep different conventions for different parts of a monorepo without bloating context

Lazy loading is on by default. The SDK can disable it with `AgentBuilder.without_nested_agents_md()`.

## Best Practices

### 1. Keep it Concise
- Aim for ≤150 lines for best results
- Focus on essentials that the agent needs to know
- Link to detailed docs rather than duplicating content

### 2. Be Specific
Clear, actionable instructions work best:

```markdown
❌ "React project"
✅ "React 18 with TypeScript, Vite, and Tailwind CSS"

❌ "Use good coding practices"
✅ "Always add type hints to function signatures"
```

### 3. Use Code Examples
Show, don't tell. One real code snippet is worth three paragraphs:

```markdown
## Error Handling Pattern

Always wrap external API calls in try/catch with specific errors:

\```python
async def fetch_user(user_id: str) -> User:
    try:
        response = await api_client.get(f"/users/{user_id}")
        return User.from_dict(response.json())
    except HTTPError as e:
        if e.status == 404:
            raise UserNotFoundError(user_id)
        raise APIError(f"Failed to fetch user: {e}")
\```
```

### 4. Set Clear Boundaries
Tell the agent what to never touch:

```markdown
## Boundaries

- Never commit secrets (.env, credentials.json, *.key)
- Never modify vendor/ directory
- Never touch production configs (config/prod.yaml)
- Never run destructive commands without confirmation
```

### 5. Six Core Areas

Focus on these key sections:

1. **Commands** (setup, run, test, deploy)
2. **Testing** (how to run, what to check)
3. **Project Structure** (key directories, file organization)
4. **Code Style** (conventions, patterns)
5. **Git Workflow** (branching, commit messages)
6. **Boundaries** (what never to touch)

### 6. File-Scoped Commands
For large codebases, avoid commands that scan the entire repository:

```markdown
❌ `npm run lint` (scans all files, slow)
✅ `npm run lint:file <path>` (targeted, fast)
```

### 7. Use Emphasis for Critical Rules
Add "IMPORTANT" or "YOU MUST" for rules that must be followed:

```markdown
**IMPORTANT**: Always run `./scripts/dev.sh check` before committing to avoid CI failures.

**YOU MUST**: Never push directly to main branch - all changes go through PR review.
```

## Comparison to Other Tools

### Similar Tools
AGENTS.md is compatible with:
- **Codex CLI** (OpenAI): Automatic hierarchical loading
- **OpenCode**: Two-tier global + project loading
- **Cursor**: Supports AGENTS.md alongside other rule systems
- **Jules** (Google): Reads AGENTS.md automatically

### ouro Behavior
Like Codex CLI and Jules, ouro auto-loads AGENTS.md deterministically:
- **Deterministic**: Loaded every run, no reliance on LLM judgement
- **Hierarchical**: Eager walk CWD → `/` at startup, plus lazy loading of subdirectory AGENTS.md when a file under them is read; nearest file wins on conflict
- **Project tier only**: No `@import` directives, size caps, or user-global tier

### Migration from Other Tools
If you're coming from another tool, your existing AGENTS.md should work as-is. ouro will read and follow the same instructions.

## Examples

### Simple Project

```markdown
# MyApp Project Instructions

## Setup
\```bash
pip install -r requirements.txt
python manage.py migrate
\```

## Running
\```bash
python manage.py runserver
\```

## Testing
\```bash
pytest tests/
\```

## Code Style
- Python 3.12+ with type hints
- Format with black (line length: 100)
- Sort imports with isort
```

### Complex Monorepo

**Root AGENTS.md**:
```markdown
# Monorepo Root Instructions

## Structure
- `/backend` - Python FastAPI services
- `/frontend` - React TypeScript app
- `/mobile` - React Native app

## Git Workflow
- Create feature branches from `main`
- PR title: `[area] description` (e.g., `[backend] add auth`)
- Squash merge to main

## CI
GitHub Actions runs tests on all PRs
```

**backend/AGENTS.md**:
```markdown
# Backend Instructions

## Stack
- Python 3.12+, FastAPI, SQLAlchemy, PostgreSQL

## Running
\```bash
cd backend
./scripts/dev.sh run
\```

## Testing
\```bash
./scripts/dev.sh test
\```

## Code Conventions
- Async-first (use `async def` for all endpoints)
- Type hints required on all function signatures
- Pydantic models for request/response schemas
```

## Troubleshooting

### AGENTS.md Not Loaded
- Ensure file is named exactly `AGENTS.md` (case-sensitive)
- A working-directory or parent AGENTS.md is loaded eagerly at startup; a subdirectory AGENTS.md loads only once the agent **reads a file under that subdirectory** (sibling subtrees are never scanned)
- Empty / whitespace-only files are skipped

### Wrong AGENTS.md Taking Precedence
- The nearest AGENTS.md to the working directory wins on conflict
- If working in a subdirectory, ensure you want the subdirectory version
- Use `cd` to change the working directory if needed

### Instructions Not Being Followed
- Use emphasis: "IMPORTANT", "YOU MUST", "NEVER"
- Be more specific with actionable commands
- Put critical rules at the top of the file
- Keep instructions concise and scannable

## Further Reading

- [AGENTS.md Official Site](https://agents.md/) - Cross-platform standard
- [GitHub Blog: How to write a great agents.md](https://github.blog/ai-and-ml/github-copilot/how-to-write-a-great-agents-md-lessons-from-over-2500-repositories/)
- [Builder.io: AGENTS.md tips](https://www.builder.io/blog/agents-md)
- [ouro Configuration Guide](configuration.md) - Model setup and runtime settings
