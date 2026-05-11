"""Generate a lightweight production-readiness snapshot for Atlas services."""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List

import yaml


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _read_yaml_object(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return payload if isinstance(payload, dict) else {}


def _account_batch_summary(index_payload: Dict[str, Any]) -> Dict[str, Any]:
    scheduler = index_payload.get("scheduler") if isinstance(index_payload, dict) else {}
    scheduler = scheduler if isinstance(scheduler, dict) else {}
    accounts = index_payload.get("accounts") if isinstance(index_payload, dict) else []
    accounts = accounts if isinstance(accounts, list) else []

    enabled_accounts: List[Dict[str, Any]] = []
    for item in accounts:
        if not isinstance(item, dict):
            continue
        if item.get("enabled", True) is False:
            continue
        enabled_accounts.append(
            {
                "name": str(item.get("name", "")).strip(),
                "config": str(item.get("config", "")).strip(),
            }
        )

    return {
        "mode": str(scheduler.get("mode", "unknown")).strip() or "unknown",
        "max_parallel_accounts": _safe_int(scheduler.get("max_parallel_accounts", 0), 0),
        "cooldown_between_accounts_sec": _safe_int(
            scheduler.get("cooldown_between_accounts_sec", 0), 0
        ),
        "tasks_per_account_per_turn": _safe_int(
            scheduler.get(
                "tasks_per_account_per_turn",
                scheduler.get("episodes_per_account_per_turn", 0),
            ),
            0,
        ),
        "enabled_account_count": len(enabled_accounts),
        "enabled_accounts": enabled_accounts,
    }


def _file_snapshot(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False}
    stat = path.stat()
    return {
        "path": str(path),
        "exists": True,
        "size_bytes": int(stat.st_size),
        "mtime_epoch": int(stat.st_mtime),
        "age_sec": max(0, int(time.time() - stat.st_mtime)),
    }


def _service_state(service_name: str) -> Dict[str, Any]:
    if platform.system().lower() != "linux":
        return {"name": service_name, "supported": False}
    try:
        active = subprocess.run(
            ["systemctl", "is-active", service_name],
            check=False,
            capture_output=True,
            text=True,
        )
        enabled = subprocess.run(
            ["systemctl", "is-enabled", service_name],
            check=False,
            capture_output=True,
            text=True,
        )
        return {
            "name": service_name,
            "supported": True,
            "active": (active.stdout or "").strip() or "unknown",
            "enabled": (enabled.stdout or "").strip() or "unknown",
        }
    except Exception as exc:
        return {"name": service_name, "supported": True, "error": str(exc)}


def _health_summary(snapshot: Dict[str, Any]) -> str:
    batch = snapshot.get("account_batch", {}) if isinstance(snapshot, dict) else {}
    services = snapshot.get("services", []) if isinstance(snapshot, dict) else []
    outputs = snapshot.get("outputs", {}) if isinstance(snapshot, dict) else {}
    enabled_count = _safe_int(batch.get("enabled_account_count", 0), 0)
    tasks_per_turn = _safe_int(batch.get("tasks_per_account_per_turn", 0), 0)
    cooldown = _safe_int(batch.get("cooldown_between_accounts_sec", 0), 0)
    solver_state = "unknown"
    for item in services:
        if isinstance(item, dict) and item.get("name") == "atlas-solver.service":
            solver_state = str(item.get("active", "unknown"))
            break
    solver_log = outputs.get("solver_log", {}) if isinstance(outputs, dict) else {}
    solver_age = solver_log.get("age_sec", "n/a")
    return (
        f"solver={solver_state} accounts={enabled_count} "
        f"tasks_per_turn={tasks_per_turn} cooldown={cooldown}s "
        f"solver_log_age={solver_age}"
    )


def build_health_snapshot(
    *,
    app_dir: Path,
    index_path: Path,
    output_path: Path | None = None,
) -> Dict[str, Any]:
    services = [
        "atlas-solver.service",
        "atlas-discord-bot.service",
        "atlas-solver-health.timer",
        "atlas-episode-review-refresh.timer",
        "atlas-drive-uploader.timer",
    ]
    snapshot = {
        "generated_at_epoch": int(time.time()),
        "app_dir": str(app_dir),
        "index_path": str(index_path),
        "account_batch": _account_batch_summary(_read_yaml_object(index_path)),
        "services": [_service_state(name) for name in services],
        "outputs": {
            "solver_log": _file_snapshot(app_dir / "outputs" / "solver_service.log"),
            "discord_log": _file_snapshot(app_dir / "outputs" / "discord_bot_service.log"),
            "review_index": _file_snapshot(app_dir / "outputs" / "episodes_review_index.json"),
            "dashboard": _file_snapshot(app_dir / "outputs" / "atlas_os_dashboard.html"),
        },
    }
    snapshot["summary_line"] = _health_summary(snapshot)
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description="Write a compact Atlas health snapshot")
    parser.add_argument("--app-dir", default=".", help="Atlas application root")
    parser.add_argument("--index", default="configs/accounts/index.yaml", help="Scheduler index YAML")
    parser.add_argument(
        "--output",
        default="outputs/health_snapshot.json",
        help="Where to write the JSON snapshot",
    )
    args = parser.parse_args()

    app_dir = Path(args.app_dir).resolve()
    index_path = Path(args.index)
    if not index_path.is_absolute():
        index_path = (app_dir / index_path).resolve()
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = (app_dir / output_path).resolve()

    snapshot = build_health_snapshot(app_dir=app_dir, index_path=index_path, output_path=output_path)
    print(snapshot["summary_line"])
    print(f"[health] snapshot: {output_path}")


__all__ = [
    "_safe_int",
    "_read_yaml_object",
    "_account_batch_summary",
    "_file_snapshot",
    "_service_state",
    "_health_summary",
    "build_health_snapshot",
    "main",
]
