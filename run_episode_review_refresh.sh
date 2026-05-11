#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOG_FILE="${LOG_FILE:-$SCRIPT_DIR/outputs/episode_review_refresh.log}"
PYTHON_BIN="${PYTHON_BIN:-$SCRIPT_DIR/.venv/bin/python}"

mkdir -p "$(dirname "$LOG_FILE")"

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
  echo "[episode-review-refresh] missing python executable: $PYTHON_BIN" >&2
  exit 1
fi

exec >>"$LOG_FILE" 2>&1
echo "[episode-review-refresh] starting $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
exec "$PYTHON_BIN" atlas_episode_dashboard_publish.py --skip-sync --skip-upload
