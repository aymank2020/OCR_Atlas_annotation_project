# Atlas Pipeline Audit Continuation Note

Saved on: 2026-04-13
Workspace: `E:\OCR_annotation_Atlas`

## What I reviewed

- `src/rules/policy_gate.py`
- `src/solver/segments.py`
- `src/solver/chat_only.py`
- `src/solver/orchestrator.py`
- `src/solver/legacy_impl.py`
- `src/rules/consistency.py`
- `src/infra/artifacts.py`
- `run_gemini_chat_json.py`
- `atlas_triplet_compare.py`

## Confirmed implemented

1. Policy gate now prefers DOM/source durations over Gemini plan durations for overlong checks.
   - File: `src/rules/policy_gate.py`
   - This is the most important fix and is actually present.

2. Segment extraction now waits for temporary DOM stability before reading rows.
   - File: `src/solver/segments.py`
   - `_wait_for_segments_stable()` exists and is called from `extract_segments()`.

3. Raw Gemini/chat subprocess output is saved before JSON parsing.
   - File: `src/solver/chat_only.py`
   - `raw_gemini_response_{episode}_{request_id}.txt` is written before `json.loads()`.

4. Orchestrator now logs basic plan-vs-DOM duration mismatch warnings.
   - File: `src/solver/orchestrator.py`

5. A consistency module was added.
   - File: `src/rules/consistency.py`

## Confirmed gaps / problems still remaining

1. The "pre-submit consistency guard" is in the wrong place.
   - Current location: `src/solver/legacy_impl.py` around line 5817
   - It runs before `apply_labels(...)`, not before the final submit click.
   - This means it does not guard the actual final DOM state after labels are applied.

2. `_pre_submit_duration_check()` exists but is not used anywhere.
   - File: `src/solver/segments.py`
   - It must be wired into the submit path, otherwise it is dead code.

3. Clean-state protocol is incomplete.
   - Current implementation only invalidates cached labels for the current task in `legacy_impl.py`.
   - Missing:
     - clearing segment caches
     - clearing task state artifacts when needed
     - clearing broader episode-scoped temp files
     - dedicated `_clear_episode_state()` helper in `src/infra/artifacts.py`

4. Browser/session isolation per episode is not implemented.
   - `legacy_impl.py` still reuses the same browser context/page across episodes in the main loop.
   - This does not satisfy the requested "new browser context per episode" design.

5. Gemini single-chat-session policy is not implemented.
   - `chat_only.py` spawns isolated subprocesses for labels / ops / repair.
   - `atlas_triplet_compare.py` opens new chat pages/tabs in the web flow.
   - This means one episode can still create multiple independent Gemini interactions.

6. Request observability is incomplete.
   - `request_id` is created after the subprocess finishes, not at request start.
   - There is no structured start/end log with a shared request ID across the full request lifecycle.

7. Structured logging is still summary-style, not the requested forensic JSON logging.
   - `extract_segments()` logs count and max duration only.
   - Missing:
     - per-segment structured rows
     - checksum/hash of the full segment list in logs
     - exact payload logging before Gemini
     - source tagging across all stages

8. "After every UI action, re-fetch and wait for update" is only partially covered.
   - Current stabilization is inside `extract_segments()`.
   - I have not yet confirmed a strict post-action re-fetch/wait boundary after every split/merge operation itself.

## High-confidence next actions

1. Move the consistency guard into the real final submit path.
   - Best target: `src/solver/segments.py` inside `apply_labels()`
   - Run both:
     - `validate_pre_submit_consistency(...)`
     - `_pre_submit_duration_check(...)`
   - Do this immediately before `_browser._click_submit_with_verification(...)`

2. Add a real episode-state cleanup helper.
   - File: `src/infra/artifacts.py`
   - New helper idea: `_clear_episode_state(cfg, task_id, *, clear_task_state=False)`
   - Remove stale:
     - `segments_{task}.json`
     - `gemini_labels_cache_{task}.json`
     - optionally `task_state_{task}.json`
     - episode-scoped raw response temp files if appropriate

3. Improve chat request observability.
   - Generate `request_id` before subprocess launch in `chat_only.py`
   - Log:
     - request start
     - request end
     - prompt path
     - episode id
     - mode
     - timeout
     - return code / duration

