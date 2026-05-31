# RFC: Grep Content Tool Improvements

- Status: Draft
- Authors: Yixin Luo
- Date: 2026-05-31

## Summary

Improve `grep_content` to reduce repetitive tool calls by borrowing design patterns from Claude Code's `GrepTool`: adding `head_limit`/`offset` pagination, `type` filtering, smarter output formatting with clear completion signals, and anti-repetition guardrails in the tool description.

## Problem

In long sessions, `grep_content` is the most frequent trigger of `RepeatedToolCallRule` warnings. Session analysis shows a common loop:

1. `grep_content(pattern="aiohttp|ClientSession", mode="with_context", ...)`
2. Result returns matches in 2 files
3. Model reads one file with `read_file`
4. Model calls the **exact same** `grep_content` again
5. `RepeatedToolCallRule` blocks it on the 3rd repeat
6. Model switches to `shell(grep -rn ...)` — same search, different tool

This wastes tokens and iterations. The root causes are:

- **No clear "completion" signal**: The model can't tell if the search was exhaustive or truncated
- **No pagination**: Large result sets are silently truncated with `max_count=50`, but the model doesn't know how to continue
- **Parameter mismatch with intent**: `max_count` limits total results, `max_matches_per_file` limits per file — but neither communicates "there's more" clearly
- **Tool description doesn't warn against repetition**: Unlike Claude Code's "ALWAYS use Grep for search tasks. NEVER invoke `grep` or `rg` as a Bash command", ouro's description doesn't establish grep_content as the canonical search tool

## Goals

- Add `head_limit` + `offset` pagination (like Claude Code's `head_limit`/`offset`)
- Add `type` parameter for file-type filtering (like Claude Code's `--type`)
- Restructure output to clearly signal truncation and how to paginate
- Update tool description to discourage `shell`/`bash` for search and warn against repetition
- Keep backward compatibility: existing parameter names and defaults unchanged

## Non-goals

- Changing `RepeatedToolCallRule` logic (it's working as designed)
- Adding result caching or memoization (out of scope; rules handle repetition)
- Changing the ripgrep/Python fallback split
- Adding new output modes beyond the three existing ones

## Proposed Behavior (User-Facing)

### New Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `head_limit` | integer | 250 | Max results to return (lines/files/counts). 0 = unlimited. |
| `offset` | integer | 0 | Skip first N results before applying head_limit. |
| `type` | string | None | File type filter (rg `--type`), e.g. "py", "js", "rust". More efficient than glob for standard types. |

`max_count` and `max_matches_per_file` are **deprecated** (kept for compatibility but ignored when `head_limit` is set). A deprecation warning is included in the result if the old params are used.

### Output Format Changes

**When results are truncated:**
```
Found 3 files (showing first 250, use offset=250 to see more)
ouro/interfaces/bot/server.py
ouro/interfaces/bot/channel/slack.py
ouro/core/loop/agent.py
```

**When no truncation:**
```
Found 3 files
ouro/interfaces/bot/server.py
ouro/interfaces/bot/channel/slack.py
ouro/core/loop/agent.py
```

**Content mode with truncation:**
```
[Showing 250 lines with offset=0 — use offset=250 to continue]
ouro/interfaces/bot/server.py:11:from aiohttp import web
...
```

### Tool Description Update

Add to the description:
- "ALWAYS use `grep_content` for code search. NEVER use `shell` to run `grep` or `rg` — this tool has correct permissions and ignores."
- "If you just searched for a pattern and got results, do NOT run the exact same search again. Read the files or refine your pattern instead."

## Invariants (Must Not Regress)

- Existing `grep_content` calls with current parameters continue to work
- Default behavior without new params is unchanged (no surprise truncation)
- `files_only` mode still returns just file paths
- `with_context` mode still supports `context_lines`
- `count` mode still returns per-file counts
- ripgrep path and Python fallback behavior unchanged

## Design Sketch (Minimal)

### Parameter Handling

In `GrepTool.execute()`, detect deprecated params:
```python
if max_count != 50 or max_matches_per_file != 5:
    # Old params used — map them to head_limit for compatibility
    head_limit = head_limit or max_count
    # max_matches_per_file is dropped (rg -m is per-file, incompatible with global head_limit)
```

Default `head_limit=250` when not specified (same as Claude Code). Explicit `head_limit=0` means unlimited.

### Output Builder

Add helper `_format_result(items, mode, head_limit, offset)` that:
1. Applies `head_limit`/`offset` to the result list
2. Builds the summary line with truncation info
3. Returns `(content_str, was_truncated)`

### Description Update

Append anti-repetition guidance to the existing description string.

## Alternatives Considered

- **Keep `max_count` as primary limiter**: Rejected. `max_count` is ambiguous (total results? per file?). `head_limit` is clearer and matches Claude Code's convention.
- **Add result caching in the tool**: Rejected. Caching belongs at the loop/rules layer, not in individual tools. The tool should be stateless.
- **Raise `RepeatedToolCallRule.threshold` for grep_content only**: Rejected. This masks the symptom rather than fixing the cause (model doesn't know search is complete).
- **Add a `search_id` or `cache_key` parameter**: Rejected. Too complex; the model doesn't track IDs.

## Test Plan

- Unit tests (`test/test_grep_tool.py`):
  - `head_limit` truncates results, shows pagination hint
  - `offset` skips first N results
  - `head_limit=0` returns unlimited
  - `type` parameter filters by file type
  - Deprecated `max_count` maps to `head_limit` with warning
  - No truncation hint when results fit within limit
- Targeted: `./scripts/dev.sh test -q test/test_grep_tool.py`
- Smoke: `python main.py --task "find all uses of asyncio in ouro/" --verify`

## Rollout / Migration

- Backward compatibility: old params still work, just with deprecation notice
- No config changes
- No migration steps for users

## Risks & Mitigations

- **Model still repeats searches**: Mitigation: the clearer "showing X of Y" + pagination hint makes it obvious the search is complete. The description update also explicitly warns against repetition.
- **250 default too low for some workflows**: Mitigation: `head_limit=0` escape hatch is documented. Can adjust default based on usage.
- **Breaking scripts that parse grep_content output**: Mitigation: output format change is additive (adds summary line), doesn't change the list format.

## Open Questions

- Should we add `head_limit` to other tools (`glob_files`, `shell`) for consistency?
- Should the pagination hint include the total count (requires counting all results before truncating)?
