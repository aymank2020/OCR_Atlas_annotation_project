#!/usr/bin/env bash
set -euo pipefail

# ═══════════════════════════════════════════════════════════════════════
# run_production.sh — Full production pipeline runner
#
# Integrates all phases:
#   Phase 1: submit_gate.py (hard gate)
#   Phase 2: atlas_repair_loop.py (repair before manual queue)
#   Phase 3: Knowledge enrichment from Discord/WhatsApp
#   Phase 4: Single-model mode, cost tracking
#   + Drive sync, dashboard rebuild, manual queue reporting
#
# Usage:
#   bash run_production.sh                        # full run
#   EPISODE_ID=68d3... bash run_production.sh     # single episode
#   KNOWLEDGE_UPDATE=1 bash run_production.sh     # update context from knowledge files
# ═══════════════════════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ -f ".venv/bin/activate" && -z "${VIRTUAL_ENV:-}" ]]; then
  source .venv/bin/activate
fi
if [[ -f ".env" ]]; then
  set -a; source .env; set +a
  echo "[prod] loaded_env=.env"
fi

if command -v python >/dev/null 2>&1; then
  PY="python"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
else
  echo "[prod] error: no python found"; exit 1
fi

# ── Configuration ─────────────────────────────────────────────────────
CONFIG="${CONFIG:-sample_web_auto_solver_production.yaml}"
OUTPUTS_DIR="${OUTPUTS_DIR:-outputs}"
REMOTE="${REMOTE:-gdrive}"
PASS_SCORE_THRESHOLD="${PASS_SCORE_THRESHOLD:-95}"
STRICT_GATE="${STRICT_GATE:-1}"           # PRODUCTION DEFAULT: always strict
REQUIRE_TIER2="${REQUIRE_TIER2:-0}"       # 1 = require Tier2 input; 0 = allow placeholder/fallback
FORCE_REGENERATE="${FORCE_REGENERATE:-0}"
EPISODE_ID="${EPISODE_ID:-}"              # empty = run all ready episodes
DRIVE_LINK="${DRIVE_LINK:-}"
KNOWLEDGE_UPDATE="${KNOWLEDGE_UPDATE:-0}"
DISCORD_JSON="${DISCORD_JSON:-}"          # path to Discord export JSON
WHATSAPP_TXT="${WHATSAPP_TXT:-}"          # path to WhatsApp export TXT
AUTO_BUILD_CONTEXT_PACK="${AUTO_BUILD_CONTEXT_PACK:-1}"
RESUME_ONLY="${RESUME_ONLY:-1}"

echo "[prod] ═══════════════════════════════════════"
echo "[prod] OCR Annotation Atlas — Production Run"
echo "[prod] $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "[prod] ═══════════════════════════════════════"
echo "[prod] config=$CONFIG"
echo "[prod] strict_gate=$STRICT_GATE"
echo "[prod] require_tier2=$REQUIRE_TIER2"
echo "[prod] pass_score_threshold=$PASS_SCORE_THRESHOLD"
echo "[prod] episode_id=${EPISODE_ID:-ALL}"
echo "[prod] knowledge_update=$KNOWLEDGE_UPDATE"

