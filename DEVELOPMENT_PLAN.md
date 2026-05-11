# OCR Annotation Atlas - Development Plan

## Update Applied: 2026-05-11

### Policy Changes (Per Discord Level-3 Announcement)

1. **Max Segment Duration: 10s -> 20s**
   - All segments must not exceed 20 seconds
   - Sweet spot remains 2-5 seconds
   - Segments over 20s must be split

2. **Dense Labels Required (Not Just Preferred)**
   - Always use Dense labels over Coarse labels
   - Dense = greater granularity and accuracy
   - Coarse = too broad, may miss important actions
   - When in doubt, use Dense labels

3. **Max 2 Actions Per Segment** (unchanged)
   - Already enforced by policy gate

### Code Changes Applied

| File | Change |
|------|--------|
| `src/infra/solver_config.py:168` | Default `max_segment_duration_sec`: 10.0 -> 20.0 |
| `src/rules/policy_gate.py:34` | Default `max_segment_duration_sec`: 10.0 -> 20.0 |
| `src/rules/policy_gate.py:173-216` | DOM-grounded duration check: DESYNC now downgrades to warning instead of blocking error when DOM is within limits |
| `src/solver/prompting.py:89-91` | Prompt: "never exceed 10.0 seconds" -> "never exceed 20.0 seconds" |
| `src/solver/prompting.py:98-100` | Prompt: "Prefer dense" -> "ALWAYS use DENSE labels over coarse" |
| `src/solver/prompting.py:154` | Prompt: "coarse single-goal" -> "specific Dense label" |
| `src/solver/legacy_impl.py:3397-3398` | Prompt: "Use coarse single-goal" -> "Use DENSE labels" |
| `src/solver/legacy_impl.py:3460` | Prompt: "coarse single-goal" -> "specific Dense label" |
| `src/solver/segments.py:660,665,670,1136` | Default duration fallbacks: 10.0 -> 20.0 |
| `src/solver/gemini.py:1801` | Default `max_segment_duration_sec`: 10.0 -> 20.0 |
| `src/solver/orchestrator.py:589` | Default `max_segment_duration_sec`: 10.0 -> 20.0 |
| `src/solver/pre_submit_compare.py:874` | Default `max_segment_duration_sec`: 10.0 -> 20.0 |
| `src/solver/complex_test_harness.py:379` | Default `max_segment_duration_sec`: 10.0 -> 20.0 |
| `src/policy/context_manager.py:62` | `max_segment_seconds`: 10.0 -> 20.0 |
| `src/policy/context_manager.py:84-97` | Added `dense_label_required: True` and density instruction |
| `src/policy/context_manager.py:96` | Policy: "never exceed 10 seconds" -> "never exceed 20 seconds" |
| 5 YAML config files | `max_segment_duration_sec: 10.0` -> `20.0` |
| `data/gemini_policy_v1.txt` | Updated max duration to 20s, added Dense label rule |
| `data/gemini_policy_discord_live.txt` | Updated all 10s references to 20s, added Dense label requirement |
| `data/policy/generated_prompt_summary.txt` | Updated max duration to 20s, added Dense label note |

### Critical Behavioral Change: DESYNC Handling

**Before:** When Gemini plan says duration > 10s but DOM shows duration <= 10s, the error was BLOCKING (the episode would fail).

**After:** When Gemini plan says duration > 20s but DOM shows duration <= 20s, the error is DOWNGRADED to a WARNING (the episode can continue). Only when DOM confirms the segment is truly overlong (> 20s) does it remain a blocking error.

This prevents false rejections caused by Gemini hallucinating timestamps.

---

## Server Migration

- Old server: decommissioned
- New server: `178.105.100.92` (root/CRgtPiVwWxkV3uRrbxnU)
- GitHub: https://github.com/aymank2020/OCR_Atlas_annotation_project.git

## Remaining TODO (Future Priority)

### High Priority
1. Push to GitHub (blocked by large git history - needs shallow clone or filter)
2. Update server deployment config for new IP
3. Verify production_hetzner.yaml has correct server settings

### Medium Priority
4. Refactor `legacy_impl.py` (8000+ lines God Object) into modular units
5. Eliminate `import_module()` circular imports in `orchestrator.py` and `segments.py`
6. Define dataclasses for Segment, Label, PolicyResult to replace `Dict[str, Any]`
7. Remove global mutable state (`_ACTIVE_HEARTBEAT_CALLBACK`, `_GEMINI_REQUEST_TIMESTAMPS`, etc.)

### Low Priority
8. Extract magic numbers into named constants
9. Add exception hierarchy (DesyncError, PolicyViolationError, etc.)
10. Unify documentation language