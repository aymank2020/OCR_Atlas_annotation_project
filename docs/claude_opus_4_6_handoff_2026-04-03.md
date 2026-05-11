# Claude Opus 4.6 Handoff Report

Date: 2026-04-03  
Workspace: `E:\OCR_annotation_Atlas`  
Repo: `aymank2020/OCR_Annotation_Atlas`  
Remote `main` base currently at local `HEAD`: `da32db3`  
Status note: this report includes **new local stage-2 refactor changes that are tested but not yet committed/pushed**, because they are pending discussion first.

## 1. What This Project Is

`Atlas Capture` is a sovereign automation/annotation system centered on:
- automated browser operation against Atlas task rooms
- policy-aware label correction with Gemini
- Discord-driven rule harvesting and policy consolidation
- local/offline-safe artifacts for resumability and auditability
- hardened Colab packaging for zero-budget cloud execution
- a newer real-time speech/transcription sub-system (`atlas_scribe`) for low-latency voice workflows

The project is no longer just a single solver script. It is now a broader operational stack with:
- annotation automation
- policy/rules infrastructure
- streaming voice experimentation
- packaging/deployment utilities
- internal dashboards and operational reports

## 2. High-Level Current Architecture

### Core solver path
- CLI entry/shim: `atlas_web_auto_solver.py`
- legacy orchestration body: `src/solver/legacy_impl.py`
- extracted packages:
  - `src/infra`
  - `src/solver`
  - `src/rules`

### Policy/rules path
- runtime policy retrieval: `src/policy/context_manager.py`
- validator logic: `validator.py`
- local policy files:
  - `data/policy/current_policy.json`
  - `data/policy/staged_rules.jsonl`
  - `prompts/golden_rules.md`
  - `data/gemini_policy_v1.txt`
  - `data/gemini_policy_discord_live.txt`

### Voice/streaming path
- `atlas_scribe.py`
- `atlas_scribe_dashboard.py`
- `atlas_scribe_realtime_api.py`
- `atlas_realtime_ws_clients.py`
- `atlas_scribe_realtime_demo.html`

### Packaging / Colab path
- `package_for_colab.py`
- `Atlas_Colab_Runner.ipynb`
- `configs/production_colab.yaml`
- local artifact: `Atlas_Project_Colab.zip`

## 3. Major Completed Work Before This Stage

These were already implemented before the current local stage-2 refactor batch:

### A. Atlas OS dashboard work
- Added Python-generated single-file dashboard output for operational visibility.
- Main files:
  - `atlas_os_dashboard.py`
  - `prompts/atlas_os_dashboard_prompt.md`
  - `tests/test_atlas_os_dashboard.py`
  - generated HTML in `outputs/atlas_os_dashboard.html`

### B. Discord rule sync and policy merge
- Harvested local Discord archive data for the target date window when direct Discord API access failed.
- Extracted candidate rules, matched them against current policy, promoted trusted rules, and staged untrusted ones.
- Produced sync reports and updated policy corpus.

### C. Real-time voice latency upgrade
- Implemented micro-chunk streaming, interim/final transcript handling, ghost-writing UI behavior, local VAD/fallback VAD, and WebSocket-ready provider abstraction.
- Added FastAPI browser bridge and demo page.
- Deepgram-ready provider path exists, with local fallback preserved.

### D. Hardened audit + Colab packaging
- Hardened watchdog behavior.
- Reduced Colab package from a large full-archive style bundle to a minimal clean runtime package.
- Excluded heavy/sensitive runtime folders and secrets from the ZIP.
- Added manifest generation and packaging tests.

### E. Stage-1 solver refactor
- Created package structure:
  - `src/infra`
  - `src/solver`
  - `src/rules`
- Preserved `atlas_web_auto_solver.py` as a compatibility shim.
- Added `configs/production_colab.yaml`.
- Updated `Atlas_Colab_Runner.ipynb` to sync against `origin/main`.
- Merged that stage to GitHub `main`.

## 4. What Was Implemented In The New Local Stage-2 Batch

This is the part currently awaiting discussion/approval before I commit and push it.

### 4.1 Real execution logic moved out of the monolith

Previously, the new package files were mostly wrappers over `src/solver/legacy_impl.py`.

Now, real implementations live in these files:

#### `src/infra/runtime.py`
- shutdown event
- signal handler registration
- heartbeat sleep helper for long waits/backoff

#### `src/infra/solver_config.py`
- `_load_selectors_yaml`
- `_deep_merge`
- `_cfg_get`
- `_resolve_secret`
- `_apply_global_gemini_video_policy`
- `_apply_global_run_policy`
- `load_config`

This module now contains real config behavior rather than only re-exporting from the monolith.

#### `src/rules/labels.py`
- label rewrite and normalization
- gripper/tool-term normalization
- no-action helpers
- verb-start policy helpers
- autofix heuristics
- continuity-merge heuristics
- no-action pause rewrite
- numeral-to-word rewrite
- mechanical-motion-to-goal rewrite
- Tier-3 label rewrite pipeline
- minimum-safety normalization

#### `src/rules/policy_gate.py`
- full lexical/timestamp policy gate logic
- validation report saving
- timestamp/no-action error classifiers

#### `src/solver/prompting.py`
- prompt construction
- optional system-instruction file loading
- chunk consistency memory helpers
- chunk consistency prompt hint
- lazy proxy only for `_request_labels_with_optional_segment_chunking` because the orchestration-heavy chunk/request flow still lives in the monolith

### 4.2 `legacy_impl` now uses extracted modules

