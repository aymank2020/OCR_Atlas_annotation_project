#!/usr/bin/env bash
set -euo pipefail

# Update repo safely, then archive non-essential local artifacts.
# Works on server and local Linux/WSL.
#
# Usage:
#   BRANCH=feature/phase1-hardening bash ./update_and_archive.sh
#
# Optional env:
#   APP_DIR=/root/OCR_annotation_Atlas
#   REPO_URL=https://github.com/aymank2020/OCR_Annotation_Atlas.git
#   RUN_ARCHIVE=1
#   INCLUDE_VENV=0
#   SAFE_UPDATE_AUTOSTASH=1

BRANCH="${BRANCH:-feature/phase1-hardening}"
APP_DIR="${APP_DIR:-$(pwd)}"
REPO_URL="${REPO_URL:-https://github.com/aymank2020/OCR_Annotation_Atlas.git}"
RUN_ARCHIVE="${RUN_ARCHIVE:-1}"
INCLUDE_VENV="${INCLUDE_VENV:-0}"

cd "$APP_DIR"

if [[ ! -x "./safe_update_preserve_local.sh" ]]; then
  chmod +x ./safe_update_preserve_local.sh
fi

echo "[update-archive] app_dir=$APP_DIR"
echo "[update-archive] branch=$BRANCH"
echo "[update-archive] run_archive=$RUN_ARCHIVE"
echo "[update-archive] include_venv=$INCLUDE_VENV"

./safe_update_preserve_local.sh "$BRANCH" "$APP_DIR" "$REPO_URL"

if [[ "$RUN_ARCHIVE" == "1" ]]; then
  if [[ ! -x "./archive_unused_files.sh" ]]; then
    chmod +x ./archive_unused_files.sh
  fi
  INCLUDE_VENV="$INCLUDE_VENV" APP_DIR="$APP_DIR" ./archive_unused_files.sh
fi

echo "[update-archive] done"
