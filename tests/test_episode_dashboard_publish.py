import json

from atlas_episode_dashboard_publish import _write_episode_comparison, _flatten_episode_ids


def test_write_episode_comparison_generates_manifest_and_csv(tmp_path):
    episode_id = "690acbb2188e6e5c5b7b3be5"
    bundle_dir = tmp_path / episode_id
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / f"text_{episode_id}_current.txt").write_text(
        "1\t0.0\t2.0\tpick up shirt\n2\t2.0\t5.0\tplace shirt on table\n",
        encoding="utf-8",
    )
    (bundle_dir / f"text_{episode_id}_update.txt").write_text(
        "1\t0.0\t2.0\tpick up shirt\n2\t2.0\t5.0\tplace shirt on mat\n",
        encoding="utf-8",
    )
    (bundle_dir / f"validation_{episode_id}.json").write_text(
        json.dumps({"ok": False, "errors": ["segment 2 changed"], "warnings": [], "segment_count": 2}),
        encoding="utf-8",
    )
    (bundle_dir / f"task_state_{episode_id}.json").write_text(
        json.dumps({"labels_ready": True, "last_error": ""}),
        encoding="utf-8",
    )

    outputs = _write_episode_comparison(bundle_dir, episode_id)

    manifest = json.loads(outputs["manifest"].read_text(encoding="utf-8"))
    csv_text = outputs["comparison_csv"].read_text(encoding="utf-8")
    assert manifest["changed_count"] == 1
    assert manifest["validation"]["ok"] is False
    assert "old_label,new_label,status" in csv_text
    assert outputs["comparison_json"].exists()


def test_flatten_episode_ids_preserves_order_and_deduplicates():
    assert _flatten_episode_ids(["a", " ", "b", "a", "", "c"]) == ["a", "b", "c"]
