"""Render skills section for system prompt injection."""

from __future__ import annotations

from .types import SkillInfo

SKILLS_USAGE_RULES = """\
- Discovery: The list above is an index of skills available in this session. Skill bodies live on disk at the listed `SKILL.md` paths.
- Trigger: Use a skill when the user asks for it by name or when its description clearly matches the task. Do not carry a skill across turns unless it is still relevant.
- Progressive disclosure: After choosing a skill, open its `SKILL.md` and read only what is needed. Resolve relative paths from the skill directory, and load referenced scripts, assets, or reference files only when they are relevant.
- Coordination: If several skills apply, choose the minimal useful set and mention the order briefly.
- Fallback: If a skill is missing or does not fit cleanly, say so and continue with the next-best approach."""


def render_skills_section(skills: list[SkillInfo]) -> str | None:
    """Render available skills as a system prompt section.

    Args:
        skills: List of loaded skill metadata.

    Returns:
        Formatted markdown section, or None if no skills available.
    """
    if not skills:
        return None

    lines: list[str] = []
    lines.append("## Skills")
    lines.append(
        "A skill is a set of local instructions to follow that is stored in a `SKILL.md` file. "
        "Below is the list of skills that can be used. Each entry includes a name, description, "
        "and file path so you can open the source for full instructions when using a specific skill."
    )
    lines.append("### Available skills")

    for skill in sorted(skills, key=lambda s: s.name):
        path_str = str(skill.path).replace("\\", "/")
        lines.append(f"- {skill.name}: {skill.description} (file: {path_str}/SKILL.md)")

    lines.append("### How to use skills")
    lines.append(SKILLS_USAGE_RULES)

    return "\n".join(lines)
