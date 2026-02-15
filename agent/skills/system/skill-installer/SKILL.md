---
name: skill-installer
description: Install ouro skills from GitHub repositories or list available skills from a curated registry. Use when a user asks to list installable skills, install a skill from a repo, or manage installed skills.
---

# Skill Installer

Helps install skills from GitHub or other sources.

## Quick Commands

List installed skills:
```bash
ls -la ~/.ouro/skills/
```

Install from GitHub (ouro has built-in support):
```
$install <git-url>
```

Or use the helper script:
```bash
python scripts/install_skill.py --url https://github.com/owner/repo
python scripts/install_skill.py --url https://github.com/owner/repo#path/to/skill
```

## Installation Sources

### From GitHub URL

Install a skill from any public GitHub repository:

```bash
python scripts/install_skill.py --url https://github.com/owner/repo
```

For private repos, ensure git credentials are configured.

### From Subdirectory

If the skill is in a subdirectory, use the `#path` suffix:

```bash
python scripts/install_skill.py --url https://github.com/owner/repo#skills/my-skill
```

### From Local Path

Copy a local skill directory:

```bash
cp -r /path/to/skill ~/.ouro/skills/skill-name
```

## Listing Skills

### List Installed Skills

```bash
python scripts/list_skills.py --installed
```

Or directly:
```bash
ls ~/.ouro/skills/
```

### List Available Skills from Registry

```bash
python scripts/list_skills.py --repo owner/repo --path skills
```

## Behavior

- Skills are installed to `~/.ouro/skills/<skill-name>`
- Installation fails if the destination already exists (no overwrite)
- Git clone uses `--depth 1` for efficiency
- After installation, restart ouro to pick up new skills

## Notes

- Private repos require git credentials or `GITHUB_TOKEN`/`GH_TOKEN` environment variable
- Installed skills are loaded on ouro startup
- Each skill must have a valid `SKILL.md` with `name` and `description` in frontmatter
