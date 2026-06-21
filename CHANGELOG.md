# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.1] - 2026-06-21

### Added

- **OpenAI Codex subscription adapter**: added subscription-based Codex support, model catalog updates, and retry handling for transient Codex transport failures (#229, #227, #242).
- **Agent Tracing Monitor foundation**: added an RFC and first core tracing primitives, including trace events/spans, context propagation, in-memory and JSONL exporters, redaction, truncation, and package registration (#239, #241).
- **Progress event bus and sinks**: refactored progress reporting into a shared event bus with source metadata, JSON progress output, and clearer CLI/TUI task and swarm rendering (#231, #232, #228).

### Changed

- **Swarm robustness and observability**: redesigned swarm execution around Task V2, improved worker shutdown/coordination, surfaced sub-agent source prefixes, and renamed the swarm config flag (#234, #236, #237, #233, #235).
- **LLM reliability**: retry transient LLM disconnects and upgrade LiteLLM to `1.87.0` (#238, #226).
- **GitHub Copilot model catalog**: updated OAuth model discovery/catalog entries (#225).
- **Documentation**: restructured README Features and Architecture sections (#222).

### Fixed

- **TUI rendering**: escape tool-call markup and colorize status bar metrics for clearer, safer terminal output (#240, #243).
- **Session persistence**: incrementally persist sessions and print the session ID on interactive exit (#223, #224).

## [0.5.0] - 2026-05-31

### Added

- **Task V2**: persistent task store with dependency graphs (`task_create`, `task_list`, `task_update`, `task_delete`, `task_link`, `task_unlink`, `task_show`) backed by SQLite. Supports `status`, `priority`, `tags`, `due_date`, and topological ordering via `task_list --order topo` (#214).
- **Agent Swarm**: multi-agent coordination with automatic task decomposition. The orchestrator breaks down complex tasks into subtasks, spawns specialized workers, and aggregates results. Includes `task_claim` tool for workers to pick up tasks (#216, #219).
- **Auto-swarm mode**: `--mode auto-swarm` enables fully automatic task decomposition and multi-agent execution without manual orchestration (#219).
- **Task V2 documentation**: new `docs/tasks.md` covering task lifecycle, dependency graphs, and swarm usage (#215).

### Changed

- **Memory compression threshold**: increased default from 60K to 256K tokens to reduce compaction frequency (#212).
- **Status bar improvements**: replaced Mode indicator with ↑↓ arrows for KV cache read/write, cleaner layout (#206, #207).
- **Session resumption**: restored status bar state and added session prefix on resume (#213).
- **Token usage persistence**: token usage stats are now persisted and restored on session resume (#217).

### Fixed

- **`grep_content` token waste**: output is now grouped by file with `head_limit`/`offset` pagination, `type` filter, and anti-repetition hints to reduce `RepeatedToolCallRule` triggers (#218, #220).
- **`smart_edit` stale detection**: added mtime + content hash checks to warn when a file changed between read and edit (#210).
- **`ReadBeforeWriteRule` partial-read guard**: prevents overwrites when only a portion of a file was read (#208).
- **Shell exit-code interpretation**: semantic interpretation of exit codes in shell tool results (#209).

## [0.4.4] - 2026-05-24

### Added

- **Session history replay**: resumed sessions now render full history using the same TUI components as live turns (`print_user_message`, `print_assistant_message`, `print_tool_call`, `print_tool_result`) via `ProgressSink.on_session_loaded` (#203).
- **Compaction panel**: compaction summaries in resumed sessions render in a dedicated amber/warning-styled **Compaction** panel instead of plain user messages (#204).

### Fixed

- **TUI markup error**: removed `⚠` unicode character from blocked-tool panel title that caused Rich `MarkupError` (#201).
- **TUI rollback on exception**: added `rollback_incomplete_exchange()` in exception handlers to prevent conversation state corruption when tool calls are interrupted (#201).
- **TUI visual cleanup**: removed redundant "Assistant:" prefix and "✓ Final answer received" marker from interactive output (#202).
- **Attribution**: updated Co-Authored-By email from old GitHub username `ahahoul007` to `ouro-ai-lab` (#199).

## [0.4.3] - 2026-05-24

### Added

- **Memory blocks**: named, size-bounded markdown blocks under
  `~/.ouro/memory/blocks/{user,project,scratch}.md` always loaded into the
  system prompt. The agent edits them via a new `memory_block_edit` tool
  (`read` / `replace` / `append` operations). Strict blocks (`user`,
  `project`) reject overflow with an actionable error; `scratch` is lenient
  with FIFO truncation. Inspired by Letta/MemGPT's core memory.
- **Pluggable Rule abstraction**: deterministic pre-dispatch guards for the
  agent loop. Includes `ReadBeforeWriteRule` to block blind overwrites of
  unread files (#190, #192).
- **Deterministic AGENTS.md auto-loading**: project-wide and per-directory
  rule files are loaded automatically based on the working directory (#193).
- **Lazy subdirectory AGENTS.md loading**: nested `AGENTS.md` files are
  loaded on-demand when tools target their directories (#196).
- **Commit/PR attribution**: shell tool descriptions now include Co-Authored-By
  and PR attribution footers for ouro-generated commits (#194).

### Changed (BREAKING)

- **`LTM_CONVERSATION_SEARCH_ENABLED` flag removed**. The
  `conversation_search` tool + FTS5 index (introduced in PR #188 as opt-in)
  are now always on, matching memory blocks. Both layers are peers of the
  same long-term memory feature; gating one but not the other was an
  asymmetry. Setting the flag has no effect after this PR.
- **`LongTermMemoryManager` replaced by `MemoryBlockManager`**. The old
  `memory.md` + daily file (`YYYY-MM-DD.md`) + LLM consolidator system is
  removed. Existing `~/.ouro/memory/memory.md` and daily files remain on
  disk but are **no longer read**; users who want to keep their data can
  manually copy it into a block. `LONG_TERM_MEMORY_ENABLED`,
  `LONG_TERM_MEMORY_CONSOLIDATION_THRESHOLD`, `LONG_TERM_MEMORY_DAILY_WINDOW`,
  and `LONG_TERM_MEMORY_DAILY_RETENTION` config keys are gone (setting them
  has no effect). The `LongTermMemoryManager` public class is replaced by
  `MemoryBlockManager` in `ouro.capabilities`.
- **Compaction no longer auto-extracts long-term memories**. The
  `<long_term_memories>` XML block was removed from compaction prompts;
  memory is now agent-driven via `memory_block_edit` instead of
  opportunistically dumped during compaction. The conversation itself is
  still searchable via `conversation_search` (FTS5).

### Removed (BREAKING — from PR #189)

- **mem0 backend removed**. `MEM0_ENABLED`, `MEM0_USER_ID`, and all
  `MEM0_*` env overrides are gone; setting them has no effect. The
  `Mem0MemoryStore` and `Mem0LongTermMemory` classes are deleted, and
  the `mem0ai` + `qdrant-client` dependencies are dropped from
  `pyproject.toml`. `YamlFileMemoryStore` is now the only persistence
  backend. The new `LTM_CONVERSATION_SEARCH_ENABLED` flag (SQLite
  FTS5, no embedder) covers the cross-session recall use case that
  mem0 originally addressed.

## [0.4.2] - 2026-05-20

### Added

- **mem0 integration**: optional vector-memory backend via mem0. Enable
  by installing the `mem0` extra (`pip install ouro-ai[mem0]`) and
  configuring it in `~/.ouro/config`. A new `BaseLongTermMemory` ABC
  unifies the contract across the in-tree memory store and mem0.

### Fixed

- **Loop death loops**: detect and break self-reinforcing tool-call
  loops where compaction summaries re-encode repeated tool calls as
  "patterns" and feed them back into the model (#185).
- **Token tracker**: wire actual LLM usage into `TokenTracker` so the
  status bar reflects real token counts instead of stale/zero values (#183).

### Docs

- Updated README and `docs/memory-management.md` to cover the mem0
  backend and configuration (#186).

## [0.4.1] - 2026-05-08

### Fixed

- **Packaging**: include `ouro.capabilities.compaction` in the wheel
  and add an invariant check so missing subpackages fail the build
  rather than silently breaking PyPI installs (#182).

## [0.4.0] - 2026-04-27

### Changed

- **Three-layer architecture**: code reorganized under a new `ouro/`
  namespace with strict import boundaries enforced by `import-linter`:
  `ouro.interfaces` → `ouro.capabilities` → `ouro.core`. Reverse
  imports are forbidden.
- **Hooks-based agent loop**: `ouro.core.loop.Agent` is a class-based
  ReAct loop that takes optional `Hook` objects. Memory, compaction,
  and Ralph-style verification are now implemented as hooks
  (`MemoryHook`, `VerificationHook`) rather than baked into the loop.
- **Canonical assembly via `AgentBuilder`**: build a `ComposedAgent`
  with `AgentBuilder().with_llm(...).with_tools(...).with_memory(...)
  .with_skills(...).with_verification(...).build()`.
- **`ProgressSink` Protocol**: capabilities no longer import
  `terminal_ui` or `AsyncSpinner` directly. UI feedback flows through
  an injected sink; the TUI ships `TuiProgressSink`, headless mode
  uses `NullProgressSink`.
- **MultiTaskTool sub-loop**: now spins up a fresh memoryless
  `core.loop.Agent` for each sub-task (uses the public SDK; no
  reach into private methods).

### Removed (breaking)

- Top-level imports of `agent`, `llm`, `memory`, `tools`, `bot`,
  `utils`, `config`, `main`, `interactive`, `cli` are gone. Migrate to:

  | Old                              | New                                              |
  | -------------------------------- | ------------------------------------------------ |
  | `from agent.agent import LoopAgent`     | `from ouro.capabilities import ComposedAgent` (or `AgentBuilder`) |
  | `from agent.tool_executor import ToolExecutor` | `from ouro.capabilities.tools import ToolExecutor` |
  | `from llm import ...`            | `from ouro.core.llm import ...`                  |
  | `from memory import ...`         | `from ouro.capabilities.memory import ...`       |
  | `from tools.base import BaseTool`| `from ouro.capabilities.tools.base import BaseTool` |
  | `from tools.<builtin> import X`  | `from ouro.capabilities.tools.builtins.<builtin> import X` |
  | `from bot.X import Y`            | `from ouro.interfaces.bot.X import Y`            |
  | `from utils import terminal_ui`  | `from ouro.interfaces.tui import terminal_ui`    |
  | `from utils import get_logger`   | `from ouro.core.log import get_logger`           |
  | `from config import Config`      | `from ouro.config import Config`                 |

- The `LoopAgent` / `BaseAgent` classes are removed. Use
  `ComposedAgent` (or the bare `core.loop.Agent` for the SDK).
- The `_react_loop` / `_ralph_loop` private methods are gone.
  Verification is now `VerificationHook`; the public entry point is
  `ComposedAgent.run(task, *, verify=True)`.

### Verification

- `./scripts/dev.sh check` now runs `importlint` (boundary contracts)
  in addition to precommit + typecheck + tests.
- The `ouro` console script entry point moved from `cli:main` to
  `ouro.interfaces.cli.entry:main`. Existing user-facing CLI flags
  are unchanged.
- Runtime files under `~/.ouro/{config, models.yaml, sessions/,
  memory/, logs/, .auth/, skills/, bot/}` are unchanged. Sessions
  written by 0.3.x can be resumed by 0.4.0.

## [0.3.1] - 2026-03-04

### Added

- Bot: file sending/receiving support with image message handling (#142)
- Bot: @mention filtering for multi-bot channels (#141)
- Bot: message queue with intelligent coalescing for bursty inputs (#151)
- Bot: configurable proactive task timeout (#143)
- Bot: emoji reactions replacing text acknowledgements (#148)
- Skills: add `agent-browser` as built-in system skill (#146)

### Changed

- Bot: migrate heartbeat from tool to system prompt injection (#149)
- Docs: split README into separate CLI Guide and Bot Guide (#138)

### Fixed

- TUI: escape user messages in Rich markup to prevent `MarkupError` crash on bracket-containing content (#153)
- LLM: remove LiteLLM StreamHandlers that leak debug logs to console (#144)
- Bot: enable file logging in bot mode (#140)
- Bot: skill installer writes to bot skills dir in bot mode (#139)
- Bot: add missing permissions docs and save images to disk (#145)
- Skills: only bootstrap system skills in bot mode (#147)

## [0.3.0] - 2026-02-24

### Added

- Bot Mode — long-connection channels with Feishu WebSocket and Slack Socket Mode support (#119)
- Bot proactive mechanisms with `manage_cron` & `manage_heartbeat` tools for scheduled and periodic tasks (#129)
- Bot session isolation with persistent data paths and session resume across restarts (#130)
- Long-term memory split into `memory.md` + daily files for better organization (#133)
- `/memory` interactive command for viewing and managing long-term memory (#120)

### Changed

- Simplify long-term memory to single-file architecture with compaction-integrated memory extraction (#120)
- Unify skills directory structure, `/skills` command, and remove dead code (#123)
- Token-only compaction trigger replacing heuristic-based memory compaction (#127)
- Update README to reflect CLI + Bot dual-mode positioning (#132)

### Fixed

- Bot: load skills registry correctly in bot mode (#125)
- Bot: reload skills from disk on new session creation (#126)
- Bot: remove redundant default heartbeat checklist (#131)
- Bot: skip heartbeat when checklist is empty + fix `HEARTBEAT_OK` detection (#134)
- Bot: remove active-hours gating from proactive tasks (#136)

## [0.2.4] - 2026-02-21

### Added

- Cache-safe forking for memory compaction — compaction reuses the main conversation's prefix for prompt cache hits, reducing compaction cost by ~90% (#117)
- Run-scoped `reasoning_effort` control via CLI (`--reasoning-effort`) and interactive `/reasoning` menu (#105)
- LLM cache token tracking & display with cache read/write breakdown in statistics panel (#106)
- Parallel execution for same-turn readonly tool calls via `asyncio.TaskGroup` (#103)
- `--verify` CLI flag to explicitly enable Ralph Loop self-verification in `--task` mode (#98)
- ChatGPT OAuth PKCE login with browser-based auth flow and manual paste fallback (#111)
- OAuth provider picker login/logout for ChatGPT/Codex with catalog-sync model list (#92)
- Token counting accuracy improvement with `litellm.token_counter`, fixing 40–57% underestimation for CJK text (#108)
- Support installing ouro from git branch in Harbor (`AGENT_BRANCH` config) (#95)

### Changed

- Simplify tool design: 12 → 10 tools — merged `explore_context` + `parallel_execute` into `multi_task` with DAG-based dependency scheduling, removed background shell mechanism (#100)
- Improve `multi_task` dependency semantics: structured sub-agent results (`SUMMARY` / `KEY_FINDINGS` / `ERRORS`), strict dependency satisfaction (#113)
- Improve slash autocomplete engine with fuzzy ranking, boundary bonus, and gap penalty (#97)
- `--task` mode no longer runs Ralph Loop by default (use `--verify` to enable) (#98)

### Fixed

- TUI: single-line spinner to eliminate ghost `╭─ Thinking ─╮` artifacts left by Rich's multi-line `Live(transient=True)` (#118)
- TUI: correct spinner titles and messages across agent lifecycle (was hardcoded to "Thinking") (#116)
- Pin ouro version in `harbor-run.sh` to prevent container version drift (#94)

## [0.2.3] - 2026-02-14

### Added

- Harbor installed agent integration for containerized evaluation (e.g. Terminal-Bench 2.0) with Jinja2 install script and auto-generated `models.yaml`
- `harbor-run.sh` convenience script with proxy/env configuration
- Python 3.13+ support by migrating from `tree-sitter-languages` to individual language packages with `abi3` wheels
- 47 unit tests for code structure tool covering all 9 supported languages

### Changed

- Reorder system prompt sections for improved structure (`workflow` and `tool_usage_guidelines` before `agents_md`)
- Disable long-term memory by default (set `LONG_TERM_MEMORY_ENABLED=true` in `~/.ouro/config` to enable)
- Remove redundant `<critical_rules>` section from agent system prompt
- Update to tree-sitter 0.25 API (`Query()` constructor + `QueryCursor.captures()`)
- Harden `install-ouro.sh.j2` with `pipefail`, increased retry count/delay, and post-install verification

### Fixed

- Harbor Docker proxy support: rewrite `127.0.0.1` → `host.docker.internal` for container networking
- Add retry logic for network-dependent commands in Harbor install (`apt-get`, `curl`, `uv`)
- Fix `harbor-run.sh` timeout flag (`--timeout-multiplier`) and default dataset (`terminal-bench-sample@2.0`)
- Fix Kotlin grammar query patterns (`simple_identifier`/`type_identifier` → `identifier`)

## [0.2.2] - 2026-02-08

### Fixed

- Include missing `agent.skills` and `memory.long_term` subpackages in wheel, fixing `ModuleNotFoundError` on PyPI install

## [0.2.1] - 2026-02-08

### Added

- Cross-session long-term memory system with git-backed persistence (`~/.ouro/memory/`)
- LLM-driven memory consolidation for decisions, preferences, and project facts
- Skills system MVP with YAML frontmatter parsing, registry, and installer
- Bundled system skills: skill-creator and skill-installer
- `/skills` interactive menu for listing, installing, and uninstalling skills

### Changed

- Updated README with new Ouroboros logo, PyPI/license badges, and contributing section
- Added RFC 008 design document for long-term memory system

## [0.2.0] - 2026-02-08

### Changed

- Rename project from `aloop` to `ouro` (Ouroboros)
- PyPI package name is now `ouro-ai` (`pip install ouro-ai`)
- CLI entry point renamed from `aloop` to `ouro`
- Runtime directory moved from `~/.aloop/` to `~/.ouro/`
- GitHub repository moved to `ouro-ai-labs/ouro`
- Updated ASCII logo and SVG branding

## [0.1.2] - 2026-02-04

### Added

- AGENTS.md support with on-demand reading for agent context

### Changed

- Refactor tool outputs to remove emoji and redundant text
- Remove redundant and unused tools for cleaner codebase

## [0.1.1] - 2026-02-02

### Fixed

- Include missing `agent.prompts` and `memory.store` subpackages in wheel

### Changed

- Add `pip install ouro-ai` as primary installation method in README

## [0.1.0] - 2026-02-02

### Added

- ReAct agent loop with tool-calling capabilities
- Ralph Loop outer verification for task completion
- Plan-Execute agent with four-phase architecture
- Interactive CLI with rich terminal UI and theme system
- `--version` / `-V` CLI flag
- `--task` mode with raw output (no Rich UI)
- Codex-style slash command autocomplete
- `/compact` memory compression and `/clean` command
- `/model` commands for runtime model switching
- Graceful Ctrl+C interrupt for long-running tool calls
- File operations tools (read, write, search, edit, glob, grep)
- Smart edit tool with backup support
- Shell execution with background task support
- Web search (via ddgs) and web fetch tools
- Code navigator with multi-language tree-sitter support
- Timer and notification tools
- Parallel execution tool and explore tool
- Memory management with compression, YAML-based persistence, and session resume
- Multi-provider LLM support via LiteLLM with thinking/reasoning display
- Model configuration via `~/.ouro/models.yaml` with interactive setup
- Async-first runtime (async LLM, memory, and tools)
- CHANGELOG.md
- GitHub Actions CI and release workflow (tag-triggered PyPI publishing)