# ── Step 0: Knowledge enrichment (if requested) ───────────────────────
if [[ "$KNOWLEDGE_UPDATE" == "1" ]]; then
  echo "[prod] ── Step 0: Knowledge collection ──"
  knowledge_args=("--outputs-dir" "$OUTPUTS_DIR" "--update-context")
  if [[ -n "$DISCORD_JSON" && -f "$DISCORD_JSON" ]]; then
    knowledge_args+=("--discord-json" "$DISCORD_JSON")
  fi
  if [[ -n "$WHATSAPP_TXT" && -f "$WHATSAPP_TXT" ]]; then
    knowledge_args+=("--whatsapp-txt" "$WHATSAPP_TXT")
  fi
  if [[ ${#knowledge_args[@]} -gt 3 ]]; then
    "$PY" atlas_knowledge_collector.py "${knowledge_args[@]}"
    echo "[prod] knowledge collection done"
  else
    echo "[prod] warn: no Discord/WhatsApp files provided, skipping knowledge collection"
  fi
fi

# ── Step 1: Sync from Drive if local outputs are empty ────────────────
if [[ -n "$DRIVE_LINK" ]]; then
  echo "[prod] ── Step 1: Sync check ──"
  "$PY" atlas_sync_if_zero.py \
    --outputs-dir "$OUTPUTS_DIR" \
    --drive-link "$DRIVE_LINK" \
    --remote "$REMOTE" || echo "[prod] warn: sync check had non-fatal error"
fi

# ── Step 2: Build context pack ────────────────────────────────────────
if [[ "$AUTO_BUILD_CONTEXT_PACK" == "1" ]]; then
  echo "[prod] ── Step 2: Context pack build ──"
  SOURCE_INDEX="$OUTPUTS_DIR/episodes_review_index.json"
  if [[ -f "$SOURCE_INDEX" ]]; then
    "$PY" atlas_build_vertex_fewshot.py \
      --index "$SOURCE_INDEX" \
      --results-jsonl "$OUTPUTS_DIR/triplet_compare_results.jsonl" \
      --results-dir "$OUTPUTS_DIR/triplet_compare" \
      --outputs-dir "$OUTPUTS_DIR" \
      --out-dir "$OUTPUTS_DIR/vertex_fewshot" \
      --max-examples 120 \
      --pass-score-threshold "$PASS_SCORE_THRESHOLD" \
      --max-chars-per-candidate 1800 || echo "[prod] warn: context pack build had non-fatal error"

    BUNDLE="$OUTPUTS_DIR/vertex_fewshot/context_bundle.txt"
    if [[ -f "$BUNDLE" ]]; then
      # Merge with knowledge if it exists
      KNOWLEDGE_SUMMARY="$OUTPUTS_DIR/knowledge/knowledge_summary.txt"
      if [[ -f "$KNOWLEDGE_SUMMARY" ]]; then
        cat "$BUNDLE" "$KNOWLEDGE_SUMMARY" > "prompts/atlas_vertex_context_pack.txt"
        echo "[prod] context pack merged with knowledge"
      else
        cp -f "$BUNDLE" "prompts/atlas_vertex_context_pack.txt"
      fi
    fi
  fi
fi

# ── Step 3: Run pipeline ───────────────────────────────────────────────
echo "[prod] ── Step 3: Pipeline run ──"

set +e
if [[ -n "$EPISODE_ID" ]]; then
  # Single episode mode
  echo "[prod] single_episode_mode: $EPISODE_ID"
  EPISODE_ID="$EPISODE_ID" \
  CONFIG="$CONFIG" \
  OUTPUTS_DIR="$OUTPUTS_DIR" \
  REMOTE="$REMOTE" \
  PASS_SCORE_THRESHOLD="$PASS_SCORE_THRESHOLD" \
  STRICT_GATE="$STRICT_GATE" \
  REQUIRE_TIER2="$REQUIRE_TIER2" \
  FORCE_REGENERATE="$FORCE_REGENERATE" \
  bash run_single_episode_4way.sh
else
  # Batch mode
  echo "[prod] batch_mode: all ready episodes"
  CONFIG="$CONFIG" \
  OUTPUTS_DIR="$OUTPUTS_DIR" \
  REMOTE="$REMOTE" \
  PASS_SCORE_THRESHOLD="$PASS_SCORE_THRESHOLD" \
  STRICT_GATE="$STRICT_GATE" \
  REQUIRE_TIER2="$REQUIRE_TIER2" \
  RESUME_ONLY="$RESUME_ONLY" \
  bash run_triplet_with_ready_videos.sh
fi

PIPELINE_EXIT=$?
set -e

# ── Step 4: Cost report ────────────────────────────────────────────────
echo "[prod] ── Step 4: Cost report ──"
"$PY" cost_report.py \
  --usage-log "$OUTPUTS_DIR/gemini_usage.jsonl" \
  --timezone "Africa/Cairo" \
  --last-hours 24 || true

# ── Step 5: Manual queue report ───────────────────────────────────────
echo "[prod] ── Step 5: Manual queue status ──"
MANUAL_QUEUE="$OUTPUTS_DIR/manual_queue.jsonl"
if [[ -f "$MANUAL_QUEUE" ]]; then
  QUEUE_COUNT=$("$PY" -c "
import sys, json
eids = set()
try:
    with open('$MANUAL_QUEUE', 'r', encoding='utf-8') as f:
        for line in f:
            txt = line.strip()
            if not txt: continue
            try:
                r = json.loads(txt)
                eid = r.get('episode_id')
                if eid: eids.add(eid)
            except: pass
    print(len(eids))
except: print(0)
")
  echo "[prod] manual_queue_unique_episodes=$QUEUE_COUNT (see $MANUAL_QUEUE)"
  # Print last 5 entries
  echo "[prod] last_queued:"
  tail -n 5 "$MANUAL_QUEUE" | "$PY" -c "
import sys, json
for line in sys.stdin:
    line=line.strip()
    if not line: continue
    try:
        r=json.loads(line)
        print(f\"  ep={r.get('episode_id','?')} reason={r.get('reason','?')} winner={r.get('winner','?')}\")
    except: pass
" || true
else
  echo "[prod] manual_queue: empty (all episodes approved or not yet run)"
fi

# ── Step 6: Rebuild dashboard ─────────────────────────────────────────
echo "[prod] ── Step 6: Dashboard rebuild ──"
"$PY" atlas_dashboard_v2.py --outputs-dir "$OUTPUTS_DIR"
READY_INDEX="$OUTPUTS_DIR/episodes_ready_for_triplet.json"
REVIEW_INDEX="$OUTPUTS_DIR/episodes_review_index.json"
INDEX_TO_USE="$REVIEW_INDEX"
if [[ -f "$READY_INDEX" ]]; then INDEX_TO_USE="$READY_INDEX"; fi
"$PY" atlas_review_viewer_gen.py --index "$INDEX_TO_USE" --out "$OUTPUTS_DIR/atlas_review_viewer.html" || true

# ── Step 7: Sync to Drive ─────────────────────────────────────────────
if [[ -n "$DRIVE_LINK" ]] && command -v rclone >/dev/null 2>&1; then
  echo "[prod] ── Step 7: Drive sync ──"
  # Extract FOLDER_ID using portable sed instead of non-portable grep -oP
  FOLDER_ID=$(echo "$DRIVE_LINK" | sed -n 's|.*/folders/\([a-zA-Z0-9_-]\{1,\}\).*|\1|p' || true)
  if [[ -n "$FOLDER_ID" ]]; then
    DEST="${REMOTE}:"
    # Sync key outputs to Drive
    for f in \
      "$OUTPUTS_DIR/atlas_dashboard.html" \
      "$OUTPUTS_DIR/atlas_review_viewer.html" \
      "$OUTPUTS_DIR/triplet_compare_results.jsonl" \
      "$OUTPUTS_DIR/manual_queue.jsonl" \
      "$OUTPUTS_DIR/repair_history.jsonl" \
      "$OUTPUTS_DIR/gemini_usage.jsonl"; do
      if [[ -f "$f" ]]; then
        rclone copy "$f" "$DEST" --drive-root-folder-id "$FOLDER_ID" --progress 2>/dev/null || true
      fi
    done
    # Sync triplet compare results folder
    if [[ -d "$OUTPUTS_DIR/triplet_compare" ]]; then
      rclone copy "$OUTPUTS_DIR/triplet_compare" "${DEST}triplet_compare" \
        --drive-root-folder-id "$FOLDER_ID" --progress 2>/dev/null || true
    fi
    echo "[prod] drive sync complete (folder=$FOLDER_ID)"
  else
    echo "[prod] warn: could not extract folder ID from DRIVE_LINK (sync skipped)"
  fi
fi

# ── Final Summary ─────────────────────────────────────────────────────
echo "[prod] ═══════════════════════════════════════"
echo "[prod] Production run complete"
echo "[prod] exit_code=$PIPELINE_EXIT"
echo "[prod] key_outputs:"
echo "[prod]   dashboard: $(pwd)/$OUTPUTS_DIR/atlas_dashboard.html"
echo "[prod]   viewer:    $(pwd)/$OUTPUTS_DIR/atlas_review_viewer.html"
echo "[prod]   results:   $(pwd)/$OUTPUTS_DIR/triplet_compare_results.jsonl"
echo "[prod] ═══════════════════════════════════════"

exit $PIPELINE_EXIT
