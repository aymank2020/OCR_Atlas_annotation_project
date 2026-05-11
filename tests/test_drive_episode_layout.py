from __future__ import annotations

import os
from pathlib import Path

from atlas_drive_episode_layout import organize_episode_outputs, parse_age_to_seconds


def _make_old(path: Path, now_ts: float) -> None:
    old_ts = now_ts - 7200
    os.utime(path, (old_ts, old_ts))


def test_parse_age_to_seconds_supports_common_units():
    assert parse_age_to_seconds("45") == 45
    assert parse_age_to_seconds("30m") == 1800
    assert parse_age_to_seconds("2h") == 7200
    assert parse_age_to_seconds("1d") == 86400


def test_organize_episode_outputs_moves_old_files_into_per_episode_folder(tmp_path):
    now_ts = 2_000_000_000.0
    outputs_dir = tmp_path / "outputs"
    account_dir = outputs_dir / "danatimer"
    account_dir.mkdir(parents=True, exist_ok=True)
    episode_id = "690ae115b37a848b0dbe6fdf"

    labels_path = account_dir / f"labels_{episode_id}.json"
    labels_path.write_text("{}", encoding="utf-8")
    prompt_path = account_dir / f"prompt_{episode_id}.txt"
    prompt_path.write_text("prompt", encoding="utf-8")
    fresh_video = account_dir / f"video_{episode_id}.mp4"
    fresh_video.write_bytes(b"fresh")
    note_path = account_dir / "atlas_os_dashboard.html"
    note_path.write_text("dashboard", encoding="utf-8")

    _make_old(labels_path, now_ts)
    _make_old(prompt_path, now_ts)
    os.utime(fresh_video, (now_ts - 60, now_ts - 60))
    os.utime(note_path, (now_ts - 7200, now_ts - 7200))

    summary = organize_episode_outputs(outputs_dir, min_age_seconds=1800, now_ts=now_ts)

    assert summary["moved_files"] == 2
    assert (account_dir / "episodes" / episode_id / labels_path.name).exists()
    assert (account_dir / "episodes" / episode_id / prompt_path.name).exists()
    assert fresh_video.exists()
    assert note_path.exists()
    assert not labels_path.exists()
    assert not prompt_path.exists()


def test_organize_episode_outputs_skips_files_already_nested_or_bundle_dirs(tmp_path):
    now_ts = 2_000_000_000.0
    outputs_dir = tmp_path / "outputs"
    episode_id = "690ae115b37a848b0dbe6fdf"

    nested = outputs_dir / "danatimer" / "episodes" / episode_id / f"labels_{episode_id}.json"
    nested.parent.mkdir(parents=True, exist_ok=True)
    nested.write_text("{}", encoding="utf-8")
    _make_old(nested, now_ts)

    bundle = outputs_dir / "live_episode_bundles" / episode_id / f"prompt_{episode_id}.txt"
    bundle.parent.mkdir(parents=True, exist_ok=True)
    bundle.write_text("bundle", encoding="utf-8")
    _make_old(bundle, now_ts)

    summary = organize_episode_outputs(outputs_dir, min_age_seconds=1800, now_ts=now_ts)

    assert summary["moved_files"] == 0
    assert summary["skipped_nested"] >= 2
    assert nested.exists()
    assert bundle.exists()
