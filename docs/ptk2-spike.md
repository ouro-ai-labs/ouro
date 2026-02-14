# PTK2 Spike Plan (Single Renderer)

Goal: validate whether a prompt_toolkit single-renderer architecture delivers
meaningfully smoother interactive UX than the current mixed Rich + prompt flow.

This is a **spike**, not a final migration. We keep existing interactive mode as default.

## Modification Points

1. **New PTK2 mode entrypoint**
   - Add `OURO_TUI=ptk2` switch in `main.py`.
   - Route to a new `run_interactive_mode_ptk2(agent)` implementation.

2. **Single-renderer app shell**
   - Add a full-screen prompt_toolkit app with:
     - output pane
     - input pane
     - bottom status line
   - Keep all rendering inside one PTK application.

3. **Logic reuse from existing interactive flow**
   - Reuse `InteractiveSession` command and agent orchestration logic.
   - Avoid changing command semantics (`/help`, `/reset`, `/stats`, ...).

4. **Output routing**
   - Route `terminal_ui.console` + stdout/stderr to PTK output pane.
   - Add ANSI stripping for readable pane output.

5. **Input bridge**
   - Replace `InteractiveSession` prompt reads with a PTK queue-backed prompt bridge.
   - Keep slash completer behavior in PTK2 input.

6. **Documentation + tests**
   - Document experimental mode usage.
   - Add focused tests for PTK2 output helpers.

## TODO

- [x] Create spike plan + scope document.
- [x] Add RFC for PTK2 single-renderer spike.
- [x] Implement `utils/tui/ptk2_mode.py` (minimal vertical slice).
- [x] Add `OURO_TUI=ptk2` switch in `main.py`.
- [x] Add output helper tests (`strip_ansi`, chunk handling).
- [x] Update `README.md` and `docs/examples.md` with PTK2 usage.
- [x] Run `./scripts/dev.sh check`.
- [x] Manual A/B smoke test (`OURO_TUI=ptk2` vs default) and record observations.

## Acceptance for this spike

- PTK2 mode starts with `OURO_TUI=ptk2 ouro`.
- User can type a normal prompt, receive assistant output, and continue.
- Slash commands still execute through existing interactive logic.
- No default-mode regressions.
