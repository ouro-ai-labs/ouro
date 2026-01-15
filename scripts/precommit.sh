#!/bin/bash
set -euo pipefail

source ./scripts/_env.sh

"$PYTHON" -m pre_commit run --all-files
