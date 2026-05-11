#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOG_FILE="${LOG_FILE:-$SCRIPT_DIR/outputs/discord_bot_service.log}"
PYTHON_BIN="${PYTHON_BIN:-$SCRIPT_DIR/.venv/bin/python}"
CONFIG_PATH="${ATLAS_DISCORD_CONFIG:-configs/production_hetzner.yaml}"

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
  echo "[discord-bot] missing python executable: $PYTHON_BIN" >&2
  exit 1
fi

exec >>"$LOG_FILE" 2>&1
echo "[discord-bot] starting $(date -u '+%Y-%m-%dT%H:%M:%SZ') config=$CONFIG_PATH"
exec "$PYTHON_BIN" atlas_discord_bot.py --config "$CONFIG_PATH"
