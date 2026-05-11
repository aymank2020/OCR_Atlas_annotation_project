# OCR Annotation Atlas - Junie Guidelines

## Mission
Maintain and improve the Atlas video-annotation QA pipeline (not a generic OCR toolkit rewrite).
Primary flow is:
1) generate/collect candidates
2) compare candidates against source video
3) enforce strict quality gate
4) update review artifacts (viewer/dashboard)

## Critical Rules
- Do not rewrite project architecture unless explicitly requested.
- Keep existing production scripts working:
  - `atlas_triplet_batch.py`
  - `atlas_triplet_compare.py`
  - `run_triplet_with_ready_videos.sh`
  - `atlas_review_viewer_gen.py`
  - `atlas_dashboard_gen.py`
  - `vertex_create_cache.py`
  - `atlas_build_vertex_fewshot.py`
- Preserve server secrets and local runtime state:
  - never overwrite `.env`
  - never overwrite `sample_web_auto_solver_vps.yaml` keys unless asked
  - do not delete `.state/*`
- Never run destructive git commands.

## Quality Gate Policy (Mandatory)
- Minimum accepted score is `95`.
- Any winner score `< 95` is a failure.
- `winner=none` is failure.
- `submit_safe_solution` must match winner (if present), otherwise failure.
- Hallucinating winner is failure.

## Default Runtime Assumptions
- Config file: `sample_web_auto_solver_vps.yaml`
- Remote: `gdrive`
- Vertex location: `global` for Gemini preview models
- Preferred model family: `gemini-3.1-pro-preview`

## Resume-First Execution
For unstable network, always resume instead of restarting full runs.
- Preferred command:
  - `RESUME_ONLY=1 PASS_SCORE_THRESHOLD=95 ./run_triplet_with_ready_videos.sh`
- Full rerun only when requested:
  - `RESUME_ONLY=0 PASS_SCORE_THRESHOLD=95 ./run_triplet_with_ready_videos.sh`

## Common Operational Fixes
1) If most episodes are skipped as `missing_inputs: video_path`:
   - build/run with ready-only index (`episodes_ready_for_triplet.json`) or use `run_triplet_with_ready_videos.sh`.
2) If Vertex cache is expired:
   - recreate cache using `vertex_create_cache.py`
   - update `vertex_cached_content_name` in `sample_web_auto_solver_vps.yaml`
   - keep `vertex_location: "global"`
3) If viewer shows missing timed labels:
   - verify files exist:
     - `outputs/chat_reviews/<eid>/text_<eid>_chat.txt`
     - `outputs/vertex_chat_reviews/<eid>/text_<eid>_vertex_chat.txt`
   - regenerate viewer after any batch run.

## Validation Before Finishing
- Run compile checks for touched Python files:
  - `python -m py_compile <files...>`
- Regenerate artifacts when relevant:
  - `python atlas_review_viewer_gen.py ...`
  - `python atlas_dashboard_gen.py --outputs-dir outputs`
- Report concise status with:
  - what changed
  - what command to run next
  - any blockers

## Communication Style
- Keep replies concise and command-ready.
- Prefer copy-paste-safe commands.
- Avoid long theoretical explanations unless asked.
