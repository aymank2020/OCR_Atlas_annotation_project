"""
Generate a single-file "Atlas OS" dashboard for the Central Rule Authority.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence

from src.policy import context_manager


DEFAULT_POLICY_ROOT = Path("data/policy")
DEFAULT_DISCORD_DIR = Path("discord")
DEFAULT_OUTPUTS_DIR = Path("outputs")
DEFAULT_REVIEW_INDEX = DEFAULT_OUTPUTS_DIR / "episodes_review_index.json"
DEFAULT_OUTPUT = Path("outputs/atlas_os_dashboard.html")


def _load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        clean = line.strip()
        if not clean:
            continue
        try:
            payload = json.loads(clean)
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _read_text(path: Path, default: str = "") -> str:
    if not path.exists():
        return default
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return default


def _parse_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _display_ts(value: Any) -> str:
    parsed = _parse_iso(value)
    return parsed.strftime("%Y-%m-%d %H:%M UTC") if parsed else "Unknown"


def _relative_age(value: Any) -> str:
    parsed = _parse_iso(value)
    if parsed is None:
        return "unknown age"
    delta = datetime.now(timezone.utc) - parsed
    seconds = max(0, int(delta.total_seconds()))
    if seconds < 60:
        return "moments ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def _channel_key(value: Any) -> str:
    raw = "".join(ch for ch in str(value or "").lower() if ch.isalnum())
    return raw[:-1] if raw.endswith("s") else raw


def _word_count(value: Any) -> int:
    text = str(value or "").replace("/", " ").replace("-", " ").strip()
    return len([part for part in text.split() if part])


def _token_estimate(value: Any) -> int:
    words = _word_count(value)
    return max(1, math.ceil(words * 1.25)) if words else 0


def _field_label(field_path: str) -> str:
    aliases = {
        "engine_limits.max_segment_seconds": "Max Segment",
        "annotation.preferred_density_sec": "Density Window",
        "annotation.max_atomic_actions": "Atomic Actions",
        "annotation.max_label_words": "Label Words",
        "lexicon.forbidden_verbs": "Forbidden Verbs",
        "lexicon.forbidden_narrative_words": "Narrative Words",
    }
    return aliases.get(field_path, field_path.replace(".", " / "))


def _value_preview(value: Any) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{key}: {val}" for key, val in value.items())
    if isinstance(value, list):
        return ", ".join(str(item) for item in value[:4])
    return str(value)


def _is_active_promoted(record: Dict[str, Any]) -> bool:
    if str(record.get("status", "")).lower() != "promoted":
        return False
    expires_at = _parse_iso(record.get("expires_at"))
    return expires_at is None or expires_at > datetime.now(timezone.utc)


def _recent_markers(discord_dir: Path) -> List[Dict[str, str]]:
    if not discord_dir.exists():
        return []
    markers: List[Dict[str, str]] = []
    for pattern in ("atlas-announcements/*/*page_*.json", "level-3-questions/*/*page_*.json", "harvest_*.json"):
        for path in sorted(discord_dir.glob(pattern), key=lambda item: item.stat().st_mtime, reverse=True)[:3]:
            label = path.stem if path.parent == discord_dir else path.parent.parent.name
            markers.append(
                {
                    "label": label,
                    "path": path.name,
                    "updated_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
                }
            )
    return markers[:6]


def _sync_status(
    current_policy: Dict[str, Any],
    staged_rules: Sequence[Dict[str, Any]],
    trust_config: Dict[str, Any],
    discord_dir: Path,
) -> Dict[str, Any]:
    expected = [str(item) for item in trust_config.get("trusted_channels", []) if str(item).strip()]
    expected_map = {_channel_key(item): item for item in expected}
    observed: Dict[str, str] = {}
    for source in current_policy.get("sources", []):
        channel = str(source.get("channel", "")).strip()
        if channel:
            observed[_channel_key(channel)] = channel
    for record in staged_rules:
        channel = str(record.get("channel", "")).strip()
        if channel:
            observed.setdefault(_channel_key(channel), channel)
    for marker in _recent_markers(discord_dir):
        observed.setdefault(_channel_key(marker["label"]), marker["label"])
    rows = []
    synced = 0
    for key, label in expected_map.items():
        ok = key in observed
        synced += int(ok)
        rows.append({"name": label, "state": "Synced" if ok else "Watching", "tone": "ok" if ok else "warn", "source": observed.get(key, "Awaiting ingest")})
    expected_count = len(expected_map)
    pct = round((synced / expected_count) * 100, 1) if expected_count else 0.0
    state = "Synchronized" if synced == expected_count and synced else ("Partial Coverage" if synced else "Awaiting Harvest")
    tone = "ok" if synced == expected_count and synced else ("warn" if synced else "idle")
    return {
        "state": state,
        "tone": tone,
        "coverage_pct": pct,
        "synced_count": synced,
        "expected_count": expected_count,
        "channel_rows": rows,
        "recent_markers": _recent_markers(discord_dir),
    }


def _token_economy(records: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    source_rows = list(records) or [{"field_path": "annotation.max_atomic_actions", "raw_text": "Each segment is limited to two atomic actions.", "value": 2}]
    rows = sorted(source_rows, key=lambda row: str(row.get("timestamp", "")), reverse=True)[:6]
    labels: List[str] = []
    prose: List[int] = []
    atomic: List[int] = []
    detail_rows: List[Dict[str, Any]] = []
    prose_total = 0
    atomic_total = 0
    for row in reversed(rows):
        field_path = str(row.get("field_path", "")) or "runtime.rule"
        raw_text = str(row.get("raw_text", "")).strip() or str(row.get("summary", "")).strip() or field_path
        atomic_repr = f"{field_path}: {_value_preview(row.get('value'))}"
        prose_tokens = _token_estimate(raw_text)
        atomic_tokens = max(1, _token_estimate(atomic_repr))
        label = _field_label(field_path)
        labels.append(label)
        prose.append(prose_tokens)
        atomic.append(atomic_tokens)
        prose_total += prose_tokens
        atomic_total += atomic_tokens
        detail_rows.append({"label": label, "raw_text": raw_text, "atomic_repr": atomic_repr, "prose_tokens": prose_tokens, "atomic_tokens": atomic_tokens, "saved": max(0, prose_tokens - atomic_tokens)})
    savings_pct = round((1 - (atomic_total / prose_total)) * 100, 1) if prose_total else 0.0
    return {"labels": labels, "prose": prose, "atomic": atomic, "prose_total": prose_total, "atomic_total": atomic_total, "savings_pct": savings_pct, "detail_rows": detail_rows}


def _staging_rows(staged_rules: Sequence[Dict[str, Any]], current_policy: Dict[str, Any]) -> Dict[str, Any]:
    pending = [row for row in staged_rules if str(row.get("status", "")).lower() == "staged"]
    note = ""
    if not pending:
        pending = [
            {
                "rule_id": str(item.get("rule_id", "")) or f"demo-{idx}",
                "summary": f"Candidate review for {_field_label(str(item.get('field_path', 'runtime.rule')))}",
                "field_path": str(item.get("field_path", "")),
                "value": item.get("value"),
                "author": str(item.get("author", "trusted-source")),
                "channel": str(item.get("channel", "Discord")),
                "timestamp": str(item.get("timestamp", "")),
                "confidence": 0.88,
                "trust_tier": str(item.get("trust_tier", "trusted_auto")),
                "status": "candidate_demo",
                "is_demo": True,
            }
            for idx, item in enumerate(list(reversed(current_policy.get("sources", [])))[:4], start=1)
        ]
        note = "No real staged rules are waiting on disk, so the queue is seeded from recent trusted promotions to demonstrate the workflow."
    rows = []
    for row in sorted(pending, key=lambda item: str(item.get("timestamp", "")), reverse=True)[:6]:
        rows.append(
            {
                "rule_id": str(row.get("rule_id", ""))[:18],
                "summary": str(row.get("summary", "")) or f"Review {_field_label(str(row.get('field_path', 'runtime.rule')))}",
                "field_path": _field_label(str(row.get("field_path", "runtime.rule"))),
                "author": str(row.get("author", "unknown")),
                "channel": str(row.get("channel", "Discord")),
                "confidence": round(float(row.get("confidence", 0.0) or 0.0) * 100, 1),
                "timestamp": _display_ts(row.get("timestamp")),
                "age": _relative_age(row.get("timestamp")),
                "status": str(row.get("status", "staged")),
                "trust_tier": str(row.get("trust_tier", "community")),
                "value_preview": _value_preview(row.get("value")),
                "is_demo": bool(row.get("is_demo")),
            }
        )
    return {"rows": rows, "pending_count": len(rows), "note": note}


def _retrieval_map(policy_root: Path) -> Dict[str, Any]:
    retrieved = context_manager.retrieve_runtime_rules(
        [{"label": "pick up chopped dough and place it in tray", "raw_text": "video annotation dense action timing validator error"}],
        trigger="validator_error",
        budget={"rules": 4, "examples": 1},
        current_policy_path=policy_root / "current_policy.json",
        staged_rules_path=policy_root / "staged_rules.jsonl",
        lessons_path=Path("data/knowledge/policy_lessons.jsonl"),
        golden_path=Path("data/knowledge/golden_index.jsonl"),
    )
    rules: List[str] = []
    examples: List[str] = []
    section = ""
    for line in retrieved.splitlines():
        clean = line.strip()
        if clean.startswith("==="):
            section = clean.strip("= ").lower()
        elif clean.startswith("-"):
            (examples if "golden" in section else rules).append(clean[1:].strip())
    if not rules:
        policy = context_manager.load_current_policy(policy_root / "current_policy.json")
        rules = [str(item) for item in context_manager.get_policy("runtime.universal_rules", [], policy=policy)[:4]]
    return {"task": "Video Annotation", "trigger": "validator_error", "rules": rules[:4], "examples": examples[:1], "nodes": ["Discord Managers", "Central Rule Authority", "JSON Vault", "Selective Retrieval", "Python API Executor"]}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _normalize_compare_label(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _parse_segment_text(value: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in str(value or "").splitlines():
        clean = line.strip()
        if not clean:
            continue
        parts = clean.split("\t", 3)
        if len(parts) < 4:
            continue
        index_text, start_text, end_text, label = parts
        try:
            index = int(index_text)
        except Exception:
            index = len(rows) + 1
        rows.append(
            {
                "index": index,
                "start_text": str(start_text),
                "end_text": str(end_text),
                "start": _safe_float(start_text),
                "end": _safe_float(end_text),
                "label": str(label).strip(),
            }
        )
    return rows


def _segment_compare_rows(old_text: Any, new_text: Any) -> List[Dict[str, Any]]:
    old_rows = {row["index"]: row for row in _parse_segment_text(old_text)}
    new_rows = {row["index"]: row for row in _parse_segment_text(new_text)}
    rows: List[Dict[str, Any]] = []
    for index in sorted(set(old_rows) | set(new_rows)):
        old_row = old_rows.get(index)
        new_row = new_rows.get(index)
        old_label = str(old_row.get("label", "") if old_row else "")
        new_label = str(new_row.get("label", "") if new_row else "")
        if old_row and new_row:
            status = "same" if _normalize_compare_label(old_label) == _normalize_compare_label(new_label) else "changed"
        elif old_row:
            status = "removed"
        else:
            status = "added"
        window_source = old_row or new_row or {}
        rows.append(
            {
                "index": index,
                "window": f"{window_source.get('start_text', '')}-{window_source.get('end_text', '')}",
                "old_label": old_label,
                "new_label": new_label,
                "status": status,
            }
        )
    return rows


def _human_size(path: Path) -> str:
    try:
        size = path.stat().st_size
    except Exception:
        return ""
    if size < 1024:
        return f"{size} B"
    if size < 1024**2:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024**2):.2f} MB"


def _relative_output_path(path_value: Any, outputs_dir: Path) -> str:
    raw = str(path_value or "").strip()
    if not raw:
        return ""
    path = Path(raw)
    if path.parts and path.parts[0] == outputs_dir.name:
        return Path(*path.parts[1:]).as_posix()
    candidate = path if path.is_absolute() else Path.cwd() / path
    try:
        return candidate.resolve().relative_to(outputs_dir.resolve()).as_posix()
    except Exception:
        return path.as_posix()


def _path_mtime(path_value: Any) -> float:
    raw = str(path_value or "").strip()
    if not raw:
        return 0.0
    path = Path(raw)
    candidate = path if path.is_absolute() else Path.cwd() / path
    try:
        return candidate.stat().st_mtime
    except Exception:
        return 0.0


def _artifact_entry(label: str, path_value: Any, outputs_dir: Path) -> Dict[str, Any] | None:
    raw = str(path_value or "").strip()
    if not raw:
        return None
    path = Path(raw)
    candidate = path if path.is_absolute() else Path.cwd() / path
    return {
        "label": label,
        "path": _relative_output_path(raw, outputs_dir),
        "size": _human_size(candidate),
    }


def _episode_intelligence(review_index_path: Path, outputs_dir: Path) -> Dict[str, Any]:
    payload = _load_json(review_index_path, {}) or {}
    episodes_raw = payload.get("episodes", []) if isinstance(payload, dict) else []
    if not isinstance(episodes_raw, list) or not episodes_raw:
        return {
            "available": False,
            "total": 0,
            "status_counts": {},
            "viewer_path": _relative_output_path(outputs_dir / "atlas_review_viewer.html", outputs_dir),
            "review_index_path": _relative_output_path(review_index_path, outputs_dir),
            "recent": [],
            "featured": {},
        }

    enriched: List[Dict[str, Any]] = []
    for record in episodes_raw:
        if not isinstance(record, dict):
            continue
        tier2_text = str(record.get("tier2_text", "") or "")
        tier3_text = str(record.get("tier3_text", "") or "")
        validation = record.get("validation") if isinstance(record.get("validation"), dict) else {}
        task_state = record.get("task_state") if isinstance(record.get("task_state"), dict) else {}
        comparison_rows = _segment_compare_rows(tier2_text, tier3_text)
        artifacts = [
            item
            for item in [
                _artifact_entry("Episode Video", record.get("video_path"), outputs_dir),
                _artifact_entry("Old Solution", record.get("tier2_text_path"), outputs_dir),
                _artifact_entry("New Solution", record.get("tier3_text_path"), outputs_dir),
                _artifact_entry("Validation JSON", record.get("validation_path"), outputs_dir),
            ]
            if item
        ]
        modified_epoch = max(
            [
                _path_mtime(record.get("video_path")),
                _path_mtime(record.get("tier2_text_path")),
                _path_mtime(record.get("tier3_text_path")),
                _path_mtime(record.get("validation_path")),
            ]
        )
        enriched.append(
            {
                "episode_id": str(record.get("episode_id", "")),
                "task_url": str(record.get("task_url", "")),
                "feedback_url": str(record.get("feedback_url", "")),
                "open_url": str(record.get("open_url", "")),
                "review_status": str(record.get("review_status", "unknown")),
                "status_source": str(record.get("status_source", "local_evidence")),
                "validation_ok": validation.get("ok"),
                "validation_errors": [str(item) for item in validation.get("errors", [])],
                "validation_warnings": [str(item) for item in validation.get("warnings", [])],
                "segment_count": int(validation.get("segment_count") or len(_parse_segment_text(tier3_text) or _parse_segment_text(tier2_text))),
                "old_segment_count": len(_parse_segment_text(tier2_text)),
                "new_segment_count": len(_parse_segment_text(tier3_text)),
                "changed_count": sum(1 for row in comparison_rows if row["status"] != "same"),
                "old_text": tier2_text,
                "new_text": tier3_text,
                "comparison_rows": comparison_rows,
                "artifacts": artifacts,
                "video_path": _relative_output_path(record.get("video_path"), outputs_dir),
                "last_error": str(task_state.get("last_error", "")),
                "labels_ready": bool(task_state.get("labels_ready")),
                "video_ready": bool(task_state.get("video_ready")),
                "submission_ready": bool(task_state.get("episode_submitted") or task_state.get("submitted")),
                "modified_epoch": modified_epoch,
                "modified_at": datetime.fromtimestamp(modified_epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if modified_epoch else "Unknown",
            }
        )

    enriched.sort(key=lambda item: (float(item.get("modified_epoch", 0.0)), item.get("episode_id", "")), reverse=True)
    featured = next((item for item in enriched if item["old_text"] or item["new_text"] or item["comparison_rows"]), enriched[0])
    recent = [
        {
            "episode_id": item["episode_id"],
            "review_status": item["review_status"],
            "validation_ok": item["validation_ok"],
            "changed_count": item["changed_count"],
            "old_segment_count": item["old_segment_count"],
            "new_segment_count": item["new_segment_count"],
            "modified_at": item["modified_at"],
            "task_url": item["task_url"],
            "last_error": item["last_error"],
        }
        for item in enriched[:6]
    ]
    return {
        "available": True,
        "total": int(payload.get("total") or len(enriched)),
        "status_counts": dict(payload.get("status_counts", {})) if isinstance(payload, dict) else {},
        "viewer_path": _relative_output_path(outputs_dir / "atlas_review_viewer.html", outputs_dir),
        "review_index_path": _relative_output_path(review_index_path, outputs_dir),
        "recent": recent,
        "featured": featured,
    }


def _discord_ops(outputs_dir: Path, review_index_path: Path) -> Dict[str, Any]:
    bot_status = _load_json(outputs_dir / "discord_bot_status.json", {}) or {}
    rule_sync = _load_json(outputs_dir / "discord_rule_sync_report.json", {}) or {}
    feedback_summary = _load_json(outputs_dir / "training_feedback" / "live" / "last_run_summary.json", {}) or {}
    feedback_index_path = Path(str(feedback_summary.get("training_dir", "")).strip()) / "INDEX.json"
    feedback_index = _load_json(feedback_index_path, {}) if str(feedback_summary.get("training_dir", "")).strip() else {}
    review_index = _load_json(review_index_path, {}) or {}

    rule_report = rule_sync.get("policy_report", {}) if isinstance(rule_sync.get("policy_report"), dict) else {}
    status_counts = review_index.get("status_counts", {}) if isinstance(review_index.get("status_counts"), dict) else {}
    commands = [
        {"command": "status!", "description": "Return the latest Discord sync, feedback, and review snapshot."},
        {"command": "sync!", "description": "Run the project-wide Discord sync and repo refresh flow."},
        {"command": "rule: ...", "description": "Append a manual canonical rule entry and trigger sync."},
        {"command": "correction: ...", "description": "Store an explicit correction note for the context pack."},
    ]
    last_error = str(bot_status.get("last_error", "") or feedback_summary.get("error", "") or "").strip()
    alerts: List[Dict[str, str]] = []
    if last_error:
        alerts.append({"tone": "warn", "title": "Last runtime error", "detail": last_error})
    if not str(rule_sync.get("generated_at_utc", "")).strip():
        alerts.append({"tone": "warn", "title": "Rule sync report missing", "detail": "outputs/discord_rule_sync_report.json has not been generated yet."})
    if str(feedback_summary.get("status", "")).strip().lower() == "error":
        alerts.append({"tone": "warn", "title": "Feedback collector error", "detail": str(feedback_summary.get("error", "")).strip() or "Collector reported an unknown error."})
    if not alerts:
        alerts.append({"tone": "ok", "title": "Discord loop healthy", "detail": "Rule sync and reporting artifacts are present with no current errors captured."})

    bot_state = str(bot_status.get("last_event", "")).strip() or "awaiting_status_file"
    bot_tone = "ok" if bot_state not in {"awaiting_status_file", "history_export_error"} and not last_error else ("warn" if last_error else "idle")
    feedback_state = str(feedback_summary.get("status", feedback_index.get("gemini_status", "unknown"))).strip() or "unknown"
    feedback_tone = "ok" if feedback_state.lower() in {"ok", "healthy"} else ("warn" if feedback_state.lower() == "error" else "idle")

    review_lines = [f"{key}: {value}" for key, value in sorted(status_counts.items())]
    return {
        "bot": {
            "state": bot_state,
            "tone": bot_tone,
            "ready_at": _display_ts(bot_status.get("ready_at")),
            "last_history_export_at": _display_ts(bot_status.get("last_history_export_at")),
            "last_sync_at": _display_ts(bot_status.get("last_sync_at")),
            "command_channel_id": str(bot_status.get("command_channel_id", "")).strip() or "unconfigured",
            "target_channel_ids": [str(item) for item in bot_status.get("target_channel_ids", []) if str(item).strip()],
            "last_command": str(bot_status.get("last_command", "")).strip() or "No recent command captured.",
        },
        "rule_sync": {
            "generated_at": _display_ts(rule_sync.get("generated_at_utc")),
            "message_count": int(rule_sync.get("message_count", 0) or 0),
            "channel_count": int(rule_sync.get("channel_count", 0) or 0),
            "promoted_count": len(rule_report.get("promoted_rule_ids", []) or []),
            "candidate_count": int(rule_report.get("candidate_count", 0) or 0),
        },
        "feedback": {
            "state": feedback_state,
            "tone": feedback_tone,
            "generated_at": _display_ts(feedback_summary.get("generated_at") or feedback_index.get("generated_at")),
            "episodes_collected": int(feedback_index.get("episodes_collected", 0) or 0),
            "feedback_entries_found": int(feedback_index.get("feedback_entries_found", 0) or 0),
            "training_dir": _relative_output_path(feedback_summary.get("training_dir", ""), outputs_dir),
        },
        "review_export": {
            "generated_at": _display_ts(review_index.get("generated_at")),
            "total": int(review_index.get("total", 0) or 0),
            "status_lines": review_lines,
        },
        "commands": commands,
        "alerts": alerts,
    }


def build_dashboard_payload(
    policy_root: Path = DEFAULT_POLICY_ROOT,
    discord_dir: Path = DEFAULT_DISCORD_DIR,
    outputs_dir: Path = DEFAULT_OUTPUTS_DIR,
    review_index_path: Path = DEFAULT_REVIEW_INDEX,
) -> Dict[str, Any]:
    context_manager.ensure_policy_files(policy_root)
    current_policy = context_manager.load_current_policy(policy_root / "current_policy.json")
    staged_rules = _load_jsonl(policy_root / "staged_rules.jsonl")
    trust_config = _load_json(policy_root / "trust_config.json", context_manager.DEFAULT_TRUST_CONFIG) or {}
    diff = _load_json(policy_root / "policy_diff.json", {}) or {}
    summary_lines = [line for line in _read_text(policy_root / "generated_prompt_summary.txt").splitlines() if line.strip()]
    active_promoted = [row for row in staged_rules if _is_active_promoted(row)]
    sync = _sync_status(current_policy, staged_rules, trust_config, discord_dir)
    economy = _token_economy(staged_rules or current_policy.get("sources", []))
    staging = _staging_rows(staged_rules, current_policy)
    retrieval = _retrieval_map(policy_root)
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "rule_authority": {
            "master_version": str(current_policy.get("policy_version", "atlas-discord-cra-v1")),
            "authority_mode": str(current_policy.get("authority_mode", "trusted_auto")),
            "effective_at": _display_ts(current_policy.get("effective_at")),
            "generated_at": _display_ts(current_policy.get("generated_at")),
            "active_rules": len(active_promoted),
            "source_count": len(current_policy.get("sources", [])),
            "changed_fields": [str(item) for item in diff.get("changed_fields", []) if str(item).strip()],
            "summary_lines": summary_lines,
            "sync": sync,
        },
        "token_economy": economy,
        "staging": staging,
        "retrieval_map": retrieval,
        "episodes": _episode_intelligence(review_index_path=review_index_path, outputs_dir=outputs_dir),
        "discord_ops": _discord_ops(outputs_dir=outputs_dir, review_index_path=review_index_path),
        "kpis": [
            {"label": "Master Version", "value": str(current_policy.get("policy_version", "atlas-discord-cra-v1")), "sub": sync["state"]},
            {"label": "Sync Coverage", "value": f"{sync['coverage_pct']:.1f}%", "sub": f"{sync['synced_count']}/{sync['expected_count']} tracked channels"},
            {"label": "Promoted Rules", "value": str(len(active_promoted)), "sub": f"{len(diff.get('changed_fields', []))} changed fields in last rebuild"},
            {"label": "Token Savings", "value": f"{economy['savings_pct']:.1f}%", "sub": "Atomic chunks vs prose-heavy guidance"},
        ],
    }


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Atlas OS | Centralized Rule Authority</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <script src="https://unpkg.com/lucide@latest"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Space+Grotesk:wght@400;500;700&display=swap" rel="stylesheet">
  <script>
    tailwind.config = { theme: { extend: { fontFamily: { display: ["Space Grotesk", "sans-serif"], mono: ["IBM Plex Mono", "monospace"] } } } };
  </script>
  <style>
    body{font-family:"Space Grotesk",sans-serif;background:radial-gradient(circle at top left,rgba(34,211,238,.16),transparent 26%),radial-gradient(circle at 85% 10%,rgba(52,211,153,.14),transparent 24%),linear-gradient(180deg,#020617 0%,#02040b 100%);color:#dbeafe}
    body::before{content:"";position:fixed;inset:0;pointer-events:none;background-image:linear-gradient(rgba(34,211,238,.07) 1px,transparent 1px),linear-gradient(90deg,rgba(34,211,238,.07) 1px,transparent 1px);background-size:42px 42px;mask-image:linear-gradient(180deg,rgba(0,0,0,.85),transparent 100%);opacity:.45}
    .panel{background:rgba(8,17,31,.84);border:1px solid rgba(52,211,153,.14);box-shadow:0 0 0 1px rgba(34,211,238,.05),0 18px 60px rgba(2,6,23,.55);backdrop-filter:blur(18px)}
    .mono{font-family:"IBM Plex Mono",monospace}
    .flash{animation:flash .9s ease}
    @keyframes flash{0%{box-shadow:none}40%{box-shadow:0 0 0 1px rgba(52,211,153,.7),0 0 30px rgba(34,211,238,.22)}100%{box-shadow:none}}
  </style>
</head>
<body class="min-h-screen">
  <!-- Developer Notes:
    Replace the inline DATA payload with Flask/FastAPI routes like:
    GET /api/policy/current
    GET /api/policy/staged
    POST /api/policy/promote/{rule_id}
    POST /api/context/refresh
    Approve/Reject is intentionally simulated client-side until the Python backend exposes mutations.
  -->
  <script>const DATA=__ATLAS_OS_DATA__;</script>
  <div class="mx-auto flex max-w-[1550px] gap-6 px-4 py-4 md:px-6 lg:px-8">
    <aside class="panel sticky top-4 hidden h-[calc(100vh-2rem)] w-72 shrink-0 rounded-3xl p-5 lg:block">
      <div class="mb-8">
        <div class="mb-4 inline-flex h-12 w-12 items-center justify-center rounded-2xl border border-emerald-400/20 bg-emerald-400/10 text-emerald-300"><i data-lucide="radar" class="h-6 w-6"></i></div>
        <p class="mono text-[0.68rem] uppercase tracking-[0.3em] text-cyan-300">Atlas OS</p>
        <h1 class="mt-2 font-display text-2xl font-bold text-white">Central Rule Authority</h1>
        <p class="mt-3 text-sm leading-6 text-slate-400">Discord ingestion, atomic rule promotion, and selective retrieval for the Python runtime.</p>
      </div>
      <nav class="space-y-2 text-sm text-slate-300">
        <a href="#overview" class="block rounded-2xl px-3 py-2 hover:bg-cyan-400/5">Overview</a>
        <a href="#authority" class="block rounded-2xl px-3 py-2 hover:bg-cyan-400/5">Rule Authority</a>
        <a href="#discordops" class="block rounded-2xl px-3 py-2 hover:bg-cyan-400/5">Discord Ops</a>
        <a href="#episodes" class="block rounded-2xl px-3 py-2 hover:bg-cyan-400/5">Episode Intelligence</a>
        <a href="#economy" class="block rounded-2xl px-3 py-2 hover:bg-cyan-400/5">Token Economy</a>
        <a href="#staging" class="block rounded-2xl px-3 py-2 hover:bg-cyan-400/5">Staging Area</a>
        <a href="#retrieval" class="block rounded-2xl px-3 py-2 hover:bg-cyan-400/5">Retrieval Map</a>
      </nav>
      <div class="mt-8 rounded-2xl border border-emerald-400/10 bg-emerald-400/5 p-4">
        <p class="mono text-[0.65rem] uppercase tracking-[0.28em] text-emerald-300">Rendered</p>
        <p id="renderedAt" class="mt-2 text-sm text-slate-200"></p>
      </div>
    </aside>
    <main class="min-w-0 flex-1 space-y-6">
      <section id="overview" class="panel rounded-[2rem] px-5 py-5 md:px-7 md:py-6">
        <div class="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p class="mono text-[0.68rem] uppercase tracking-[0.3em] text-cyan-300">AIOps Control Plane</p>
            <h2 class="mt-3 font-display text-3xl font-bold text-white md:text-4xl">Atlas Capture: Discord Ingest to API Execution</h2>
            <p class="mt-3 max-w-3xl text-sm leading-7 text-slate-400">This single page makes the invisible rule pipeline visible: Discord manager guidance becomes atomic rule chunks, lands in the JSON vault, and is only retrieved when the Python executor actually needs it.</p>
          </div>
          <button id="refreshBtn" class="inline-flex items-center gap-2 rounded-2xl border border-cyan-400/20 bg-cyan-400/10 px-4 py-3 text-sm font-medium text-cyan-200 transition hover:bg-cyan-400/15"><i data-lucide="refresh-cw" class="h-4 w-4"></i>Context Refresh</button>
        </div>
        <div id="kpis" class="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-4"></div>
      </section>

      <section id="discordops" class="grid gap-6 xl:grid-cols-[1.08fr,0.92fr]">
        <div class="panel rounded-[2rem] p-6">
          <div class="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
            <div><p class="mono text-[0.68rem] uppercase tracking-[0.3em] text-cyan-300">Discord Operations</p><h3 class="mt-2 font-display text-2xl font-bold text-white">Bot Health, Rule Sync, and Feedback Reporting</h3></div>
            <div id="discordBotBadge" class="rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] border-slate-700 bg-slate-800/60 text-slate-300">awaiting status</div>
          </div>
          <div id="discordOpsCards" class="mt-6 grid gap-4 md:grid-cols-2"></div>
          <div class="mt-6 rounded-3xl border border-slate-800 bg-slate-950/30 p-5">
            <p class="font-semibold text-white">Command Center</p>
            <p id="discordCommandMeta" class="mt-2 text-sm text-slate-400"></p>
            <div id="discordCommandList" class="mt-4 grid gap-3 md:grid-cols-2"></div>
          </div>
        </div>
        <div class="panel rounded-[2rem] p-6">
          <div class="flex items-start justify-between gap-4">
            <div><p class="mono text-[0.68rem] uppercase tracking-[0.3em] text-fuchsia-300">Quality Signals</p><h3 class="mt-2 font-display text-2xl font-bold text-white">Discord + Feedback Alerts</h3></div>
            <div class="rounded-2xl border border-fuchsia-400/15 bg-fuchsia-400/5 px-4 py-3"><p id="discordReviewTotal" class="mono text-lg text-fuchsia-200"></p><p class="text-xs uppercase tracking-[0.2em] text-slate-400">reviewed episodes</p></div>
          </div>
          <div id="discordAlerts" class="mt-6 space-y-3"></div>
          <div class="mt-6 rounded-3xl border border-slate-800 bg-slate-950/30 p-5">
            <p class="font-semibold text-white">Review Export Status</p>
            <p id="discordReviewGenerated" class="mt-2 text-sm text-slate-400"></p>
            <div id="discordReviewLines" class="mt-4 flex flex-wrap gap-2"></div>
          </div>
        </div>
      </section>

      <section id="episodes" class="space-y-6">
        <div class="panel rounded-[2rem] p-6">
          <div class="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
            <div><p class="mono text-[0.68rem] uppercase tracking-[0.3em] text-fuchsia-300">Episode Intelligence</p><h3 class="mt-2 font-display text-2xl font-bold text-white">Live Episode, Old Solution, New Solution, and Comparison Grid</h3></div>
            <div class="flex flex-wrap gap-2" id="episodeUtilityLinks"></div>
          </div>
          <div class="mt-6 grid gap-6 xl:grid-cols-[1.05fr,0.95fr]">
            <div class="space-y-4">
              <div class="rounded-[1.75rem] border border-slate-800 bg-slate-950/35 p-5">
                <div class="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <p class="mono text-[0.65rem] uppercase tracking-[0.24em] text-slate-400">featured episode</p>
                    <p id="featuredEpisodeId" class="mt-3 mono text-xl text-white"></p>
                    <p id="featuredEpisodeMeta" class="mt-3 text-sm leading-6 text-slate-400"></p>
                  </div>
                  <div id="featuredEpisodeStatus" class="rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em]"></div>
                </div>
                <div id="episodeStatGrid" class="mt-5 grid gap-3 md:grid-cols-3"></div>
              </div>
              <div class="rounded-[1.75rem] border border-slate-800 bg-slate-950/35 p-5">
                <p class="mono text-[0.65rem] uppercase tracking-[0.24em] text-cyan-300">bundle files</p>
                <div id="episodeArtifacts" class="mt-4 grid gap-3"></div>
              </div>
              <div class="rounded-[1.75rem] border border-slate-800 bg-slate-950/35 p-5">
                <p class="mono text-[0.65rem] uppercase tracking-[0.24em] text-amber-300">validation + runtime state</p>
                <div id="episodeValidation" class="mt-4 space-y-3"></div>
              </div>
            </div>
            <div class="space-y-4">
              <div class="rounded-[1.75rem] border border-slate-800 bg-slate-950/35 p-5">
                <div class="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p class="mono text-[0.65rem] uppercase tracking-[0.24em] text-emerald-300">episode fleet</p>
                    <p class="mt-2 text-sm text-slate-400">Recent episodes discovered in the review index, including validation and solution drift.</p>
                  </div>
                  <div id="episodeTotal" class="mono text-lg text-emerald-200"></div>
                </div>
                <div id="episodeStatusCounts" class="mt-5 flex flex-wrap gap-2"></div>
              </div>
              <div id="recentEpisodeCards" class="grid gap-3"></div>
            </div>
          </div>
        </div>

        <div class="grid gap-6 xl:grid-cols-2">
          <div class="panel rounded-[2rem] p-6">
            <p class="mono text-[0.68rem] uppercase tracking-[0.3em] text-slate-300">Old Solution</p>
            <h3 class="mt-2 font-display text-2xl font-bold text-white">Current Labels Before Update</h3>
            <pre id="oldSolutionText" class="mt-5 overflow-x-auto rounded-[1.75rem] border border-slate-800 bg-slate-950/35 p-5 text-sm leading-7 text-slate-300"></pre>
          </div>
          <div class="panel rounded-[2rem] p-6">
            <p class="mono text-[0.68rem] uppercase tracking-[0.3em] text-emerald-300">New Solution</p>
            <h3 class="mt-2 font-display text-2xl font-bold text-white">Updated Labels from the Solver</h3>
            <pre id="newSolutionText" class="mt-5 overflow-x-auto rounded-[1.75rem] border border-slate-800 bg-slate-950/35 p-5 text-sm leading-7 text-slate-300"></pre>
          </div>
        </div>

        <div class="panel rounded-[2rem] p-6">
          <div class="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
            <div><p class="mono text-[0.68rem] uppercase tracking-[0.3em] text-cyan-300">Comparison Grid</p><h3 class="mt-2 font-display text-2xl font-bold text-white">Segment-by-Segment Delta Table</h3></div>
            <div class="rounded-2xl border border-cyan-400/15 bg-cyan-400/5 px-4 py-3"><p id="episodeChangedCount" class="mono text-lg text-cyan-200"></p><p class="text-xs uppercase tracking-[0.2em] text-slate-400">changed rows</p></div>
          </div>
          <div class="mt-6 overflow-hidden rounded-[1.75rem] border border-slate-800">
            <div class="overflow-x-auto">
              <table class="min-w-full bg-slate-950/30 text-left text-sm">
                <thead class="border-b border-slate-800 bg-slate-950/60 text-xs uppercase tracking-[0.2em] text-slate-400"><tr><th class="px-4 py-4">Segment</th><th class="px-4 py-4">Window</th><th class="px-4 py-4">Old Solution</th><th class="px-4 py-4">New Solution</th><th class="px-4 py-4">Delta</th></tr></thead>
                <tbody id="episodeComparisonBody"></tbody>
              </table>
            </div>
          </div>
        </div>
      </section>

      <section id="authority" class="grid gap-6 xl:grid-cols-[1.15fr,0.85fr]">
        <div class="panel rounded-[2rem] p-6">
          <div class="flex items-start justify-between gap-4">
            <div><p class="mono text-[0.68rem] uppercase tracking-[0.3em] text-emerald-300">Rule Authority Status</p><h3 class="mt-2 font-display text-2xl font-bold text-white">Current Master Version</h3></div>
            <div id="syncBadge" class="rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em]"></div>
          </div>
          <div class="mt-6 grid gap-4 md:grid-cols-2">
            <div class="rounded-3xl border border-emerald-400/15 bg-slate-950/40 p-5"><p class="text-sm text-slate-400">Master Version</p><p id="masterVersion" class="mt-2 mono text-xl text-white"></p><p id="authorityMode" class="mt-3 text-sm text-emerald-300"></p></div>
            <div class="rounded-3xl border border-cyan-400/15 bg-slate-950/40 p-5"><p class="text-sm text-slate-400">Policy Window</p><p id="effectiveAt" class="mt-2 text-sm text-white"></p><p id="policyStamp" class="mt-3 text-sm text-cyan-300"></p></div>
          </div>
          <div class="mt-6 rounded-3xl border border-slate-800 bg-slate-950/30 p-5">
            <div class="flex items-center justify-between gap-3"><p class="font-semibold text-white">Canonical Policy Snapshot</p><span id="sourceCounter" class="mono text-xs uppercase tracking-[0.2em] text-slate-400"></span></div>
            <div id="summaryLines" class="mt-4 space-y-3 text-sm leading-6 text-slate-300"></div>
          </div>
        </div>
        <div class="panel rounded-[2rem] p-6">
          <div class="flex items-start justify-between gap-4">
            <div><p class="mono text-[0.68rem] uppercase tracking-[0.3em] text-cyan-300">Discord Sync Surface</p><h3 class="mt-2 font-display text-2xl font-bold text-white">Main Channel Coverage</h3></div>
            <div class="rounded-2xl border border-cyan-400/15 bg-cyan-400/5 px-3 py-2 text-right"><p id="coveragePct" class="mono text-lg text-cyan-200"></p><p class="text-[0.68rem] uppercase tracking-[0.2em] text-slate-400">coverage</p></div>
          </div>
          <div id="channelList" class="mt-6 space-y-3"></div>
          <div class="mt-6 rounded-3xl border border-slate-800 bg-slate-950/30 p-5"><p class="font-semibold text-white">Recent Harvest Markers</p><div id="markerList" class="mt-4 space-y-3 text-sm text-slate-300"></div></div>
        </div>
      </section>

      <section id="economy" class="grid gap-6 xl:grid-cols-[1.1fr,0.9fr]">
        <div class="panel rounded-[2rem] p-6">
          <div class="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
            <div><p class="mono text-[0.68rem] uppercase tracking-[0.3em] text-amber-300">Token Economy Monitor</p><h3 class="mt-2 font-display text-2xl font-bold text-white">Prose-heavy Rules vs Atomic Rules</h3></div>
            <div class="rounded-2xl border border-amber-400/15 bg-amber-400/5 px-4 py-3"><p id="savingsPct" class="mono text-lg text-amber-200"></p><p class="text-xs uppercase tracking-[0.2em] text-slate-400">estimated savings</p></div>
          </div>
          <div class="mt-6 rounded-3xl border border-slate-800 bg-slate-950/30 p-4"><canvas id="economyChart" height="180"></canvas></div>
        </div>
        <div class="panel rounded-[2rem] p-6">
          <p class="mono text-[0.68rem] uppercase tracking-[0.3em] text-emerald-300">Chunk Compression Ledger</p>
          <h3 class="mt-2 font-display text-2xl font-bold text-white">Why the Vault Is Cheaper</h3>
          <div class="mt-5 grid gap-4 md:grid-cols-2">
            <div class="rounded-3xl border border-slate-800 bg-slate-950/30 p-5"><p class="text-sm text-slate-400">Prose-heavy Load</p><p id="proseTotal" class="mt-2 mono text-2xl text-white"></p></div>
            <div class="rounded-3xl border border-slate-800 bg-slate-950/30 p-5"><p class="text-sm text-slate-400">Atomic Chunk Load</p><p id="atomicTotal" class="mt-2 mono text-2xl text-white"></p></div>
          </div>
          <div id="economyRows" class="mt-6 space-y-3"></div>
        </div>
      </section>

      <section id="staging" class="panel rounded-[2rem] p-6">
        <div class="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div><p class="mono text-[0.68rem] uppercase tracking-[0.3em] text-cyan-300">The Staging Area</p><h3 class="mt-2 font-display text-2xl font-bold text-white">Recent Discord Manager Updates Awaiting Promotion</h3></div>
          <div class="rounded-2xl border border-cyan-400/15 bg-cyan-400/5 px-4 py-3"><p id="pendingCount" class="mono text-lg text-cyan-200"></p><p class="text-xs uppercase tracking-[0.2em] text-slate-400">rows in queue</p></div>
        </div>
        <p id="stagingNote" class="mt-4 text-sm leading-6 text-slate-400"></p>
        <div class="mt-6 overflow-hidden rounded-[1.75rem] border border-slate-800">
          <div class="overflow-x-auto">
            <table class="min-w-full bg-slate-950/30 text-left text-sm">
              <thead class="border-b border-slate-800 bg-slate-950/60 text-xs uppercase tracking-[0.2em] text-slate-400"><tr><th class="px-4 py-4">Rule Chunk</th><th class="px-4 py-4">Source</th><th class="px-4 py-4">Confidence</th><th class="px-4 py-4">Value</th><th class="px-4 py-4">Actions</th></tr></thead>
              <tbody id="stagingBody"></tbody>
            </table>
          </div>
        </div>
      </section>

      <section id="retrieval" class="grid gap-6 xl:grid-cols-[1.05fr,0.95fr]">
        <div class="panel rounded-[2rem] p-6">
          <p class="mono text-[0.68rem] uppercase tracking-[0.3em] text-emerald-300">Rule Retrieval Map</p>
          <h3 class="mt-2 font-display text-2xl font-bold text-white">Selective Context for the Python Runtime</h3>
          <div id="flowNodes" class="mt-6 grid gap-4 md:grid-cols-5"></div>
          <div class="mt-6 rounded-3xl border border-slate-800 bg-slate-950/30 p-5"><div class="flex flex-wrap items-center gap-3"><span class="rounded-full border border-emerald-400/20 bg-emerald-400/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-emerald-200">Task: <span id="taskLabel"></span></span><span class="rounded-full border border-cyan-400/20 bg-cyan-400/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-cyan-200">Trigger: <span id="triggerLabel"></span></span></div><p class="mt-4 text-sm leading-7 text-slate-400">The runtime uses bounded retrieval: it injects only rule chunks that overlap the current task, instead of replaying entire Discord conversations.</p></div>
        </div>
        <div class="panel rounded-[2rem] p-6">
          <p class="mono text-[0.68rem] uppercase tracking-[0.3em] text-cyan-300">Relevant Rule Chunks</p>
          <h3 class="mt-2 font-display text-2xl font-bold text-white">Retrieved for the Current Task</h3>
          <div id="retrievedRules" class="mt-6 flex flex-wrap gap-3"></div>
          <div id="goldenExamples" class="mt-6 space-y-3"></div>
          <div class="mt-6 rounded-3xl border border-slate-800 bg-slate-950/30 p-5"><p class="mono text-[0.68rem] uppercase tracking-[0.3em] text-slate-400">activity log</p><div id="consoleLines" class="mt-4 space-y-2 text-sm text-slate-300"></div></div>
        </div>
      </section>
    </main>
  </div>
  <script>
    const toneClass=(t)=>t==="ok"?"border-emerald-400/20 bg-emerald-400/10 text-emerald-200":t==="warn"?"border-amber-400/20 bg-amber-400/10 text-amber-200":"border-slate-700 bg-slate-800/60 text-slate-300";
    const statusClass=(status,validationOk)=>{
      if(status==="submitted")return "border-emerald-400/20 bg-emerald-400/10 text-emerald-200";
      if(status==="disputed")return "border-rose-400/20 bg-rose-400/10 text-rose-200";
      if(validationOk===false || status==="policy_fail")return "border-amber-400/20 bg-amber-400/10 text-amber-200";
      if(status==="error")return "border-orange-400/20 bg-orange-400/10 text-orange-200";
      return "border-cyan-400/20 bg-cyan-400/10 text-cyan-200";
    };
    const esc=(v)=>String(v??"").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;").replaceAll("'","&#39;");
    const log=(line)=>{const root=document.getElementById("consoleLines");const el=document.createElement("div");el.className="rounded-2xl border border-slate-800 bg-slate-950/20 px-4 py-3";el.textContent=line;root.prepend(el);while(root.children.length>4)root.removeChild(root.lastChild);};
    document.getElementById("renderedAt").textContent=DATA.generated_at;
    document.getElementById("kpis").innerHTML=DATA.kpis.map((i)=>`<div class="rounded-[1.75rem] border border-slate-800 bg-slate-950/35 p-5"><p class="text-sm text-slate-400">${esc(i.label)}</p><p class="mt-3 font-display text-2xl font-bold text-white">${esc(i.value)}</p><p class="mt-2 text-sm text-slate-400">${esc(i.sub)}</p></div>`).join("");
    const episodeData=DATA.episodes||{};
    if(episodeData.available && episodeData.featured && episodeData.featured.episode_id){
      const featured=episodeData.featured;
      document.getElementById("featuredEpisodeId").textContent=featured.episode_id;
      document.getElementById("featuredEpisodeMeta").textContent=`Updated ${featured.modified_at} | old ${featured.old_segment_count} segments | new ${featured.new_segment_count} segments`;
      const featuredStatus=document.getElementById("featuredEpisodeStatus");
      featuredStatus.className=`rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] ${statusClass(featured.review_status, featured.validation_ok)}`;
      featuredStatus.textContent=featured.review_status.replaceAll("_"," ");
      document.getElementById("episodeStatGrid").innerHTML=[
        {label:"Changed Segments",value:featured.changed_count,sub:"rows changed by the solver"},
        {label:"Validation",value:featured.validation_ok===true?"PASS":featured.validation_ok===false?"FAIL":"UNKNOWN",sub:`${featured.segment_count} segments checked`},
        {label:"Runtime State",value:featured.labels_ready?"labels ready":"labels pending",sub:featured.last_error||"no runtime error captured"},
      ].map((item)=>`<div class="rounded-3xl border border-slate-800 bg-slate-950/20 p-4"><p class="text-sm text-slate-400">${esc(item.label)}</p><p class="mt-2 font-display text-2xl font-bold text-white">${esc(item.value)}</p><p class="mt-2 text-xs text-slate-500">${esc(item.sub)}</p></div>`).join("");
      document.getElementById("episodeArtifacts").innerHTML=(featured.artifacts.length?featured.artifacts.map((item)=>`<a href="${encodeURI(item.path)}" class="flex items-center justify-between gap-4 rounded-3xl border border-slate-800 bg-slate-950/20 px-4 py-3 transition hover:border-cyan-400/20 hover:bg-cyan-400/5"><div><p class="font-semibold text-white">${esc(item.label)}</p><p class="mt-1 mono text-xs text-cyan-300">${esc(item.path)}</p></div><p class="text-xs text-slate-400">${esc(item.size)}</p></a>`).join(""):`<div class="rounded-3xl border border-slate-800 bg-slate-950/20 px-4 py-3 text-slate-400">No local artifact files were found for the featured episode.</div>`);
      document.getElementById("episodeValidation").innerHTML=[
        `<div class="rounded-3xl border border-slate-800 bg-slate-950/20 px-4 py-3"><p class="font-semibold text-white">Task URL</p><a href="${esc(featured.task_url)}" class="mt-2 inline-block text-sm text-cyan-300 hover:text-cyan-200" target="_blank" rel="noreferrer">${esc(featured.task_url)}</a></div>`,
        `<div class="rounded-3xl border border-slate-800 bg-slate-950/20 px-4 py-3"><p class="font-semibold text-white">Validation Errors</p>${featured.validation_errors.length?`<ul class="mt-3 space-y-2 text-sm text-amber-200">${featured.validation_errors.map((line)=>`<li class="rounded-2xl border border-amber-400/15 bg-amber-400/5 px-3 py-2">${esc(line)}</li>`).join("")}</ul>`:`<p class="mt-3 text-sm text-slate-400">No validation errors recorded.</p>`}</div>`,
        `<div class="rounded-3xl border border-slate-800 bg-slate-950/20 px-4 py-3"><p class="font-semibold text-white">Warnings + Submission</p><p class="mt-3 text-sm text-slate-300">${featured.validation_warnings.length?featured.validation_warnings.map((line)=>esc(line)).join(" | "):"No validation warnings recorded."}</p><p class="mt-3 text-sm text-slate-400">${featured.submission_ready?"Submission evidence exists for this episode.":"No submission evidence captured yet."}</p></div>`
      ].join("");
      document.getElementById("oldSolutionText").textContent=featured.old_text||"No old solution text found.";
      document.getElementById("newSolutionText").textContent=featured.new_text||"No new solution text found.";
      document.getElementById("episodeChangedCount").textContent=String(featured.changed_count);
      document.getElementById("episodeComparisonBody").innerHTML=(featured.comparison_rows.length?featured.comparison_rows.map((row)=>`<tr class="border-b border-slate-800/80 align-top"><td class="px-4 py-4 mono text-xs text-slate-400">${esc(row.index)}</td><td class="px-4 py-4 mono text-xs text-slate-500">${esc(row.window)}</td><td class="px-4 py-4 text-slate-300">${esc(row.old_label||"")}</td><td class="px-4 py-4 text-white">${esc(row.new_label||"")}</td><td class="px-4 py-4"><span class="rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] ${row.status==="same"?"border-emerald-400/20 bg-emerald-400/10 text-emerald-200":row.status==="changed"?"border-amber-400/20 bg-amber-400/10 text-amber-200":"border-slate-700 bg-slate-800/60 text-slate-300"}">${esc(row.status)}</span></td></tr>`).join(""):`<tr><td colspan="5" class="px-4 py-8 text-center text-slate-400">No comparison rows are available for the featured episode.</td></tr>`);
      document.getElementById("episodeTotal").textContent=`${episodeData.total} episodes indexed`;
      document.getElementById("episodeStatusCounts").innerHTML=Object.entries(episodeData.status_counts||{}).map(([key,value])=>`<span class="rounded-full border px-3 py-2 text-xs font-semibold uppercase tracking-[0.2em] ${statusClass(key,null)}">${esc(key.replaceAll("_"," "))}: ${esc(value)}</span>`).join("");
      document.getElementById("recentEpisodeCards").innerHTML=(episodeData.recent||[]).map((item)=>`<div class="rounded-[1.75rem] border border-slate-800 bg-slate-950/25 p-4"><div class="flex flex-wrap items-start justify-between gap-3"><div><p class="mono text-sm text-white">${esc(item.episode_id)}</p><p class="mt-2 text-sm text-slate-400">${esc(item.modified_at)}</p></div><div class="rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] ${statusClass(item.review_status, item.validation_ok)}">${esc(item.review_status.replaceAll("_"," "))}</div></div><div class="mt-4 grid gap-3 md:grid-cols-3"><div><p class="text-xs uppercase tracking-[0.18em] text-slate-500">old</p><p class="mt-2 text-sm text-white">${esc(item.old_segment_count)}</p></div><div><p class="text-xs uppercase tracking-[0.18em] text-slate-500">new</p><p class="mt-2 text-sm text-white">${esc(item.new_segment_count)}</p></div><div><p class="text-xs uppercase tracking-[0.18em] text-slate-500">changed</p><p class="mt-2 text-sm text-cyan-200">${esc(item.changed_count)}</p></div></div><p class="mt-4 text-sm text-slate-400">${esc(item.last_error||"No runtime error captured.")}</p><a href="${esc(item.task_url)}" target="_blank" rel="noreferrer" class="mt-4 inline-flex text-sm text-cyan-300 hover:text-cyan-200">Open task</a></div>`).join("");
      document.getElementById("episodeUtilityLinks").innerHTML=[
        episodeData.viewer_path?`<a href="${encodeURI(episodeData.viewer_path)}" class="inline-flex items-center gap-2 rounded-2xl border border-fuchsia-400/20 bg-fuchsia-400/10 px-4 py-3 text-sm font-medium text-fuchsia-200 transition hover:bg-fuchsia-400/15">Open Review Viewer</a>`:"",
        episodeData.review_index_path?`<a href="${encodeURI(episodeData.review_index_path)}" class="inline-flex items-center gap-2 rounded-2xl border border-cyan-400/20 bg-cyan-400/10 px-4 py-3 text-sm font-medium text-cyan-200 transition hover:bg-cyan-400/15">Open Review Index JSON</a>`:""
      ].filter(Boolean).join("");
    }else{
      document.getElementById("featuredEpisodeId").textContent="No episode review data available";
      document.getElementById("featuredEpisodeMeta").textContent="Generate outputs/episodes_review_index.json to populate this section.";
      document.getElementById("featuredEpisodeStatus").className="rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] border-slate-700 bg-slate-800/60 text-slate-300";
      document.getElementById("featuredEpisodeStatus").textContent="awaiting data";
      document.getElementById("episodeStatGrid").innerHTML='<div class="rounded-3xl border border-slate-800 bg-slate-950/20 p-4 text-sm text-slate-400">No episode intelligence artifacts found yet.</div>';
      document.getElementById("episodeArtifacts").innerHTML='<div class="rounded-3xl border border-slate-800 bg-slate-950/20 px-4 py-3 text-slate-400">No episode bundle files were found.</div>';
      document.getElementById("episodeValidation").innerHTML='<div class="rounded-3xl border border-slate-800 bg-slate-950/20 px-4 py-3 text-slate-400">Validation data will appear here after the review index is generated.</div>';
      document.getElementById("oldSolutionText").textContent="No old solution text found.";
      document.getElementById("newSolutionText").textContent="No new solution text found.";
      document.getElementById("episodeComparisonBody").innerHTML='<tr><td colspan="5" class="px-4 py-8 text-center text-slate-400">No comparison rows are available.</td></tr>';
      document.getElementById("episodeChangedCount").textContent="0";
      document.getElementById("episodeTotal").textContent="0 episodes indexed";
      document.getElementById("recentEpisodeCards").innerHTML='<div class="rounded-[1.75rem] border border-slate-800 bg-slate-950/25 p-4 text-sm text-slate-400">Recent episode cards will appear here once review artifacts exist.</div>';
    }
    const auth=DATA.rule_authority;
    document.getElementById("masterVersion").textContent=auth.master_version;
    document.getElementById("authorityMode").textContent=auth.authority_mode.replaceAll("_"," ");
    document.getElementById("effectiveAt").textContent=`Effective: ${auth.effective_at}`;
    document.getElementById("policyStamp").textContent=`Generated: ${auth.generated_at}`;
    document.getElementById("sourceCounter").textContent=`${auth.active_rules} active promoted rules | ${auth.source_count} traced sources`;
    const badge=document.getElementById("syncBadge");badge.className=`rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] ${toneClass(auth.sync.tone)}`;badge.textContent=auth.sync.state;
    document.getElementById("summaryLines").innerHTML=auth.summary_lines.map((line)=>`<div class="rounded-2xl border border-slate-800 bg-slate-950/20 px-4 py-3">${esc(line)}</div>`).join("");
    document.getElementById("coveragePct").textContent=`${auth.sync.coverage_pct.toFixed(1)}%`;
    document.getElementById("channelList").innerHTML=auth.sync.channel_rows.map((item)=>`<div class="flex items-start justify-between gap-4 rounded-3xl border border-slate-800 bg-slate-950/25 p-4"><div><p class="font-semibold text-white">${esc(item.name)}</p><p class="mt-1 text-sm text-slate-400">${esc(item.source)}</p></div><div class="rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] ${toneClass(item.tone)}">${esc(item.state)}</div></div>`).join("");
    document.getElementById("markerList").innerHTML=(auth.sync.recent_markers.length?auth.sync.recent_markers.map((m)=>`<div class="rounded-2xl border border-slate-800 bg-slate-950/20 px-4 py-3"><p class="font-medium text-white">${esc(m.label)}</p><p class="mt-1 mono text-xs text-slate-500">${esc(m.path)}</p><p class="mt-2 text-sm text-slate-400">Updated ${esc(m.updated_at.replace("T"," ").replace("+00:00"," UTC"))}</p></div>`).join(""):`<div class="rounded-2xl border border-slate-800 bg-slate-950/20 px-4 py-3 text-slate-400">No recent Discord markers found.</div>`);
    const discord=DATA.discord_ops||{};
    const bot=discord.bot||{};
    const ruleSync=discord.rule_sync||{};
    const feedback=discord.feedback||{};
    const reviewExport=discord.review_export||{};
    const discordBadge=document.getElementById("discordBotBadge");
    discordBadge.className=`rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] ${toneClass(bot.tone||"idle")}`;
    discordBadge.textContent=(bot.state||"awaiting_status_file").replaceAll("_"," ");
    document.getElementById("discordOpsCards").innerHTML=[
      {label:"Bot Health",value:(bot.state||"awaiting_status_file").replaceAll("_"," "),sub:`ready ${bot.ready_at||"Unknown"} | export ${bot.last_history_export_at||"Unknown"}`},
      {label:"Rule Sync",value:`${ruleSync.message_count||0} msgs / ${ruleSync.channel_count||0} chans`,sub:`promoted ${ruleSync.promoted_count||0} | generated ${ruleSync.generated_at||"Unknown"}`},
      {label:"Feedback Collector",value:(feedback.state||"unknown").replaceAll("_"," "),sub:`episodes ${feedback.episodes_collected||0} | entries ${feedback.feedback_entries_found||0}`},
      {label:"Review Export",value:`${reviewExport.total||0} indexed`,sub:`generated ${reviewExport.generated_at||"Unknown"}`},
    ].map((item)=>`<div class="rounded-[1.75rem] border border-slate-800 bg-slate-950/25 p-4"><p class="text-sm text-slate-400">${esc(item.label)}</p><p class="mt-3 font-display text-2xl font-bold text-white">${esc(item.value)}</p><p class="mt-2 text-sm text-slate-400">${esc(item.sub)}</p></div>`).join("");
    document.getElementById("discordCommandMeta").textContent=`Command channel ${esc(bot.command_channel_id||"unconfigured")} | targets ${esc((bot.target_channel_ids||[]).join(", ")||"none")} | last command: ${esc(bot.last_command||"none")}`;
    document.getElementById("discordCommandList").innerHTML=(discord.commands||[]).map((item)=>`<div class="rounded-3xl border border-slate-800 bg-slate-950/20 px-4 py-3"><p class="mono text-xs text-cyan-300">${esc(item.command)}</p><p class="mt-2 text-sm text-slate-400">${esc(item.description)}</p></div>`).join("");
    document.getElementById("discordReviewTotal").textContent=String(reviewExport.total||0);
    document.getElementById("discordReviewGenerated").textContent=`Latest export: ${reviewExport.generated_at||"Unknown"} | Feedback run: ${feedback.generated_at||"Unknown"}`;
    document.getElementById("discordReviewLines").innerHTML=(reviewExport.status_lines&&reviewExport.status_lines.length?reviewExport.status_lines.map((line)=>`<span class="rounded-full border border-fuchsia-400/20 bg-fuchsia-400/10 px-3 py-2 text-xs font-semibold uppercase tracking-[0.2em] text-fuchsia-200">${esc(line)}</span>`).join(""):`<span class="rounded-full border border-slate-700 bg-slate-800/60 px-3 py-2 text-xs font-semibold uppercase tracking-[0.2em] text-slate-300">No review status counts yet</span>`);
    document.getElementById("discordAlerts").innerHTML=(discord.alerts||[]).map((item)=>`<div class="rounded-3xl border border-slate-800 bg-slate-950/25 p-4"><div class="flex items-start justify-between gap-3"><p class="font-semibold text-white">${esc(item.title)}</p><span class="rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] ${toneClass(item.tone||"idle")}">${esc((item.tone||"idle").replaceAll("_"," "))}</span></div><p class="mt-3 text-sm text-slate-400">${esc(item.detail)}</p></div>`).join("");
    const eco=DATA.token_economy;
    document.getElementById("savingsPct").textContent=`${eco.savings_pct.toFixed(1)}%`;
    document.getElementById("proseTotal").textContent=`${eco.prose_total} tokens`;
    document.getElementById("atomicTotal").textContent=`${eco.atomic_total} tokens`;
    document.getElementById("economyRows").innerHTML=eco.detail_rows.map((r)=>`<div class="rounded-3xl border border-slate-800 bg-slate-950/25 p-4"><div class="flex flex-wrap items-center justify-between gap-3"><p class="font-semibold text-white">${esc(r.label)}</p><p class="mono text-xs uppercase tracking-[0.2em] text-emerald-300">-${esc(r.saved)} tokens</p></div><p class="mt-3 text-sm text-slate-400">Prose: ${esc(r.raw_text)}</p><p class="mt-2 mono text-xs text-cyan-300">Atomic: ${esc(r.atomic_repr)}</p></div>`).join("");
    new Chart(document.getElementById("economyChart"),{type:"bar",data:{labels:eco.labels,datasets:[{label:"Prose-heavy Rules",data:eco.prose,borderRadius:10,backgroundColor:"rgba(245,158,11,.82)"},{label:"Atomic Rules",data:eco.atomic,borderRadius:10,backgroundColor:"rgba(52,211,153,.82)"}]},options:{responsive:true,plugins:{legend:{labels:{color:"#cbd5e1",usePointStyle:true,boxWidth:8}}},scales:{x:{ticks:{color:"#94a3b8"},grid:{display:false}},y:{ticks:{color:"#94a3b8"},grid:{color:"rgba(148,163,184,.12)"}}}}});
    const staging=DATA.staging;
    document.getElementById("pendingCount").textContent=staging.pending_count;
    document.getElementById("stagingNote").textContent=staging.note||"Promotion controls are ready. Approve or reject to simulate movement into production.";
    document.getElementById("stagingBody").innerHTML=staging.rows.map((r,i)=>`<tr data-row="${i}" class="border-b border-slate-800/80 align-top"><td class="px-4 py-4"><p class="font-semibold text-white">${esc(r.summary)}</p><p class="mt-2 mono text-xs text-cyan-300">${esc(r.field_path)} | ${esc(r.rule_id)}</p><p class="mt-2 text-xs text-slate-500 state">${esc(r.status)}${r.is_demo?" | demo":""}</p></td><td class="px-4 py-4"><p class="text-white">${esc(r.author)}</p><p class="mt-2 text-sm text-slate-400">${esc(r.channel)}</p><p class="mt-2 text-xs text-slate-500">${esc(r.timestamp)} | ${esc(r.age)}</p></td><td class="px-4 py-4"><div class="inline-flex rounded-full border border-emerald-400/20 bg-emerald-400/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-emerald-200">${esc(r.confidence)}%</div><p class="mt-2 text-xs text-slate-500">${esc(r.trust_tier)}</p></td><td class="px-4 py-4 text-sm text-slate-300">${esc(r.value_preview)}</td><td class="px-4 py-4"><div class="flex flex-wrap gap-2"><button data-act="approve" data-row="${i}" class="rounded-2xl border border-emerald-400/20 bg-emerald-400/10 px-3 py-2 text-xs font-semibold uppercase tracking-[0.2em] text-emerald-200">Approve</button><button data-act="reject" data-row="${i}" class="rounded-2xl border border-rose-400/20 bg-rose-400/10 px-3 py-2 text-xs font-semibold uppercase tracking-[0.2em] text-rose-200">Reject</button></div></td></tr>`).join("");
    document.getElementById("stagingBody").addEventListener("click",(e)=>{const btn=e.target.closest("button[data-act]");if(!btn)return;const row=btn.closest("tr");const idx=Number(btn.dataset.row);const act=btn.dataset.act;const item=staging.rows[idx];if(!row||!item)return;item.status=act==="approve"?"promoted_local":"rejected_local";row.classList.add("flash");row.querySelector(".state").textContent=`${item.status}${item.is_demo?" | demo":""}`;row.querySelectorAll("button").forEach((b)=>b.disabled=true);btn.textContent=act==="approve"?"Approved":"Rejected";document.getElementById("pendingCount").textContent=staging.rows.filter((x)=>!String(x.status).includes("_local")).length;log(`${act==="approve"?"Promotion simulated":"Rejection simulated"} for ${item.field_path}.`);});
    const ret=DATA.retrieval_map;
    document.getElementById("taskLabel").textContent=ret.task;
    document.getElementById("triggerLabel").textContent=ret.trigger;
    document.getElementById("flowNodes").innerHTML=ret.nodes.map((n,i)=>`<div class="rounded-3xl border border-slate-800 bg-slate-950/25 p-4"><p class="mono text-[0.65rem] uppercase tracking-[0.24em] text-slate-500">Stage ${i+1}</p><p class="mt-3 font-semibold text-white">${esc(n)}</p></div>`).join("");
    document.getElementById("retrievedRules").innerHTML=ret.rules.map((r)=>`<div class="rounded-full border border-cyan-400/20 bg-cyan-400/10 px-4 py-2 text-sm text-cyan-100">${esc(r)}</div>`).join("");
    document.getElementById("goldenExamples").innerHTML=ret.examples.map((g)=>`<div class="rounded-3xl border border-emerald-400/15 bg-emerald-400/5 p-4"><p class="mono text-[0.65rem] uppercase tracking-[0.24em] text-emerald-300">golden example</p><p class="mt-3 text-sm leading-6 text-slate-300">${esc(g)}</p></div>`).join("");
    log(`Runtime retrieval prepared for ${ret.task} using trigger ${ret.trigger}.`);
    log("JSON vault narrowed the context down to relevant canonical rules only.");
    document.getElementById("refreshBtn").addEventListener("click",()=>{["overview","authority","discordops","episodes","economy","staging","retrieval"].forEach((id,i)=>setTimeout(()=>{const node=document.getElementById(id);node.classList.remove("flash");void node.offsetWidth;node.classList.add("flash");},i*90));log("Context refresh animation completed. Runtime cache now reflects the latest local policy snapshot.");});
    lucide.createIcons();
  </script>
</body>
</html>"""


