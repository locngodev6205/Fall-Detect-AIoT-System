#!/usr/bin/env bash
# Match the virtualenv selection of fall_detect/run_edge.sh.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -d "$ROOT_DIR/../venv" ]; then
    source "$ROOT_DIR/../venv/bin/activate"
elif [ -d "$ROOT_DIR/venv" ]; then
    source "$ROOT_DIR/venv/bin/activate"
else
    echo "Không tìm thấy ../venv hoặc venv trong fall_detect." >&2
    exit 1
fi
exec python3 "$ROOT_DIR/update/install.py" --source "$ROOT_DIR" --env "$ROOT_DIR/.env.edge" "$@"
