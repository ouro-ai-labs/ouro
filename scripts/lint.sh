#!/bin/bash
set -euo pipefail

source ./scripts/_env.sh

"$PYTHON" -m black --check .
"$PYTHON" -m isort --check-only .
"$PYTHON" -m ruff check .
