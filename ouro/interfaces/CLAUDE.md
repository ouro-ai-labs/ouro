# ouro.interfaces — User-Facing Layer

`AGENTS.md` is a symlink to this file.

The top layer. User-facing CLI, TUI, and bot channels. Importable
freely from `ouro.capabilities` and `ouro.core` (downward). Nothing
in `ouro.core` or `ouro.capabilities` may import from here — caught
by `import-linter`.

## What lives here

- `cli/main.py` — argparse + dispatch (interactive / --task / --bot /
  --login / --logout / --resume / etc.).
- `cli/factory.py` — builds a `ComposedAgent` for the standard CLI/bot
  via `AgentBuilder`. The TUI sink (`TuiProgressSink`) is wired here.
- `cli/entry.py` — thin shim registered as `[project.scripts] ouro`.
- `tui/interactive.py` — `InteractiveSession`, slash commands,
  prompt_toolkit input loop.
- `tui/{terminal_ui, progress, theme, status_bar, components, …}` — UI
  primitives. `tui_progress.py` is the `ProgressSink` implementation
  injected into capabilities.
- `bot/server.py` — aiohttp webhook server, channel registration,
  cron + proactive scheduling.
- `bot/session_router.py` — per-conversation `ComposedAgent` factory
  with disk-persisted conversation map.
- `bot/channel/{lark,slack,wechat,base}.py` — channel implementations.
- `bot/proactive.py`, `bot/soul.py`, `bot/message_queue.py`.

## When editing

- Keep capabilities/core untouched when only the UX changes here.
- If you find yourself wanting capabilities to call into a TUI
  function, define a ProgressSink-style Protocol in capabilities and
  implement it here instead.
- TUI test surface lives at `test/test_interactive_*.py`,
  `test/test_slash_*.py`, `test/test_lark_channel.py`, etc. Bot tests
  at `test/test_bot_*.py`.

## CLI entry

Stable user-facing command:

```bash
ouro                                 # interactive
ouro --task "..."                    # one-shot
ouro --task "..." --verify           # one-shot + Ralph outer loop
ouro --bot                           # webhook daemon
ouro --login | --logout              # OAuth flows
ouro --resume [latest|<prefix>]      # restore a saved session
```

Internally `ouro` resolves to `ouro.interfaces.cli.entry:main`.
