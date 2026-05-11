#!/usr/bin/env bash
set -euo pipefail

# One-command server deploy:
# 1) safe git update while preserving server secrets/state
# 2) run production pipeline (single episode or batch)
#
# Usage:
#   bash deploy_update_and_run.sh
#   BRANCH=main bash deploy_update_and_run.sh
#   EPISODE_ID=68d3... bash deploy_update_and_run.sh

BRANCH="${BRANCH:-main}"
APP_DIR="${APP_DIR:-/root/OCR_annotation_Atlas}"
REPO_URL="${REPO_URL:-https://github.com/aymank2020/OCR_Annotation_Atlas.git}"

CONFIG="${CONFIG:-sample_web_auto_solver_production.yaml}"
REMOTE="${REMOTE:-gdrive}"
PASS_SCORE_THRESHOLD="${PASS_SCORE_THRESHOLD:-95}"
STRICT_GATE="${STRICT_GATE:-1}"
REQUIRE_TIER2="${REQUIRE_TIER2:-0}"
RESUME_ONLY="${RESUME_ONLY:-1}"
AUTO_BUILD_CONTEXT_PACK="${AUTO_BUILD_CONTEXT_PACK:-1}"
FORCE_REGENERATE="${FORCE_REGENERATE:-0}"
SAFE_UPDATE_AUTOSTASH="${SAFE_UPDATE_AUTOSTASH:-0}"
EPISODE_ID="${EPISODE_ID:-}"
DRIVE_LINK="${DRIVE_LINK:-}"
KNOWLEDGE_UPDATE="${KNOWLEDGE_UPDATE:-0}"
DISCORD_JSON="${DISCORD_JSON:-}"
WHATSAPP_TXT="${WHATSAPP_TXT:-}"

echo "[deploy] app_dir=$APP_DIR"
echo "[deploy] branch=$BRANCH"
echo "[deploy] strict_gate=$STRICT_GATE"
echo "[deploy] require_tier2=$REQUIRE_TIER2"
echo "[deploy] pass_score_threshold=$PASS_SCORE_THRESHOLD"
echo "[deploy] episode_id=${EPISODE_ID:-ALL}"

cd "$APP_DIR"

if [[ ! -x "./safe_update_preserve_local.sh" ]]; then
  chmod +x ./safe_update_preserve_local.sh
fi
SAFE_UPDATE_AUTOSTASH="$SAFE_UPDATE_AUTOSTASH" ./safe_update_preserve_local.sh "$BRANCH" "$APP_DIR" "$REPO_URL"

if [[ ! -x "./run_production.sh" ]]; then
  chmod +x ./run_production.sh
fi

CONFIG="$CONFIG" \
REMOTE="$REMOTE" \
PASS_SCORE_THRESHOLD="$PASS_SCORE_THRESHOLD" \
STRICT_GATE="$STRICT_GATE" \
REQUIRE_TIER2="$REQUIRE_TIER2" \
RESUME_ONLY="$RESUME_ONLY" \
AUTO_BUILD_CONTEXT_PACK="$AUTO_BUILD_CONTEXT_PACK" \
FORCE_REGENERATE="$FORCE_REGENERATE" \
EPISODE_ID="$EPISODE_ID" \
DRIVE_LINK="$DRIVE_LINK" \
KNOWLEDGE_UPDATE="$KNOWLEDGE_UPDATE" \
DISCORD_JSON="$DISCORD_JSON" \
WHATSAPP_TXT="$WHATSAPP_TXT" \
bash ./run_production.sh

echo "[deploy] done"
