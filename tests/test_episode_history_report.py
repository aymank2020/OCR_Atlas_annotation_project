from pathlib import Path

import atlas_episode_history_report as history


def test_build_episode_history_report_merges_local_and_remote_evidence(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    outputs = app_dir / "outputs"
    outputs.mkdir(parents=True)

    (outputs / "episodes_review_index.json").write_text(
        """
{
  "episodes": [
    {
      "episode_id": "68f40e7a3c67cee4a50a003d",
      "review_status": "labeled_not_submitted",
      "feedback_url": "https://audit.atlascapture.io/feedback/68f40e7a3c67cee4a50a003d"
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )
    (outputs / "task_state_68f40e7a3c67cee4a50a003d.json").write_text(
        '{"labels_ready": true, "episode_submitted": false, "has_error": false}',
        encoding="utf-8",
    )
    (outputs / "validation_68f40e7a3c67cee4a50a003d.json").write_text(
        '{"ok": false, "errors": ["segment 2: duration 24.8s exceeds max 10.0s"], "warnings": []}',
        encoding="utf-8",
    )

    compare_dir = outputs / "danatimer" / "pre_submit_compare" / "68f40e7a3c67cee4a50a003d"
    compare_dir.mkdir(parents=True)
    (compare_dir / "68f40e7a3c67cee4a50a003d_pre_submit_compare.json").write_text(
        """
{
  "decision": "chat_compare_missing_video_attachment",
  "block_apply": true,
  "block_reason": "Chat UI response did not confirm a successful video attachment."
}
""".strip(),
        encoding="utf-8",
    )

    memory_dir = outputs / "gemini_memory_sources"
    memory_dir.mkdir(parents=True)
    (memory_dir / "manual_feedback_snapshot.json").write_text(
        """
{
  "episodes": [
    {
      "episode_id": "68edeea3f0eef071291219ec",
      "quality_score": "100%",
      "feedback_url": "https://audit.atlascapture.io/feedback/68edeea3f0eef071291219ec",
      "notes": "Confirmed reviewed episode with 100% quality."
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )

    remote_summary = {
        "review_index": {
            "episodes": [
                {
                    "episode_id": "68f438c5c6fe72b3547be742",
                    "review_status": "labeled_not_submitted",
                    "feedback_url": "https://audit.atlascapture.io/feedback/68f438c5c6fe72b3547be742",
                }
            ]
        },
        "manual_feedback": {},
        "task_states": [
            {
                "episode_id": "68f438c5c6fe72b3547be742",
                "path": "/srv/atlas/OCR_annotation_Atlas/outputs/wafaabayoumi/task_state_68f438c5c6fe72b3547be742.json",
                "mtime_epoch": 1700000000,
                "payload": {"labels_ready": True, "episode_submitted": True},
            }
        ],
        "validations": [],
        "pre_submit_compares": [],
        "feedback_page_paths": [],
    }

    report = history.build_episode_history_report(
        app_dir=app_dir,
        remote_summary=remote_summary,
    )

    assert report["summary"]["total_episodes"] == 3
    by_id = {item["episode_id"]: item for item in report["episodes"]}

    blocked = by_id["68f40e7a3c67cee4a50a003d"]
    assert blocked["seen_local"] is True
    assert blocked["blocked"] is True
    assert "duration 24.8s exceeds max 10.0s" in blocked["blocked_reason"]
    assert blocked["latest_compare_decision"] == "chat_compare_missing_video_attachment"

    reviewed = by_id["68edeea3f0eef071291219ec"]
    assert reviewed["feedback_seen"] is True
    assert reviewed["reviewed_quality"] == "100%"

    remote = by_id["68f438c5c6fe72b3547be742"]
    assert remote["seen_server"] is True
    assert remote["submitted_local_evidence"] is True
    assert remote["accounts"] == ["wafaabayoumi"]


def test_summarize_outputs_tree_collects_feedback_page_snapshots(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs" / "gemini_memory_sources" / "atlas_feedback_pages"
    outputs.mkdir(parents=True)
    snapshot_path = outputs / "01_https_audit_atlascapture_io_feedback_68edeea3f0eef071291219ec.txt"
    snapshot_path.write_text("Loading feedback...", encoding="utf-8")

    summary = history._summarize_outputs_tree(tmp_path / "outputs")

    assert str(snapshot_path) in summary["feedback_page_paths"]
