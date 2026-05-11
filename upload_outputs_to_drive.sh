#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/root/OCR_annotation_Atlas}"
OUTPUT_DIR="${OUTPUT_DIR:-$APP_DIR/outputs}"
REMOTE_NAME="${RCLONE_REMOTE:-gdrive}"
REMOTE_PATH="${RCLONE_PATH:-OCR_annotation_Atlas/vps_outputs}"
ROOT_FOLDER_ID="${GDRIVE_ROOT_FOLDER_ID:-}"
EPISODE_LAYOUT_SCRIPT="${EPISODE_LAYOUT_SCRIPT:-$APP_DIR/atlas_drive_episode_layout.py}"
EPISODE_LAYOUT_MIN_AGE="${EPISODE_LAYOUT_MIN_AGE:-${MIN_AGE:-30m}}"

# Keep recently-created files locally so active runs are not interrupted.
MIN_AGE="${MIN_AGE:-30m}"

# Tune transfer behavior.
TRANSFERS="${RCLONE_TRANSFERS:-4}"
CHECKERS="${RCLONE_CHECKERS:-8}"
CHUNK_SIZE="${RCLONE_CHUNK_SIZE:-64M}"
RETRIES="${RCLONE_RETRIES:-10}"
LOW_RETRIES="${RCLONE_LOW_RETRIES:-20}"

LOG_FILE="${UPLOAD_LOG_FILE:-$APP_DIR/outputs/drive_uploader.log}"

if ! command -v rclone >/dev/null 2>&1; then
  echo "[drive-uploader] rclone is not installed." >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"
mkdir -p "$(dirname "$LOG_FILE")"

# Force uploads to use VPS direct IP, not browser proxy package.
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

if [[ -f "$EPISODE_LAYOUT_SCRIPT" ]]; then
  PYTHON_BIN="$(command -v python3 || command -v python || true)"
  if [[ -n "$PYTHON_BIN" ]]; then
    echo "[drive-uploader] organizing per-episode folders under ${OUTPUT_DIR} (min-age=${EPISODE_LAYOUT_MIN_AGE})"
    "$PYTHON_BIN" "$EPISODE_LAYOUT_SCRIPT" --root "$OUTPUT_DIR" --min-age "$EPISODE_LAYOUT_MIN_AGE"
  else
    echo "[drive-uploader] warning: python not found, skipping episode-folder organization"
  fi
fi

args=(
  move "$OUTPUT_DIR" "${REMOTE_NAME}:${REMOTE_PATH}"
  --min-age "$MIN_AGE"
  --delete-empty-src-dirs
  --transfers "$TRANSFERS"
  --checkers "$CHECKERS"
  --drive-chunk-size "$CHUNK_SIZE"
  --retries "$RETRIES"
  --low-level-retries "$LOW_RETRIES"
  --stats-one-line
  --log-file "$LOG_FILE"
  --log-level INFO
  --exclude "solver_service*.log"
  --exclude "solver_health.log"
  --exclude "manual_run.log"
  --exclude "drive_uploader.log"
  --exclude "*.part"
  --exclude ".keep"
)

if [[ -n "$ROOT_FOLDER_ID" ]]; then
  args+=(--drive-root-folder-id "$ROOT_FOLDER_ID")
fi

echo "[drive-uploader] moving old outputs to ${REMOTE_NAME}:${REMOTE_PATH} (min-age=${MIN_AGE})"
rclone "${args[@]}"
echo "[drive-uploader] done"
