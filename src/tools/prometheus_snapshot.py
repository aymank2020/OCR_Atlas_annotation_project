"""Export Atlas health snapshot data as Prometheus text exposition."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, Iterable, List

from src.tools.health_snapshot import build_health_snapshot


def _bool_metric(value: Any) -> int:
    if isinstance(value, bool):
        return 1 if value else 0
    text = str(value or "").strip().lower()
    return 1 if text in {"true", "yes", "enabled", "active"} else 0


def render_prometheus_metrics(snapshot: Dict[str, Any]) -> str:
    lines: List[str] = []
    batch = snapshot.get("account_batch", {}) if isinstance(snapshot, dict) else {}
    lines.append("# HELP atlas_scheduler_enabled_accounts Number of enabled scheduler accounts.")
    lines.append("# TYPE atlas_scheduler_enabled_accounts gauge")
    lines.append(f"atlas_scheduler_enabled_accounts {int(batch.get('enabled_account_count', 0) or 0)}")
    lines.append("# HELP atlas_scheduler_tasks_per_turn Tasks per account per turn.")
    lines.append("# TYPE atlas_scheduler_tasks_per_turn gauge")
    lines.append(f"atlas_scheduler_tasks_per_turn {int(batch.get('tasks_per_account_per_turn', 0) or 0)}")
    lines.append("# HELP atlas_scheduler_cooldown_seconds Cooldown between account turns in seconds.")
    lines.append("# TYPE atlas_scheduler_cooldown_seconds gauge")
    lines.append(
        f"atlas_scheduler_cooldown_seconds {int(batch.get('cooldown_between_accounts_sec', 0) or 0)}"
    )

    services = snapshot.get("services", []) if isinstance(snapshot, dict) else []
    lines.append("# HELP atlas_service_active Service active state (1 active, 0 otherwise).")
    lines.append("# TYPE atlas_service_active gauge")
    lines.append("# HELP atlas_service_enabled Service enabled state (1 enabled, 0 otherwise).")
    lines.append("# TYPE atlas_service_enabled gauge")
    for item in services:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        labels = f'{{service="{name}"}}'
        lines.append(f"atlas_service_active{labels} {_bool_metric(item.get('active') == 'active')}")
        lines.append(f"atlas_service_enabled{labels} {_bool_metric(item.get('enabled'))}")

    outputs = snapshot.get("outputs", {}) if isinstance(snapshot, dict) else {}
    lines.append("# HELP atlas_output_age_seconds Age of key output artifacts in seconds.")
    lines.append("# TYPE atlas_output_age_seconds gauge")
    lines.append("# HELP atlas_output_exists Whether the key output artifact exists.")
    lines.append("# TYPE atlas_output_exists gauge")
    for key, item in outputs.items():
        if not isinstance(item, dict):
            continue
        labels = f'{{artifact="{key}"}}'
        lines.append(f"atlas_output_exists{labels} {_bool_metric(item.get('exists'))}")
        lines.append(f"atlas_output_age_seconds{labels} {int(item.get('age_sec', 0) or 0)}")

    return "\n".join(lines) + "\n"


def write_prometheus_metrics(metrics_text: str, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(metrics_text, encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Write Atlas health metrics in Prometheus format")
    parser.add_argument("--app-dir", default=".", help="Atlas application root")
    parser.add_argument("--index", default="configs/accounts/index.yaml", help="Scheduler index YAML")
    parser.add_argument("--snapshot-output", default="outputs/health_snapshot.json")
    parser.add_argument("--metrics-output", default="outputs/health_snapshot.prom")
    args = parser.parse_args()

    app_dir = Path(args.app_dir).resolve()
    index_path = Path(args.index)
    if not index_path.is_absolute():
        index_path = (app_dir / index_path).resolve()
    snapshot_output = Path(args.snapshot_output)
    if not snapshot_output.is_absolute():
        snapshot_output = (app_dir / snapshot_output).resolve()
    metrics_output = Path(args.metrics_output)
    if not metrics_output.is_absolute():
        metrics_output = (app_dir / metrics_output).resolve()

    snapshot = build_health_snapshot(app_dir=app_dir, index_path=index_path, output_path=snapshot_output)
    metrics = render_prometheus_metrics(snapshot)
    write_prometheus_metrics(metrics, metrics_output)
    print(snapshot["summary_line"])
    print(f"[metrics] snapshot: {snapshot_output}")
    print(f"[metrics] prometheus: {metrics_output}")


__all__ = ["render_prometheus_metrics", "write_prometheus_metrics", "main"]
