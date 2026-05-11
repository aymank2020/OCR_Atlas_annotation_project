from pathlib import Path

from atlas_discord_bot import build_discord_runtime_snapshot, format_discord_status_message


def test_discord_runtime_snapshot_collects_rule_sync_feedback_and_review_counts(tmp_path):
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    (outputs_dir / "discord_rule_sync_report.json").write_text(
        '{"generated_at_utc":"2026-04-04T05:00:00Z","message_count":7,"channel_count":2,"policy_report":{"promoted_rule_ids":["r1","r2"],"candidate_count":1}}',
        encoding="utf-8",
    )
    training_live = outputs_dir / "training_feedback" / "live"
    training_run = outputs_dir / "training_feedback" / "runs" / "training_feedback_20260404_050000"
    training_live.mkdir(parents=True, exist_ok=True)
    training_run.mkdir(parents=True, exist_ok=True)
    (training_live / "last_run_summary.json").write_text(
        f'{{"training_dir":"{training_run.as_posix()}","status":"ok","generated_at":"2026-04-04T05:01:00"}}',
        encoding="utf-8",
    )
    (training_run / "INDEX.json").write_text(
        '{"episodes_collected":3,"feedback_entries_found":6,"generated_at":"2026-04-04T05:01:00"}',
        encoding="utf-8",
    )
    (outputs_dir / "episodes_review_index.json").write_text(
        '{"generated_at":"2026-04-04T05:02:00","total":4,"status_counts":{"submitted":2,"policy_fail":1}}',
        encoding="utf-8",
    )

    snapshot = build_discord_runtime_snapshot(
        outputs_dir=outputs_dir,
        command_channel_id=123,
        target_channel_ids=[456, 789],
        ready_at="2026-04-04T04:59:00Z",
        last_event="ready",
        last_command="status!",
        last_sync_at="2026-04-04T05:00:30Z",
        last_history_export_at="2026-04-04T05:00:40Z",
    )

    assert snapshot["rule_sync"]["promoted_count"] == 2
    assert snapshot["feedback"]["episodes_collected"] == 3
    assert snapshot["review_index"]["total"] == 4

    message = format_discord_status_message(snapshot)
    assert "Atlas Discord status" in message
    assert "rule_sync: messages=7 channels=2 promoted=2" in message
