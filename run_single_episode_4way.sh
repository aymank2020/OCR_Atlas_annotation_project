#!/usr/bin/env bash
set -euo pipefail

# Run 4-way compare for exactly one episode:
# Tier2 (employee) vs Tier3 API vs Tier3 Chat vs Vertex Chat
#
# Usage:
#   EPISODE_ID=68d3110528e87fa66804713c bash ./run_single_episode_4way.sh
# or:
#   bash ./run_single_episode_4way.sh 68d3110528e87fa66804713c

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
  echo "[single4] loaded_env=.env"
else
  echo "[single4] warning: .env not found"
fi

if command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
else
  echo "[single4] error: no python interpreter found (python/python3)."
  exit 1
fi

EPISODE_ID="${EPISODE_ID:-${1:-}}"
if [[ -z "$EPISODE_ID" ]]; then
  echo "[single4] error: missing EPISODE_ID"
  echo "[single4] usage: EPISODE_ID=<id> bash ./run_single_episode_4way.sh"
  exit 1
fi
if [[ ! "$EPISODE_ID" =~ ^[0-9a-fA-F]{24}$ ]]; then
  echo "[single4] error: invalid EPISODE_ID format ($EPISODE_ID) - expected 24 hex chars"
  exit 1
fi

CONFIG="${CONFIG:-sample_web_auto_solver_production.yaml}"
OUTPUTS_DIR="${OUTPUTS_DIR:-outputs}"
SOURCE_INDEX="${SOURCE_INDEX:-$OUTPUTS_DIR/episodes_review_index.json}"
SINGLE_INDEX="${SINGLE_INDEX:-$OUTPUTS_DIR/episodes_single_${EPISODE_ID}.json}"
REMOTE="${REMOTE:-gdrive}"
MODEL="${MODEL:-gemini-3.1-pro-preview}"
COMPARE_MODEL="${COMPARE_MODEL:-}"
CHAT_TIMED_MODEL="${CHAT_TIMED_MODEL:-}"
VERTEX_CHAT_MODEL="${VERTEX_CHAT_MODEL:-}"
API_UPDATE_MODEL="${API_UPDATE_MODEL:-}"
PASS_SCORE_THRESHOLD="${PASS_SCORE_THRESHOLD:-95}"
OVERWRITE_RESULTS="${OVERWRITE_RESULTS:-1}"
# 1 = force compare stage to run on Vertex AI and use cached content from VERTEX_CACHED_CONTENT_NAME
# 0 = keep original config compare_auth_mode
USE_VERTEX_COMPARE_GATE="${USE_VERTEX_COMPARE_GATE:-1}"
# 1 = delete cached/generated files for this episode before running (force fresh generation)
FORCE_REGENERATE="${FORCE_REGENERATE:-0}"
# 1 = enforce strict quality gate policy for production safety
STRICT_GATE="${STRICT_GATE:-1}"
REQUIRE_TIER2="${REQUIRE_TIER2:-0}"
EFFECTIVE_CONFIG="$CONFIG"

if [[ -z "${ALLOW_MISSING_TIER2+x}" ]]; then
  if [[ "$REQUIRE_TIER2" == "1" ]]; then
    ALLOW_MISSING_TIER2="0"
  else
    ALLOW_MISSING_TIER2="1"
  fi
fi

if [[ "$STRICT_GATE" == "1" ]]; then
  OVERWRITE_RESULTS="1"
fi

echo "[single4] episode_id=$EPISODE_ID"
echo "[single4] config=$CONFIG"
echo "[single4] source_index=$SOURCE_INDEX"
echo "[single4] single_index=$SINGLE_INDEX"
echo "[single4] remote=$REMOTE"
echo "[single4] pass_score_threshold=$PASS_SCORE_THRESHOLD"
echo "[single4] overwrite_results=$OVERWRITE_RESULTS"
echo "[single4] use_vertex_compare_gate=$USE_VERTEX_COMPARE_GATE"
echo "[single4] force_regenerate=$FORCE_REGENERATE"
echo "[single4] strict_gate=$STRICT_GATE"
echo "[single4] require_tier2=$REQUIRE_TIER2"
echo "[single4] allow_missing_tier2=$ALLOW_MISSING_TIER2"