4. Decide whether to fully enforce one-chat-per-episode or keep current architecture.
   - Current architecture is multi-request by design.
   - If strict single-chat policy is required, this needs a deeper redesign in:
     - `chat_only.py`
     - `run_gemini_chat_json.py`
     - `atlas_triplet_compare.py`
   - This is not a small patch.

## Important truth check

The earlier statement that the whole plan was "completed بالكامل" is not accurate.
The core P0 policy-gate fix is real, but several other items are only partial or not yet wired into the production path.

## Resume plan for next session

Start with these exact edits:

1. Patch `src/solver/segments.py`
   - call pre-submit consistency + duration guard right before submit

2. Patch `src/infra/artifacts.py`
   - add `_clear_episode_state()`

3. Patch `src/solver/legacy_impl.py`
   - replace the current early consistency call with proper episode-state cleanup usage

4. Patch `src/solver/chat_only.py`
   - move request ID creation to subprocess start and add better lifecycle logging

5. Re-run quick import validation
   - `python -c "import src.solver.segments; import src.rules.policy_gate; import src.solver.chat_only; import src.solver.orchestrator; import src.solver.legacy_impl"`

## Update after implementation pass

Completed in this session:

1. Added a real episode-state cleanup helper in `src/infra/artifacts.py`
   - clears task-scoped caches
   - clears chat cache directory under `outputs/_chat_only/<task_id>`
   - optionally clears shared dumps

2. Rewired clean-state usage in `src/solver/legacy_impl.py`
   - episode start now calls `_clear_episode_state(...)`
   - old "pre-submit" check was re-labeled as a pre-apply consistency check
   - `apply_labels(...)` now receives `episode_id`, `segment_plan`, and `source_segments`

3. Added the real final guard inside `src/solver/segments.py`
   - `apply_labels(...)` now runs:
     - `validate_pre_submit_consistency(...)`
     - `_pre_submit_duration_check(...)`
   - both run before the final submit click

4. Improved `validate_pre_submit_consistency(...)`
   - blocking on live DOM vs extracted-source drift
   - warning-only on plan-vs-DOM timestamp drift
   - this avoids reintroducing false blocks caused by Gemini timestamp hallucinations

5. Improved extraction/structural observability
   - extraction log now includes a checksum
   - structural operations now wait for segment stabilization after success

6. Improved chat request observability in `src/solver/chat_only.py`
   - request ID generated at request start
   - start/fail/raw-saved/completed lifecycle logs added
   - stdout/stderr dumps are saved on subprocess failure

Validation completed:

- `python -m py_compile` passed for edited files
- `_clear_episode_state(...)` behavior test passed
- `validate_pre_submit_consistency(...)` behavior test passed for a non-blocking plan-vs-DOM drift case

Still open:

1. Strict one-chat-session-per-episode is still not implemented.
2. New browser context per episode is still not implemented.
3. Direct CLI `import` validation hits a pre-existing circular import:
   - `src/solver/video.py` imports `src/solver/legacy_impl.py`
   - `src/solver/legacy_impl.py` imports `src/solver/video.py` and dereferences it at module import time

## Update after v2 foundation pass

Completed in this pass:

1. Added v2 hardening flags in `src/infra/solver_config.py`
   - `use_episode_runtime_v2`
   - `strict_single_chat_session`
   - `force_episode_browser_isolation`
   - `gemini_transport_max_retries`
   - `targeted_repair_max_rounds`
   - `structured_episode_reports`
   - `desync_snapshot_tolerance_sec`

2. Added new foundation modules
   - `src/solver/video_core.py`
   - `src/solver/desync.py`
   - `src/solver/reliability.py`
   - `src/solver/episode_runtime.py`
   - `src/solver/gemini_session.py`

3. Fixed the legacy import cycle by extracting pure video helpers
   - `src/solver/video.py` no longer imports `legacy_impl` at module load
   - blocking modal access is now lazy-imported only at runtime
   - clean import now passes:
     - `python -c "from src.solver import legacy_impl, video, video_core, segments; print('ok')"`

