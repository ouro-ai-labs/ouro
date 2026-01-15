#!/bin/bash
set -euo pipefail

STRICT="${TYPECHECK_STRICT:-0}"

source ./scripts/_env.sh

set +e
"$PYTHON" -m mypy \
  agent llm memory tools utils main.py config.py
status=$?
set -e

if [[ "$status" -ne 0 ]] && [[ "$STRICT" == "1" ]]; then
  exit "$status"
fi

exit 0
