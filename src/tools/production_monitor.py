"""Production monitor, alerting, and lightweight self-healing for Atlas services."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import requests

from src.tools.health_snapshot import build_health_snapshot


ISSUE_PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("chat_attachment_missing", "chat_compare_missing_video_attachment"),
    ("policy_gate_blocked", "[run] policy gate blocked apply for this episode."),
    ("playwright_epipe", "Error: write EPIPE"),
    ("target_closed", "TargetClosedError"),
    ("quota_exhausted", "RESOURCE_EXHAUSTED"),
    ("rooms_unavailable", "Rooms are unavailable"),
    ("traceback", "Traceback (most recent call last):"),
    ("solver_timeout", "[runner] timed out account="),
)


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _read_text_tail(path: Path, max_chars: int = 12000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="ignore")
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _has_non_keyboardinterrupt_traceback(text: str) -> bool:
    marker = "Traceback (most recent call last):"
    if marker not in text:
        return False
    for chunk in text.split(marker)[1:]:
        snippet = chunk[:2000]
        if "KeyboardInterrupt" in snippet:
            continue
        return True
    return False


def _detect_log_markers(text: str) -> List[str]:
    found: List[str] = []
    for code, marker in ISSUE_PATTERNS:
        if code == "traceback":
            if _has_non_keyboardinterrupt_traceback(text):
                found.append(code)
            continue
        if marker in text:
            found.append(code)
    return found


def _guess_account_from_path(path: Path) -> str:
    parts = [part.lower() for part in path.parts]
    if "outputs" in parts:
        idx = parts.index("outputs")
        if idx + 1 < len(parts):
            candidate = path.parts[idx + 1]
            if (
                idx + 2 < len(parts)
                and candidate not in {"training_feedback", "complex_test", "pre_submit_compare"}
            ):
                return candidate
    return "unknown"


def _review_index_episode_ids(review_index: Dict[str, Any]) -> set[str]:
    episodes = review_index.get("episodes", []) if isinstance(review_index, dict) else []
    out: set[str] = set()
    for item in episodes:
        if not isinstance(item, dict):
            continue
        eid = str(item.get("episode_id", "")).strip().lower()
        if eid:
            out.add(eid)
    return out


def _find_submit_lag_candidates(
    task_state_paths: Iterable[Path],
    review_episode_ids: set[str],
    *,
    now_epoch: float | None = None,
    min_age_sec: int = 1800,
) -> List[Dict[str, Any]]:
    now_epoch = float(now_epoch or time.time())
    candidates: List[Dict[str, Any]] = []
    for path in task_state_paths:
        payload = _load_json(path, {})
        if not isinstance(payload, dict):
            continue
        submitted = bool(payload.get("episode_submitted") or payload.get("submitted"))
        if not submitted:
            continue
        eid = path.stem.replace("task_state_", "").strip().lower()
        if not eid or eid in review_episode_ids:
            continue
        age_sec = max(0, int(now_epoch - path.stat().st_mtime))
        if age_sec < int(min_age_sec):
            continue
        candidates.append(
            {
                "episode_id": eid,
                "account": _guess_account_from_path(path),
                "task_state_path": str(path),
                "age_sec": age_sec,
            }
        )
    return sorted(candidates, key=lambda item: (-int(item["age_sec"]), item["episode_id"]))


def _service_active(snapshot: Dict[str, Any], name: str) -> str:
    for item in snapshot.get("services", []):
        if isinstance(item, dict) and item.get("name") == name:
            return str(item.get("active", "unknown"))
    return "unknown"


def _send_telegram_message(token: str, chat_id: int, text: str) -> bool:
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text[:4000],
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        return response.ok
    except Exception:
        return False


def _restart_solver(app_dir: Path) -> bool:
    import subprocess

    script = app_dir / "start_production_cycle.sh"
    if not script.exists():
        return False
    try:
        result = subprocess.run(
            ["bash", str(script)],
            cwd=str(app_dir),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def _build_issue_signature(issue_codes: List[str], submit_lag: List[Dict[str, Any]], feedback_status: str, solver_active: str) -> str:
    payload = {
        "issues": sorted(issue_codes),
        "submit_lag_ids": [item.get("episode_id", "") for item in submit_lag[:10]],
        "feedback_status": feedback_status,
        "solver_active": solver_active,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def build_monitor_snapshot(
    *,
    app_dir: Path,
    index_path: Path,
    output_path: Path | None = None,
    state_path: Path | None = None,
    submit_lag_min_age_sec: int = 1800,
    auto_restart_solver: bool = False,
) -> Dict[str, Any]:
    outputs_dir = app_dir / "outputs"
    snapshot = build_health_snapshot(app_dir=app_dir, index_path=index_path)
    solver_log_path = outputs_dir / "solver_service.log"
    log_tail = _read_text_tail(solver_log_path)
    issue_codes = _detect_log_markers(log_tail)

    feedback_summary_path = outputs_dir / "training_feedback" / "live" / "last_run_summary.json"
    feedback_summary = _load_json(feedback_summary_path, {})
    feedback_status = str(feedback_summary.get("status", "unknown")).strip() or "unknown"
    feedback_age_sec = 0.0
    try:
        feedback_age_sec = max(0.0, time.time() - feedback_summary_path.stat().st_mtime)
    except Exception:
        feedback_age_sec = float("inf")
    feedback_status_max_age_sec = 7200.0
    if feedback_status.lower() == "error" and feedback_age_sec <= feedback_status_max_age_sec:
        issue_codes.append("feedback_collector_error")

    review_index = _load_json(outputs_dir / "episodes_review_index.json", {})
    task_state_paths = list(outputs_dir.rglob("task_state_*.json"))
    submit_lag = _find_submit_lag_candidates(
        task_state_paths,
        _review_index_episode_ids(review_index),
        min_age_sec=submit_lag_min_age_sec,
    )
    if submit_lag:
        issue_codes.append("submit_feedback_lag")

    production_enabled_flag = app_dir / ".state" / "production_enabled.flag"
    solver_active = _service_active(snapshot, "atlas-solver.service")
    auto_restart_attempted = False
    auto_restart_succeeded = False
    if auto_restart_solver and production_enabled_flag.exists() and solver_active not in {"active", "activating"}:
        auto_restart_attempted = True
        auto_restart_succeeded = _restart_solver(app_dir)
        if auto_restart_succeeded:
            snapshot = build_health_snapshot(app_dir=app_dir, index_path=index_path)
            solver_active = _service_active(snapshot, "atlas-solver.service")
            issue_codes = [code for code in issue_codes if code != "solver_inactive"]
        else:
            issue_codes.append("solver_inactive")
    elif production_enabled_flag.exists() and solver_active not in {"active", "activating"}:
        issue_codes.append("solver_inactive")

    issue_codes = sorted(set(issue_codes))
    state_payload = _load_json(state_path, {}) if state_path is not None else {}
    last_signature = str(state_payload.get("last_issue_signature", "")).strip()
    signature = _build_issue_signature(issue_codes, submit_lag, feedback_status, solver_active)

    result = {
        "generated_at_epoch": int(time.time()),
        "app_dir": str(app_dir),
        "index_path": str(index_path),
        "health": snapshot,
        "solver_log_path": str(solver_log_path),
        "issue_codes": issue_codes,
        "feedback_status": feedback_status,
        "submit_lag": submit_lag,
        "production_enabled": production_enabled_flag.exists(),
        "auto_restart_attempted": auto_restart_attempted,
        "auto_restart_succeeded": auto_restart_succeeded,
        "issue_signature": signature,
        "issue_signature_changed": signature != last_signature,
    }

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if state_path is not None:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {
                    "last_issue_signature": signature,
                    "updated_at_epoch": result["generated_at_epoch"],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return result


def render_alert_text(snapshot: Dict[str, Any]) -> str:
    health = snapshot.get("health", {}) if isinstance(snapshot.get("health"), dict) else {}
    summary_line = str(health.get("summary_line", "")).strip()
    issues = snapshot.get("issue_codes", []) if isinstance(snapshot.get("issue_codes"), list) else []
    submit_lag = snapshot.get("submit_lag", []) if isinstance(snapshot.get("submit_lag"), list) else []
    lines = [
        "Atlas monitor update",
        summary_line or "No summary available.",
        f"Issues: {', '.join(issues) if issues else 'none'}",
    ]
    if snapshot.get("auto_restart_attempted"):
        lines.append(
            f"Auto-restart solver: {'ok' if snapshot.get('auto_restart_succeeded') else 'failed'}"
        )
    if submit_lag:
        lines.append("Submit/feedback lag:")
        for item in submit_lag[:5]:
            lines.append(
                f"- {item.get('episode_id', '?')} account={item.get('account', 'unknown')} age={item.get('age_sec', 0)}s"
            )
    return "\n".join(lines)


def maybe_send_alerts(
    snapshot: Dict[str, Any],
    *,
    telegram_token: str,
    allowed_chats: List[int],
    force: bool = False,
) -> int:
    if not telegram_token or not allowed_chats:
        return 0
    issue_codes = snapshot.get("issue_codes", []) if isinstance(snapshot.get("issue_codes"), list) else []
    if not issue_codes and not force:
        return 0
    if not snapshot.get("issue_signature_changed") and not force:
        return 0
    text = render_alert_text(snapshot)
    sent = 0
    for chat_id in allowed_chats:
        if _send_telegram_message(telegram_token, int(chat_id), text):
            sent += 1
    return sent


def main() -> None:
    parser = argparse.ArgumentParser(description="Atlas production monitor and Telegram alerts")
    parser.add_argument("--app-dir", default=".", help="Atlas application root")
    parser.add_argument("--index", default="configs/accounts/index.yaml", help="Scheduler index YAML")
    parser.add_argument("--output", default="outputs/production_monitor/last_snapshot.json", help="JSON output path")
    parser.add_argument("--state", default="outputs/production_monitor/last_alert_state.json", help="Alert state path")
    parser.add_argument("--submit-lag-min-age-sec", type=int, default=1800, help="Age threshold before flagging submitted episodes missing from review index")
    parser.add_argument("--auto-restart-solver", action="store_true", help="Restart solver if production flag exists and solver is inactive")
    parser.add_argument("--force-alert", action="store_true", help="Send Telegram alert even if signature did not change")
    args = parser.parse_args()

    app_dir = Path(args.app_dir).resolve()
    index_path = Path(args.index)
    if not index_path.is_absolute():
        index_path = (app_dir / index_path).resolve()
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = (app_dir / output_path).resolve()
    state_path = Path(args.state)
    if not state_path.is_absolute():
        state_path = (app_dir / state_path).resolve()

    token = str(__import__("os").environ.get("TELEGRAM_BOT_TOKEN", "") or "").strip()
    allowed_raw = str(__import__("os").environ.get("TELEGRAM_ALLOWED_CHATS", "") or "").strip()
    allowed_chats = [int(item.strip()) for item in allowed_raw.split(",") if item.strip().lstrip("-").isdigit()]

    snapshot = build_monitor_snapshot(
        app_dir=app_dir,
        index_path=index_path,
        output_path=output_path,
        state_path=state_path,
        submit_lag_min_age_sec=args.submit_lag_min_age_sec,
        auto_restart_solver=bool(args.auto_restart_solver),
    )
    sent_count = maybe_send_alerts(
        snapshot,
        telegram_token=token,
        allowed_chats=allowed_chats,
        force=bool(args.force_alert),
    )
    print(render_alert_text(snapshot))
    print(f"[monitor] snapshot: {output_path}")
    print(f"[monitor] alerts_sent: {sent_count}")


__all__ = [
    "_detect_log_markers",
    "_find_submit_lag_candidates",
    "build_monitor_snapshot",
    "render_alert_text",
    "maybe_send_alerts",
    "main",
]
