# AGENTS.md

Project: `OCR_annotation_Atlas`
Root: `E:\OCR_annotation_Atlas`

## Purpose

This repository automates Atlas Capture episode labeling end to end:

1. open/reserve an episode
2. extract live segments from the Atlas UI
3. generate labels and optional structural repair guidance through Gemini
4. validate the result against policy
5. apply labels in the UI
6. verify and submit safely

This is a stateful browser + AI + policy pipeline. The biggest failure mode is not a simple syntax bug. It is desync between:

- live DOM state
- extracted/source segment state
- Gemini plan state
- final submit state

## Critical Rule: Source of Truth

When debugging timestamps or duration mismatches, treat these sources differently:

- `live DOM` is the real current UI state
- `source_segments` is the extracted DOM snapshot used for the current solve pass
- `segment_plan` is AI output and may hallucinate timestamps

For duration enforcement, DOM/source timestamps are the ground truth.
Do not treat Gemini timestamps as authoritative for policy blocking.

## Files That Matter Most

- `src/solver/legacy_impl.py`
  Main episode runner and integration glue.

- `src/solver/orchestrator.py`
  Policy gate orchestration, compare/retry flow, repair orchestration.

- `src/solver/segments.py`
  Segment extraction, structural operations, label apply, submit guard path.

- `src/rules/policy_gate.py`
  Final policy validation rules.

- `src/rules/consistency.py`
  Live DOM vs extracted source consistency checks before submit.

- `src/solver/chat_only.py`
  Chat-web subprocess wrapper, request observability, raw response persistence.

- `src/solver/video_core.py`
  Dependency-light video helpers extracted to break import cycles cleanly.

- `src/solver/desync.py`
  Snapshot/checksum helpers and blocking-vs-warning desync decisions.

- `src/solver/reliability.py`
  Retry-stage/reason taxonomy plus structured episode report primitives.

- `src/solver/episode_runtime.py`
  Episode-scoped runtime container for isolated Atlas/Gemini resources in the v2 path.

- `src/solver/gemini_session.py`
  Single-session Gemini manager foundation and response-integrity validation.

- `atlas_triplet_compare.py`
  Deep Gemini chat-web interaction logic. Important for session/tab behavior.

- `src/infra/artifacts.py`
  Task-scoped caches, output dumps, cleanup helpers.

## Current Known Risk Areas

### 1. Desync / false rejection

Typical symptom:
- UI shows segment duration like `5s`
- policy rejects the same segment as `15s` or `20s`

Most likely causes:
- stale extracted state
- Gemini hallucinated timestamps in `segment_plan`
- DOM changed after extraction

### 2. Async UI timing

Atlas UI appears to be React-like and may update after split/merge/edit actions.
Prefer stability checks over simple element existence checks.

### 3. Chat session behavior

The current repository now has two chat-web paths:

- legacy subprocess path
- v2 registered-session path

The v2 path now includes:

- `EpisodeRuntime`
- `GeminiSession`
- strict segment-integrity validation in `chat_only.py`
- transport retry/backoff in `chat_only.py`
- one registered Gemini session per episode when the canary flags are enabled

Atlas episode-context isolation is now wired into `legacy_impl.run(...)` behind:

- `run.use_episode_runtime_v2`
- `run.force_episode_browser_isolation`
- `run.strict_single_chat_session`

When all three flags are on, `legacy_impl.py` now:

- refreshes `gemini.chat_web_storage_state` from the bootstrap CDP context
- opens a per-episode Gemini context/page
- registers one Gemini session for `chat_only.py` to reuse across labels/planner/repair calls

The legacy subprocess path is still the fallback if session registration fails or v2 flags are off.

The current chat-web stack may still open multiple requests/pages across one episode on the legacy path.
If debugging missing Gemini responses or session leakage, inspect:

- `src/solver/chat_only.py`
- `run_gemini_chat_json.py`
- `atlas_triplet_compare.py`

Live canary findings from `2026-04-14`:

- `room_url=/tasks/room/normal` may show room-disabled/unavailable messaging even while `/tasks`
  still contains active reserved episodes and working `Label` links.
- The browser fallback now prefers direct `/tasks` label links after room-disabled recovery.
- The old v2 watchdog hard-exit was caused by missing heartbeat propagation during long chat-web waits.
- Current main Gemini risk is different:
  - chat-web may render partial JSON while the page is still in `Thinking`
  - if waiting logic is too strict, the solver can re-query unnecessarily and bloat the thread
- New live probe artifacts for this behavior are under:
  - `outputs/danatimer_canary_v2/live_probe_20260414/`
  - `outputs/danatimer_canary_v2/live_probe_20260414_b/`

When running a live canary from the terminal, prefer unbuffered mode:

```powershell
python -u atlas_web_auto_solver.py --config config_account_danatimer_canary_v2.yaml
```

Atlas `/tasks` reserve-state note:

- If the page shows `No Episodes Reserved`, `Reserve a batch of episodes`, or a CTA like
  `Reserve 3 Episodes`, do not treat that as a terminal no-task page.
- The solver should reserve immediately from `/tasks`, confirm the dialog, then look again for
  `Label` links.

Upload optimization note:

- Prefer `ffmpeg` over OpenCV for upload optimization when both are available.
- On this workstation, OpenCV compressed poorly and produced oversized `_upload_opt.mp4` files.
- The current `danatimer` configs now target `15 MB` and prefer `ffmpeg`.

Dry-run policy note:

