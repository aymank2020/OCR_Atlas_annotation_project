"""Build a durable episode history ledger from local and remote Atlas artifacts."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import textwrap
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List


EPISODE_ID_RE = re.compile(r"([0-9a-f]{24})", re.IGNORECASE)


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _extract_episode_id(text: str) -> str:
    match = EPISODE_ID_RE.search(text or "")
    return match.group(1).lower() if match else ""


def _guess_account_from_path(path: Path) -> str:
    parts = [part.lower() for part in path.parts]
    if "outputs" in parts:
        idx = parts.index("outputs")
        if idx + 2 < len(parts):
            candidate = path.parts[idx + 1]
            if candidate.lower() not in {
                "archive",
                "atlas_feedback_pages",
                "complex_test",
                "drive_publish_staging",
                "gemini_memory_sources",
                "live_episode_bundles",
                "pre_submit_compare",
                "production_monitor",
                "training_feedback",
            } and "." not in candidate:
                return candidate
    return "unknown"


def _empty_record(episode_id: str) -> Dict[str, Any]:
    return {
        "episode_id": episode_id,
        "accounts": [],
        "seen_local": False,
        "seen_server": False,
        "opened": False,
        "labels_ready": False,
        "validation_ok": False,
        "submitted_local_evidence": False,
        "feedback_seen": False,
        "disputes_seen": False,
        "blocked": False,
        "blocked_reason": "",
        "reviewed_quality": "",
        "review_statuses": [],
        "feedback_url": "",
        "atlas_url": "",
        "disputes_url": "",
        "latest_compare_decision": "",
        "latest_compare_block_reason": "",
        "latest_validation_errors": [],
        "latest_validation_warnings": [],
        "source_count": 0,
        "sources": [],
        "notes": [],
        "related_paths": [],
        "last_seen_epoch": 0,
    }


def _get_record(records: Dict[str, Dict[str, Any]], episode_id: str) -> Dict[str, Any]:
    episode_id = (episode_id or "").strip().lower()
    if not episode_id:
        raise ValueError("episode_id is required")
    record = records.get(episode_id)
    if record is None:
        record = _empty_record(episode_id)
        records[episode_id] = record
    return record


def _append_unique(target: List[Any], value: Any) -> None:
    if value in (None, "", []):
        return
    if value not in target:
        target.append(value)


def _mark_seen(record: Dict[str, Any], source_scope: str, source_tag: str) -> None:
    if source_scope == "server":
        record["seen_server"] = True
    else:
        record["seen_local"] = True
    _append_unique(record["sources"], source_tag)
    record["source_count"] = len(record["sources"])


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _coerce_epoch(value: Any) -> int:
    try:
        return int(float(value))
    except Exception:
        return 0


def _update_last_seen(record: Dict[str, Any], candidate_epoch: int) -> None:
    if candidate_epoch > int(record.get("last_seen_epoch", 0)):
        record["last_seen_epoch"] = candidate_epoch


def _merge_review_index(
    records: Dict[str, Dict[str, Any]],
    payload: Dict[str, Any],
    *,
    source_scope: str,
) -> None:
    episodes = payload.get("episodes", []) if isinstance(payload, dict) else []
    for item in episodes:
        if not isinstance(item, dict):
            continue
        episode_id = _extract_episode_id(str(item.get("episode_id", "")))
        if not episode_id:
            continue
        record = _get_record(records, episode_id)
        _mark_seen(record, source_scope, f"{source_scope}:review_index")
        record["opened"] = True
        record["labels_ready"] = record["labels_ready"] or _coerce_bool(
            (item.get("task_state") or {}).get("labels_ready")
        )
        record["submitted_local_evidence"] = record["submitted_local_evidence"] or _coerce_bool(
            (item.get("task_state") or {}).get("episode_submitted")
        ) or _coerce_bool((item.get("task_state") or {}).get("submitted")) or str(
            item.get("review_status", "")
        ).strip().lower() == "submitted"

        validation = item.get("validation")
        if isinstance(validation, dict):
            record["validation_ok"] = record["validation_ok"] or _coerce_bool(validation.get("ok"))
            for error in validation.get("errors", []) if isinstance(validation.get("errors"), list) else []:
                _append_unique(record["latest_validation_errors"], str(error))
            for warning in validation.get("warnings", []) if isinstance(validation.get("warnings"), list) else []:
                _append_unique(record["latest_validation_warnings"], str(warning))

        review_status = str(item.get("review_status", "")).strip()
        if review_status:
            _append_unique(record["review_statuses"], review_status)
            lowered = review_status.lower()
            if lowered not in {"submitted", "unknown"}:
                record["blocked"] = True
                if not record["blocked_reason"]:
                    record["blocked_reason"] = review_status

        for key in ("feedback_url", "atlas_url", "disputes_url"):
            value = str(item.get(key, "")).strip()
            if value and not record.get(key):
                record[key] = value

        for path_str in item.get("related_files", []) if isinstance(item.get("related_files"), list) else []:
            _append_unique(record["related_paths"], str(path_str))
            account = _guess_account_from_path(Path(path_str))
            if account != "unknown":
                _append_unique(record["accounts"], account)

        task_state = item.get("task_state")
        if isinstance(task_state, dict):
            if _coerce_bool(task_state.get("has_error")) and not record["blocked_reason"]:
                record["blocked"] = True
                record["blocked_reason"] = str(task_state.get("last_error", "")).strip() or "task_state_error"
            elif str(task_state.get("last_error", "")).strip() and not record["blocked_reason"]:
                record["blocked"] = True
                record["blocked_reason"] = str(task_state.get("last_error", "")).strip()

        _update_last_seen(record, _coerce_epoch(item.get("mtime_epoch")))


def _merge_task_state_item(
    records: Dict[str, Dict[str, Any]],
    episode_id: str,
    path: str,
    payload: Dict[str, Any],
    *,
    source_scope: str,
    mtime_epoch: int = 0,
) -> None:
    record = _get_record(records, episode_id)
    _mark_seen(record, source_scope, f"{source_scope}:task_state")
    record["opened"] = True
    record["labels_ready"] = record["labels_ready"] or _coerce_bool(payload.get("labels_ready"))
    record["submitted_local_evidence"] = record["submitted_local_evidence"] or _coerce_bool(
        payload.get("episode_submitted")
    ) or _coerce_bool(payload.get("submitted"))
    if _coerce_bool(payload.get("validation_ok")):
        record["validation_ok"] = True
    if _coerce_bool(payload.get("has_error")) or str(payload.get("last_error", "")).strip():
        record["blocked"] = True
        if not record["blocked_reason"]:
            record["blocked_reason"] = str(payload.get("last_error", "")).strip() or "task_state_error"
    account = _guess_account_from_path(Path(path))
    if account != "unknown":
        _append_unique(record["accounts"], account)
    _append_unique(record["related_paths"], path)
    _update_last_seen(record, mtime_epoch)


def _merge_validation_item(
    records: Dict[str, Dict[str, Any]],
    episode_id: str,
    path: str,
    payload: Dict[str, Any],
    *,
    source_scope: str,
    mtime_epoch: int = 0,
) -> None:
    record = _get_record(records, episode_id)
    _mark_seen(record, source_scope, f"{source_scope}:validation")
    record["opened"] = True
    record["validation_ok"] = record["validation_ok"] or _coerce_bool(payload.get("ok"))
    errors = payload.get("errors", []) if isinstance(payload.get("errors"), list) else []
    warnings = payload.get("warnings", []) if isinstance(payload.get("warnings"), list) else []
    for error in errors:
        _append_unique(record["latest_validation_errors"], str(error))
    for warning in warnings:
        _append_unique(record["latest_validation_warnings"], str(warning))
    if errors:
        record["blocked"] = True
        if not record["blocked_reason"]:
            record["blocked_reason"] = str(errors[0])
    account = _guess_account_from_path(Path(path))
    if account != "unknown":
        _append_unique(record["accounts"], account)
    _append_unique(record["related_paths"], path)
    _update_last_seen(record, mtime_epoch)


def _merge_compare_item(
    records: Dict[str, Dict[str, Any]],
    episode_id: str,
    path: str,
    payload: Dict[str, Any],
    *,
    source_scope: str,
    mtime_epoch: int = 0,
) -> None:
    record = _get_record(records, episode_id)
    _mark_seen(record, source_scope, f"{source_scope}:pre_submit_compare")
    record["opened"] = True
    decision = str(payload.get("decision", "")).strip()
    if decision:
        record["latest_compare_decision"] = decision
    block_reason = str(payload.get("block_reason", "")).strip()
    if block_reason:
        record["latest_compare_block_reason"] = block_reason
    if _coerce_bool(payload.get("block_apply")) or decision.startswith("chat_compare_"):
        record["blocked"] = True
        if not record["blocked_reason"]:
            record["blocked_reason"] = block_reason or decision
    account = _guess_account_from_path(Path(path))
    if account != "unknown":
        _append_unique(record["accounts"], account)
    _append_unique(record["related_paths"], path)
    _update_last_seen(record, mtime_epoch)


def _merge_manual_feedback_snapshot(
    records: Dict[str, Dict[str, Any]],
    payload: Dict[str, Any],
    *,
    source_scope: str,
) -> None:
    episodes = payload.get("episodes", []) if isinstance(payload, dict) else []
    now_epoch = int(time.time())
    for item in episodes:
        if not isinstance(item, dict):
            continue
        episode_id = _extract_episode_id(str(item.get("episode_id", "")) or str(item.get("feedback_url", "")))
        if not episode_id:
            continue
        record = _get_record(records, episode_id)
        _mark_seen(record, source_scope, f"{source_scope}:manual_feedback")
        record["feedback_seen"] = True
        quality_score = str(item.get("quality_score", "")).strip()
        if quality_score:
            record["reviewed_quality"] = quality_score
        feedback_url = str(item.get("feedback_url", "")).strip()
        if feedback_url and not record["feedback_url"]:
            record["feedback_url"] = feedback_url
        note = str(item.get("notes", "")).strip()
        if note:
            _append_unique(record["notes"], note)
        _update_last_seen(record, now_epoch)


def _merge_feedback_page_paths(
    records: Dict[str, Dict[str, Any]],
    paths: Iterable[Path],
    *,
    source_scope: str,
) -> None:
    now_epoch = int(time.time())
    for path in paths:
        episode_id = _extract_episode_id(path.name)
        if not episode_id:
            continue
        record = _get_record(records, episode_id)
        _mark_seen(record, source_scope, f"{source_scope}:feedback_page_snapshot")
        record["feedback_seen"] = True
        _append_unique(record["related_paths"], str(path))
        _append_unique(record["notes"], "Feedback page snapshot captured.")
        _update_last_seen(record, now_epoch)


def _summarize_outputs_tree(outputs_dir: Path) -> Dict[str, Any]:
    review_index = _load_json(outputs_dir / "episodes_review_index.json", {})
    manual_feedback = _load_json(
        outputs_dir / "gemini_memory_sources" / "manual_feedback_snapshot.json",
        {},
    )
    summary = {
        "review_index": review_index,
        "manual_feedback": manual_feedback,
        "task_states": [],
        "validations": [],
        "pre_submit_compares": [],
        "feedback_page_paths": [],
    }

    for path in outputs_dir.rglob("task_state_*.json"):
        payload = _load_json(path, {})
        summary["task_states"].append(
            {
                "episode_id": _extract_episode_id(path.stem),
                "path": str(path),
                "mtime_epoch": int(path.stat().st_mtime),
                "payload": payload if isinstance(payload, dict) else {},
            }
        )
    for path in outputs_dir.rglob("validation_*.json"):
        payload = _load_json(path, {})
        summary["validations"].append(
            {
                "episode_id": _extract_episode_id(path.stem),
                "path": str(path),
                "mtime_epoch": int(path.stat().st_mtime),
                "payload": payload if isinstance(payload, dict) else {},
            }
        )
    for path in outputs_dir.rglob("*_pre_submit_compare.json"):
        payload = _load_json(path, {})
        summary["pre_submit_compares"].append(
            {
                "episode_id": _extract_episode_id(path.stem),
                "path": str(path),
                "mtime_epoch": int(path.stat().st_mtime),
                "payload": payload if isinstance(payload, dict) else {},
            }
        )
    feedback_dir = outputs_dir / "gemini_memory_sources" / "atlas_feedback_pages"
    if feedback_dir.exists():
        for path in feedback_dir.glob("*.txt"):
            if _extract_episode_id(path.name):
                summary["feedback_page_paths"].append(str(path))
    return summary


def _merge_summary(
    records: Dict[str, Dict[str, Any]],
    summary: Dict[str, Any],
    *,
    source_scope: str,
) -> None:
    _merge_review_index(records, summary.get("review_index", {}), source_scope=source_scope)
    _merge_manual_feedback_snapshot(records, summary.get("manual_feedback", {}), source_scope=source_scope)
    _merge_feedback_page_paths(
        records,
        [Path(item) for item in summary.get("feedback_page_paths", []) if str(item).strip()],
        source_scope=source_scope,
    )

    for item in summary.get("task_states", []):
        if not isinstance(item, dict):
            continue
        episode_id = _extract_episode_id(str(item.get("episode_id", "")) or str(item.get("path", "")))
        if episode_id:
            _merge_task_state_item(
                records,
                episode_id,
                str(item.get("path", "")),
                item.get("payload", {}) if isinstance(item.get("payload"), dict) else {},
                source_scope=source_scope,
                mtime_epoch=_coerce_epoch(item.get("mtime_epoch")),
            )

    for item in summary.get("validations", []):
        if not isinstance(item, dict):
            continue
        episode_id = _extract_episode_id(str(item.get("episode_id", "")) or str(item.get("path", "")))
        if episode_id:
            _merge_validation_item(
                records,
                episode_id,
                str(item.get("path", "")),
                item.get("payload", {}) if isinstance(item.get("payload"), dict) else {},
                source_scope=source_scope,
                mtime_epoch=_coerce_epoch(item.get("mtime_epoch")),
            )

    for item in summary.get("pre_submit_compares", []):
        if not isinstance(item, dict):
            continue
        episode_id = _extract_episode_id(str(item.get("episode_id", "")) or str(item.get("path", "")))
        if episode_id:
            _merge_compare_item(
                records,
                episode_id,
                str(item.get("path", "")),
                item.get("payload", {}) if isinstance(item.get("payload"), dict) else {},
                source_scope=source_scope,
                mtime_epoch=_coerce_epoch(item.get("mtime_epoch")),
            )


def _finalize_record(record: Dict[str, Any]) -> Dict[str, Any]:
    record["accounts"] = sorted(record["accounts"])
    record["sources"] = sorted(record["sources"])
    record["review_statuses"] = sorted(record["review_statuses"])
    record["related_paths"] = sorted(record["related_paths"])
    record["latest_validation_errors"] = list(dict.fromkeys(record["latest_validation_errors"]))
    record["latest_validation_warnings"] = list(dict.fromkeys(record["latest_validation_warnings"]))
    record["notes"] = list(dict.fromkeys(record["notes"]))
    record["source_count"] = len(record["sources"])
    if record["reviewed_quality"]:
        record["feedback_seen"] = True
    if record["latest_validation_errors"]:
        record["blocked"] = True
        record["blocked_reason"] = record["latest_validation_errors"][0]
    elif record["latest_compare_block_reason"]:
        record["blocked"] = True
        record["blocked_reason"] = record["latest_compare_block_reason"]
    if record["submitted_local_evidence"] and not record["feedback_seen"]:
        _append_unique(record["notes"], "Submitted evidence exists locally, but feedback has not been seen yet.")
    if record["feedback_seen"] and not record["submitted_local_evidence"]:
        _append_unique(record["notes"], "Feedback evidence exists without a retained local submit artifact.")
    return record


def _history_summary(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "total_episodes": len(records),
        "seen_local": sum(1 for item in records if item.get("seen_local")),
        "seen_server": sum(1 for item in records if item.get("seen_server")),
        "blocked": sum(1 for item in records if item.get("blocked")),
        "submitted_local_evidence": sum(1 for item in records if item.get("submitted_local_evidence")),
        "feedback_seen": sum(1 for item in records if item.get("feedback_seen")),
        "reviewed_quality_count": sum(1 for item in records if str(item.get("reviewed_quality", "")).strip()),
    }


def _render_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# Episode History Report",
        "",
        f"- Generated at: `{report.get('generated_at_utc', '')}`",
        f"- Total episodes: `{report.get('summary', {}).get('total_episodes', 0)}`",
        f"- Seen locally: `{report.get('summary', {}).get('seen_local', 0)}`",
        f"- Seen on server: `{report.get('summary', {}).get('seen_server', 0)}`",
        f"- Blocked: `{report.get('summary', {}).get('blocked', 0)}`",
        f"- Submitted evidence: `{report.get('summary', {}).get('submitted_local_evidence', 0)}`",
        f"- Feedback seen: `{report.get('summary', {}).get('feedback_seen', 0)}`",
        "",
        "## Episodes",
        "",
    ]
    for item in report.get("episodes", [])[:200]:
        lines.extend(
            [
                f"### {item.get('episode_id', '')}",
                "",
                f"- Accounts: `{', '.join(item.get('accounts', [])) or 'unknown'}`",
                f"- Seen local/server: `{item.get('seen_local')}` / `{item.get('seen_server')}`",
                f"- Blocked: `{item.get('blocked')}`",
                f"- Submitted evidence: `{item.get('submitted_local_evidence')}`",
                f"- Feedback seen: `{item.get('feedback_seen')}`",
                f"- Reviewed quality: `{item.get('reviewed_quality', '') or 'n/a'}`",
                f"- Review statuses: `{', '.join(item.get('review_statuses', [])) or 'n/a'}`",
                f"- Compare decision: `{item.get('latest_compare_decision', '') or 'n/a'}`",
                f"- Block reason: `{item.get('blocked_reason', '') or 'n/a'}`",
                f"- Sources: `{', '.join(item.get('sources', [])) or 'n/a'}`",
            ]
        )
        if item.get("notes"):
            lines.append(f"- Notes: `{' | '.join(item.get('notes', []))}`")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def fetch_remote_summary(*, server_host: str, server_app_dir: str, ssh_bin: str = "ssh") -> Dict[str, Any]:
    remote_script = textwrap.dedent(
        """
        import json
        import re
        import sys
        from pathlib import Path

        APP_DIR = Path(sys.argv[1])
        OUTPUTS = APP_DIR / "outputs"

        def load_json(path, default):
            if not path.exists():
                return default
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return default

        def eid(text):
            match = re.search(r"([0-9a-f]{24})", str(text), re.I)
            return match.group(1).lower() if match else ""

        result = {
            "review_index": load_json(OUTPUTS / "episodes_review_index.json", {}),
            "manual_feedback": load_json(OUTPUTS / "gemini_memory_sources" / "manual_feedback_snapshot.json", {}),
            "task_states": [],
            "validations": [],
            "pre_submit_compares": [],
            "feedback_page_paths": [],
        }

        for path in OUTPUTS.rglob("task_state_*.json"):
            payload = load_json(path, {})
            result["task_states"].append(
                {
                    "episode_id": eid(path.stem),
                    "path": str(path),
                    "mtime_epoch": int(path.stat().st_mtime),
                    "payload": payload if isinstance(payload, dict) else {},
                }
            )
        for path in OUTPUTS.rglob("validation_*.json"):
            payload = load_json(path, {})
            result["validations"].append(
                {
                    "episode_id": eid(path.stem),
                    "path": str(path),
                    "mtime_epoch": int(path.stat().st_mtime),
                    "payload": payload if isinstance(payload, dict) else {},
                }
            )
        for path in OUTPUTS.rglob("*_pre_submit_compare.json"):
            payload = load_json(path, {})
            result["pre_submit_compares"].append(
                {
                    "episode_id": eid(path.stem),
                    "path": str(path),
                    "mtime_epoch": int(path.stat().st_mtime),
                    "payload": payload if isinstance(payload, dict) else {},
                }
            )
        feedback_dir = OUTPUTS / "gemini_memory_sources" / "atlas_feedback_pages"
        if feedback_dir.exists():
            for path in feedback_dir.glob("*.txt"):
                if eid(path.name):
                    result["feedback_page_paths"].append(str(path))

        print(json.dumps(result, ensure_ascii=False))
        """
    ).strip()
    command = [ssh_bin, server_host, "python3", "-", server_app_dir]
    result = subprocess.run(
        command,
        input=remote_script,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "remote summary failed").strip())
    payload = json.loads(result.stdout or "{}")
    return payload if isinstance(payload, dict) else {}


def build_episode_history_report(
    *,
    app_dir: Path,
    output_json: Path | None = None,
    output_md: Path | None = None,
    remote_summary: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    outputs_dir = app_dir / "outputs"
    records: Dict[str, Dict[str, Any]] = {}
    local_summary = _summarize_outputs_tree(outputs_dir)
    _merge_summary(records, local_summary, source_scope="local")
    if remote_summary:
        _merge_summary(records, remote_summary, source_scope="server")

    episodes = [_finalize_record(item) for item in records.values()]
    episodes.sort(
        key=lambda item: (
            0 if item.get("feedback_seen") else 1,
            0 if item.get("submitted_local_evidence") else 1,
            0 if item.get("seen_server") else 1,
            -int(item.get("last_seen_epoch", 0)),
            item.get("episode_id", ""),
        )
    )
    report = {
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "app_dir": str(app_dir),
        "summary": _history_summary(episodes),
        "episodes": episodes,
    }
    if output_json is not None:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if output_md is not None:
        output_md.parent.mkdir(parents=True, exist_ok=True)
        output_md.write_text(_render_markdown(report), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a durable Atlas episode history ledger")
    parser.add_argument("--app-dir", default=".", help="Atlas application root")
    parser.add_argument("--output-json", default="outputs/episode_history_report.json", help="Where to write the JSON report")
    parser.add_argument("--output-md", default="outputs/episode_history_report.md", help="Where to write the Markdown report")
    parser.add_argument("--server-host", default="", help="Optional SSH host for Hetzner summary")
    parser.add_argument("--server-app-dir", default="/srv/atlas/OCR_annotation_Atlas", help="Atlas application root on the remote server")
    args = parser.parse_args()

    app_dir = Path(args.app_dir).resolve()
    output_json = Path(args.output_json)
    if not output_json.is_absolute():
        output_json = (app_dir / output_json).resolve()
    output_md = Path(args.output_md)
    if not output_md.is_absolute():
        output_md = (app_dir / output_md).resolve()

    remote_summary = None
    if str(args.server_host).strip():
        remote_summary = fetch_remote_summary(
            server_host=str(args.server_host).strip(),
            server_app_dir=str(args.server_app_dir).strip(),
        )

    report = build_episode_history_report(
        app_dir=app_dir,
        output_json=output_json,
        output_md=output_md,
        remote_summary=remote_summary,
    )
    print(
        "episodes={total} local={local} server={server} feedback={feedback}".format(
            total=report["summary"]["total_episodes"],
            local=report["summary"]["seen_local"],
            server=report["summary"]["seen_server"],
            feedback=report["summary"]["feedback_seen"],
        )
    )
    print(f"[history] json: {output_json}")
    print(f"[history] md: {output_md}")


__all__ = [
    "_extract_episode_id",
    "_guess_account_from_path",
    "_summarize_outputs_tree",
    "fetch_remote_summary",
    "build_episode_history_report",
    "main",
]
