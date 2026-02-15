"""Data models for skills registry."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SkillInfo:
    name: str
    description: str
    path: Path


@dataclass(frozen=True)
class ResolvedInput:
    original: str
    rendered: str
    invoked_skill: str | None
    arguments: str
