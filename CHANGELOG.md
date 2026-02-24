# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
