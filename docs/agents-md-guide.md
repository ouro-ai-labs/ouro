# AGENTS.md Guide

## Overview

ouro supports project-specific instructions via AGENTS.md files. The agent will automatically look for and read these files when relevant (e.g., before modifying code, exploring a codebase, or starting complex tasks).

## How It Works

- **Location**: Place AGENTS.md in your project directory (or subdirectories)
- **Discovery**: Agent uses nearest AGENTS.md (subdirectory wins over parent)
- **Reading**: Agent reads AGENTS.md when needed (not automatically at startup)
- **Format**: Plain markdown, no special syntax required

## When Agent Reads AGENTS.md

The agent will look for AGENTS.md in these situations:
- Before modifying code or making significant changes
- Before exploring an unfamiliar codebase
- When you mention project-specific workflows or conventions
- At the start of complex multi-step tasks

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
project/
├── AGENTS.md          # General project rules
└── backend/
    ├── AGENTS.md      # Backend-specific rules (wins when in backend/)
    └── api/
        └── AGENTS.md  # API-specific rules (wins when in api/)
```

The agent uses the **nearest** AGENTS.md relative to the working directory. This allows you to:
- Define general rules at the project root
- Override with specific rules for subdirectories
- Keep different conventions for different parts of a monorepo

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

### ouro Difference
Unlike other tools that auto-load AGENTS.md at startup:
- **On-demand reading**: Agent decides when to read based on context
- **Token-efficient**: Only loads when relevant (saves tokens on simple tasks)
- **Flexible**: Agent adapts based on task complexity
- **Tool-based**: Uses existing tools (no special loader needed)

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

### Agent Not Reading AGENTS.md
- Ensure file is named exactly `AGENTS.md` (case-sensitive)
- Verify file is in project directory or parent directories
- Try mentioning "check project instructions" in your request

### Agent Reading Wrong AGENTS.md
- The agent chooses the nearest AGENTS.md to the working directory
- If working in a subdirectory, ensure you want the subdirectory version
- Use `cd` to change directories if needed

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