4. Upgraded desync handling
   - `src/rules/consistency.py` now uses snapshot/checksum helpers from `src/solver/desync.py`
   - `segments.py` now uses a shared checksum builder instead of a local one-off hash path

5. Upgraded chat reliability
   - `src/solver/chat_only.py` now has transport retry wrapping with backoff
   - explicit segment hallucinations / duplicate indices are rejected instead of silently remapped
   - duplicate exported definitions in `chat_only.py` were corrected so the rich implementation remains active

6. Restored missing compatibility aliases in `src/solver/legacy_impl.py`
   - `_submit_transition_observed`
   - `_submit_episode`

Validation completed in this pass:

- `python -m py_compile` passed for:
  - `src/solver/video_core.py`
  - `src/solver/video.py`
  - `src/solver/desync.py`
  - `src/solver/reliability.py`
  - `src/solver/episode_runtime.py`
  - `src/solver/gemini_session.py`
  - `src/rules/consistency.py`
  - `src/solver/segments.py`
  - `src/solver/chat_only.py`
  - `src/solver/legacy_impl.py`

- Passed tests:
  - `tests/test_v2_hardening_foundation.py` -> `5 passed`
  - `tests/test_refactored_module_sources.py` + `tests/test_chat_only_solver.py` -> `36 passed`
  - `tests/test_segments_structural_ops.py` + `tests/test_submit_gate.py` -> `20 passed`

Remaining next-phase work:

1. Wire `EpisodeRuntime` into the real episode loop in `src/solver/legacy_impl.py`
   - fresh Atlas context per episode from saved storage state
   - lifecycle logging for created/destroyed contexts

2. Add a real `GeminiSession` execution path behind `use_episode_runtime_v2`
   - one chat page/session per episode
   - same-session targeted repair
   - minimal-history replay on restart

3. Emit structured per-episode JSON reports
   - attach checksum
   - retry stage/reason
   - desync flag
   - failure class

4. Use the new screenshot/runbook guide when Atlas UI changes
   - see `docs/atlas_v2_hardening_guide.md`

## Update after Phase 2 Atlas runtime canary pass

Completed in this pass:

1. Wired `EpisodeRuntime` into the real `run(...)` loop in `src/solver/legacy_impl.py`
   - activation happens after an episode is opened
   - bootstrap room page/context are preserved
   - when `run.use_episode_runtime_v2=true` and `run.force_episode_browser_isolation=true`
     the solver opens a fresh Atlas context/page for that episode from storage state

2. Added lifecycle/runtime logging helpers in `src/solver/legacy_impl.py`
   - emits structured runtime events for `context_created` and `context_destroyed`
   - restores the bootstrap room page after isolated-episode cleanup

3. Added structured per-episode report emission
   - report path: `outputs/episode_reports/episode_<task_id>.json`
   - append-only log: `outputs/episode_reports/episodes.jsonl`
   - report includes:
     - `episode_id`
     - `context_id`
     - `segment_checksum`
     - `segment_count`
     - `page_url`
     - `submit_blocked`
     - `failure_class`
     - task-state excerpt
     - runtime lifecycle events

4. Added targeted tests for the new runtime/report helpers
   - `_emit_episode_report(...)`
   - `_activate_episode_runtime_v2(...)`

Validation completed in this pass:

- `python -m py_compile src\solver\legacy_impl.py tests\test_v2_hardening_foundation.py`
- `python -c "from src.solver import legacy_impl, video, video_core, segments, chat_only, gemini_session, desync, reliability; print('imports-ok')"`
- targeted regression suite:
  - `63 passed`

Still open after this pass:

1. Gemini single-session-per-episode is still foundation-only and not yet the default execution path.
2. `EpisodeRuntime` currently isolates Atlas execution only; Gemini still uses the legacy chat-web/subprocess path.
3. Retry-stage metadata is not yet fully propagated into the structured episode report.

## Update after Phase 3 Gemini session bridge pass

Completed in this pass:

1. Wired a real `GeminiSession` path into `src/solver/chat_only.py`
   - `run_labels_generation(...)` now uses the registered episode session when:
     - `run.use_episode_runtime_v2=true`
     - `run.strict_single_chat_session=true`
   - `run_structural_planner(...)` now uses the same session
   - `run_repair_query(...)` now uses the same session
   - legacy subprocess execution remains as fallback when no v2 session is registered

