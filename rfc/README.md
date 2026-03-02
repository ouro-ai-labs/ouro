# RFCs (Design Docs)

This folder contains design RFCs for significant changes in ouro.

## How to add a new RFC

1. Copy `TEMPLATE.md` to a new file named `NNN-short-description.md`.
2. Pick the next available 3-digit number (do **not** reuse numbers).
3. Keep the first draft short and functional:
   - Goals / Non-goals
   - Proposed behavior (user-facing)
   - Acceptance criteria + test plan
4. Implement via multiple small PRs when possible.

## Index

Tip: keep this list up to date when adding an RFC.

- RFC 001: Four-Phase Agent Architecture
- RFC 002: Tool Result Handling / Size Validation
- RFC 003: AsyncIO-First Migration
- RFC 004: Composable Planning Tools
- RFC 005: Timer + Notify Tools
- RFC 006: Ralph Loop (Outer Verification)
- RFC 007: Memory Persistence Refactor
- RFC 008: Cross-Session Long-Term Memory
- RFC 009: Codex Login via LiteLLM ChatGPT Provider
- RFC 010: Multi-Model Configuration (v2)
- RFC 011: Skills System MVP
- RFC 012: Bot Message Queue with Intelligent Coalescing

## Note on numbering

RFC numbers must be unique. If you add an RFC from a long-lived branch, renumber it before merge.
