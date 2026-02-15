from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class CommandSpec:
    name: str
    description: str = ""
    args_hint: str = ""
    group: str = ""
    subcommands: dict[str, CommandSpec] = field(default_factory=dict)

    @property
    def display(self) -> str:
        if self.args_hint:
            return f"/{self.name} {self.args_hint}"
        return f"/{self.name}"


@dataclass(frozen=True, slots=True)
class CommandRegistry:
    commands: list[CommandSpec]

    def to_help_map(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for cmd in self.commands:
            result[cmd.name] = cmd.description
            for sub_name, sub in cmd.subcommands.items():
                key = f"{cmd.name} {sub_name}".strip()
                result[key] = sub.description
        return result

    def to_subcommand_map(self) -> dict[str, dict[str, str]]:
        result: dict[str, dict[str, str]] = {}
        for cmd in self.commands:
            if cmd.subcommands:
                result[cmd.name] = {k: v.description for k, v in cmd.subcommands.items()}
        return result

    def to_display_map(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for cmd in self.commands:
            result[cmd.name] = cmd.display
            for sub_name, sub in cmd.subcommands.items():
                key = f"{cmd.name} {sub_name}".strip()
                extra = f" {sub.args_hint}" if sub.args_hint else ""
                result[key] = f"/{cmd.name} {sub_name}{extra}"
        return result