if [[ "$FORCE_REGENERATE" == "1" ]]; then
  removed=0
  for f in \
    "$OUTPUTS_DIR/text_${EPISODE_ID}_update.txt" \
    "$OUTPUTS_DIR/chat_reviews/${EPISODE_ID}/text_${EPISODE_ID}_chat.txt" \
    "$OUTPUTS_DIR/chat_reviews/${EPISODE_ID}/labels_${EPISODE_ID}.json" \
    "$OUTPUTS_DIR/vertex_chat_reviews/${EPISODE_ID}/text_${EPISODE_ID}_vertex_chat.txt" \
    "$OUTPUTS_DIR/vertex_chat_reviews/${EPISODE_ID}/labels_${EPISODE_ID}_vertex_chat.json" \
    "$OUTPUTS_DIR/api_reviews/${EPISODE_ID}/text_${EPISODE_ID}_api.txt" \
    "$OUTPUTS_DIR/api_reviews/${EPISODE_ID}/labels_${EPISODE_ID}_api.json" \
    "$OUTPUTS_DIR/triplet_compare/triplet_compare_${EPISODE_ID}.json"; do
    if [[ -f "$f" ]]; then
      rm -f "$f"
      removed=$((removed + 1))
    fi
  done
  echo "[single4] force_regenerate_removed_files=$removed"
fi

if [[ "$USE_VERTEX_COMPARE_GATE" == "1" ]]; then
  if [[ -n "${VERTEX_CACHED_CONTENT_NAME:-}" ]]; then
    EFFECTIVE_CONFIG="$OUTPUTS_DIR/single4_config_${EPISODE_ID}.yaml"
    BASE_CONFIG="$CONFIG" EFFECTIVE_CONFIG="$EFFECTIVE_CONFIG" VERTEX_CACHED_CONTENT_NAME="$VERTEX_CACHED_CONTENT_NAME" STRICT_GATE="$STRICT_GATE" "$PYTHON_BIN" - <<'PY'
import os
import re
from pathlib import Path

import yaml

base_cfg_path = Path(os.environ["BASE_CONFIG"]).resolve()
effective_cfg_path = Path(os.environ["EFFECTIVE_CONFIG"]).resolve()
cache_name = str(os.environ.get("VERTEX_CACHED_CONTENT_NAME", "") or "").strip()

if not base_cfg_path.exists() or not base_cfg_path.is_file():
    raise SystemExit(f"[single4] error: base config not found: {base_cfg_path}")

cfg = yaml.safe_load(base_cfg_path.read_text(encoding="utf-8")) or {}
if not isinstance(cfg, dict):
    raise SystemExit("[single4] error: base config root must be YAML object")

gem = cfg.get("gemini", {})
if not isinstance(gem, dict):
    gem = {}

# Force compare gate to run on Vertex.
gem["compare_auth_mode"] = "vertex_ai"
gem["vertex_chat_auth_mode"] = "vertex_ai"
gem["vertex_cached_content_name"] = cache_name
if str(os.environ.get("STRICT_GATE", "0") or "0").strip() == "1":
    gem["compare_fail_on_none"] = True

# Keep endpoint location aligned with cache location (common case: global).
m = re.search(r"/locations/([^/]+)/cachedContents/", cache_name)
if m:
    gem["vertex_location"] = str(m.group(1) or "").strip() or gem.get("vertex_location", "global")

cfg["gemini"] = gem
effective_cfg_path.parent.mkdir(parents=True, exist_ok=True)
effective_cfg_path.write_text(
    yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False),
    encoding="utf-8",
)
print(f"[single4] effective_config_written={effective_cfg_path}")
print(f"[single4] compare_auth_mode={gem.get('compare_auth_mode')}")
print(f"[single4] vertex_chat_auth_mode={gem.get('vertex_chat_auth_mode')}")
print(f"[single4] vertex_location={gem.get('vertex_location')}")
PY
  else
    echo "[single4] warning: VERTEX_CACHED_CONTENT_NAME is empty; compare gate stays on config defaults."
  fi