I did not only create new implementations. I also changed `src/solver/legacy_impl.py` so that:
- runtime globals are bound to `src.infra.runtime`
- prompt helpers are rebound to `src.solver.prompting`
- rule/policy helpers are rebound to `src.rules.labels` and `src.rules.policy_gate`

This means the monolith is no longer the sole runtime source of truth for those helper areas.

### 4.3 New verification assets

Added:
- `tests/test_refactored_module_sources.py`
- `docs/solver_refactor_stage2_map.md`

The new test verifies:
- legacy runtime aliases point to the extracted runtime module
- legacy prompt/rule/policy helper names point to extracted modules
- `configs/production_colab.yaml` still loads successfully through `src.infra.solver_config.load_config`

## 5. Current File Inventory For Refactor Discussion

### Compatibility layer
- `atlas_web_auto_solver.py`

### Extracted infra
- `src/infra/runtime.py`
- `src/infra/solver_config.py`
- `src/infra/browser_auth.py`
- `src/infra/artifacts.py`

### Extracted rules
- `src/rules/labels.py`
- `src/rules/policy_gate.py`

### Extracted solver helpers
- `src/solver/prompting.py`
- `src/solver/browser.py`
- `src/solver/video.py`
- `src/solver/gemini.py`
- `src/solver/segments.py`
- `src/solver/orchestrator.py`
- `src/solver/cli.py`

### Legacy body still carrying heavy execution flow
- `src/solver/legacy_impl.py`

## 6. Test / Verification Status

### Current local stage-2 results
- targeted compatibility tests after deeper extraction: `41 passed`
- full project test suite: `174 passed, 1 skipped`

### Known warning still present
- `src/purify/knowledge_builder.py` still emits a deprecation warning for `google.generativeai`
- this is not a current test failure, but it is a migration item

## 7. Colab Packaging Status

Local package rebuilt after the stage-2 changes:
- `Atlas_Project_Colab.zip`
- size now about `9.68 MB`

Why the ZIP is small:
- it is now a clean runtime package, not a full archive of local data/state/cache/videos
- heavy or sensitive local artifacts are intentionally excluded

Colab runner expectations now:
- notebook: `Atlas_Colab_Runner.ipynb`
- config: `configs/production_colab.yaml`
- sync target: `origin/main`

## 8. Design Intent Behind The Refactor

The decomposition strategy is intentionally staged:

### Already extracted first
- pure or low-risk helpers
- policy/rule logic
- prompt construction
- runtime/config behavior

### Deliberately postponed
- Playwright-heavy browser actions
- Gemini upload/retry/network orchestration
- timestamp clicking / row editing UI logic
- top-level `run()` orchestration

Reason:
- those parts are the highest risk for behavioral regression
- extracting pure functions first creates stable seams and tests
- later batches can move orchestration using the new seams safely

## 9. What Still Remains In The Monolith

These are the main remaining chunks in `src/solver/legacy_impl.py`:
- Playwright navigation and resilience helpers
- task reservation/release loops
- segment row resolution and editing
- video discovery/download/split/reencode
- Gemini upload/request/retry/quota handling
- task artifact persistence glue
- final high-level `run()` control flow

## 10. Recommended Next Extraction Batches

If Claude agrees with the current direction, the next safest sequence is:

1. Move segment normalization/application flow into `src/solver/segments.py`
2. Move artifact persistence and resume helpers into `src/infra/artifacts.py`
3. Move Gemini request/upload parsing and quota helpers into `src/solver/gemini.py`
4. Move browser row/action helpers into `src/solver/browser.py`
5. Extract `run()` orchestration last into `src/solver/orchestrator.py`

## 11. Architecture Questions For Claude Opus 4.6

Please review and respond on these points:

1. Is the current staged extraction strategy sound, or should we switch to a more aggressive split sooner?
2. Should `DEFAULT_CONFIG` remain in the monolith temporarily, or is it worth fully relocating next?
3. Would you recommend introducing dataclasses or typed config objects now, or postpone until after the heavy extraction batches?
4. Is the current “legacy name rebinding” approach acceptable as a transition pattern, or should we replace it with thin wrappers immediately?
5. Which next batch is safest to extract after rules/prompting/runtime:
   - segments
   - artifacts
   - gemini
   - browser
6. Do you see hidden circular-dependency or ownership risks in the current package boundaries?
7. Should the project adopt stronger architectural boundaries now, such as:
   - `infra` never importing `solver`
   - `rules` staying fully UI/network agnostic
   - `solver` split into `domain`, `ui`, `providers`, `workflow`

## 12. Current Local Diff Summary

These are the local not-yet-pushed files for the stage-2 batch:
- `src/infra/runtime.py`
- `src/infra/solver_config.py`
- `src/rules/labels.py`
- `src/rules/policy_gate.py`
- `src/solver/prompting.py`
- `src/solver/legacy_impl.py`
- `tests/test_refactored_module_sources.py`
- `docs/solver_refactor_stage2_map.md`

## 13. Suggested Claude Prompt Framing

Use Claude as a senior refactor reviewer with this exact focus:
- validate the staged decomposition strategy
- inspect whether the new module ownership is correct
- identify hidden regression risks in rebinding monolith names to extracted modules
- suggest the best next extraction order
- comment on whether to keep the transition shim/rebind approach or replace it with explicit wrappers
- review if Colab compatibility and CLI compatibility are still properly protected by the current structure

## 14. Bottom-Line Summary

The project is in a materially better state than the original 10k-line single-file shape:
- public compatibility is preserved
- Colab flow is cleaner
- packaging is hardened
- rules/prompting/runtime now have real modular implementations
- tests are green

The key question for Claude is no longer “does the project need refactoring?”  
It is now: “is this staged extraction boundary the right one, and what is the safest next batch?”
