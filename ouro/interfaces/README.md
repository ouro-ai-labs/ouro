# `ouro.interfaces` — CLI / TUI / Bot

The top layer. User-facing entry points. Imports flow downward into
`ouro.capabilities` and `ouro.core`. Nothing in those layers may
import from here.

This layer does **not** expose an SDK — it ships entry callables.

## What's inside

```
ouro.interfaces
├── cli/                     # argparse + dispatch
│   ├── main.py              # CLI flag parsing + dispatch
│   ├── factory.py           # create_agent() — wires AgentBuilder
│   └── entry.py             # `[project.scripts] ouro` shim
├── tui/                     # interactive REPL
│   ├── interactive.py       # InteractiveSession (slash commands, status bar)
│   ├── input_handler.py     # prompt_toolkit input
│   ├── command_registry.py  # /help, /reset, /stats, /resume, /model, /skills, /reasoning, /login, /logout, /theme
│   ├── status_bar.py
│   ├── theme.py
│   ├── components.py
│   ├── progress.py          # AsyncSpinner
│   ├── terminal_ui.py       # rich-based console
│   ├── tui_progress.py      # TuiProgressSink (the ProgressSink injected into capabilities)
│   ├── slash_autocomplete.py
│   ├── model_ui.py / oauth_ui.py / reasoning_ui.py / skills_ui.py
└── bot/                     # webhook server + IM channels
    ├── server.py            # aiohttp app, route registration, cron loop
    ├── session_router.py    # per-conversation ComposedAgent factory
    ├── message_queue.py     # debounce / coalesce bursty inputs
    ├── proactive.py         # CronScheduler + ProactiveExecutor
    ├── soul.py              # ~/.ouro/bot/soul.md
    └── channel/             # base.py, lark.py, slack.py, wechat.py
```

## CLI entry

Stable user-facing surface (unchanged across the refactor):

```bash
ouro                                         # interactive TUI (default)
ouro --task "<…>"                            # one-shot
ouro --task "<…>" --verify                   # one-shot + Ralph outer loop
ouro --resume latest                         # resume most-recent session
ouro --resume <session-id-prefix>            # resume by id prefix
ouro --model openai/gpt-4o                   # pick model for this run
ouro --reasoning-effort high                 # off | minimal | low | medium | high | xhigh
ouro --login   /  --logout                   # OAuth (ChatGPT Codex, Copilot)
ouro --bot                                   # webhook daemon (Lark / Slack / WeChat)
ouro --version
```

Internally `ouro` resolves to `ouro.interfaces.cli.entry:main`.

`ouro.interfaces.cli.factory.create_agent(model_id=None, sessions_dir=None,
memory_dir=None)` is the canonical assembly path — both the CLI and the
bot factory call it. It wires `AgentBuilder` with the standard tool set
plus `TuiProgressSink`, then post-injects `MultiTaskTool(agent)`.

See the [CLI Guide](../../docs/cli-guide.md) for the slash-command
catalog and keyboard shortcuts.

## TUI

`InteractiveSession` (in `tui/interactive.py`) drives the REPL:

- prompt_toolkit input with history (`~/.ouro/.history`),
- slash commands resolved by `CommandRegistry`,
- status bar shows current model + memory stats,
- `Ctrl+C` cancels the in-flight task; `Ctrl+L` clears; `Ctrl+T`
  toggles thinking; `Ctrl+S` toggles stats.

`TuiProgressSink` is the bridge between capabilities and rich UI: it
implements the `ouro.core.loop.ProgressSink` Protocol and renders via
`terminal_ui` + `AsyncSpinner`. The interactive shell still prints the
final returned answer itself; the sink is mainly for incremental
progress events (thinking, tool calls/results, spinners, completion
markers). When you pass `--bot` (or call `AgentBuilder` yourself with a
quieter sink), capabilities' UI calls become no-ops automatically.

## Bot

`ouro --bot` starts an aiohttp webhook server. Each enabled channel
(`LARK_*`, `SLACK_*`, `WECHAT_ENABLED` env vars) registers routes; the
`SessionRouter` maps `{channel}:{conversation_id}` → a per-conversation
`ComposedAgent` with its own memory.

```
~/.ouro/bot/
├── soul.md                 # personality / tone (load_soul)
├── cron_jobs.json          # CronScheduler persistence
└── conversation_map.yaml   # conv-id → session-id, survives restarts
```

`CronScheduler` (in `bot/proactive.py`) drives recurring and one-time
tasks. The `manage_cron` tool plugged into each agent talks to it
through a capabilities-local `CronScheduler` Protocol — capabilities
never imports the interface implementation.

See the [Bot Guide](../../docs/bot-guide.md) for channel setup
(Lark / Slack / WeChat), proactive tasks, and the soul file.

## Adding a new channel

1. Subclass `Channel` in `bot/channel/<your_channel>.py` with
   `IncomingMessage` / `OutgoingMessage` round-tripping.
2. Register it in `bot/server.py:run_bot` next to the existing
   Lark / Slack / WeChat blocks (gated on a sensible env-var check).
3. Add a focused test under `test/test_<your_channel>.py`.

## Adding a new slash command

1. Add the spec in `tui/command_registry.py`.
2. Implement the handler on `InteractiveSession` in `tui/interactive.py`.
3. Update [docs/cli-guide.md](../../docs/cli-guide.md).
4. Add a unit test under `test/test_slash_*.py`.

## See also

- [Interfaces layer agent instructions](CLAUDE.md) — rules for editing this layer.
- [TUI UX stability](tui/CLAUDE.md) — autocomplete + skills test discipline.
- [CLI Guide](../../docs/cli-guide.md) — full slash-command + shortcut reference.
- [Bot Guide](../../docs/bot-guide.md) — channel setup + proactive tasks.
- [Capabilities layer README](../capabilities/README.md) — what this layer assembles.
