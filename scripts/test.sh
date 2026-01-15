#!/bin/bash
set -euo pipefail

source ./scripts/_env.sh

"$PYTHON" -m pytest test/ "$@"
