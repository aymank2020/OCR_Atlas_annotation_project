"""
Fetch Discord messages from a guild, extract canonical rule updates, and sync
the project master rule artifacts.

This script uses the Discord REST API directly with a bot token so it does not
depend on discord.py being installed.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence

import requests

from discord_updates_collector import parse_input_file
from src.policy import context_manager


DISCORD_API_BASE = "https://discord.com/api/v10"
CHANNEL_TYPES_TO_SCAN = {0, 5, 10, 11, 12}
DEFAULT_START = "2026-01-01T00:00:00+00:00"
LOCAL_EXPORT_GLOBS = (
    "discord/**/*.json",
    "discord/**/*.txt",
    "outputs/discord_exports/**/*.json",
    "outputs/discord_exports/**/*.txt",
)

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_EXPORT = PROJECT_ROOT / "outputs" / "discord_exports" / "harvest_2026-01-01_to_now.json"
DEFAULT_REPORT = PROJECT_ROOT / "outputs" / "discord_rule_sync_report.json"
GOLDEN_RULES_PATH = PROJECT_ROOT / "prompts" / "golden_rules.md"
MAIN_POLICY_TEXT_PATH = PROJECT_ROOT / "data" / "gemini_policy_v1.txt"
LIVE_POLICY_TEXT_PATH = PROJECT_ROOT / "data" / "gemini_policy_discord_live.txt"

GOLDEN_START = "<!-- BEGIN_CANONICAL_DISCORD_SYNC -->"
GOLDEN_END = "<!-- END_CANONICAL_DISCORD_SYNC -->"
MAIN_START = "# BEGIN_DISCORD_LIVE_UPDATES"
MAIN_END = "# END_DISCORD_LIVE_UPDATES"


def _load_dotenv_map(path: Path) -> Dict[str, str]:
    env_map: Dict[str, str] = {}
    if not path.exists():
        return env_map
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = str(raw or "").strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env_map[key.strip()] = value.strip().strip('"').strip("'")
    return env_map


def _read_secret(name: str, env_map: Dict[str, str]) -> str:
    return str(env_map.get(name, "") or "").strip()


def _parse_iso(text: str) -> datetime:
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
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


def _upsert_managed_block(base_text: str, start_marker: str, end_marker: str, block_body: str) -> str:
    managed = f"{start_marker}\n{block_body.rstrip()}\n{end_marker}\n"
    text = base_text or ""
    if start_marker in text and end_marker in text:
        start_idx = text.find(start_marker)
        end_idx = text.find(end_marker, start_idx)
        if end_idx >= 0:
            tail = end_idx + len(end_marker)
            while tail < len(text) and text[tail] in "\r\n":
                tail += 1
            return text[:start_idx] + managed + text[tail:]
    if text and not text.endswith("\n"):
        text += "\n"
    if text and not text.endswith("\n\n"):
        text += "\n"
    return text + managed


def _discord_get(url: str, headers: Dict[str, str], params: Dict[str, Any] | None = None) -> Any:
    while True:
        resp = requests.get(url, headers=headers, params=params, timeout=(15, 120))
        if resp.status_code == 429:
            retry_after = 1.0
            try:
                payload = resp.json()
                retry_after = float(payload.get("retry_after", 1.0))
            except Exception:
                retry_after = 1.0
            time.sleep(max(1.0, retry_after))
            continue
        if resp.status_code != 200:
            raise RuntimeError(f"Discord API failed {resp.status_code}: {(resp.text or '')[:400]}")
        return resp.json()


def fetch_guild_channels(bot_token: str, guild_id: int) -> List[Dict[str, Any]]:
    headers = {"Authorization": f"Bot {bot_token}"}
    url = f"{DISCORD_API_BASE}/guilds/{guild_id}/channels"
    payload = _discord_get(url, headers=headers)
    if not isinstance(payload, list):
        raise RuntimeError("Discord channels response was not a list.")
    channels = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        raw_type = item.get("type", -1)
        try:
            channel_type = int(raw_type)
        except Exception:
            channel_type = -1
        if channel_type not in CHANNEL_TYPES_TO_SCAN:
            continue
        channels.append(item)
    channels.sort(key=lambda row: (int(row.get("position", 0) or 0), str(row.get("name", ""))))
    return channels


def _normalize_message(raw: Dict[str, Any], channel: Dict[str, Any]) -> Dict[str, Any]:
    author = raw.get("author") if isinstance(raw.get("author"), dict) else {}
    attachments = []
    for item in raw.get("attachments", []) or []:
        if isinstance(item, dict):
            url = str(item.get("url") or item.get("proxy_url") or item.get("filename") or "").strip()
            if url:
                attachments.append(url)
    channel_name = str(channel.get("name", "") or "").strip()
    return {
        "id": str(raw.get("id", "") or "").strip(),
        "timestamp": str(raw.get("timestamp", "") or "").strip(),
        "content": str(raw.get("content", "") or "").strip(),
        "channel": f"#{channel_name}" if channel_name and not channel_name.startswith("#") else channel_name,
        "channel_id": str(channel.get("id", "") or "").strip(),
        "author": {
            "username": str(author.get("username", "") or author.get("global_name", "") or "unknown").strip(),
            "id": str(author.get("id", "") or "").strip(),
        },
        "attachments": attachments,
        "message_link": (
            f"https://discord.com/channels/"
            f"{channel.get('guild_id', '')}/{channel.get('id', '')}/{raw.get('id', '')}"
        ),
    }


def fetch_channel_messages(
    *,
    bot_token: str,
    channel: Dict[str, Any],
    after_dt: datetime,
) -> List[Dict[str, Any]]:
    headers = {"Authorization": f"Bot {bot_token}"}
    url = f"{DISCORD_API_BASE}/channels/{channel['id']}/messages"
    before: str | None = None
    out: List[Dict[str, Any]] = []

    while True:
        params: Dict[str, Any] = {"limit": 100}
        if before:
            params["before"] = before
        page = _discord_get(url, headers=headers, params=params)
        if not isinstance(page, list) or not page:
            break

        reached_older_history = False
        for raw in page:
            if not isinstance(raw, dict):
                continue
            ts_text = str(raw.get("timestamp", "") or "").strip()
            if not ts_text:
                continue
            try:
                ts = _parse_iso(ts_text)
            except Exception:
                continue
            if ts < after_dt:
                reached_older_history = True
                continue
            out.append(_normalize_message(raw, channel))

        if reached_older_history or len(page) < 100:
            break
        before = str(page[-1].get("id", "") or "").strip()
        if not before:
            break
        time.sleep(0.15)

    out.sort(key=lambda row: row.get("timestamp", ""))
    return out


def _render_policy_sync_block(
    *,
    current_policy: Dict[str, Any],
    staged_records: Sequence[Dict[str, Any]],
    fetch_stats: Dict[str, Any],
    policy_report: Dict[str, Any],
) -> str:
    summary = context_manager.build_policy_prompt_summary(policy=current_policy)
    active_promoted = [
        row
        for row in staged_records
        if str(row.get("status", "")).strip().lower() == "promoted"
    ]
    active_promoted.sort(key=lambda row: str(row.get("timestamp", "")), reverse=True)
    staged_only = [
        row
        for row in staged_records
        if str(row.get("status", "")).strip().lower() == "staged"
    ]
    staged_only.sort(key=lambda row: str(row.get("timestamp", "")), reverse=True)

    lines: List[str] = []
    lines.append("## Canonical Discord Rule Sync")
    lines.append(f"- Synced at: {_iso_now()}")
    lines.append(f"- Discord scan window: {fetch_stats['start_date']} -> {fetch_stats['end_date']}")
    lines.append(f"- Text channels scanned: {fetch_stats['channel_count']}")
    lines.append(f"- Messages fetched: {fetch_stats['message_count']}")
    lines.append(f"- Canonical candidates extracted: {policy_report.get('candidate_count', 0)}")
    lines.append(f"- Changed fields this run: {len(policy_report.get('changed_fields', []))}")
    lines.append("")
    lines.append("### Current Canonical Policy")
    for item in summary.splitlines():
        lines.append(f"- {item.lstrip('- ').strip()}")
    if active_promoted:
        lines.append("")
        lines.append("### Active Promoted Rules")
        for row in active_promoted[:12]:
            field_path = str(row.get("field_path", "") or "").strip()
            summary_text = str(row.get("summary", "") or "").strip() or field_path
            lines.append(
                f"- `{field_path}`: {summary_text} | "
                f"{row.get('author', 'unknown')} in {row.get('channel', 'unknown')} | "
                f"{row.get('timestamp', '')}"
            )
    if staged_only:
        lines.append("")
        lines.append("### Pending / Non-Promoted Candidates")
        for row in staged_only[:10]:
            field_path = str(row.get("field_path", "") or "").strip()
            lines.append(
                f"- `{field_path}`: {row.get('summary', '')} | "
                f"reason={row.get('decision_reason', 'pending')} | "
                f"{row.get('author', 'unknown')} | {row.get('timestamp', '')}"
            )
    return "\n".join(lines).rstrip()


def _normalize_local_message(raw: Dict[str, Any]) -> Dict[str, Any] | None:
    msg_id = str(raw.get("id", "") or "").strip()
    timestamp = str(raw.get("timestamp", "") or "").strip()
    if not msg_id or not timestamp:
        return None
    author_name = str(raw.get("author", "") or "unknown").strip() or "unknown"
    channel_name = str(raw.get("channel_name", "") or "").strip()
    if channel_name and not channel_name.startswith("#"):
        channel_name = f"#{channel_name}"
    attachments = raw.get("attachments", []) if isinstance(raw.get("attachments"), list) else []
    return {
        "id": msg_id,
        "timestamp": timestamp,
        "content": str(raw.get("content", "") or "").strip(),
        "channel": channel_name,
        "channel_id": str(raw.get("channel_id", "") or "").strip(),
        "author": {"username": author_name},
        "attachments": attachments,
        "source_file": str(raw.get("source_file", "") or "").strip(),
    }


def collect_local_export_messages(after_dt: datetime) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    deduped: Dict[str, Dict[str, Any]] = {}
    per_channel: Dict[str, Dict[str, Any]] = {}

    for pattern in LOCAL_EXPORT_GLOBS:
        for path in PROJECT_ROOT.glob(pattern):
            if not path.is_file():
                continue
            try:
                parsed_messages = parse_input_file(path)
            except Exception:
                continue
            for raw in parsed_messages:
                if not isinstance(raw, dict):
                    continue
                normalized = _normalize_local_message(raw)
                if normalized is None:
                    continue
                try:
                    ts = _parse_iso(str(normalized.get("timestamp", "")))
                except Exception:
                    continue
                if ts < after_dt:
                    continue
                msg_id = str(normalized["id"])
                previous = deduped.get(msg_id)
                if previous is None or str(normalized.get("timestamp", "")) > str(previous.get("timestamp", "")):
                    deduped[msg_id] = normalized
                channel_key = str(normalized.get("channel") or normalized.get("channel_id") or path.name)
                row = per_channel.setdefault(
                    channel_key,
                    {
                        "channel_id": str(normalized.get("channel_id", "") or "").strip(),
                        "channel_name": channel_key,
                        "message_count": 0,
                        "error": "",
                    },
                )
                row["message_count"] += 1

    messages = sorted(deduped.values(), key=lambda row: str(row.get("timestamp", "")))
    channels = sorted(per_channel.values(), key=lambda row: str(row.get("channel_name", "")))
    return messages, channels


def _write_master_rule_artifacts(
    *,
    fetch_stats: Dict[str, Any],
    policy_report: Dict[str, Any],
    policy_root: Path,
) -> None:
    current_policy = context_manager.load_current_policy(policy_root / "current_policy.json")
    staged_records = _read_jsonl(policy_root / "staged_rules.jsonl")
    block = _render_policy_sync_block(
        current_policy=current_policy,
        staged_records=staged_records,
        fetch_stats=fetch_stats,
        policy_report=policy_report,
    )

    GOLDEN_RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
    golden_text = GOLDEN_RULES_PATH.read_text(encoding="utf-8") if GOLDEN_RULES_PATH.exists() else ""
    GOLDEN_RULES_PATH.write_text(
        _upsert_managed_block(golden_text, GOLDEN_START, GOLDEN_END, block),
        encoding="utf-8",
    )

    MAIN_POLICY_TEXT_PATH.parent.mkdir(parents=True, exist_ok=True)
    main_text = MAIN_POLICY_TEXT_PATH.read_text(encoding="utf-8") if MAIN_POLICY_TEXT_PATH.exists() else ""
    MAIN_POLICY_TEXT_PATH.write_text(
        _upsert_managed_block(main_text, MAIN_START, MAIN_END, block),
        encoding="utf-8",
    )
    LIVE_POLICY_TEXT_PATH.write_text(block + "\n", encoding="utf-8")


def run_sync(
    *,
    start_date: str,
    export_path: Path,
    report_path: Path,
    policy_root: Path,
) -> Dict[str, Any]:
    env_map = _load_dotenv_map(PROJECT_ROOT / ".env")
    bot_token = _read_secret("DISCORD_BOT_TOKEN", env_map)
    guild_id_raw = _read_secret("DISCORD_GUILD_ID", env_map)
    if not bot_token:
        raise RuntimeError("DISCORD_BOT_TOKEN is missing in .env.")
    if not guild_id_raw:
        raise RuntimeError("DISCORD_GUILD_ID is missing in .env.")

    after_dt = _parse_iso(start_date)
    guild_id = int(guild_id_raw)
    all_messages: List[Dict[str, Any]] = []
    per_channel: List[Dict[str, Any]] = []
    source_mode = "live_discord_api"
    source_error = ""
    try:
        channels = fetch_guild_channels(bot_token, guild_id)
        for channel in channels:
            channel_row = {
                "channel_id": str(channel.get("id", "") or "").strip(),
                "channel_name": str(channel.get("name", "") or "").strip(),
                "message_count": 0,
                "error": "",
            }
            try:
                messages = fetch_channel_messages(bot_token=bot_token, channel=channel, after_dt=after_dt)
                all_messages.extend(messages)
                channel_row["message_count"] = len(messages)
            except Exception as exc:
                channel_row["error"] = str(exc)
            per_channel.append(channel_row)
    except Exception as exc:
        source_mode = "local_exports_fallback"
        source_error = str(exc)
        all_messages, per_channel = collect_local_export_messages(after_dt)

    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_payload = {
        "generated_at_utc": _iso_now(),
        "guild_id": guild_id,
        "source_mode": source_mode,
        "source_error": source_error,
        "start_date": start_date,
        "end_date": _iso_now(),
        "channel_count": len(per_channel),
        "message_count": len(all_messages),
        "channels": per_channel,
        "messages": all_messages,
    }
    export_path.write_text(json.dumps(export_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    policy_report = context_manager.ingest_message_entries(all_messages, policy_root=policy_root)
    _write_master_rule_artifacts(
        fetch_stats=export_payload,
        policy_report=policy_report,
        policy_root=policy_root,
    )

    report = {
        "generated_at_utc": _iso_now(),
        "start_date": start_date,
        "end_date": export_payload["end_date"],
        "export_path": str(export_path),
        "policy_root": str(policy_root),
        "channel_count": len(per_channel),
        "message_count": len(all_messages),
        "channels": per_channel,
        "policy_report": policy_report,
        "current_policy_path": str(policy_root / "current_policy.json"),
        "staged_rules_path": str(policy_root / "staged_rules.jsonl"),
        "golden_rules_path": str(GOLDEN_RULES_PATH),
        "main_policy_text_path": str(MAIN_POLICY_TEXT_PATH),
        "live_policy_text_path": str(LIVE_POLICY_TEXT_PATH),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Discord history into the Atlas canonical rule store.")
    parser.add_argument("--start-date", default=DEFAULT_START, help="Inclusive ISO timestamp, default 2026-01-01 UTC")
    parser.add_argument("--export-path", default=str(DEFAULT_EXPORT), help="Raw Discord export JSON path")
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT), help="Sync report JSON path")
    parser.add_argument("--policy-root", default=str(PROJECT_ROOT / "data" / "policy"), help="Canonical policy root")
    args = parser.parse_args()

    report = run_sync(
        start_date=args.start_date,
        export_path=Path(args.export_path).resolve(),
        report_path=Path(args.report_path).resolve(),
        policy_root=Path(args.policy_root).resolve(),
    )
    print(f"[discord-sync] messages={report['message_count']}")
    print(f"[discord-sync] channels={report['channel_count']}")
    print(f"[discord-sync] export={report['export_path']}")
    print(f"[discord-sync] report={Path(args.report_path).resolve()}")


if __name__ == "__main__":
    main()
