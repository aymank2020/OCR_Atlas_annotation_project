#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOG_FILE="${LOG_FILE:-$SCRIPT_DIR/outputs/command_hub.log}"
STREAMLIT_BIN="${STREAMLIT_BIN:-$SCRIPT_DIR/.venv/bin/streamlit}"
HUB_PORT="${HUB_PORT:-8500}"
HUB_HOST="${HUB_HOST:-127.0.0.1}"

mkdir -p "$(dirname "$LOG_FILE")"

if [[ -f ".env" ]]; then
  set -a
  source .env
  set +a
fi

if [[ ! -x "$STREAMLIT_BIN" ]]; then
  echo "[command-hub] missing streamlit executable: $STREAMLIT_BIN" >&2
  exit 1
fi

exec >>"$LOG_FILE" 2>&1
echo "[command-hub] starting $(date -u '+%Y-%m-%dT%H:%M:%SZ') host=$HUB_HOST port=$HUB_PORT"
exec "$STREAMLIT_BIN" run atlas_command_hub.py --server.address "$HUB_HOST" --server.port "$HUB_PORT"
