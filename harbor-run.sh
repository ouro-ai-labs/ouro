#!/bin/bash
set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────
# LLM API key (required)
export OURO_API_KEY="${OURO_API_KEY:-}"

# LLM API base URL (optional, for proxy/relay APIs)
# export OURO_BASE_URL="https://your-proxy-api.com"

# LLM request timeout in seconds (default: 600)
# export OURO_TIMEOUT=600

# Model to use
MODEL="anthropic/kimi-k2-5-latest"

# Dataset to evaluate
DATASET="terminal-bench-sample@2.0"

# Timeout multiplier (default setup=360s, so 2.0 → 720s). Increase for slow networks.
TIMEOUT_MULTIPLIER=2.0

# ── Proxy  ─────────────────────────────────────────────────────────
# Clash/proxy port on localhost. Set to empty to disable.
PROXY_PORT="7890"

if [ -n "$PROXY_PORT" ]; then
    export http_proxy="http://127.0.0.1:${PROXY_PORT}"
    export https_proxy="http://127.0.0.1:${PROXY_PORT}"
    # Unset SOCKS proxy to avoid socksio dependency in harbor
    unset all_proxy ALL_PROXY 2>/dev/null || true
fi

# ── Validation ───────────────────────────────────────────────────────────────
if [ -z "$OURO_API_KEY" ]; then
    echo "Error: OURO_API_KEY is not set. Export it or edit this script." >&2
    exit 1
fi

# ── Run ──────────────────────────────────────────────────────────────────────
harbor run \
    --agent-import-path ouro_harbor.ouro_agent:OuroAgent \
    --model "$MODEL" \
    --timeout-multiplier "$TIMEOUT_MULTIPLIER" \
    --dataset "$DATASET" \
    "$@"
