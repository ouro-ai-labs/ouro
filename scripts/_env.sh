#!/bin/bash
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
  echo "❌ uv not found. Install uv (https://github.com/astral-sh/uv) first."
  exit 1
fi

if [[ ! -x ".venv/bin/python" ]]; then
  echo "❌ .venv not found. Run ./scripts/bootstrap.sh first."
  exit 1
fi

export PYTHON="${PYTHON:-.venv/bin/python}"