fi

echo "[single4] effective_config=$EFFECTIVE_CONFIG"

EPISODE_ID="$EPISODE_ID" SOURCE_INDEX="$SOURCE_INDEX" SINGLE_INDEX="$SINGLE_INDEX" OUTPUTS_DIR="$OUTPUTS_DIR" "$PYTHON_BIN" - <<'PY'
import json
import os
from pathlib import Path

eid = str(os.environ["EPISODE_ID"]).strip().lower()
src = Path(os.environ["SOURCE_INDEX"])
dst = Path(os.environ["SINGLE_INDEX"])
outputs_dir = Path(os.environ.get("OUTPUTS_DIR", "outputs")).resolve()

def _load_episodes(path: Path):
    if not path.exists() or not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    episodes = payload.get("episodes", []) if isinstance(payload, dict) else payload
    return episodes if isinstance(episodes, list) else []

picked = None
index_candidates = [src, outputs_dir / "episodes_ready_for_triplet.json", outputs_dir / "episodes_review_index.json"]
seen = set()
for idx in index_candidates:
    key = str(idx.resolve())
    if key in seen:
        continue
    seen.add(key)
    episodes = _load_episodes(idx)
    for ep in episodes:
        if not isinstance(ep, dict):
            continue
        if str(ep.get("episode_id") or "").strip().lower() == eid:
            picked = dict(ep)
            print(f"[single4] episode_found_in_index={idx}")
            break
    if picked is not None:
        break

if picked is None:
    print(f"[single4] episode_not_in_index={eid}; building synthetic record from outputs/")

    def _first_existing(candidates):
        for p in candidates:
            if p.exists() and p.is_file():
                return p
        return None

    video_main = _first_existing(
        [
            outputs_dir / f"video_{eid}.mp4",
            outputs_dir / f"video_{eid}_upload_opt.mp4",
        ]
    )
    if video_main is None:
        raise SystemExit(
            f"[single4] error: episode not found in index and no local video found for {eid} "
            f"(expected {outputs_dir}/video_{eid}.mp4)"
        )

    tier2_path = _first_existing([outputs_dir / f"text_{eid}_current.txt"])
    api_path = _first_existing(
        [
            outputs_dir / f"text_{eid}_update.txt",
            outputs_dir / "api_reviews" / eid / f"text_{eid}_api.txt",
        ]
    )

    related = []
    for p in [
        video_main,
        outputs_dir / f"video_{eid}_upload_opt.mp4",
        outputs_dir / f"text_{eid}_current.txt",
        outputs_dir / f"text_{eid}_update.txt",
        outputs_dir / f"labels_{eid}.json",
        outputs_dir / f"task_state_{eid}.json",
        outputs_dir / "chat_reviews" / eid / f"text_{eid}_chat.txt",
        outputs_dir / "vertex_chat_reviews" / eid / f"text_{eid}_vertex_chat.txt",
    ]:
        if p.exists() and p.is_file():
            related.append(str(p))

    for d in [outputs_dir / "chat_reviews" / eid, outputs_dir / "vertex_chat_reviews" / eid, outputs_dir / "api_reviews" / eid]:
        if d.exists() and d.is_dir():
            for p in sorted(d.glob("*")):
                if p.is_file():
                    related.append(str(p))

    picked = {
        "episode_id": eid,
        "review_status": "manual_single_run",
        "video_path": str(video_main),
        "tier2_text_path": str(tier2_path) if tier2_path else "",
        "tier3_text_path": str(api_path) if api_path else "",
        "related_files": sorted(set(related)),
    }
    print(
        f"[single4] synthetic_record: video={'yes' if video_main else 'no'} "
        f"tier2={'yes' if tier2_path else 'no'} api={'yes' if api_path else 'no'} "
        f"related_files={len(picked['related_files'])}"
    )

