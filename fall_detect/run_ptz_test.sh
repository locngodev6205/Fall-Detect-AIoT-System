#!/usr/bin/env bash
set -e
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"
if [ -d "$ROOT_DIR/../venv" ]; then
    source "$ROOT_DIR/../venv/bin/activate"
elif [ -d "$ROOT_DIR/venv" ]; then
    source "$ROOT_DIR/venv/bin/activate"
fi
exec python3 -u "$ROOT_DIR/tests/manual_ptz_web.py" "$@"