2. Extended `EpisodeRuntime` to support Gemini re-open and persistence
   - stores Gemini browser/state/page metadata
   - persists Gemini storage state on close
   - can reopen a fresh Gemini context/page for the same episode after page crash

3. Wired Gemini runtime activation into `src/solver/legacy_impl.py`
   - refreshes `gemini.chat_web_storage_state` from the bootstrap CDP context
   - creates a per-episode Gemini context/page when strict single-session mode is enabled
   - registers one Gemini session per episode through `src/solver/chat_only.py`
   - unregisters the session during episode cleanup

4. Propagated Gemini metadata into structured episode reports
   - `gemini_session_id`
   - `request_id`
   - `retry_stage`
   - `retry_reason`
   - `gemini_latency_ms`
   - recent Gemini validation errors

5. Added/expanded tests for the new bridge
   - Gemini storage-state default exists in config
   - runtime activation can register Gemini session
   - `chat_only` can use the registered Gemini session for labels
   - final episode report includes Gemini session/request metadata

Validation completed in this pass:

- `python -m py_compile src\infra\solver_config.py src\solver\episode_runtime.py src\solver\gemini_session.py src\solver\chat_only.py src\solver\legacy_impl.py tests\test_v2_hardening_foundation.py`
- `python -c "from src.solver import legacy_impl, video, video_core, segments, chat_only, gemini_session, desync, reliability; print('imports-ok')"`
- regression suite:
  - `66 passed`

Still open after this pass:

1. The v2 Gemini session path is now real, but still gated by canary flags and fallback remains active.
2. Intelligent three-stage retry orchestration is only partially expressed through the new session metadata; the orchestration layer still needs a full staged controller.
3. We still need a live canary run with fresh screenshots if the company changes Atlas or Gemini UI controls.

## Update after Phase 4 staged retry hardening pass

Completed in this pass:

1. Upgraded targeted repair on the v2 Gemini session path
   - `chat_only.run_repair_query(...)` now accepts:
     - `failing_indices`
     - `current_plan`
     - `retry_reason`
   - when a registered v2 session exists, repair requests now call:
     - `GeminiSession.repair_failed_segments(...)`
   - this makes targeted repair use true `targeted_repair_1` / `targeted_repair_2`
     stages instead of a generic transport request

2. Added retry-stage metadata propagation to chat payloads
   - `src/solver/gemini.py` now carries into `labels_payload["_meta"]`:
     - `request_id`
     - `gemini_session_id`
     - `retry_stage`
     - `retry_reason`
     - `gemini_latency_ms`
     - `raw_response_path`
   - task-state persistence now mirrors these fields for resume/debug/report flows

3. Hardened overlong auto-repair escalation in `src/solver/orchestrator.py`
   - targeted repair rounds now track:
     - `targeted_repair_1`
     - `targeted_repair_2`
   - if overlong segments still remain after the targeted rounds:
     - invalidate cached labels
     - re-extract from DOM
     - rebuild prompt
     - run one final `full_reset_regenerate` label pass

4. Added tests for:
   - targeted repair via registered Gemini session
   - payload meta propagation of retry/session fields
   - escalation from targeted repair to `full_reset_regenerate`

Validation completed in this pass:

- `python -m py_compile src\solver\chat_only.py src\solver\gemini.py src\solver\orchestrator.py tests\test_v2_hardening_foundation.py tests\test_chat_only_solver.py`
- regression suite:
  - `69 passed`

Still open after this pass:

1. We still need a live canary run for the new single-session Gemini path.
2. We still need refreshed screenshots from a real browser run if the company UI changed.
3. The final production decision is still the same: keep v2 behind canary flags until that live run is clean.

## Update after live canary audit on 2026-04-14

Completed in this pass:

1. Ran real canary sessions with `config_account_danatimer_canary_v2.yaml`
   - Chrome/CDP reused the real profile successfully
   - `run.use_episode_runtime_v2=true`
   - `run.strict_single_chat_session=true`
   - `run.force_episode_browser_isolation=true`
   - `run.structured_episode_reports=true`

