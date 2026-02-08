# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
