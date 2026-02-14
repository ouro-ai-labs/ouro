# PTK-tuned interactive mode

This document tracks incremental performance improvements for the interactive TUI
without losing any existing commands or features.

Enable the mode:

```bash
OURO_TUI=ptk ouro
```

## Goals

- Preserve all interactive commands and behaviors from `interactive.py`.
- Improve perceived smoothness (less prompt corruption/flicker).
- Reduce ESC/ALT latency as much as possible without breaking common terminals.

## TODO

- [x] Add `OURO_TUI=ptk` toggle (no behavior changes in default mode).
- [x] Wrap interactive mode in `prompt_toolkit.patch_stdout()` to prevent prompt corruption.
- [x] Tune `ttimeoutlen/timeoutlen` in PTK mode for snappier ESC.
- [x] Add unit tests verifying PTK mode timeout tuning.
- [x] Reduce repeated completion/suggestion computations (simple caching).
- [x] Remove redundant completion refresh triggers (avoid triple `start_completion()` on `/`).
- [x] Avoid duplicate completion tasks on insertions (let prompt_toolkit `complete_while_typing` handle inserts; only force refresh on deletions).
- [ ] (Optional) Evaluate disabling Codex-style forced `start_completion()` refresh in PTK mode (requires manual acceptance testing on multiple terminals).
- [x] Cache prompt styling per theme to avoid rebuilding styles each prompt.
- [x] Avoid rebuilding default command help map on every completion.
- [ ] (Optional) Investigate status bar output frequency; reduce redundant re-renders without removing status information.
- [ ] (Optional) Add a debug flag to log prompt_toolkit key parsing timings.

## Acceptance checklist

- `/help`, `/reset`, `/stats`, `/resume`, `/skills`, `/model` all work.
- Output during tool execution does not break the input prompt.
- `Esc` closes the completion menu and feels responsive.
