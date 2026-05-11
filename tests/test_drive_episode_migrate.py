from atlas_drive_episode_migrate import (
    build_episode_target,
    normalize_remote_listing_entry,
    plan_remote_migration,
    should_migrate_remote_path,
)


def test_should_migrate_remote_path_only_matches_flat_episode_files():
    assert should_migrate_remote_path("labels_690ae115b37a848b0dbe6fdf.json")
    assert should_migrate_remote_path("video_690ae115b37a848b0dbe6fdf.mp4")
    assert not should_migrate_remote_path("episodes/690ae115b37a848b0dbe6fdf/video_690ae115b37a848b0dbe6fdf.mp4")
    assert not should_migrate_remote_path("training_feedback/runs/file.json")
    assert not should_migrate_remote_path("atlas_os_dashboard.html")


def test_build_episode_target_uses_full_episode_id_folder():
    assert (
        build_episode_target("segments_690ae115b37a848b0dbe6fdf.json")
        == "episodes/690ae115b37a848b0dbe6fdf/segments_690ae115b37a848b0dbe6fdf.json"
    )


def test_plan_remote_migration_groups_flat_files_and_skips_nested_entries():
    plan = plan_remote_migration(
        [
            "segments_690ae115b37a848b0dbe6fdf.json",
            "task_state_690ae115b37a848b0dbe6fdf.json",
            "episodes/690ae115b37a848b0dbe6fdf/video_690ae115b37a848b0dbe6fdf.mp4",
            "atlas_os_dashboard.html",
        ]
    )
    assert [item["source"] for item in plan] == [
        "segments_690ae115b37a848b0dbe6fdf.json",
        "task_state_690ae115b37a848b0dbe6fdf.json",
    ]


def test_normalize_remote_listing_entry_strips_account_prefix():
    assert (
        normalize_remote_listing_entry(
            "OCR_annotation_Atlas/vps_outputs/danatimer/labels_690ae115b37a848b0dbe6fdf.json",
            "danatimer",
        )
        == "labels_690ae115b37a848b0dbe6fdf.json"
    )
