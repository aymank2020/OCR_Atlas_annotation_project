#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/srv/atlas/OCR_annotation_Atlas}"
INDEX_PATH="${ATLAS_ACCOUNTS_INDEX:-configs/accounts/index.yaml}"
LOG_FILE="${PRODUCTION_MONITOR_LOG_FILE:-$APP_DIR/outputs/production_monitor.log}"
AUTO_RESTART_SOLVER="${AUTO_RESTART_SOLVER:-1}"
PYTHON_BIN="${PYTHON_BIN:-$APP_DIR/.venv/bin/python}"

cd "$APP_DIR"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "[production-monitor] missing python executable: $PYTHON_BIN" >&2
  exit 1
fi

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

mkdir -p "$APP_DIR/outputs/production_monitor"

ARGS=(
  --app-dir "$APP_DIR"
  --index "$INDEX_PATH"
)
if [[ "$AUTO_RESTART_SOLVER" == "1" ]]; then
  ARGS+=(--auto-restart-solver)
fi

"$PYTHON_BIN" atlas_production_monitor.py "${ARGS[@]}" >>"$LOG_FILE" 2>&1