dst.parent.mkdir(parents=True, exist_ok=True)
dst.write_text(json.dumps({"episodes": [picked]}, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"[single4] single_episode_index_saved={dst}")
PY

batch_args=(
  --config "$EFFECTIVE_CONFIG"
  --outputs-dir "$OUTPUTS_DIR"
  --index "$SINGLE_INDEX"
  --remote "$REMOTE"
  --limit 1
  --model "$MODEL"
  --pass-score-threshold "$PASS_SCORE_THRESHOLD"
  --generate-chat-timed-missing
  --generate-vertex-chat-missing
  --regenerate-api-missing
  --regenerate-api-from-video
)

if [[ "$ALLOW_MISSING_TIER2" == "1" ]]; then
  batch_args+=(--allow-missing-tier2)
else
  batch_args+=(--no-allow-missing-tier2)
fi

if [[ -n "$COMPARE_MODEL" ]]; then
  batch_args+=(--compare-model "$COMPARE_MODEL")
fi
if [[ -n "$CHAT_TIMED_MODEL" ]]; then
  batch_args+=(--chat-timed-model "$CHAT_TIMED_MODEL")
fi
if [[ -n "$VERTEX_CHAT_MODEL" ]]; then
  batch_args+=(--vertex-chat-model "$VERTEX_CHAT_MODEL")
fi
if [[ -n "$API_UPDATE_MODEL" ]]; then
  batch_args+=(--api-update-model "$API_UPDATE_MODEL")
fi

if [[ "$OVERWRITE_RESULTS" == "1" ]]; then
  batch_args+=(--overwrite-evals --no-skip-existing-results)
else
  batch_args+=(--skip-existing-results)
fi

"$PYTHON_BIN" atlas_triplet_batch.py "${batch_args[@]}"

EPISODE_ID="$EPISODE_ID" OUTPUTS_DIR="$OUTPUTS_DIR" "$PYTHON_BIN" - <<'PY'
import json
import os
from pathlib import Path

eid = str(os.environ["EPISODE_ID"]).strip().lower()
out = Path(os.environ.get("OUTPUTS_DIR", "outputs")) / "triplet_compare" / f"triplet_compare_{eid}.json"
if not out.exists():
    raise SystemExit(f"[single4] warning: result file not found: {out}")

obj = json.loads(out.read_text(encoding="utf-8"))
judge = obj.get("judge_result", {}) if isinstance(obj, dict) else {}
if not isinstance(judge, dict):
    judge = {}

judge_winner = str(judge.get("winner") or "").strip().lower()
judge_submit_safe = str(judge.get("submit_safe_solution") or "").strip().lower()
judge_scores = judge.get("scores", {}) if isinstance(judge.get("scores"), dict) else {}
judge_winner_score = judge_scores.get(judge_winner) if judge_winner else None

results_jsonl = Path(os.environ.get("OUTPUTS_DIR", "outputs")) / "triplet_compare_results.jsonl"
batch_row = None
if results_jsonl.exists() and results_jsonl.is_file():
    for raw in results_jsonl.read_text(encoding="utf-8", errors="replace").splitlines():
        line = str(raw or "").strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if not isinstance(row, dict):
            continue
        if str(row.get("episode_id") or "").strip().lower() == eid:
            batch_row = row

print(f"[single4] result_file={out}")
print(f"[single4] judge_winner={judge_winner}")
print(f"[single4] judge_submit_safe={judge_submit_safe}")
print(f"[single4] judge_winner_score={judge_winner_score}")
if isinstance(batch_row, dict):
    print(f"[single4] batch_winner={str(batch_row.get('winner') or '').strip().lower()}")
    print(f"[single4] batch_score_pct={batch_row.get('score_pct')}")
    print(f"[single4] batch_quality_pass={bool(batch_row.get('quality_pass', False))}")
    print(f"[single4] batch_reason={str(batch_row.get('reason') or '').strip()}")
    print(f"[single4] batch_validator_ok={batch_row.get('validator_ok')}")
    print(f"[single4] batch_gate_reason={str(batch_row.get('gate_reason') or '').strip()}")
    if not bool(batch_row.get("quality_pass", False)):
        raise SystemExit("[single4] BLOCKED: quality gate failed (quality_pass=False)")
else:
    raise SystemExit("[single4] BLOCKED: no batch result row found for episode")
PY

echo "[single4] done"
