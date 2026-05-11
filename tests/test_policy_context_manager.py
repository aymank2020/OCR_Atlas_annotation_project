import json

import atlas_claude_smart_ai2 as claude_mod
import prompts
from src.policy import context_manager as policy_context


def test_ambiguous_trusted_rule_stays_staged(tmp_path):
    policy_root = tmp_path / "policy"
    report = policy_context.ingest_message_entries(
        [
            {
                "id": "2001",
                "content": "The max segment duration is changing soon, more details later.",
                "author": {"username": "sentientcake"},
                "timestamp": "2026-04-02T10:00:00+00:00",
                "channel": "#LEVEL3_ANNOUNCEMENT",
            }
        ],
        policy_root=policy_root,
    )

    policy = policy_context.load_current_policy(policy_root / "current_policy.json")
    staged_rows = (policy_root / "staged_rules.jsonl").read_text(encoding="utf-8")
    assert report["changed_fields"] == []
    assert policy_context.get_policy("engine_limits.max_segment_seconds", policy=policy) == 10.0
    assert '"decision_reason": "not_exact_enough"' in staged_rows


def test_non_policy_noise_does_not_mutate_canonical_policy(tmp_path):
    policy_root = tmp_path / "policy"
    report = policy_context.ingest_message_entries(
        [
            {
                "id": "2002",
                "content": "Security alert: never share your phone number with scammers.",
                "author": {"username": "community_member"},
                "timestamp": "2026-04-02T11:00:00+00:00",
                "channel": "#LEVEL3_ANNOUNCEMENT",
            }
        ],
        policy_root=policy_root,
    )

    policy = policy_context.load_current_policy(policy_root / "current_policy.json")
    assert report["candidate_count"] == 0
    assert report["changed_fields"] == []
    assert policy_context.get_policy("engine_limits.max_segment_seconds", policy=policy) == 10.0


