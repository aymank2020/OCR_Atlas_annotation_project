# Atlas V2 Hardening Guide

Saved on: 2026-04-13  
Workspace: `E:\OCR_annotation_Atlas`

## Purpose

This guide documents the current hardening state of the Atlas solver, the new `v2`
foundation modules, the exact canary flags to use, and the baseline screenshots to
compare against if Atlas or Gemini changes their UI.

This file is the operational handoff for continuing the redesign in phases without
losing context.

## Current Phase Status

### Completed in Phase 1

- DOM/source snapshot checking is centralized through `src/solver/desync.py`
- chat transport retries now exist in `src/solver/chat_only.py`
- hallucinated/duplicate explicit segment indices are rejected in `chat_only.py`
- pure video helpers moved into `src/solver/video_core.py`
- the `video.py ↔ legacy_impl.py` circular import is fixed
- foundational `EpisodeRuntime` and `GeminiSession` modules now exist for the `v2` path

### Completed in Phase 2 Canary Integration

- `EpisodeRuntime` is now wired into the real `legacy_impl.run(...)` loop for Atlas-only isolation
- the bootstrap room page is preserved while isolated episode pages run in fresh contexts
- structured per-episode JSON reports are emitted when `run.structured_episode_reports=true`

### Completed in Phase 3 Gemini Session Bridge

- `chat_only.py` now has a real `GeminiSession` execution path behind the `v2` canary flags
- labels generation, structural planning, and repair queries can all reuse the same Gemini session for one episode
- `legacy_impl.py` refreshes `gemini.chat_web_storage_state` from the bootstrap CDP context before episode isolation
- `EpisodeRuntime` now opens a per-episode Gemini context/page when strict single-session mode is enabled
- structured episode reports now include Gemini session/request metadata when available

### Completed in Phase 4 Staged Retry Hardening

- targeted repair on the v2 session path now uses `GeminiSession.repair_failed_segments(...)`
- retry metadata now propagates through `labels_payload["_meta"]` and task-state persistence
- overlong repair now escalates to one `full_reset_regenerate` pass after targeted rounds fail
- the current regression baseline for the hardening slices is now `69 passed`

### Not yet completed

- global rollout of the Atlas-isolated `v2` path beyond canary flags
- live canary validation on production Chrome/CDP with screenshots refreshed after the new Gemini path
- full orchestration-level three-stage retry controller as the default policy flow

## New Modules

- `src/solver/video_core.py`
  Pure video/file helpers. Keep this module dependency-light.

- `src/solver/desync.py`
  Builds `SegmentSnapshot`, computes checksums, and decides whether drift is blocking.

- `src/solver/reliability.py`
  Retry stage/reason taxonomy and per-episode report primitives.

- `src/solver/episode_runtime.py`
  Episode-scoped Atlas/Gemini context container for the v2 path.

- `src/solver/gemini_session.py`
  Single-session Gemini manager foundation plus response integrity validation.

## Canary Flags

Use these in a canary config first. Do not enable everything globally before replay and
limited production validation.

```yaml
run:
  use_episode_runtime_v2: true
  strict_single_chat_session: true
  force_episode_browser_isolation: true
  gemini_transport_max_retries: 3
  targeted_repair_max_rounds: 2
  structured_episode_reports: true
  desync_snapshot_tolerance_sec: 0.25
```

## Validation Commands

```powershell
python -m py_compile src\solver\video_core.py src\solver\video.py src\solver\desync.py src\solver\reliability.py src\solver\episode_runtime.py src\solver\gemini_session.py src\rules\consistency.py src\solver\segments.py src\solver\chat_only.py src\solver\legacy_impl.py
```

```powershell
$env:PYTHONPATH='.'
python -m pytest -q tests\test_v2_hardening_foundation.py tests\test_refactored_module_sources.py tests\test_chat_only_solver.py tests\test_segments_structural_ops.py tests\test_submit_gate.py
```

```powershell
python -c "from src.solver import legacy_impl, video, video_core, segments, chat_only, gemini_session, desync, reliability; print('imports-ok')"
```

## Baseline Screenshots

These screenshots already exist in the repository outputs and should be treated as the
known baseline when the company changes selectors, layout, upload controls, or Gemini UI.

### Architecture

![Architecture Overview](../outputs/report_assets/architecture_overview.png)

![Episode Flow](../outputs/report_assets/episode_flow.png)

### Gemini / Drive Picker Baseline

- `../outputs/drive_root_probe_20260405_v2/01_start.png`
- `../outputs/drive_root_probe_20260405_v2/02_menu.png`
- `../outputs/drive_root_probe_20260405_v2/03_picker_open.png`
- `../outputs/drive_root_probe_20260405_v2/04_after_search.png`
- `../outputs/drive_root_probe_20260405_v2/05_folder_opened.png`

### Failure / Debug Baseline

- `../outputs/danatimer/debug_episode_failure_20260405_010020.png`
- `../outputs/danatimer/debug_episode_failure_20260405_011340.png`
- `../outputs/danatimer/debug_episode_failure_20260405_020451.png`
- `../outputs/danatimer/debug_episode_failure_20260405_021311.png`

