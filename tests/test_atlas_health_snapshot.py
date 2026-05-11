from pathlib import Path

import atlas_health_snapshot as health
import atlas_prometheus_snapshot as prom


def test_account_batch_summary_filters_disabled_accounts() -> None:
    payload = {
        "scheduler": {
            "mode": "sequential",
            "max_parallel_accounts": 1,
            "cooldown_between_accounts_sec": 45,
            "tasks_per_account_per_turn": 5,
        },
        "accounts": [
            {"name": "a1", "config": "configs/accounts/a1.yaml", "enabled": True},
            {"name": "a2", "config": "configs/accounts/a2.yaml", "enabled": False},
            {"name": "a3", "config": "configs/accounts/a3.yaml"},
        ],
    }

    summary = health._account_batch_summary(payload)

    assert summary["mode"] == "sequential"
    assert summary["tasks_per_account_per_turn"] == 5
    assert summary["enabled_account_count"] == 2
    assert [item["name"] for item in summary["enabled_accounts"]] == ["a1", "a3"]


def test_build_health_snapshot_writes_summary(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    outputs = app_dir / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "solver_service.log").write_text("ok", encoding="utf-8")
    (outputs / "episodes_review_index.json").write_text("{}", encoding="utf-8")

    index_path = app_dir / "configs" / "accounts" / "index.yaml"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(
        """
scheduler:
  mode: sequential
  max_parallel_accounts: 1
  cooldown_between_accounts_sec: 45
  tasks_per_account_per_turn: 5
accounts:
  - name: danatimer
    config: configs/accounts/danatimer.yaml
    enabled: true
""".strip(),
        encoding="utf-8",
    )
    out_path = outputs / "health_snapshot.json"

    snapshot = health.build_health_snapshot(app_dir=app_dir, index_path=index_path, output_path=out_path)

    assert out_path.exists()
    assert snapshot["account_batch"]["enabled_account_count"] == 1
    assert "solver=" in snapshot["summary_line"]


def test_account_batch_summary_accepts_episodes_per_turn_alias() -> None:
    payload = {
        "scheduler": {
            "mode": "sequential",
            "max_parallel_accounts": 1,
            "cooldown_between_accounts_sec": 45,
            "episodes_per_account_per_turn": 5,
        },
        "accounts": [{"name": "a1", "config": "configs/accounts/a1.yaml", "enabled": True}],
    }

    summary = health._account_batch_summary(payload)

    assert summary["tasks_per_account_per_turn"] == 5


def test_render_prometheus_metrics_contains_scheduler_and_output_metrics(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    outputs = app_dir / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "solver_service.log").write_text("ok", encoding="utf-8")

    index_path = app_dir / "configs" / "accounts" / "index.yaml"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(
        """
scheduler:
  mode: sequential
  max_parallel_accounts: 1
  cooldown_between_accounts_sec: 45
  tasks_per_account_per_turn: 5
accounts:
  - name: danatimer
    config: configs/accounts/danatimer.yaml
    enabled: true
""".strip(),
        encoding="utf-8",
    )
    snapshot = health.build_health_snapshot(app_dir=app_dir, index_path=index_path)
    metrics = prom.render_prometheus_metrics(snapshot)

    assert "atlas_scheduler_enabled_accounts 1" in metrics
    assert 'atlas_output_exists{artifact="solver_log"} 1' in metrics
