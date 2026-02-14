# RFC 009: PTK2 Single-Renderer Interactive Spike

## Status

Draft

## Summary

Introduce an experimental interactive mode (`OURO_TUI=ptk2`) that uses a single
prompt_toolkit renderer for input and output. This is intended to evaluate
whether unified rendering reduces flicker/latency compared to the current
mixed Rich + prompt flow.

## Problem Statement

Current interactive UX mixes:
- prompt_toolkit for input/completion
- Rich console output/status rendering

Under high output, this can cause redraw contention (prompt movement, flicker,
and occasional completion instability).

## Goals

- Validate single-renderer UX improvements quickly.
- Preserve existing command semantics by reusing `InteractiveSession` logic.
- Keep old interactive mode as default/fallback.

## Non-Goals (Spike)

- Full UI parity in this first iteration.
- Replacing all Rich formatting with native PTK widgets.
- Removing existing interactive mode.

## Proposed Approach

1. Add `run_interactive_mode_ptk2(agent)`.
2. Build a full-screen PTK app with output pane, input line, and status line.
3. Reuse `InteractiveSession` for command handling and agent orchestration.
4. Bridge input through an async queue (PTK input -> session prompt requests).
5. Route terminal output (`terminal_ui.console`, stdout/stderr) into PTK output pane.

## Alternatives Considered

- Continue tuning mixed renderer only (`patch_stdout` + timeouts)
  - Pros: low risk
  - Cons: limited ceiling; contention still exists
- Rewrite interactive business logic for PTK2
  - Pros: cleaner long-term architecture
  - Cons: high parity risk (rejected previously)

## Risks

- Some nested prompt_toolkit flows (e.g. picker dialogs) may still compete with
  the PTK2 app in spike phase.
- Output capture fidelity (ANSI stripping, multiline formatting) may not match
  Rich exactly in v1 spike.

## Success Criteria (Spike)

- `OURO_TUI=ptk2` launches and supports multi-turn chatting.
- Slash commands execute through existing session logic.
- Prompt remains stable during high-volume output.
- Default mode remains unchanged.
