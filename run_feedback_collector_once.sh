#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/root/OCR_annotation_Atlas}"
CONFIG_FILE="${CONFIG_FILE:-sample_web_auto_solver_vps.yaml}"
MAX_EPISODES="${MAX_EPISODES:-20}"
LOG_FILE="${FEEDBACK_LOG_FILE:-$APP_DIR/outputs/feedback_collector.log}"
FEEDBACK_SKIP_GEMINI="${FEEDBACK_SKIP_GEMINI:-0}"

cd "$APP_DIR"

if [[ ! -d ".venv" ]]; then
  echo "[feedback-runner] missing .venv in $APP_DIR" >&2
  exit 1
fi

source .venv/bin/activate

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

# Reuse the primary account aliases when this collector runs outside the account scheduler.
: "${ATLAS_LOGIN_EMAIL:=${ATLAS_LOGIN_EMAIL_DANATIMER:-}}"
: "${ATLAS_EMAIL:=${ATLAS_EMAIL_DANATIMER:-${ATLAS_LOGIN_EMAIL:-}}}"
: "${GMAIL_EMAIL:=${GMAIL_EMAIL_DANATIMER:-}}"
: "${GMAIL_USER:=${GMAIL_USER_DANATIMER:-${GMAIL_EMAIL:-}}}"
: "${GMAIL_APP_PASSWORD:=${GMAIL_APP_PASSWORD_DANATIMER:-}}"
: "${GEMINI_API_KEYS_FREE_POOL:=${GEMINI_API_KEYS_FREE_POOL_DANATIMER:-${GEMINI_API_KEYS_FREE_POOL:-}}}"
: "${GEMINI_API_KEY_OPS:=${GEMINI_API_KEY_FREE_OPS:-${GEMINI_API_KEY_OPS:-}}}"
: "${GEMINI_API_KEY:=${GEMINI_API_KEY_OPS:-${GEMINI_API_KEY:-}}}"
: "${GOOGLE_API_KEY:=${GEMINI_API_KEY_OPS:-${GOOGLE_API_KEY:-}}}"

# Backend HTTP calls should use VPS direct network path.
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

mkdir -p "$APP_DIR/outputs"

args=(
  --config "$CONFIG_FILE"
  --continuous
  --max-cycles 1
  --max-episodes "$MAX_EPISODES"
  --no-profile
)

if [[ "$FEEDBACK_SKIP_GEMINI" == "1" ]]; then
  args+=(--skip-gemini)
elif [[ -z "${GEMINI_API_KEY:-}" && -z "${GOOGLE_API_KEY:-}" ]]; then
  echo "[feedback-runner] GEMINI_API_KEY/GOOGLE_API_KEY not found; forcing --skip-gemini"
  args+=(--skip-gemini)
fi

python -u atlas_feedback_training_export.py \
  "${args[@]}" \
  >>"$LOG_FILE" 2>&1