2. Confirmed real Atlas UI drift and documented the new room fallback behavior
   - `/tasks/room/normal` can show room-disabled/unavailable messaging
   - `/tasks` still exposes active reserved episodes and usable `Label` links
   - fixed browser fallback so the solver prefers `/tasks` label links after room-disabled recovery

3. Captured new live baseline artifacts for the changed UI
   - `outputs/danatimer_canary_v2/manual_baseline_20260414_065851/01_room_state.html`
   - `outputs/danatimer_canary_v2/manual_baseline_20260414_065851/01_room_state.txt`
   - `outputs/danatimer_canary_v2/manual_baseline_20260414_065851/02_tasks_root.html`
   - `outputs/danatimer_canary_v2/manual_baseline_20260414_065851/02_tasks_root.txt`
   - `outputs/danatimer_canary_v2/manual_baseline_20260414_065851/03_room_state_windows_capture.png`
   - `outputs/danatimer_canary_v2/manual_baseline_20260414_065851/04_tasks_root_windows_capture.png`

4. Fixed the v2 heartbeat gap that caused silent watchdog termination
   - passed `heartbeat` through the registered-session path in `src/solver/chat_only.py`
   - added keepalive support to:
     - `src/solver/gemini_session.py`
     - `atlas_triplet_compare.py`
   - result: the solver no longer hard-exits silently while Gemini is waiting

5. Ran a deeper live canary and isolated the next real Gemini failure mode
   - the first live episode progressed through:
     - episode open
     - isolated Atlas/Gemini runtime creation
     - video preparation
     - DOM extraction
     - chunked chat-web labeling
   - the old watchdog kill disappeared
   - the next failure was a session-health problem during chunking:
     - `Keyboard.type: Target page, context or browser has been closed`
     - then `Gemini chat input not visible on session page`

6. Hardened Gemini session recovery after the live failure
   - classified `chat input not visible` as `page_crash`/transport failure
   - widened page-crash restart logic in `src/solver/gemini_session.py`
   - added request lifecycle tracing for the v2 Gemini path
   - added live probes that captured the actual Gemini page state during the long wait

7. Captured live Gemini probe artifacts that changed the diagnosis
   - `outputs/danatimer_canary_v2/live_probe_20260414/gemini_ctx0_page0_1776151255.png`
   - `outputs/danatimer_canary_v2/live_probe_20260414/gemini_ctx0_page0_1776151255.txt`
   - `outputs/danatimer_canary_v2/live_probe_20260414_b/gemini_ctx0_page0_1776151578.png`
   - `outputs/danatimer_canary_v2/live_probe_20260414_b/gemini_ctx0_page0_1776151578.txt`

8. Re-diagnosed the remaining issue from the live Gemini probes
   - Gemini was not blank/crashed in the second probe
   - it was still on the same thread with:
     - uploaded `MP4 (Google Drive)` chip visible
     - partial JSON already rendered in the response
     - `Thinking` still active
   - this showed the new bottleneck is not silent death
   - it is long streaming / partial-JSON wait behavior in chat-web

9. Implemented partial-JSON/stream-stall hardening
   - `_wait_for_new_chat_response_text(...)` now:
     - returns early when strict JSON is already parseable
     - returns the current response text after a configurable stall window instead of waiting indefinitely for the spinner to stop
   - `GeminiSession` now passes `gemini.chat_web_response_stall_sec`
   - `python -u` is now preferred for live canary runs so session tracing flushes immediately

10. Re-ran a fresh canary after the latest patch
    - no label task was available on that attempt, so final live validation of the new stall logic is still pending
    - this is an Atlas availability limitation, not a new code failure

Validation completed in this pass:

- `python -m py_compile src\solver\chat_only.py src\solver\gemini_session.py src\solver\reliability.py atlas_triplet_compare.py tests\test_v2_hardening_foundation.py`
- focused regression slices:
  - `20 passed`
- live canary logs:
  - `outputs/danatimer_canary_v2/canary_live_20260414_081829.log`
  - `outputs/danatimer_canary_v2/canary_live_20260414_084841.log`
  - `outputs/danatimer_canary_v2/canary_live_20260414_093409.log`

