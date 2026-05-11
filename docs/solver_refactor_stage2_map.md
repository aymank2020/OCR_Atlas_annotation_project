# Solver Refactor Stage 2 Map

Date: 2026-04-03

## What Changed
- `src/solver/legacy_impl.py` is no longer the only source of truth for prompt/rule/runtime helpers.
- Real implementations now live in:
  - `src/infra/runtime.py`
  - `src/infra/solver_config.py`
  - `src/rules/labels.py`
  - `src/rules/policy_gate.py`
  - `src/solver/prompting.py`
- `legacy_impl` now rebinds moved helper names to these extracted modules so the existing orchestration flow keeps working without changing CLI or tests.

## Current Source Of Truth
- `src/infra/runtime.py`
  - graceful shutdown event
  - signal handlers
  - watchdog-friendly sleep heartbeat
- `src/infra/solver_config.py`
  - selector override loading
  - deep config merge
  - config path lookups
  - global Gemini/video safety defaults
  - global run defaults
  - `load_config()`
- `src/rules/labels.py`
  - Tier-3 rewrite logic
  - continuity merge heuristics
  - autofix helpers
  - no-action pause rewrites
  - verb/object attachment normalization
  - mechanical-motion to goal normalization
- `src/rules/policy_gate.py`
  - lexical/timestamp policy gate
  - validation report writer
  - policy error classifiers
- `src/solver/prompting.py`
  - prompt construction
  - optional system-instruction file loading
  - chunk consistency memory helpers

## Still In `legacy_impl`
- Playwright browser navigation/actions
- task room orchestration
- video preparation pipeline
- Gemini upload/request orchestration
- row editing and submit loops
- high-level `run()` control loop

## Why This Stage Matters
- Breaks the monolith at real execution boundaries instead of just adding wrappers.
- Makes rules/prompting/runtime independently testable.
- Reduces future risk when decomposing browser/video/Gemini flows.
- Preserves exact CLI compatibility through `atlas_web_auto_solver.py`.

## Safe Next Batches
1. Move segment normalization/apply helpers into `src/solver/segments.py` as the next pure-ish batch.
2. Move artifact persistence helpers into `src/infra/artifacts.py`.
3. Move Gemini upload/response parsing into `src/solver/gemini.py`.
4. Leave Playwright-heavy browser flow and `run()` orchestration for the last stage.
