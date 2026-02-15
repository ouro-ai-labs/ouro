# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