- `policy auto-repair` for overlong segments is execute-only.
- If a dry-run stops at policy gate, check for:
  - `execute=false (dry-run); policy auto-repair only runs during the execute/apply pass`

### 4. Legacy circular imports

The `video.py ↔ legacy_impl.py` import cycle has been broken by extracting pure helpers into
`src/solver/video_core.py`. Clean process imports now pass:

```powershell
python -c "from src.solver import legacy_impl, video, video_core, segments; print('ok')"
```

If a new cycle appears, treat it as a regression and restore the dependency rule:

- `video_core.py` must stay dependency-light
- `video.py` may lazily import runtime helpers only inside functions
- `legacy_impl.py` may alias from `video.py` / `segments.py`

## Debugging Workflow

If you need to trace one broken segment end to end, use this order:

1. find it in `extract_segments(...)` output
2. find it in `source_segments`
3. find it in `segment_plan`
4. inspect `policy_gate` decision
5. inspect final pre-submit guard output

Good question to ask an agent:

`Trace segment 9 from DOM extraction to policy_gate and explain where its duration changed.`

## Recommended Investigation Prompts

Use prompts like:

`Trace how segment durations are calculated and propagated from extraction to policy_gate.`

`Find all sources of segment data and identify where stale state can survive between episodes.`

`Explain why a segment can be 5s in the DOM but 15s in the policy input.`

`Show every place where split/merge UI actions can race with extraction.`

## What To Preserve

- Fail-closed submit behavior
- DOM-grounded duration checks
- raw Gemini response persistence before parsing
- task-scoped cache cleanup between episodes
- compatibility aliases in `legacy_impl.py` for extracted submit helpers

## What Not To Assume

- Do not assume Gemini timestamps are reliable.
- Do not assume DOM is stable immediately after UI actions.
- Do not assume one chat request equals one chat session.
- Do not assume `legacy_impl.py` comments reflect the real runtime path without checking callers.

## Verification

Preferred quick validation after edits:

```powershell
python -m py_compile src\infra\artifacts.py src\rules\consistency.py src\solver\chat_only.py src\solver\legacy_impl.py src\solver\segments.py
```

For behavior checks, prefer small focused scripts that mock:

- `extract_segments`
- `source_segments`
- `segment_plan`

instead of relying only on full production runs.

## Production Deployment Notes (2026-05-12)

### Server: 178.105.100.92 (root/CRgtPiVwWxkV3uRrbxnU)

### GitHub: https://github.com/aymank2020/OCR_Atlas_annotation_project.git (shallow clone, no large binaries)

### Policy Changes Applied

- `max_segment_duration_sec`: 10s → 20s across 8 Python files + 5 YAML configs
- Dense labels are now mandatory (not preferred): prompt updates in `src/solver/prompting.py` and `src/solver/legacy_impl.py`
- Hold-first rule for concurrent actions clarified
- Policy gate `src/rules/policy_gate.py`: when DOM duration is valid but Gemini hallucinated overlong → downgrade to WARNING (not block)
- `dense_label_required: true` in `src/policy/context_manager.py`

### Bug Fixes Applied

- `atlas_triplet_compare.py:2592`: `_pick_existing_gemini_chat_page` — don't return unrelated authenticated Gemini page when target is a dedicated conversation URL
- `src/solver/episode_runtime.py:75`: `_select_existing_gemini_page` — same fix, don't hijack unrelated authenticated tab for dedicated URLs
- `atlas_triplet_compare.py:4506,5844`: increased `page.goto` timeout from 60s to 120s for Gemini chat URLs
- `src/solver/gemini_session.py:1617`: increased `page.goto` timeout from 60s to 120s

### Canary Config (`config_account_danatimer_canary_v2.yaml`) Tuning (2026-05-12)

- `chat_web_upload_settle_min_sec`: 20 → 30 (wait longer for video upload)
- `chat_web_pre_send_ready_timeout_sec`: 30 → 60 (wait longer before pressing Send)
- `chat_web_pre_send_settle_sec`: 4 → 6
- `chat_web_response_stall_sec_pro`: 75 → 180 (wait up to 3 min for pro/thinking responses)
- `chat_web_response_stall_sec_fast`: 35 → 60
- `chat_web_allowed_model_modes`: ["pro", "thinking"] (was ["pro"] only — thinking mode must be allowed)
- `chat_web_enforce_model_mode`: false (was true — don't force-switch mode, accept whatever Gemini shows)
- `chat_web_clean_thread_per_episode`: true (was false — clean thread between episodes)

### Production Config (`configs/production_hetzner.yaml`)

- Already has `max_segment_duration_sec: 20.0`
- Server IP needs update to 178.105.100.92

### Successful Production Test (2026-05-12)

- Episode `68f3c4bb7490ff94f1ecd21f` completed end-to-end
- 6 segments extracted, labeled via Gemini (thinking mode, 157s response time)
- All labels applied (6/6), Quality Review accepted, Submit VERIFIED
- Run command: `python -u atlas_web_auto_solver.py --config config_account_danatimer_canary_v2.yaml --execute --max-episodes 1`

### Key Commands

```powershell
# Local canary run (single episode, execute mode)
python -u atlas_web_auto_solver.py --config config_account_danatimer_canary_v2.yaml --execute --max-episodes 1

# Local dry-run (no apply/submit)
python -u atlas_web_auto_solver.py --config config_account_danatimer_canary_v2.yaml --max-episodes 1

# Verify tests after code changes
python -m pytest tests/ -x -v
```
