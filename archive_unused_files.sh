#!/usr/bin/env bash
set -euo pipefail

# Archive non-essential local artifacts into .archive/<timestamp> instead of deleting.
# Usage:
#   bash ./archive_unused_files.sh
#   APP_DIR=/root/OCR_annotation_Atlas bash ./archive_unused_files.sh
#   INCLUDE_VENV=1 bash ./archive_unused_files.sh

APP_DIR="${APP_DIR:-$(pwd)}"
INCLUDE_VENV="${INCLUDE_VENV:-0}"
TS="${TS:-$(date +%Y%m%d_%H%M%S)}"
ARCHIVE_ROOT="${ARCHIVE_ROOT:-${APP_DIR}/.archive}"
ARCHIVE_DIR="${ARCHIVE_ROOT}/${TS}"

cd "$APP_DIR"
mkdir -p "$ARCHIVE_DIR"

items=(
  ".minimax"
  ".tmp_server"
  "chat_reviews"
  "info"
  "tmp"
  "__pycache__"
  "atlas_review_viewer.html"
  "code_summary.txt"
  "core_1_pipeline.txt"
  "project_structure.txt"
  "screencapture-localhost-8080-atlas-review-viewer-html-2026-03-13-19_50_16.pdf"
  "temp_fix_viewer_data.py"
)

if [[ "$INCLUDE_VENV" == "1" ]]; then
  items+=(".venv")
fi

moved=0
for rel in "${items[@]}"; do
  if [[ -e "$rel" ]]; then
    mkdir -p "$ARCHIVE_DIR/$(dirname "$rel")"
    mv "$rel" "$ARCHIVE_DIR/$rel"
    echo "[archive] moved: $rel -> $ARCHIVE_DIR/$rel"
    moved=$((moved + 1))
  fi
done

echo "[archive] archive_dir=$ARCHIVE_DIR"
echo "[archive] moved_count=$moved"
