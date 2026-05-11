import json

from atlas_os_dashboard import build_dashboard_payload, render_dashboard_html, write_dashboard


def test_atlas_os_dashboard_generates_required_sections(tmp_path):
    policy_root = tmp_path / "policy"
    discord_dir = tmp_path / "discord"
    outputs_dir = tmp_path / "outputs"
    output_path = tmp_path / "atlas_os_dashboard.html"
    review_index_path = outputs_dir / "episodes_review_index.json"

    policy_root.mkdir(parents=True, exist_ok=True)
    outputs_dir.mkdir(parents=True, exist_ok=True)
    (discord_dir / "atlas-announcements" / "sample_run").mkdir(parents=True, exist_ok=True)
    (discord_dir / "atlas-announcements" / "sample_run" / "atlas-announcements_page_1.json").write_text("[]", encoding="utf-8")

    current_policy = {
        "policy_version": "atlas-discord-cra-v2",
        "generated_at": "2026-04-03T00:00:00+00:00",
        "effective_at": "2026-04-03T00:00:00+00:00",
        "authority_mode": "trusted_auto",
        "runtime": {"universal_rules": ["Use canonical policy values.", "Keep labels atomic and bounded."]},
        "sources": [
            {
                "rule_id": "r1",
                "timestamp": "2026-04-03T00:00:00+00:00",
                "channel": "#LEVEL3_ANNOUNCEMENT",
                "author": "sentientcake",
                "trust_tier": "trusted_auto",
                "field_path": "annotation.max_atomic_actions",
                "value": 2,
            }
        ],
    }
    staged_row = {
        "rule_id": "r1",
        "message_id": "m1",
        "timestamp": "2026-04-03T00:00:00+00:00",
        "channel": "#LEVEL3_ANNOUNCEMENT",
        "author": "sentientcake",
        "trust_tier": "trusted_auto",
        "scope": "global",
        "field_path": "annotation.max_atomic_actions",
        "value": 2,
        "value_type": "integer",
        "confidence": 0.98,
        "summary": "Limit each segment to 2 atomic actions",
        "raw_text": "Going forward, each segment is limited to a maximum of two atomic actions.",
        "status": "promoted",
    }
    trust_config = {
        "trusted_channels": ["#LEVEL3_ANNOUNCEMENT", "#ATLAS_ANNOUNCEMENT"],
        "trusted_authors": ["sentientcake"],
    }
    policy_diff = {
        "policy_version": "atlas-discord-cra-v2",
        "generated_at": "2026-04-03T00:40:00+00:00",
        "changed_fields": ["annotation.max_atomic_actions"],
        "promoted_rule_ids": ["r1"],
    }

    (policy_root / "current_policy.json").write_text(json.dumps(current_policy), encoding="utf-8")
    (policy_root / "staged_rules.jsonl").write_text(json.dumps(staged_row) + "\n", encoding="utf-8")
    (policy_root / "trust_config.json").write_text(json.dumps(trust_config), encoding="utf-8")
    (policy_root / "policy_diff.json").write_text(json.dumps(policy_diff), encoding="utf-8")
    (policy_root / "generated_prompt_summary.txt").write_text(
        "Canonical policy version: atlas-discord-cra-v2\n- Maximum atomic actions per label: 2.",
        encoding="utf-8",
    )
    bundle_dir = outputs_dir / "live_episode_bundles" / "690acbb2188e6e5c5b7b3be5"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    old_solution = bundle_dir / "text_690acbb2188e6e5c5b7b3be5_current.txt"
    new_solution = bundle_dir / "text_690acbb2188e6e5c5b7b3be5_update.txt"
    validation_path = bundle_dir / "validation_690acbb2188e6e5c5b7b3be5.json"
    video_path = bundle_dir / "video_690acbb2188e6e5c5b7b3be5.mp4"
    old_solution.write_text("1\t0.0\t2.0\tpick up white t-shirt from sofa\n2\t2.0\t5.0\tplace white t-shirt on board\n", encoding="utf-8")
    new_solution.write_text("1\t0.0\t2.0\tpick up white t-shirt from sofa\n2\t2.0\t5.0\tplace white t-shirt on mat\n", encoding="utf-8")
    validation_path.write_text(
        json.dumps({"ok": False, "errors": ["segment 2: object mismatch"], "warnings": [], "segment_count": 2}),
        encoding="utf-8",
    )
    video_path.write_bytes(b"00")
    review_index = {
        "generated_at": "2026-04-03T00:45:00+00:00",
        "total": 1,
        "status_counts": {"policy_fail": 1},
        "episodes": [
            {
                "episode_id": "690acbb2188e6e5c5b7b3be5",
                "task_url": "https://audit.atlascapture.io/tasks/room/normal/label/690acbb2188e6e5c5b7b3be5",
                "review_status": "policy_fail",
                "video_path": str(video_path),
                "tier2_text_path": str(old_solution),
                "tier3_text_path": str(new_solution),
                "tier2_text": old_solution.read_text(encoding="utf-8"),
                "tier3_text": new_solution.read_text(encoding="utf-8"),
                "validation_path": str(validation_path),
                "validation": {"ok": False, "errors": ["segment 2: object mismatch"], "warnings": [], "segment_count": 2},
                "task_state": {"labels_ready": True, "video_ready": True, "last_error": ""},
            }
        ],
    }
    review_index_path.write_text(json.dumps(review_index), encoding="utf-8")
    (outputs_dir / "discord_bot_status.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-04-03T00:50:00Z",
                "command_channel_id": 1485540323584118877,
                "target_channel_ids": [1458584003605954717],
                "ready_at": "2026-04-03T00:10:00Z",
                "last_event": "history_export_ok",
                "last_command": "status!",
                "last_sync_at": "2026-04-03T00:12:00Z",
                "last_history_export_at": "2026-04-03T00:15:00Z",
                "buffer_count": 0,
            }
        ),
        encoding="utf-8",
    )
    training_live = outputs_dir / "training_feedback" / "live"
    training_run = outputs_dir / "training_feedback" / "runs" / "training_feedback_20260403_005329"
    training_live.mkdir(parents=True, exist_ok=True)
    training_run.mkdir(parents=True, exist_ok=True)
    (training_live / "last_run_summary.json").write_text(
        json.dumps(
            {
                "training_dir": str(training_run),
                "status": "ok",
                "generated_at": "2026-04-03T00:57:23",
            }
        ),
        encoding="utf-8",
    )
    (training_run / "INDEX.json").write_text(
        json.dumps(
            {
                "episodes_collected": 3,
                "feedback_entries_found": 6,
                "gemini_status": "ok",
                "generated_at": "2026-04-03T00:57:23",
            }
        ),
        encoding="utf-8",
    )

    payload = build_dashboard_payload(policy_root=policy_root, discord_dir=discord_dir, outputs_dir=outputs_dir, review_index_path=review_index_path)
    assert payload["rule_authority"]["master_version"] == "atlas-discord-cra-v2"
    assert payload["rule_authority"]["sync"]["synced_count"] >= 1
    assert payload["token_economy"]["labels"]
    assert payload["episodes"]["featured"]["episode_id"] == "690acbb2188e6e5c5b7b3be5"
    assert payload["episodes"]["featured"]["changed_count"] == 1
    assert payload["discord_ops"]["bot"]["state"] == "history_export_ok"
    assert payload["discord_ops"]["feedback"]["episodes_collected"] == 3

    html = render_dashboard_html(payload)
    assert "Rule Authority Status" in html
    assert "Discord Operations" in html
    assert "Episode Intelligence" in html
    assert "Token Economy Monitor" in html
    assert "The Staging Area" in html
    assert "Rule Retrieval Map" in html
    assert "Atlas OS" in html

    written = write_dashboard(
        output_path=output_path,
        policy_root=policy_root,
        discord_dir=discord_dir,
        outputs_dir=outputs_dir,
        review_index_path=review_index_path,
    )
    assert written.exists()
    assert "Centralized Rule Authority" in written.read_text(encoding="utf-8")
