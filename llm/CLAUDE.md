# LLM/Provider Instructions (ouro/llm)

Note: `AGENTS.md` is a symlink to this file for compatibility with agents that look for `AGENTS.md`.

## Safety

- Never log or persist API keys or auth tokens.
- Prefer additive changes; keep existing model configuration working.

## Runtime

- All network calls must have timeouts; avoid unbounded retries.
- Keep adapters pure-ish: no filesystem writes unless explicitly intended.

## Tests

- Run targeted tests for the area you touched (examples):
  - `./scripts/dev.sh test -q test/test_litellm_adapter.py`
  - `./scripts/dev.sh test -q test/test_oauth_model_sync.py`
  - `./scripts/dev.sh test -q test/test_model_manager_chatgpt.py`
- Keep live-LLM integration behind `RUN_INTEGRATION_TESTS=1`.