Still open after this pass:

1. The latest partial-JSON/stall fix still needs one clean live episode to verify end-to-end.
2. Gemini long-thread latency is now the main remaining chat-web risk area.
3. When Atlas has no available `Label` task, canary validation must wait for the next available reserved episode.

Update after reserve-flow hardening on 2026-04-14:

1. Closed the `/tasks` "No Episodes Reserved" gap that was still blocking live canary progress.
   - Atlas can land on `/tasks` with no visible `Label` row while still presenting a valid reserve CTA such as
     `Reserve 3 Episodes`.
   - `src/solver/browser.py` now treats this page state as actionable reserve inventory, not as a terminal
     "no task" outcome.

2. Strengthened reserve detection for the changed Atlas UI.
   - `_room_has_no_reserved_episodes(...)` now recognizes:
     - `No Episodes Reserved`
     - `Reserve a batch of episodes`
     - `You'll reserve`
     - `Reserve 3 Episodes` style text markers
   - if `/tasks` already exposes live label links, the reserve detector stands down and lets the solver open them.

3. Hardened reserve clicking for batch CTAs.
   - `_click_reserve_button_dynamic(...)` now explicitly targets:
     - `Reserve 3 Episodes`
     - `Reserve 2 Episodes`
     - `Reserve 1 Episode`
     - `Reserve New Episode`
   - the JS fallback now dispatches a real click event if direct `.click()` is ignored by the frontend.

4. Added focused regression coverage for this Atlas variant.
   - `tests/test_refactored_module_sources.py` now covers:
     - `/tasks` reserve-card detection
     - JS fallback reserve clicking
     - `goto_task_room(...)` recovering by reserving from `/tasks` and then opening a label URL

Validation completed for the reserve-flow hardening:

- `python -m py_compile src\solver\browser.py src\solver\legacy_impl.py tests\test_refactored_module_sources.py`
- `python -m pytest -q tests\test_refactored_module_sources.py -k "no_reserved or reserve or goto_task_room"`
  - `4 passed`
- `python -m pytest -q tests\test_v2_hardening_foundation.py tests\test_chat_only_solver.py -k "heartbeat or registered_session or transport_classifier or chat_only or repair_query or wait_for_new_chat_response_text or wait_for_chat_upload_settle"`
  - `21 passed`

Update after video optimization and policy-repair clarity hardening on 2026-04-14:

1. Fixed the upload optimizer regression that was degrading the canary path.
   - Root cause: on this Windows environment, OpenCV was available and got chosen before ffmpeg.
   - The OpenCV backend produced poor compression efficiency for Atlas uploads.
   - Result: a 128.2 MB source video only dropped to 100.4 MB, which was far above the intended upload target.

2. Changed the optimizer policy to prefer ffmpeg when it is available.
   - Added `gemini.optimize_video_prefer_ffmpeg: true`
   - Raised the default and account-level upload target from `4.0 MB` to `15.0 MB`
   - Raised inline retry targets to `[15.0, 10.0, 8.0, 6.0]`

3. Verified the fix against the real downloaded canary video.
   - source: `outputs/danatimer_canary_v2/video_690fa58ca756e2f28c63b274.mp4`
   - before fix path: `128.2 MB -> 100.4 MB`
   - after ffmpeg-preferred path: `128.2 MB -> 13.3 MB`

4. Closed the policy-gate ambiguity during dry runs.
   - `src/solver/orchestrator.py` now records `repair_skipped_reason`
   - `src/solver/legacy_impl.py` now logs a human-readable reason when policy auto-repair did not run
   - Most important case:
     - `execute=false (dry-run); policy auto-repair only runs during the execute/apply pass`

5. Added a live monitoring helper for future canaries.
   - `run_canary_live_monitor.ps1`
   - This runs the solver in unbuffered mode and tees live output into a timestamped canary log.

Validation completed for this pass:

- `python -m py_compile src\infra\solver_config.py src\solver\video_core.py src\solver\legacy_impl.py src\solver\orchestrator.py tests\test_v2_hardening_foundation.py`
- `python -m pytest -q tests\test_v2_hardening_foundation.py -k "default_flags or dry_run_skip_reason or prefers_ffmpeg or registered_session or heartbeat or transport_classifier"`
  - `9 passed`