def test_conflicting_exact_updates_resolve_by_newest_active_rule(tmp_path):
    policy_root = tmp_path / "policy"
    staged_path = policy_root / "staged_rules.jsonl"
    policy_context.ensure_policy_files(policy_root)
    staged_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "rule_id": "old",
                        "message_id": "1",
                        "timestamp": "2026-03-01T00:00:00+00:00",
                        "channel": "#LEVEL3_ANNOUNCEMENT",
                        "author": "sentientcake",
                        "trust_tier": "trusted_auto",
                        "scope": "engine",
                        "field_path": "engine_limits.max_segment_seconds",
                        "value": 60.0,
                        "value_type": "number",
                        "confidence": 0.99,
                        "summary": "Old duration",
                        "raw_text": "max segment duration is 60 seconds",
                        "status": "promoted",
                    }
                ),
                json.dumps(
                    {
                        "rule_id": "new",
                        "message_id": "2",
                        "timestamp": "2026-03-27T19:27:28+00:00",
                        "channel": "#LEVEL3_ANNOUNCEMENT",
                        "author": "sentientcake",
                        "trust_tier": "trusted_auto",
                        "scope": "engine",
                        "field_path": "engine_limits.max_segment_seconds",
                        "value": 10.0,
                        "value_type": "number",
                        "confidence": 0.99,
                        "summary": "New duration",
                        "raw_text": "max segment duration is 10 seconds",
                        "status": "promoted",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = policy_context.rebuild_current_policy(
        current_policy_path=policy_root / "current_policy.json",
        staged_rules_path=staged_path,
    )
    policy = policy_context.load_current_policy(policy_root / "current_policy.json")

    assert policy_context.get_policy("engine_limits.max_segment_seconds", policy=policy) == 10.0
    assert report["promoted_rule_ids"][-1] == "new"


def test_expired_promoted_rule_falls_back_to_previous_active_value(tmp_path):
    policy_root = tmp_path / "policy"
    staged_path = policy_root / "staged_rules.jsonl"
    policy_context.ensure_policy_files(policy_root)
    staged_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "rule_id": "baseline",
                        "message_id": "1",
                        "timestamp": "2026-03-01T00:00:00+00:00",
                        "channel": "#LEVEL3_ANNOUNCEMENT",
                        "author": "sentientcake",
                        "trust_tier": "trusted_auto",
                        "scope": "engine",
                        "field_path": "engine_limits.max_segment_seconds",
                        "value": 10.0,
                        "value_type": "number",
                        "confidence": 0.99,
                        "summary": "Baseline duration",
                        "raw_text": "max segment duration is 10 seconds",
                        "status": "promoted",
                    }
                ),
                json.dumps(
                    {
                        "rule_id": "temporary",
                        "message_id": "2",
                        "timestamp": "2026-03-15T00:00:00+00:00",
                        "channel": "#LEVEL3_ANNOUNCEMENT",
                        "author": "sentientcake",
                        "trust_tier": "trusted_auto",
                        "scope": "engine",
                        "field_path": "engine_limits.max_segment_seconds",
                        "value": 30.0,
                        "value_type": "number",
                        "confidence": 0.99,
                        "summary": "Temporary duration",
                        "raw_text": "max segment duration is 30 seconds",
                        "status": "promoted",
                        "expires_at": "2000-01-01T00:00:00+00:00",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    policy_context.rebuild_current_policy(
        current_policy_path=policy_root / "current_policy.json",
        staged_rules_path=staged_path,
    )
    policy = policy_context.load_current_policy(policy_root / "current_policy.json")
    staged_rows = staged_path.read_text(encoding="utf-8")

    assert policy_context.get_policy("engine_limits.max_segment_seconds", policy=policy) == 10.0
    assert '"inactive_reason": "expired"' in staged_rows
    assert '"active": false' in staged_rows


def test_future_expiry_rule_remains_active_until_expiry(tmp_path):
    policy_root = tmp_path / "policy"
    staged_path = policy_root / "staged_rules.jsonl"
    policy_context.ensure_policy_files(policy_root)
    staged_path.write_text(
        json.dumps(
            {
                "rule_id": "future",
                "message_id": "3001",
                "timestamp": "2026-04-02T12:00:00+00:00",
                "channel": "#LEVEL3_ANNOUNCEMENT",
                "author": "sentientcake",
                "trust_tier": "trusted_auto",
                "scope": "engine",
                "field_path": "engine_limits.max_segment_seconds",
                "value": 15.0,
                "value_type": "number",
                "confidence": 0.99,
                "summary": "Future-limited duration",
                "raw_text": "The max segment duration is now: 15 seconds",
                "status": "promoted",
                "expires_at": "2999-01-01T00:00:00+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    report = policy_context.rebuild_current_policy(
        current_policy_path=policy_root / "current_policy.json",
        staged_rules_path=staged_path,
    )

    policy = policy_context.load_current_policy(policy_root / "current_policy.json")
    staged_rows = (policy_root / "staged_rules.jsonl").read_text(encoding="utf-8")
    assert policy_context.get_policy("engine_limits.max_segment_seconds", policy=policy) == 15.0
    assert report["promoted_rule_ids"]
    assert '"active": true' in staged_rows


def test_runtime_consumers_follow_current_policy():
    policy = policy_context.load_current_policy()
    expected_max_segment = float(policy_context.get_policy("engine_limits.max_segment_seconds", 10.0, policy=policy))

    prompts.refresh_policy_assets()
    claude_mod.refresh_policy_constraints()

    assert claude_mod.MAX_SEGMENT_SECONDS == expected_max_segment
    assert f"MAXIMUM {expected_max_segment:.0f} seconds per segment" in prompts.get_video_annotation_prompt()


def test_retrieve_runtime_rules_is_bounded_and_relevant(tmp_path):
    policy_root = tmp_path / "policy"
    policy_context.ensure_policy_files(policy_root)

    staged_rule = {
        "rule_id": "r1",
        "message_id": "1",
        "timestamp": "2026-04-02T12:00:00+00:00",
        "channel": "#LEVEL3_ANNOUNCEMENT",
        "author": "sentientcake",
        "trust_tier": "trusted_auto",
        "scope": "engine",
        "field_path": "engine_limits.max_segment_seconds",
        "value": 10.0,
        "value_type": "number",
        "confidence": 0.99,
        "summary": "Set max segment duration to 10 seconds",
        "raw_text": "The max segment duration is now 10 seconds.",
        "status": "promoted",
        "expires_at": "2999-01-01T00:00:00+00:00",
    }
    lesson = {
        "category": "timestamp_policy",
        "question": "How long can a segment be?",
        "answer": "Keep segments short and inside the exact assigned window.",
    }
    lesson_path = tmp_path / "policy_lessons.jsonl"
    lesson_path.write_text(json.dumps(lesson) + "\n", encoding="utf-8")
    staged_path = policy_root / "staged_rules.jsonl"
    staged_path.write_text(json.dumps(staged_rule) + "\n", encoding="utf-8")

    context = policy_context.retrieve_runtime_rules(
        [{"label": "place item on table", "raw_text": "segment timing check"}],
        trigger="validator_error",
        budget={"rules": 2, "examples": 0},
        current_policy_path=policy_root / "current_policy.json",
        staged_rules_path=staged_path,
        lessons_path=lesson_path,
        golden_path=tmp_path / "missing.jsonl",
    )

    assert "CANONICAL AUDIT RULES" in context
    assert "10 seconds" in context
    assert "exact assigned window" in context


def test_retrieve_runtime_rules_excludes_expired_rule(tmp_path):
    policy_root = tmp_path / "policy"
    policy_context.ensure_policy_files(policy_root)
    staged_path = policy_root / "staged_rules.jsonl"
    staged_path.write_text(
        json.dumps(
            {
                "rule_id": "expired",
                "message_id": "99",
                "timestamp": "2026-04-02T12:00:00+00:00",
                "channel": "#LEVEL3_ANNOUNCEMENT",
                "author": "sentientcake",
                "trust_tier": "trusted_auto",
                "scope": "engine",
                "field_path": "engine_limits.max_segment_seconds",
                "value": 25.0,
                "value_type": "number",
                "confidence": 0.99,
                "summary": "Temporary 25-second limit",
                "raw_text": "temporary rule for segment timing",
                "status": "promoted",
                "expires_at": "2000-01-01T00:00:00+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    context = policy_context.retrieve_runtime_rules(
        [{"label": "segment timing review"}],
        trigger="validator_error",
        budget={"rules": 2, "examples": 0},
        current_policy_path=policy_root / "current_policy.json",
        staged_rules_path=staged_path,
        lessons_path=tmp_path / "missing_lessons.jsonl",
        golden_path=tmp_path / "missing_golden.jsonl",
    )

    assert "Temporary 25-second limit" not in context