### Chat Compare Baseline

- `../outputs/debug_chat_compare_live/page_0.png`
- `../outputs/debug_chat_compare_live/page_1.png`
- `../outputs/debug_chat_compare_live/page_2.png`
- `../outputs/debug_chat_compare_live/page_3.png`
- `../outputs/debug_chat_compare_live/page_4.png`

No fresh screenshots were captured during the Phase 3 code-wiring pass because that pass
stopped at local validation and test coverage. Capture new live screenshots on the first
real canary run after enabling the new Gemini session path.

## April 14 Canary Findings

The first real `v2` canary on `config_account_danatimer_canary_v2.yaml` produced two
important live findings:

1. Atlas room workflow drift is real.
   - `/tasks/room/normal` can show room-disabled/unavailable text.
   - `/tasks` can still contain active reserved episodes with working `Label` links.
   - The browser fallback was updated so `goto_task_room()` now prefers direct `/tasks`
     label links after room-disabled recovery.

2. The old silent Gemini watchdog death is fixed.
   - The registered-session `v2` path now emits heartbeats while waiting in:
     - file attach / upload settle
     - Gemini response streaming
     - seed/primer waits
   - Live canary no longer ended with a silent `os._exit(1)`.

### New live baseline artifacts

- `../outputs/danatimer_canary_v2/manual_baseline_20260414_065851/01_room_state.html`
- `../outputs/danatimer_canary_v2/manual_baseline_20260414_065851/01_room_state.txt`
- `../outputs/danatimer_canary_v2/manual_baseline_20260414_065851/02_tasks_root.html`
- `../outputs/danatimer_canary_v2/manual_baseline_20260414_065851/02_tasks_root.txt`
- `../outputs/danatimer_canary_v2/manual_baseline_20260414_065851/03_room_state_windows_capture.png`
- `../outputs/danatimer_canary_v2/manual_baseline_20260414_065851/04_tasks_root_windows_capture.png`

### Gemini live probes captured during the canary

- `../outputs/danatimer_canary_v2/live_probe_20260414/gemini_ctx0_page0_1776151255.png`
- `../outputs/danatimer_canary_v2/live_probe_20260414/gemini_ctx0_page0_1776151255.txt`
- `../outputs/danatimer_canary_v2/live_probe_20260414_b/gemini_ctx0_page0_1776151578.png`
- `../outputs/danatimer_canary_v2/live_probe_20260414_b/gemini_ctx0_page0_1776151578.txt`

These probes changed the diagnosis:

- Gemini was not blank in the second probe.
- The thread still had:
  - a visible `MP4 (Google Drive)` chip
  - partial JSON already rendered in the response
  - `Thinking` still active

This means the current remaining `chat_web` risk is no longer silent death.
It is long response streaming / partial JSON completion inside one thread.

### Additional hardening added after the live probes

- `Gemini chat input not visible on session page` is now treated as a transport/session failure
  so the registered `GeminiSession` path restarts cleanly instead of surfacing only as an
  integrity error.
- `_wait_for_new_chat_response_text(...)` now:
  - returns as soon as valid JSON is already parseable
  - returns the current response after a stall window if the stream has visibly started but is
    not finishing
- `python -u atlas_web_auto_solver.py ...` is now preferred for canary runs so v2 session
  traces flush immediately into the log file.

### Live canary logs for this audit

- `../outputs/danatimer_canary_v2/canary_live_20260414_081829.log`
- `../outputs/danatimer_canary_v2/canary_live_20260414_084841.log`
- `../outputs/danatimer_canary_v2/canary_live_20260414_093409.log`

### Current validation status

- Live canary proved:
  - `/tasks` fallback works after room-disabled recovery
  - Atlas/Gemini episode runtime creation works
  - heartbeat propagation removed the old watchdog-kill behavior
  - live Gemini probes are being captured successfully
- Final live validation of the new partial-JSON/stall fix is still pending because the latest
  rerun had no available `Label` task at that moment.

### Additional Atlas `/tasks` reserve hardening

Atlas can now present a usable work state directly on `/tasks` without any pre-opened episode:

- page card shows `No Episodes Reserved`
- page body shows `Reserve a batch of episodes`
- main CTA shows `Reserve 3 Episodes` or another batch-size variant

This is not a terminal `no task` condition.
It is now treated as an actionable reserve state.

The solver now does the following:

1. detect this page state from body text and reserve CTA visibility
2. click the reserve CTA immediately instead of logging `no label task available`
3. confirm the reserve dialog
4. refresh back into the task workflow
5. open the first available `Label` link

Implementation notes:

- `src/solver/browser.py`
  - `_room_has_no_reserved_episodes(...)` now recognizes the updated `/tasks` reserve card language
  - `_click_reserve_button_dynamic(...)` now targets `Reserve 3 Episodes` and related batch-size variants
  - the JS fallback now dispatches a click event if the frontend ignores a plain element click
