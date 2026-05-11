from pathlib import Path

import atlas_production_monitor as monitor


def test_detect_log_markers_finds_multiple_known_patterns() -> None:
    text = "\n".join(
        [
            "chat_compare_missing_video_attachment",
            "[run] policy gate blocked apply for this episode.",
            "Error: write EPIPE",
        ]
    )

    codes = monitor._detect_log_markers(text)

    assert "chat_attachment_missing" in codes
    assert "policy_gate_blocked" in codes
    assert "playwright_epipe" in codes


def test_detect_log_markers_ignores_keyboardinterrupt_traceback() -> None:
    text = "\n".join(
        [
            "Traceback (most recent call last):",
            '  File "/srv/atlas/OCR_annotation_Atlas/atlas_multi_account_runner.py", line 7, in <module>',
            "KeyboardInterrupt",
        ]
    )

    codes = monitor._detect_log_markers(text)

    assert "traceback" not in codes


def test_detect_log_markers_keeps_non_keyboard_traceback() -> None:
    text = "\n".join(
        [
            "Traceback (most recent call last):",
            '  File "/srv/atlas/OCR_annotation_Atlas/atlas_multi_account_runner.py", line 7, in <module>',
            "RuntimeError: boom",
        ]
    )

    codes = monitor._detect_log_markers(text)

    assert "traceback" in codes


def test_find_submit_lag_candidates_flags_missing_review_episode(tmp_path: Path) -> None:
    old = tmp_path / "outputs" / "danatimer" / "task_state_abc123abc123abc123abc123.json"
    old.parent.mkdir(parents=True)
    old.write_text('{"episode_submitted": true}', encoding="utf-8")

    review_ids = {"otherepisodeid000000000000"}
    result = monitor._find_submit_lag_candidates(
        [old],
        review_ids,
        now_epoch=old.stat().st_mtime + 7200,
        min_age_sec=1800,
    )

    assert len(result) == 1
    assert result[0]["episode_id"] == "abc123abc123abc123abc123"
    assert result[0]["account"] == "danatimer"


def test_find_submit_lag_candidates_skips_reviewed_episode(tmp_path: Path) -> None:
    old = tmp_path / "outputs" / "wafaabayoumi" / "task_state_def456def456def456def456.json"
    old.parent.mkdir(parents=True)
    old.write_text('{"episode_submitted": true}', encoding="utf-8")

    result = monitor._find_submit_lag_candidates(
        [old],
        {"def456def456def456def456"},
        now_epoch=old.stat().st_mtime + 7200,
        min_age_sec=1800,
    )

    assert result == []


def test_find_submit_lag_candidates_marks_root_outputs_as_unknown_account(tmp_path: Path) -> None:
    old = tmp_path / "outputs" / "task_state_ghi789ghi789ghi789ghi789.json"
    old.parent.mkdir(parents=True)
    old.write_text('{"episode_submitted": true}', encoding="utf-8")

    result = monitor._find_submit_lag_candidates(
        [old],
        set(),
        now_epoch=old.stat().st_mtime + 7200,
        min_age_sec=1800,
    )

    assert len(result) == 1
    assert result[0]["account"] == "unknown"


def test_monitor_ignores_stale_feedback_error_summary(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    (outputs / "training_feedback" / "live").mkdir(parents=True)
    summary_path = outputs / "training_feedback" / "live" / "last_run_summary.json"
    summary_path.write_text('{"status":"error"}', encoding="utf-8")
    stale_ts = summary_path.stat().st_mtime - 9000
    summary_path.touch()
    import os
    os.utime(summary_path, (stale_ts, stale_ts))

    (outputs / "solver_service.log").write_text("", encoding="utf-8")
    (outputs / "episodes_review_index.json").write_text('{"episodes":[]}', encoding="utf-8")

    result = monitor.build_monitor_snapshot(
        app_dir=tmp_path,
        index_path=tmp_path / "missing-index.yaml",
        output_path=outputs / "monitor.json",
        state_path=outputs / "monitor_state.json",
    )

    assert "feedback_collector_error" not in result["issue_codes"]
