#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOG_FILE="${LOG_FILE:-$SCRIPT_DIR/outputs/solver_service.log}"
INDEX_PATH="${ATLAS_ACCOUNTS_INDEX:-configs/accounts/index.yaml}"
PYTHON_BIN="${PYTHON_BIN:-$SCRIPT_DIR/.venv/bin/python}"
ENABLE_XVFB="${GEMINI_CHAT_ENABLE_XVFB:-1}"
XVFB_ARGS="${GEMINI_CHAT_XVFB_ARGS:--screen 0 1920x1080x24 -ac +extension RANDR}"

mkdir -p "$(dirname "$LOG_FILE")" "$SCRIPT_DIR/.state/generated_configs"

# Suppress Node deprecation warnings from Playwright components
export NODE_OPTIONS="--no-warnings"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source <(
    python3 - <<'PY'
from pathlib import Path
for line in Path(".env").read_text(encoding="utf-8-sig").splitlines():
    print(line)
PY
  )
  set +a
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "[solver] missing python executable: $PYTHON_BIN" >&2
  exit 1
fi

RUN_CMD=("$PYTHON_BIN" atlas_multi_account_runner.py --index "$INDEX_PATH" --execute --loop)
if [[ "$ENABLE_XVFB" == "1" ]] && command -v xvfb-run >/dev/null 2>&1; then
  RUN_CMD=(xvfb-run -a --server-args="$XVFB_ARGS" "${RUN_CMD[@]}")
fi

exec >>"$LOG_FILE" 2>&1
echo "[solver] starting $(date -u '+%Y-%m-%dT%H:%M:%SZ') index=$INDEX_PATH"

HEARTBEAT_PID=""
MAIN_PID=""
MAIN_PGID=""

cleanup() {
  if [[ -n "${HEARTBEAT_PID:-}" ]]; then
    kill "$HEARTBEAT_PID" >/dev/null 2>&1 || true
    wait "$HEARTBEAT_PID" 2>/dev/null || true
  fi
}

wait_for_main() {
  local wait_rc=0
  while true; do
    set +e
    wait "$MAIN_PID"
    wait_rc=$?
    set -e
    if [[ "$wait_rc" -ge 128 ]] && kill -0 "$MAIN_PID" >/dev/null 2>&1; then
      continue
    fi
    return "$wait_rc"
  done
}

forward_signal() {
  local signal_name="${1:-TERM}"
  if [[ -n "${MAIN_PID:-}" ]]; then
    if [[ -n "${MAIN_PGID:-}" ]]; then
      kill "-${signal_name}" -- "-${MAIN_PGID}" >/dev/null 2>&1 || true
    else
      kill "-${signal_name}" "$MAIN_PID" >/dev/null 2>&1 || true
    fi
  fi
}

trap cleanup EXIT
trap 'forward_signal INT' INT
trap 'forward_signal TERM' TERM

echo "[solver] starting session heartbeat monitor..."
"$PYTHON_BIN" src/infra/session_heartbeat.py &
HEARTBEAT_PID="$!"

if [[ "$ENABLE_XVFB" == "1" ]]; then
  echo "[solver] chat-web display mode: xvfb"
else
  echo "[solver] chat-web display mode: direct"
fi

if command -v setsid >/dev/null 2>&1; then
  setsid "${RUN_CMD[@]}" &
else
  "${RUN_CMD[@]}" &
fi
MAIN_PID="$!"
MAIN_PGID="$(ps -o pgid= "$MAIN_PID" 2>/dev/null | tr -d ' ' || true)"
EXIT_CODE=0
wait_for_main || EXIT_CODE=$?
cleanup
exit "$EXIT_CODE"