- `src/solver/legacy_impl.py`
  - logs `no reserved episodes or label task available right now` when the run really stopped in this state

Focused validation for this hardening:

- `python -m py_compile src\solver\browser.py src\solver\legacy_impl.py tests\test_refactored_module_sources.py`
- `python -m pytest -q tests\test_refactored_module_sources.py -k "no_reserved or reserve or goto_task_room"`
  - `4 passed`

### Upload video quality hardening

The upload optimizer now prefers `ffmpeg` over OpenCV when both are available.

Why this changed:

- On this Windows workstation, OpenCV was available and got selected first.
- The OpenCV backend reduced size poorly for Atlas videos.
- Real canary evidence showed:
  - source video: `128.2 MB`
  - OpenCV-preferred result: `100.4 MB`
  - ffmpeg-preferred result: `13.3 MB`

Configuration changes applied for `danatimer` canaries:

- `gemini.optimize_video_target_mb: 15.0`
- `gemini.optimize_video_prefer_ffmpeg: true`
- `gemini.inline_retry_target_mb: [15.0, 10.0, 8.0, 6.0]`

What this improves:

- keeps more visual detail than the earlier `4 MB` target
- reduces upload latency sharply compared with the broken OpenCV-preferred path
- gets closer to the known-good historical behavior you expected

### Why dry-run can still stop at policy gate

The overlong auto-repair path is execute-only by design:

- `src/solver/orchestrator.py::_maybe_repair_overlong_segments(...)`

If a run is started with `dry_run: true` and without `--execute`, the solver will now log the exact reason:

- `execute=false (dry-run); policy auto-repair only runs during the execute/apply pass`

This means a dry-run can still show:

- `policy gate blocked apply for this episode`

without proving that the repair architecture failed.
It only proves that the live Atlas repair/apply phase was not entered yet.

### Live monitoring helper

Use the new helper to watch future canaries live while also saving a timestamped log:

```powershell
.\run_canary_live_monitor.ps1
.\run_canary_live_monitor.ps1 -Execute
```

The helper:

1. runs `python -u atlas_web_auto_solver.py ...`
2. streams live output in the console
3. saves the full session to `outputs/danatimer_canary_v2/canary_live_<timestamp>.log`

## What To Capture If Atlas Changes

Turn these on in the config for one canary episode:

```yaml
run:
  capture_step_screenshots: true
  capture_step_screenshots_full_page: true
  capture_step_html: true
```

Then capture at least these checkpoints:

1. room page before reserve
2. episode page immediately after open
3. segment list before extraction
4. segment list after any split/merge action
5. Gemini composer before file attach
6. Gemini file picker / upload menu
7. final review state before submit
8. post-submit state or failure modal

## If The Company Changes The UI

Follow this order:

1. Reproduce the issue on one episode only.
2. Enable screenshot and HTML capture.
3. Compare the new images against the baseline paths above.
4. Check whether selectors changed in Atlas, Gemini, or both.
5. Re-run `extract_segments()` manually and compare checksum before and after the UI action.
6. If submit blocks, inspect:
   - `src/rules/consistency.py`
   - `src/solver/desync.py`
   - `src/solver/segments.py`
7. If Gemini behavior changed, inspect:
   - `src/solver/chat_only.py`
   - `src/solver/gemini_session.py`
   - `atlas_triplet_compare.py`
8. Update this guide with the new screenshot paths and the selector delta.

## Phase 2 Queue

1. Run a live canary episode with:
   - `use_episode_runtime_v2=true`
   - `strict_single_chat_session=true`
   - `force_episode_browser_isolation=true`
2. Capture fresh screenshots if Atlas or Gemini UI changed after the last baseline.
3. Promote the new Gemini session path only after replay/canary evidence is clean.
4. Finish the last mile of orchestration reporting with:
   - `episode_id`
   - `context_id`
   - `request_id`
   - `segment_checksum`
   - `retry_stage`
   - `retry_reason`
   - `desync_detected`
   - `submit_blocked`
   - `failure_class`
## 2026-04-14 live findings

- Gemini must not share Atlas bootstrap storage state. The v2 runtime now supports a separate Gemini CDP connection and can reuse the dedicated Gemini chat context from `http://127.0.0.1:9223`.
- The dedicated chat requirement for this account is:
  - account: `aymankamel24@gmail.com`
  - chat: `https://gemini.google.com/app/b3006ba9f325b55c`
- For this account/canary, Gemini is now configured to:
  - preserve the dedicated thread
  - avoid clean-thread fallback
  - use local file upload instead of Drive-first upload for chunked videos
- Current Gemini upload UI behavior:
  - the `+` button opens a menu
  - `Upload files` is the actionable local-upload menu item
  - waiting for `filechooser` on the `+` button itself is incorrect on the current UI
- Current Atlas extraction behavior on large `83`-segment pages:
  - progress heartbeats are now emitted during extraction
  - if extraction appears stalled, check for `[trace] extract_segments progress: ...` before assuming a hang
