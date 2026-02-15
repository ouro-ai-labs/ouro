"""Slash-command autocomplete engine with fuzzy ranking and Enter resolution."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SlashSuggestion:
    """A slash-command suggestion item."""

    insert_text: str
    replace_text: str
    display: str
    help_text: str


class SlashAutocompleteEngine:
    """Pure slash autocomplete logic (UI-agnostic and easy to test)."""

    def __init__(
        self,
        commands: list[str],
        command_subcommands: dict[str, dict[str, str]],
        help_texts: dict[str, str] | None = None,
        display_texts: dict[str, str] | None = None,
    ) -> None:
        self.commands = commands
        self.command_subcommands = command_subcommands
        self.help_texts = help_texts or {}
        self.display_texts = display_texts or {}

    def suggest(self, text_before_cursor: str) -> list[SlashSuggestion]:
        """Return ordered suggestions for the current text."""
        if not text_before_cursor.startswith("/"):
            return []

        cmd_text = text_before_cursor[1:]

        # Subcommand context: /model e
        if " " in cmd_text:
            base, _, rest = cmd_text.partition(" ")
            if base not in self.command_subcommands or " " in rest:
                return []

            ranked_subs = self._rank_strings(list(self.command_subcommands[base].keys()), rest)
            return [
                SlashSuggestion(
                    insert_text=sub,
                    replace_text=rest,
                    display=self.display_texts.get(f"{base} {sub}", f"/{base} {sub}"),
                    help_text=self._get_help(f"{base} {sub}"),
                )
                for sub in ranked_subs
            ]

        # Top-level command context: /he
        ranked_cmds = self._rank_strings(self.commands, cmd_text)
        return [
            SlashSuggestion(
                insert_text=cmd,
                replace_text=cmd_text,
                display=self.display_texts.get(cmd, f"/{cmd}"),
                help_text=self._get_help(cmd),
            )
            for cmd in ranked_cmds
        ]

    def _get_help(self, key: str) -> str:
        if key in self.help_texts:
            return self.help_texts[key]
        return ""

    def _rank_strings(self, candidates: list[str], query: str) -> list[str]:
        if not query:
            return candidates

        query_lower = query.lower()
        scored: list[tuple[int, float, int, str]] = []

        for i, candidate in enumerate(candidates):
            candidate_lower = candidate.lower()
            score = _fuzzy_score(query_lower, candidate_lower)
            if score is None:
                continue

            # Hard-prioritize exact/prefix before generic fuzzy.
            match_tier = 2
            if candidate_lower == query_lower:
                match_tier = 0
            elif candidate_lower.startswith(query_lower):
                match_tier = 1

            scored.append((match_tier, score, i, candidate))

        scored.sort(key=lambda x: (x[0], x[1], x[2]))
        return [candidate for _, _, _, candidate in scored]


def _fuzzy_score(query: str, text: str) -> float | None:
    """Return fuzzy score (lower is better), or None if no match.

    Mirrors pi-mono style sequential fuzzy matching with word-boundary rewards,
    gap penalties, and consecutive-match rewards.
    """

    def _score_with(normalized_query: str) -> float | None:
        if not normalized_query:
            return 0.0
        if len(normalized_query) > len(text):
            return None

        query_index = 0
        score = 0.0
        last_match_index = -1
        consecutive_matches = 0

        for i, ch in enumerate(text):
            if query_index >= len(normalized_query):
                break
            if ch != normalized_query[query_index]:
                continue

            is_word_boundary = i == 0 or text[i - 1] in " -_./:"

            if last_match_index == i - 1:
                consecutive_matches += 1
                score -= consecutive_matches * 5
            else:
                consecutive_matches = 0
                if last_match_index >= 0:
                    score += (i - last_match_index - 1) * 2

            if is_word_boundary:
                score -= 10

            score += i * 0.1
            last_match_index = i
            query_index += 1

        if query_index < len(normalized_query):
            return None

        return score

    primary = _score_with(query)
    if primary is not None:
        return primary

    # Support "ab12" <-> "12ab" style fallback.
    split_idx = 0
    while split_idx < len(query) and query[split_idx].isalpha():
        split_idx += 1

    if 0 < split_idx < len(query) and query[split_idx:].isdigit():
        swapped = query[split_idx:] + query[:split_idx]
        swapped_score = _score_with(swapped)
        if swapped_score is not None:
            return swapped_score + 5

    split_idx = 0
    while split_idx < len(query) and query[split_idx].isdigit():
        split_idx += 1

    if 0 < split_idx < len(query) and query[split_idx:].isalpha():
        swapped = query[split_idx:] + query[:split_idx]
        swapped_score = _score_with(swapped)
        if swapped_score is not None:
            return swapped_score + 5

    return None