def render_dashboard_html(payload: Dict[str, Any]) -> str:
    return HTML_TEMPLATE.replace("__ATLAS_OS_DATA__", json.dumps(payload, ensure_ascii=False))


def write_dashboard(
    output_path: Path = DEFAULT_OUTPUT,
    policy_root: Path = DEFAULT_POLICY_ROOT,
    discord_dir: Path = DEFAULT_DISCORD_DIR,
    outputs_dir: Path = DEFAULT_OUTPUTS_DIR,
    review_index_path: Path = DEFAULT_REVIEW_INDEX,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_dashboard_html(
            build_dashboard_payload(
                policy_root=policy_root,
                discord_dir=discord_dir,
                outputs_dir=outputs_dir,
                review_index_path=review_index_path,
            )
        ),
        encoding="utf-8",
    )
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the Atlas OS dashboard.")
    parser.add_argument("--policy-root", default=str(DEFAULT_POLICY_ROOT))
    parser.add_argument("--discord-dir", default=str(DEFAULT_DISCORD_DIR))
    parser.add_argument("--outputs-dir", default=str(DEFAULT_OUTPUTS_DIR))
    parser.add_argument("--review-index", default=str(DEFAULT_REVIEW_INDEX))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    out = write_dashboard(
        output_path=Path(args.output),
        policy_root=Path(args.policy_root),
        discord_dir=Path(args.discord_dir),
        outputs_dir=Path(args.outputs_dir),
        review_index_path=Path(args.review_index),
    )
    print(f"Atlas OS dashboard written to {out}")
    if args.open:
        webbrowser.open(out.resolve().as_uri())


if __name__ == "__main__":
    main()
