# Temporary Test Notes

This file is temporary for your validation run and should be deleted after you confirm the issue is solved.

## What was changed
- Integrated deterministic submit gate into batch flow (`submit_gate.py` + `atlas_triplet_batch.py`).
- Added automatic repair loop on validator failures (`atlas_repair_loop.py` used by batch).
- Enforced fail-closed single-episode run (`run_single_episode_4way.sh` exits non-zero when `quality_pass=false`).
- Enforced strict defaults in batch and production scripts.
- Switched production dashboard build to `atlas_dashboard_v2.py`.
- Added one-command runners:
  - `run_one_command.sh`
  - `deploy_update_and_run.sh`
- Strengthened validator:
  - max words per label = 20
  - disallow standalone `pick` as a starting verb (require `pick up`)

## One command to run now
```bash
bash run_one_command.sh
```

Single episode:
```bash
EPISODE_ID=<episode_id> bash run_one_command.sh
```

## What to check after run
- `outputs/triplet_compare_results.jsonl` has `quality_pass=true`.
- `outputs/manual_queue.jsonl` does not include your tested episode.
- `outputs/triplet_compare/triplet_compare_<episode>.json` exists.
- `outputs/atlas_dashboard.html` updated.

## Delete this file after success
```bash
rm -f TEMP_CHANGES_FOR_TEST.md
```
