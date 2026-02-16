# RFC Instructions (ouro)

Note: `AGENTS.md` is a symlink to this file for compatibility with agents that look for `AGENTS.md`.

This directory contains design RFCs for significant changes.

## What a good RFC looks like

- **Functional focus first**: describe user-visible behavior and constraints before implementation details.
- **Explicit scope**: include **Goals** and **Non-goals** (to prevent “scope creep” and scattered drafts).
- **Acceptance criteria**: concrete, testable statements (what must be true when done).
- **Test plan**: which tests will be added/updated and what smoke command will be run.
- **Safety**: list invariants (existing behaviors that must not regress) and a rollback plan if feasible.

## How to write

- Start from `TEMPLATE.md` and keep the first draft short (aim for ~1–2 pages).
- Prefer “small RFC + multiple small PRs” over “big RFC + big PR”.
- If the change touches CLI/config/public APIs, include examples and migration notes.

## Naming

- New RFCs: `NNN-short-description.md` (3-digit number).
- Do not reuse an existing number.
