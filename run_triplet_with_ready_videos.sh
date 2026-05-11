#!/usr/bin/env bash
set -euo pipefail

# One-shot runner:
# 1) Build episodes index that has a valid local video_path
# 2) Run triplet batch on ready episodes only
# 3) Rebuild review viewer from ready episodes

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ -f ".venv/bin/activate" && -z "${VIRTUAL_ENV:-}" ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
  echo "[run] loaded_env=.env"
else
  echo "[run] warning: .env not found"
fi

if command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
else
  echo "[run] error: no python interpreter found (python/python3)."
  exit 1
fi

CONFIG="${CONFIG:-sample_web_auto_solver_production.yaml}"
OUTPUTS_DIR="${OUTPUTS_DIR:-outputs}"
SOURCE_INDEX="${SOURCE_INDEX:-$OUTPUTS_DIR/episodes_review_index.json}"
READY_INDEX="${READY_INDEX:-$OUTPUTS_DIR/episodes_ready_for_triplet.json}"
REMOTE="${REMOTE:-gdrive}"
PASS_SCORE_THRESHOLD="${PASS_SCORE_THRESHOLD:-95}"
STRICT_GATE="${STRICT_GATE:-1}"
REQUIRE_TIER2="${REQUIRE_TIER2:-0}"
# Context pack mode:
# 1 = build fresh context bundle from outputs and overwrite prompts/atlas_vertex_context_pack.txt
# 0 = keep existing context file as-is
AUTO_BUILD_CONTEXT_PACK="${AUTO_BUILD_CONTEXT_PACK:-1}"
CONTEXT_MAX_EXAMPLES="${CONTEXT_MAX_EXAMPLES:-120}"
CONTEXT_MAX_CHARS_PER_CANDIDATE="${CONTEXT_MAX_CHARS_PER_CANDIDATE:-1800}"
# Resume mode:
# 1 = continue only missing episodes (recommended for unstable internet)
# 0 = force full re-run for all ready episodes
RESUME_ONLY="${RESUME_ONLY:-1}"

echo "[run] config=$CONFIG"
echo "[run] outputs_dir=$OUTPUTS_DIR"
echo "[run] source_index=$SOURCE_INDEX"
echo "[run] ready_index=$READY_INDEX"
echo "[run] remote=$REMOTE"
echo "[run] pass_score_threshold=$PASS_SCORE_THRESHOLD"
echo "[run] strict_gate=$STRICT_GATE"
echo "[run] require_tier2=$REQUIRE_TIER2"
echo "[run] auto_build_context_pack=$AUTO_BUILD_CONTEXT_PACK"
echo "[run] context_max_examples=$CONTEXT_MAX_EXAMPLES"
echo "[run] context_max_chars_per_candidate=$CONTEXT_MAX_CHARS_PER_CANDIDATE"
echo "[run] resume_only=$RESUME_ONLY"
echo "[run] python_bin=$PYTHON_BIN"
if [[ -n "${GEMINI_API_KEY:-}" || -n "${GOOGLE_API_KEY:-}" ]]; then
  echo "[run] gemini_api_key=present"
else
  echo "[run] gemini_api_key=missing"
fi
if [[ -n "${GOOGLE_APPLICATION_CREDENTIALS:-}" ]]; then
  echo "[run] vertex_credentials=present"
else
  echo "[run] vertex_credentials=missing"
fi

"$PYTHON_BIN" - <<'PY'
import json
import os
from pathlib import Path

outputs_dir = Path(os.environ.get("OUTPUTS_DIR", "outputs"))
src = Path(os.environ.get("SOURCE_INDEX", str(outputs_dir / "episodes_review_index.json")))
dst = Path(os.environ.get("READY_INDEX", str(outputs_dir / "episodes_ready_for_triplet.json")))

if not src.exists():
    raise SystemExit(f"[error] source index not found: {src}")

