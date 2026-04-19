# RFC 016: Agent Steering (Mid-Loop Message Injection)

- Status: Draft
- Authors: ouro-dev
- Date: 2026-04-19

## Summary

Introduce a **steering** mechanism that lets a user inject a new message while
the agent is mid-task. Steering messages are delivered between tool calls
(not during LLM streaming), causing the remaining tools in the current batch
to be skipped and the new message to be handed to the model on the next turn.
A sibling **follow-up** queue holds messages to be processed after the current
task completes. Exposed through the interactive TUI and bot/WeChat channels.

Inspired by the `steer()` / `followUp()` primitives in
[pi-mono](https://github.com/pi-inc/pi-mono)'s `packages/agent` and
`packages/coding-agent`.

## Problem

Today, once `agent.run(task)` starts, the user's only mid-task options are:

- **Wait** for the task to finish.
- **Ctrl+C** → cancel the entire run (throws `CancelledError`, rolls back the
  incomplete exchange via `rollback_incomplete_exchange`). Starts over.

There's no way to say *"stop doing that, do this instead"* without losing the
progress already made. In bot/WeChat, any message that arrives while the agent
is executing is silently queued by `ConversationQueue` and delivered as the
*next* task — never as a mid-task correction.

Concrete example (TUI):

```
> refactor auth.py to use the new middleware
⏳ [agent reads 4 files, starts editing]
   ...user realizes: "wait, I meant billing.py, not auth.py"
   ...today they have to Ctrl+C and restart from zero.
```

## Goals

- Let a user inject a message mid-task that the agent sees on its next turn.
- Skip any remaining tool calls in the currently-executing batch when a
  steering message arrives.
- Queue "do-this-after" messages (follow-ups) that fire once the current task
  finishes.
- Expose the feature consistently across **interactive TUI** and
  **bot channels** (WeChat initially; Slack/Lark inherit via the shared
  `ConversationQueue` path).
- Preserve conversation-history integrity: no dangling `tool_calls` without
  matching `tool` results.

## Non-goals

- Interrupting an in-flight **LLM streaming response** (checkpoints are between
  tool calls and between turns; the model finishes its current reply first).
- Interrupting a single **running tool call** (the tool finishes, *then*
  steering is checked before the next tool).
- Per-message priority, reordering, or deduplication within a queue.
- Changing Ctrl+C semantics (full cancel still works as today).
- Changes to `IsolatedAgentRunner` / cron job paths.

## Proposed Behavior (User-Facing)

### Interactive TUI

- While `agent.run()` is executing, the `>` prompt remains active (today it
  blocks). Text + Enter during a run queues a **steering** message by default.
- Explicit follow-up: a line starting with `/followup ` is queued as
  **follow-up** (fires after the current run completes).
- `/steering status` — slash command that prints the current steering and
  follow-up queue contents (pending messages, in order), plus whether a run
  is currently in progress. Works both idle and mid-run.
- When idle, behavior is unchanged — input is a new prompt.
- Visual cue: while the agent is running, the prompt shows
  `⚡> ` (steering) to indicate input will be injected, not started as a new
  task.

### Bot / WeChat (and other channels using `ConversationQueue`)

- A message arriving while the agent is running for that conversation is, by
  default, delivered as **steering** to the active run. **Uniform across all
  bot channels** (WeChat, Slack, Lark) — no per-channel override in v1.
- A message whose text starts with `+ ` (with space) or `/followup ` is
  delivered as **follow-up**.
- Idle messages still go through the debounce/coalesce path (unchanged).

### Delivery semantics (both surfaces)

- **Steering mode: `all`.** At each checkpoint, the entire steering queue is
  drained and injected as consecutive `role: user` messages, in arrival order,
  before the next LLM turn. (Rationale: rapid-fire corrections are typically
  one thought; the model should see the complete picture.)
- **Follow-up mode: `all`.** After the current run's final answer, the
  follow-up queue is drained and fed as a single combined prompt to a new
  `agent.run()`.
- A user sees their steering message echoed into the transcript as a regular
  user turn.

### Skipped-tool semantics

When steering is detected mid-batch, remaining tool calls are **not executed**.
Each is recorded with a synthetic result:

```
[Skipped due to user steering]
```

All `tool_calls` in the assistant message still get a matching `tool` result —
satisfying the OpenAI/Anthropic invariant and keeping the history valid.

**UI silence.** Skipped tools are **not** echoed to the user in the TUI or bot
transcript. They are logged (`logger.debug`) and visible in history only via
`/steering status` or a memory inspector. Rationale: the user just injected a
steering message — they don't need a "skipped N tools" notification cluttering
the conversation; the model's next reply will reflect the new direction.

## Invariants (Must Not Regress)

- Ctrl+C still cancels the entire run and rolls back the incomplete exchange.
- When no steering/follow-up messages arrive, the loop behaves **identically**
  to today (same turns, same tool execution order, same final-answer path).
- `_ralph_loop` verification still works; a steering injection during a Ralph
  iteration does not break the outer verification loop.
- `ConversationQueue` debounce/idle-timeout behavior is unchanged for idle
  conversations.
- Parallel tool execution path (`_execute_tools_parallel`) remains correct —
  steering is not checked mid-parallel (see Design Sketch).
- Tool results are always paired with their `tool_calls` (no API 400s).

## Design Sketch (Minimal)

### New module: `agent/steering.py`

```python
class SteeringQueues:
    def __init__(self) -> None:
        self._steering: deque[str] = deque()
        self._follow_up: deque[str] = deque()
        self._lock = asyncio.Lock()
        self._is_running = False

    def steer(self, text: str) -> None: ...        # non-blocking enqueue
    def follow_up(self, text: str) -> None: ...    # non-blocking enqueue
    def drain_steering(self) -> list[str]: ...     # `all` mode
    def drain_follow_up(self) -> list[str]: ...
    def is_running(self) -> bool: ...
    def pending_counts(self) -> tuple[int, int]: ...
```

Owned by the agent: `BaseAgent.steering = SteeringQueues()`.

### Loop checkpoint (`agent/base.py::_react_loop`)

One checkpoint, only when `use_memory=True` (mini-loops inside plan execution
are internal and don't accept user steering):

**Top of each iteration, before `_call_llm`**: drain the steering queue →
append each message as a `role: user` entry in memory → proceed to the LLM
call. The model sees injected messages on this turn.

This single checkpoint covers both "between LLM turns" and "after tool
execution" — once tools finish (or are skipped mid-batch), the loop iterates
back to the top and the checkpoint fires before the next LLM call.

### Tool-batch checkpoint (`_execute_tools_sequential`)

Between each tool in a sequential batch (line 294 loop), check
`steering.pending_counts()`. If non-zero:

- Stop executing further tools.
- For each unexecuted tool call, emit a `ToolResult` with content
  `[Skipped due to user steering]` and the correct `tool_call_id`.
- Return; the outer `_react_loop` loops back and will drain the queue at
  checkpoint #2 above.

**Parallel path:** unchanged. Readonly parallel batches are short; waiting for
all tasks to complete before checking steering is acceptable and keeps the
invariant (no half-finished parallel group).

### TUI integration (`interactive.py::InteractiveSession.run`)

Today: `prompt_async()` blocks on stdin, no input accepted during `agent.run`.
Change: `prompt_async()` is always live. Its callback:

- If `self.current_task is None`: start a new run (today's path).
- Else: route the line to `self.agent.steering.steer(...)` or
  `follow_up(...)` based on `/followup ` prefix.

The prompt glyph switches between `> ` and `⚡> ` via the existing status-bar
refresh.

### Bot integration (`bot/session_router.py` + `bot/message_queue.py`)

The session router already knows which agent is handling which conversation.
Add `agent.steering.is_running()` check in the batch-delivery callback:

- If running: drop the batch into steering (or follow-up on `+ ` / `/followup
  ` prefix).
- If idle: existing path (new prompt).

`ConversationQueue` itself is unchanged — it still debounces rapid incoming
messages; the *callback* decides routing.

### History format

Steering messages are plain user messages in `memory.messages`:

```
{"role": "user", "content": "wait, use billing.py instead"}
```

No special marker. The model cannot distinguish them from a normal prompt,
which is the desired semantics.

## Alternatives Considered

- **Single queue.** Drop the steering/follow-up distinction; all mid-task
  messages become steering. Simpler, but loses the "do this *after*" use
  case that's natural in bot channels ("+ commit when done").
- **Mode `one-at-a-time`.** Drain one queued message per iteration. Cleaner
  turn-by-turn reasoning, but wastes turns when the user types a single
  thought as three quick messages. Rejected for v1; could add as a config
  later.
- **Interrupt the LLM stream.** Cancel the in-flight `llm.call_async` on
  steering arrival. More responsive, but complicates cache semantics and
  streaming telemetry; pi-mono also deliberately avoids this.
- **Pause/resume single tool.** Per-tool cancellation is out of scope — tools
  are short enough that waiting for completion is acceptable.

## Test Plan

### Unit tests (`test/test_steering.py`, new)

- Enqueue steering on idle agent; verify drained into first turn.
- Enqueue steering mid-sequential-batch; verify remaining tools get
  `[Skipped due to user steering]` results with matching IDs.
- Enqueue multiple steering messages before a checkpoint; verify all appear
  in order as separate user messages (mode=`all`).
- Enqueue follow-up during a run; verify it does **not** appear until run
  completes, then triggers a new run.
- Verify API-payload invariant: every `tool_calls` in the assistant message
  has a matching `tool` result after steering.
- Queue overflow: enqueue > 32 steering messages; verify oldest are dropped
  with a warning log and newest are preserved.
- `/steering status` command: returns both queues' contents plus the
  `is_running()` flag, both idle and mid-run.
- Skip-tool silence: verify no `terminal_ui.print_*` call is made for skipped
  tools (only `logger.debug`).

### Existing tests (must still pass)

- `./scripts/dev.sh test -q test/test_ralph_loop.py`
- `./scripts/dev.sh test -q test/test_parallel_tools.py`
- `./scripts/dev.sh test -q test/test_bot_message_queue.py` (if present)
- `./scripts/dev.sh test -q` (full tracked suite)
- `TYPECHECK_STRICT=1 ./scripts/dev.sh typecheck`

### Smoke run

- TUI: `python main.py --mode interactive`, start a long read-heavy task,
  type a steering message mid-run, verify the model adapts.
- Bot/WeChat: start a long task via bot, send a second message while running,
  verify it arrives as steering and the agent shifts direction.

## Rollout / Migration

- **Backward compatibility:** additive. Steering queues start empty; if no one
  calls `steer()` / `follow_up()`, behavior is identical to today.
- **No config migration needed.** Optional config keys
  (`steering.enabled: true` default, `steering.followup_prefix: "+ "`) are
  read with defaults.
- **Per-surface rollout:**
  1. Land `SteeringQueues` + base-loop checkpoints + unit tests (no surface
     wiring; behavior unchanged).
  2. Wire TUI (`interactive.py`) + TUI smoke test.
  3. Wire bot session-router + WeChat smoke test.
  Each step is a separate PR.

## Risks & Mitigations

- **Dangling tool_calls → API 400.** Mitigation: `_execute_tools_sequential`
  always emits a `ToolResult` (real or skipped) for every `ToolCall` before
  returning. Asserted in unit tests.
- **Race: steering arrives between "drain check" and LLM call.** Mitigation:
  two checkpoints per iteration (before LLM + after tools) reduce the window
  to one LLM turn. Acceptable: the message is delivered on the *next* turn.
- **TUI input complexity.** `prompt_async` being always-live changes the
  existing stdin loop. Mitigation: keep the change isolated behind a flag
  during bringup; fall back to blocking prompt if the new path errors.
- **Bot channel abuse (spamming steering).** Steering messages accumulate in
  a deque; no upper bound today. Mitigation: v1 caps each queue at 32;
  overflow drops oldest with a warning log.
- **Parallel batch not checked.** Mitigation: readonly parallel batches are
  bounded (typically ≤5 tools, all fast reads); check steering immediately
  after the batch completes.

## Open Questions

*(none — resolved during RFC review on 2026-04-19)*

Resolved:

- **`/steering status` included in v1.** Shows both queues' pending messages
  and the running flag.
- **Bot default-steer is uniform across channels.** No per-channel
  configurability in v1; all bot channels (WeChat, Slack, Lark) default to
  steer mid-run.
- **Skipped tools are silent in UI.** Logged only; no user-visible
  "⏭ Skipped N tools" message.
