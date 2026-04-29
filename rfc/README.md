# RFCs (Design Docs)

This folder contains design RFCs for significant changes in ouro.

## How to add a new RFC

1. Copy `TEMPLATE.md` to a new file named `short-description.md`.
2. Use a concise, descriptive filename (no numeric prefix needed).
3. Keep the first draft short and functional:
   - Goals / Non-goals
   - Proposed behavior (user-facing)
   - Acceptance criteria + test plan
4. Implement via multiple small PRs when possible.

## Index

Tip: keep this list up to date when adding an RFC.

- [enhanced-plan-execute-agent.md](enhanced-plan-execute-agent.md) — Four-Phase Agent Architecture
- [tool-result-handling.md](tool-result-handling.md) — Tool Result Handling / Size Validation
- [asyncio-migration.md](asyncio-migration.md) — AsyncIO-First Migration
- [composable-plan-tools.md](composable-plan-tools.md) — Composable Planning Tools
- [timer-notify.md](timer-notify.md) — Timer + Notify Tools
- [ralph-loop.md](ralph-loop.md) — Ralph Loop (Outer Verification)
- [memory-persistence-refactor.md](memory-persistence-refactor.md) — Memory Persistence Refactor
- [long-term-memory.md](long-term-memory.md) — Cross-Session Long-Term Memory
- [codex-login-via-litellm-chatgpt.md](codex-login-via-litellm-chatgpt.md) — Codex Login via LiteLLM ChatGPT Provider
- [multi-model-v2.md](multi-model-v2.md) — Multi-Model Configuration (v2)
- [skills-system.md](skills-system.md) — Skills System MVP
- [bot-message-queue.md](bot-message-queue.md) — Bot Message Queue with Intelligent Coalescing
- [bot-mode.md](bot-mode.md) — Bot Mode
- [cache-safe-compaction.md](cache-safe-compaction.md) — Cache Safe Compaction
- [skills-simplification.md](skills-simplification.md) — Skills Simplification
- [proactive-mechanisms.md](proactive-mechanisms.md) — Proactive Mechanisms
- [heartbeat-system-prompt-injection.md](heartbeat-system-prompt-injection.md) — Heartbeat System Prompt Injection
- [loop-owned-message-list.md](loop-owned-message-list.md) — Loop Owned Message List
- [reasoning-controls.md](reasoning-controls.md) — Reasoning Controls
- [token-counting-accuracy.md](token-counting-accuracy.md) — Token Counting Accuracy