obj = json.loads(src.read_text(encoding="utf-8"))
rows = obj.get("episodes", []) if isinstance(obj, dict) else obj

ready = []
for rec in rows:
    if not isinstance(rec, dict):
        continue
    eid = str(rec.get("episode_id") or "").strip().lower()
    if not eid:
        continue

    vp = str(rec.get("video_path") or "").strip()
    ok = False
    if vp:
        p = Path(vp)
        ok = p.exists() and p.is_file()

    if not ok:
        alt = Path(f"outputs/video_{eid}_upload_opt.mp4")
        if alt.exists() and alt.is_file():
            rec = dict(rec)
            rec["video_path"] = str(alt.resolve())
            ok = True

    if ok:
        ready.append(rec)

dst.parent.mkdir(parents=True, exist_ok=True)
dst.write_text(json.dumps({"episodes": ready}, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"[run] ready_episodes={len(ready)}")
print(f"[run] saved_ready_index={dst}")
PY

if [[ "$AUTO_BUILD_CONTEXT_PACK" == "1" ]]; then
  CONTEXT_OUT_DIR="$OUTPUTS_DIR/vertex_fewshot"
  CONTEXT_SRC_BUNDLE="$CONTEXT_OUT_DIR/context_bundle.txt"
  CONTEXT_TARGET_FILE="prompts/atlas_vertex_context_pack.txt"

  echo "[run] building_context_pack=1"
  "$PYTHON_BIN" atlas_build_vertex_fewshot.py \
    --index "$SOURCE_INDEX" \
    --results-jsonl "$OUTPUTS_DIR/triplet_compare_results.jsonl" \
    --results-dir "$OUTPUTS_DIR/triplet_compare" \
    --outputs-dir "$OUTPUTS_DIR" \
    --out-dir "$CONTEXT_OUT_DIR" \
    --max-examples "$CONTEXT_MAX_EXAMPLES" \
    --pass-score-threshold "$PASS_SCORE_THRESHOLD" \
    --max-chars-per-candidate "$CONTEXT_MAX_CHARS_PER_CANDIDATE"

  if [[ -f "$CONTEXT_SRC_BUNDLE" ]]; then
    cp -f "$CONTEXT_SRC_BUNDLE" "$CONTEXT_TARGET_FILE"
    echo "[run] context_pack_source=$CONTEXT_SRC_BUNDLE"
    echo "[run] context_pack_target=$CONTEXT_TARGET_FILE"
  else
    echo "[run] warning: context bundle missing at $CONTEXT_SRC_BUNDLE"
  fi
else
  echo "[run] building_context_pack=0"
fi

batch_args=(
  --config "$CONFIG"
  --outputs-dir "$OUTPUTS_DIR"
  --index "$READY_INDEX"
  --remote "$REMOTE"
  --limit 0
  --generate-chat-timed-missing
  --generate-vertex-chat-missing
  --regenerate-api-missing
  --regenerate-api-from-video
  --pass-score-threshold "$PASS_SCORE_THRESHOLD"
)

if [[ "$REQUIRE_TIER2" == "1" ]]; then
  batch_args+=(--no-allow-missing-tier2)
else
  batch_args+=(--allow-missing-tier2)
fi

if [[ "$RESUME_ONLY" == "1" ]]; then
  batch_args+=(--skip-existing-results)
else
  batch_args+=(--overwrite-evals --no-skip-existing-results)
fi

"$PYTHON_BIN" atlas_triplet_batch.py "${batch_args[@]}"

"$PYTHON_BIN" atlas_review_viewer_gen.py \
  --index "$READY_INDEX" \
  --out "$OUTPUTS_DIR/atlas_review_viewer.html"

echo "[run] done."
echo "[run] results_jsonl=$OUTPUTS_DIR/triplet_compare_results.jsonl"
echo "[run] viewer=$OUTPUTS_DIR/atlas_review_viewer.html"