- `python -m pytest -q tests\test_refactored_module_sources.py -k "no_reserved or reserve or goto_task_room"`
  - `4 passed`
## 2026-04-14 - Live hardening continuation

- Confirmed the v2 Gemini runtime bug was caused by writing Gemini storage state from the Atlas bootstrap context. Patched `legacy_impl.py` and `episode_runtime.py` so Gemini can use a separate CDP browser on `9223`, reuse the dedicated Gemini chat context safely, and stop overwriting Gemini auth state with Atlas cookies.
- Confirmed the dedicated Gemini chat requirement is now respected in `gemini_session.py`: session init logs now show `clean_thread=False preserve_existing_thread=True` for the configured `https://gemini.google.com/app/b3006ba9f325b55c` chat.
- Added large-episode structural repair override in `segments.py` so split/delete repairs are not skipped on long episodes when the source DOM still contains overlong segments.
- Reduced silent extraction stalls in `segments.py` by:
  - making full-row `raw_text` fallback-only instead of unconditional
  - adding extraction progress heartbeats
  - lowering field-read timeout pressure for the canary config
- Investigated Gemini upload failures live against the current UI. Root cause: the current Gemini `+` button opens a menu first; the old flow incorrectly waited for `filechooser` on the menu trigger itself. Patched `atlas_triplet_compare.py` so the local upload path now uses `click +` -> `click Upload files` -> `filechooser`.
- Verified the upload patch with a direct live probe on the dedicated Gemini chat using the real chunk file `video_690fab618fca3b86e988eaa1_chatchunk_01.mp4`. Result:
  - `attached=True`
  - `mode=file_chooser`
  - settle confirmation detected from the current UI tokens (`MP4 (Google Drive)`, `Remove file ...`)

## Update after live validation instrumentation pass

Completed in this pass:

1. Wired a real `ValidationTracker` path into the production flow.
   - new file: `src/solver/live_validation.py`
   - `legacy_impl.run(...)` now creates an episode tracker when:
     - `run.live_validation_enabled=true`
     - or `run.structured_episode_reports=true`

2. Tracked overlong repair effectiveness inside `src/solver/orchestrator.py`
   - targeted repair rounds now record:
     - overlong indices before/after
     - planned split ops
     - applied/failed structural counts
     - stagnant/no-op/error outcomes
   - full reset regenerate is also recorded as a repair checkpoint

3. Tracked submit/guard outcomes inside `src/solver/segments.py`
   - `apply_labels(...)` now records:
     - final pre-submit snapshot
     - submit-guard blocked outcome
     - post-submit verification outcome when submit is attempted

4. Linked live validation into the episode report path
   - `src/solver/reliability.py` now exposes `live_validation_report_path`
   - `legacy_impl._finalize_current_episode_v2(...)` now saves:
     - `outputs/live_validation/validation_<episode>_<timestamp>.json`
     - and embeds the path into the structured episode report

5. Added focused regression coverage
   - new file: `tests/test_live_validation.py`
   - covers:
     - tracker forwarding from policy gate
     - repair checkpoint recording
     - submit guard recording
     - final live-validation report persistence

Validation completed in this pass:

- `python -m py_compile src/solver/live_validation.py src/solver/orchestrator.py src/solver/segments.py src/solver/legacy_impl.py tests/test_live_validation.py`
- `python -m pytest -q tests/test_live_validation.py`
  - `4 passed`
- `python -m pytest -q tests/test_v2_hardening_foundation.py -k "default_flags or emit_episode_report or finalize_current_episode_v2"`
  - `3 passed`
- `python -m pytest -q tests/test_hetzner_scheduler.py -k "submit_verification_delegates_to_segments_submit_status or persist_submit_outcome_records_unverified_reason_and_debug_artifacts"`
  - `2 passed`

Remaining next action:

1. Run one fresh live canary with `structured_episode_reports=true` (or `live_validation_enabled=true`) and confirm that:
   - the new `outputs/live_validation/*.json` report is emitted
   - repair checkpoints reflect the real DOM-grounded overlong transitions
   - submit verification evidence matches the final Atlas page state
