"""
Collect Discord guideline updates from exported logs, summarize with Gemini,
and keep project policy files synchronized.

Expected flow:
1) Export channel data to JSON/TXT (manually or via configured command).
2) This collector reads new/changed export files.
3) Sends relevant updates to Gemini as structured policy extraction.
4) Writes auto-generated Discord policy overrides and syncs main policy file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import requests
import yaml
from dotenv import load_dotenv

from src.infra.solver_config import (
    FREE_GEMINI_POOL_ENV_NAMES,
    FREE_GEMINI_SINGLE_ENV_NAMES,
    choose_rotating_gemini_key,
    collect_unique_gemini_keys,
)


DEFAULTS: Dict[str, Any] = {
    "gemini": {
        "model": "gemini-3.1-pro-preview",
        "connect_timeout_sec": 30,
        "request_timeout_sec": 300,
    },
    "discord_training": {
        "enabled": True,
        "continuous": False,
        "interval_sec": 900,
        "max_cycles": 0,
        "root_dir": "outputs/training_feedback/discord",
        "runs_subdir": "runs",
        "live_subdir": "live",
        "input_dir": "outputs/discord_exports",
        "include_subdirs": True,
        "file_patterns": ["*.json", "*.txt"],
        "max_files_per_cycle": 120,
        "max_messages_in_prompt": 350,
        "max_chars_per_message": 900,
        "min_new_messages_for_gemini": 1,
        "channel_allowlist_ids": [],
        "channel_allowlist_names": [
            "atlas-rules",
        ],
        "author_allowlist": ["Frans", "Duwop"],
        "update_keywords": [
            "update",
            "new rule",
            "guideline",
            "forbidden",
            "must",
            "do not",
            "limit",
            "gripper",
            "coarse",
            "dense",
            "atomic",
            "hallucination",
        ],
        "export_command": "",
        "export_workdir": "",
        "export_timeout_sec": 180,
        "state_filename": "collector_state.json",
        "max_seen_ids": 50000,
        "policy_override_file": "data/gemini_policy_discord_live.txt",
        "sync_policy_into_main_file": True,
        "main_policy_file": "data/gemini_policy_v1.txt",
        "managed_block_start": "# BEGIN_DISCORD_LIVE_UPDATES",
        "managed_block_end": "# END_DISCORD_LIVE_UPDATES",
    },
}


load_dotenv(Path(__file__).resolve().parent / ".env", override=False)


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def cfg_get(cfg: Dict[str, Any], path: str, default: Any = None) -> Any:
    cur: Any = cfg
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def load_config(path: Path) -> Dict[str, Any]:
    raw: Dict[str, Any] = {}
    if path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            raw = loaded
    return deep_merge(DEFAULTS, raw)


def resolve_gemini_key(cfg: Dict[str, Any]) -> str:
    explicit = str(cfg_get(cfg, "gemini.api_key", "")).strip()
    keys = collect_unique_gemini_keys(
        pool_env_names=FREE_GEMINI_POOL_ENV_NAMES,
        single_env_names=FREE_GEMINI_SINGLE_ENV_NAMES,
        explicit_values=[explicit] if explicit else [],
    )
    return choose_rotating_gemini_key(
        keys,
        cursor_name="gemini_free_ops_discord",
        state_dir=Path(".state"),
    )


def normalize_space(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def safe_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def unique_run_dir(runs_root: Path, prefix: str = "discord_updates") -> Path:
    base = f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out = runs_root / base
    if not out.exists():
        out.mkdir(parents=True, exist_ok=False)
        return out
    idx = 1
    while True:
        candidate = runs_root / f"{base}_{idx}"
        if not candidate.exists():
            candidate.mkdir(parents=True, exist_ok=False)
            return candidate
        idx += 1


def file_fingerprint(path: Path) -> Dict[str, Any]:
    st = path.stat()
    return {"size": int(st.st_size), "mtime": int(st.st_mtime)}


def load_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"files": {}, "seen_ids": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"files": {}, "seen_ids": []}
    if not isinstance(data, dict):
        return {"files": {}, "seen_ids": []}
    files = data.get("files")
    seen_ids = data.get("seen_ids")
    return {
        "files": files if isinstance(files, dict) else {},
        "seen_ids": seen_ids if isinstance(seen_ids, list) else [],
    }


def save_state(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(safe_json(data), encoding="utf-8")


def run_export_command(cfg: Dict[str, Any], run_dir: Path) -> Dict[str, Any]:
    cmd = str(cfg_get(cfg, "discord_training.export_command", "")).strip()
    if not cmd:
        return {"enabled": False, "status": "skipped", "command": ""}
    timeout_sec = int(cfg_get(cfg, "discord_training.export_timeout_sec", 180))
    workdir_cfg = str(cfg_get(cfg, "discord_training.export_workdir", "")).strip()
    cwd = Path(workdir_cfg).resolve() if workdir_cfg else Path.cwd()
    started = datetime.now().isoformat()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            shell=True,
            capture_output=True,
            text=True,
            timeout=max(10, timeout_sec),
        )
        meta = {
            "enabled": True,
            "status": "ok" if proc.returncode == 0 else "error",
            "command": cmd,
            "cwd": str(cwd),
            "returncode": int(proc.returncode),
            "started_at": started,
            "finished_at": datetime.now().isoformat(),
        }
        (run_dir / "discord_export_command.json").write_text(safe_json(meta), encoding="utf-8")
        (run_dir / "discord_export_stdout.txt").write_text(proc.stdout or "", encoding="utf-8")
        (run_dir / "discord_export_stderr.txt").write_text(proc.stderr or "", encoding="utf-8")
        return meta
    except Exception as exc:
        meta = {
            "enabled": True,
            "status": "error",
            "command": cmd,
            "cwd": str(cwd),
            "error": str(exc),
            "started_at": started,
            "finished_at": datetime.now().isoformat(),
        }
        (run_dir / "discord_export_command.json").write_text(safe_json(meta), encoding="utf-8")
        return meta


def discover_input_files(cfg: Dict[str, Any], root: Path) -> List[Path]:
    input_dir_cfg = str(cfg_get(cfg, "discord_training.input_dir", "outputs/discord_exports")).strip()
    input_dir = Path(input_dir_cfg)
    if not input_dir.is_absolute():
        input_dir = (root / input_dir).resolve()
    patterns = cfg_get(cfg, "discord_training.file_patterns", ["*.json", "*.txt"])
    include_subdirs = bool(cfg_get(cfg, "discord_training.include_subdirs", True))
    max_files = int(cfg_get(cfg, "discord_training.max_files_per_cycle", 120))
    if not isinstance(patterns, list):
        patterns = ["*.json", "*.txt"]
    files: List[Path] = []
    for pat in patterns:
        pat = str(pat).strip()
        if not pat:
            continue
        found = list(input_dir.rglob(pat) if include_subdirs else input_dir.glob(pat))
        files.extend([p for p in found if p.is_file()])
    # newest first to bias prompt toward latest updates
    files = sorted(set(files), key=lambda p: p.stat().st_mtime, reverse=True)
    if max_files > 0:
        files = files[:max_files]
    return files


def _author_name(raw: Dict[str, Any]) -> str:
    author = raw.get("author")
    if isinstance(author, dict):
        return normalize_space(author.get("name") or author.get("username") or author.get("displayName"))
    if isinstance(author, str):
        return normalize_space(author)
    for key in ("author_name", "username", "user", "sender"):
        if raw.get(key):
            return normalize_space(raw.get(key))
    return ""


def _message_content(raw: Dict[str, Any]) -> str:
    for key in ("content", "message", "text", "body"):
        if raw.get(key):
            return normalize_space(raw.get(key))
    return ""


def _attachments(raw: Dict[str, Any]) -> List[str]:
    atts = raw.get("attachments")
    out: List[str] = []
    if isinstance(atts, list):
        for item in atts:
            if isinstance(item, dict):
                val = item.get("url") or item.get("proxy_url") or item.get("filename") or item.get("name")
                if val:
                    out.append(normalize_space(val))
            elif isinstance(item, str):
                out.append(normalize_space(item))
    return [x for x in out if x]


def infer_channel_name_from_source(source_file: str) -> str:
    stem = normalize_space(Path(source_file).stem).lower()
    if not stem:
        return ""
    normalized = re.sub(r"[\s_]+", "-", stem)
    candidates = (
        "level-3-announcements",
        "daily-tips",
        "level-3-questions",
    )
    for channel_name in candidates:
        if channel_name in normalized:
            return channel_name
    return ""


def parse_discord_json_payload(data: Any, source_file: str = "") -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = []
    default_channel_id = ""
    default_channel_name = ""
    if isinstance(data, dict):
        ch = data.get("channel")
        if isinstance(ch, dict):
            default_channel_id = normalize_space(ch.get("id"))
            default_channel_name = normalize_space(ch.get("name"))
    raw_messages: Any = []
    if isinstance(data, dict):
        if isinstance(data.get("messages"), list):
            raw_messages = data.get("messages")
        elif isinstance(data.get("data"), list):
            raw_messages = data.get("data")
    elif isinstance(data, list):
        raw_messages = data
    if not isinstance(raw_messages, list):
        return messages

    for idx, raw in enumerate(raw_messages, start=1):
        if not isinstance(raw, dict):
            continue
        msg_id = normalize_space(raw.get("id") or raw.get("message_id"))
        timestamp = normalize_space(raw.get("timestamp") or raw.get("createdAt") or raw.get("created_at"))
        author = _author_name(raw)
        content = _message_content(raw)
        channel_id = normalize_space(raw.get("channel_id") or default_channel_id)
        channel_name = normalize_space(raw.get("channel_name") or default_channel_name)
        attachments = _attachments(raw)
        if not content and not attachments:
            continue
        if not msg_id:
            hash_seed = f"{source_file}|{idx}|{author}|{timestamp}|{content}|{','.join(attachments)}"
            msg_id = "hash_" + hashlib.sha1(hash_seed.encode("utf-8")).hexdigest()[:16]
        messages.append(
            {
                "id": msg_id,
                "timestamp": timestamp,
                "author": author,
                "channel_id": channel_id,
                "channel_name": channel_name,
                "content": content,
                "attachments": attachments,
                "source_file": source_file,
            }
        )
    return messages


def parse_discord_txt_payload(text: str, source_file: str = "") -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    lines = (text or "").splitlines()
    inferred_channel = infer_channel_name_from_source(source_file)
    pattern = re.compile(
        r"^\s*(?:\[(?P<ts>[^\]]+)\]\s*)?(?P<author>[^:]{1,120}):\s*(?P<content>.+?)\s*$"
    )
    for idx, line in enumerate(lines, start=1):
        line = line.strip()
        if not line:
            continue
        m = pattern.match(line)
        if m:
            ts = normalize_space(m.group("ts"))
            author = normalize_space(m.group("author"))
            content = normalize_space(m.group("content"))
        else:
            ts = ""
            author = ""
            content = normalize_space(line)
        if not content:
            continue
        msg_id = f"txt_{Path(source_file).name}_{idx}"
        out.append(
            {
                "id": msg_id,
                "timestamp": ts,
                "author": author,
                "channel_id": "",
                "channel_name": inferred_channel,
                "content": content,
                "attachments": [],
                "source_file": source_file,
            }
        )
    return out


def parse_input_file(path: Path) -> List[Dict[str, Any]]:
    suffix = path.suffix.lower()
    source = str(path)
    if suffix == ".json":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except Exception:
                return []
        return parse_discord_json_payload(data, source_file=source)
    if suffix == ".txt":
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            try:
                text = path.read_text(encoding="utf-8-sig")
            except Exception:
                return []
        return parse_discord_txt_payload(text, source_file=source)
    return []


def _allowed(value: str, allowlist: Iterable[str]) -> bool:
    value_l = normalize_space(value).lower()
    vals = [normalize_space(x).lower() for x in allowlist if normalize_space(x)]
    if not vals:
        return True
    return any(v == value_l or v in value_l for v in vals)


def message_is_relevant(msg: Dict[str, Any], cfg: Dict[str, Any]) -> bool:
    content_l = normalize_space(msg.get("content", "")).lower()
    author = normalize_space(msg.get("author", ""))
    channel_id = normalize_space(msg.get("channel_id", ""))
    channel_name = normalize_space(msg.get("channel_name", ""))
    has_media = bool(msg.get("attachments"))
    ids = cfg_get(cfg, "discord_training.channel_allowlist_ids", []) or []
    names = cfg_get(cfg, "discord_training.channel_allowlist_names", []) or []
    authors = cfg_get(cfg, "discord_training.author_allowlist", []) or []
    keywords = cfg_get(cfg, "discord_training.update_keywords", []) or []
    source_file_l = normalize_space(msg.get("source_file", "")).lower()

    channel_ok = (not ids and not names) or _allowed(channel_id, ids) or _allowed(channel_name, names)
    if not channel_ok and source_file_l:
        normalized_source = source_file_l.replace("_", "-").replace(" ", "-")
        if ids:
            channel_ok = any(normalize_space(x).lower() in normalized_source for x in ids if normalize_space(x))
        if not channel_ok and names:
            channel_ok = any(
                normalize_space(x).lower().replace("_", "-").replace(" ", "-") in normalized_source
                for x in names
                if normalize_space(x)
            )
    author_ok = (not authors) or _allowed(author, authors)
    keyword_ok = any(normalize_space(k).lower() in content_l for k in keywords if normalize_space(k))

    # Keep:
    # - Explicit channel+author governance messages
    # - Channel+keyword updates
    # - Channel messages with media and keywords (example screenshots)
    return bool(channel_ok and (author_ok or keyword_ok or (has_media and keyword_ok)))


def build_gemini_prompt(messages: List[Dict[str, Any]], max_chars_per_message: int) -> str:
    lines: List[str] = []
    lines.append("Atlas Discord policy sync request.")
    lines.append("Extract ONLY actionable annotation-policy updates from these Discord messages.")
    lines.append("Prioritize explicit admin/moderator guidance and high-confidence clarifications.")
    lines.append("")
    lines.append("Return strict JSON with keys:")
    lines.append(
        "policy_updates, enforcement_notes, prompt_additions, ui_hint_updates, "
        "config_overrides, unresolved_questions, source_highlights"
    )
    lines.append("")
    lines.append("Rules:")
    lines.append("- Keep policy_updates as short imperative bullets.")
    lines.append("- Preserve strict wording for prohibitions and limits.")
    lines.append("- If no real update exists, return empty arrays/objects.")
    lines.append("")
    lines.append("Messages:")
    for msg in messages:
        content = normalize_space(msg.get("content", ""))
        if max_chars_per_message > 0 and len(content) > max_chars_per_message:
            content = content[:max_chars_per_message].rstrip() + " ..."
        parts = [
            f"id={msg.get('id', '')}",
            f"author={msg.get('author', '')}",
            f"channel={msg.get('channel_name', '') or msg.get('channel_id', '')}",
            f"time={msg.get('timestamp', '')}",
        ]
        lines.append(f"- [{' | '.join(parts)}] {content}")
        atts = msg.get("attachments") or []
        if atts:
            lines.append(f"  attachments={json.dumps(atts, ensure_ascii=False)}")
    return "\n".join(lines)


def parse_json_object_maybe(text: str) -> Dict[str, Any]:
    raw = normalize_space(text)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    fence_match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text, flags=re.IGNORECASE)
    if fence_match:
        fenced_text = fence_match.group(1).strip()
        try:
            parsed = json.loads(fenced_text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    obj_match = re.search(r"(\{[\s\S]*\})", text)
    if obj_match:
        obj_text = obj_match.group(1).strip()
        try:
            parsed = json.loads(obj_text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return {"raw_text": text}


def call_gemini_discord_summary(cfg: Dict[str, Any], prompt_text: str) -> Dict[str, Any]:
    key = resolve_gemini_key(cfg)
    if not key:
        raise RuntimeError(
            "Missing Gemini ops key in env "
            "(GEMINI_API_KEYS_FREE_POOL / GEMINI_API_KEY_FREE_OPS / GEMINI_API_KEY_OPS)."
        )
    model = str(cfg_get(cfg, "gemini.model", "gemini-3.1-pro-preview"))
    connect_timeout = int(cfg_get(cfg, "gemini.connect_timeout_sec", 30))
    request_timeout = int(cfg_get(cfg, "gemini.request_timeout_sec", 300))
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {"Content-Type": "application/json", "X-goog-api-key": key}
    system_instruction = (
        "You are Atlas annotation policy synchronizer. "
        "Convert Discord governance messages into strict, implementation-ready rules. "
        "Do not invent policy; only extract explicit updates or high-confidence clarifications."
    )
    payload = {
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "contents": [{"role": "user", "parts": [{"text": prompt_text}]}],
        "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
    }
    resp = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=(connect_timeout, request_timeout),
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Gemini Discord summary failed: HTTP {resp.status_code}: {(resp.text or '')[:600]}")
    data = resp.json()
    text = ""
    try:
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join([str(p.get("text", "")) for p in parts if isinstance(p, dict)]).strip()
    except Exception:
        text = ""
    parsed: Dict[str, Any] = {}
    if text:
        parsed = parse_json_object_maybe(text)
    return {"http_status": 200, "raw": data, "parsed": parsed}


def normalize_policy_updates(parsed: Dict[str, Any]) -> List[str]:
    if not isinstance(parsed, dict):
        return []
    candidates: List[str] = []
    raw_updates = parsed.get("policy_updates")
    if isinstance(raw_updates, list):
        for item in raw_updates:
            if isinstance(item, str):
                candidates.append(item)
    if not candidates:
        for alt in ("rules", "updates", "prompt_additions", "enforcement_notes"):
            arr = parsed.get(alt)
            if isinstance(arr, list):
                for item in arr:
                    if isinstance(item, str):
                        candidates.append(item)
    out: List[str] = []
    seen: Set[str] = set()
    for item in candidates:
        txt = normalize_space(item).strip("-* ")
        if not txt:
            continue
        key = txt.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(txt)
    return out


def build_policy_override_text(policy_updates: List[str], sources_count: int) -> str:
    lines: List[str] = []
    lines.append("# AUTO-GENERATED FROM DISCORD UPDATES")
    lines.append(f"# generated_at: {datetime.now().isoformat()}")
    lines.append(f"# source_messages: {int(sources_count)}")
    lines.append("")
    if not policy_updates:
        lines.append("- No new actionable policy updates detected in this cycle.")
        return "\n".join(lines).strip() + "\n"
    for rule in policy_updates:
        lines.append(f"- {rule}")
    return "\n".join(lines).strip() + "\n"


def upsert_managed_block(base_text: str, start_marker: str, end_marker: str, block_body: str) -> str:
    start = normalize_space(start_marker)
    end = normalize_space(end_marker)
    body = (block_body or "").rstrip()
    managed_block = f"{start}\n{body}\n{end}\n"
    text = base_text or ""
    if start in text and end in text:
        i = text.find(start)
        j = text.find(end, i)
        if j >= 0:
            j_end = j + len(end)
            while j_end < len(text) and text[j_end] in "\r\n":
                j_end += 1
            return text[:i] + managed_block + text[j_end:]
    if text and not text.endswith("\n"):
        text += "\n"
    if text and not text.endswith("\n\n"):
        text += "\n"
    return text + managed_block


def apply_policy_sync(cfg: Dict[str, Any], root: Path, policy_updates: List[str], sources_count: int) -> Dict[str, Any]:
    override_cfg = str(cfg_get(cfg, "discord_training.policy_override_file", "data/gemini_policy_discord_live.txt")).strip()
    override_path = Path(override_cfg)
    if not override_path.is_absolute():
        override_path = (root / override_path).resolve()
    override_path.parent.mkdir(parents=True, exist_ok=True)

    override_text = build_policy_override_text(policy_updates, sources_count=sources_count)
    override_path.write_text(override_text, encoding="utf-8")

    sync_main = bool(cfg_get(cfg, "discord_training.sync_policy_into_main_file", True))
    main_updated = False
    main_path_resolved = ""
    if sync_main:
        main_cfg = str(cfg_get(cfg, "discord_training.main_policy_file", "data/gemini_policy_v1.txt")).strip()
        main_path = Path(main_cfg)
        if not main_path.is_absolute():
            main_path = (root / main_path).resolve()
        main_path_resolved = str(main_path)
        if main_path.exists():
            base_text = main_path.read_text(encoding="utf-8")
            start_marker = str(cfg_get(cfg, "discord_training.managed_block_start", "# BEGIN_DISCORD_LIVE_UPDATES"))
            end_marker = str(cfg_get(cfg, "discord_training.managed_block_end", "# END_DISCORD_LIVE_UPDATES"))
            new_text = upsert_managed_block(base_text, start_marker, end_marker, override_text.rstrip())
            if new_text != base_text:
                main_path.write_text(new_text, encoding="utf-8")
                main_updated = True

    return {
        "override_file": str(override_path),
        "main_policy_file": main_path_resolved,
        "main_policy_updated": main_updated,
    }


def _sort_key(msg: Dict[str, Any]) -> Tuple[str, str]:
    return (normalize_space(msg.get("timestamp", "")), normalize_space(msg.get("id", "")))


def collect_cycle(cfg: Dict[str, Any], root: Path, run_dir: Path, skip_gemini: bool) -> Dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    export_meta = run_export_command(cfg, run_dir)

    output_root = Path(str(cfg_get(cfg, "discord_training.root_dir", "outputs/training_feedback/discord")))
    if not output_root.is_absolute():
        output_root = (root / output_root).resolve()
    live_subdir = str(cfg_get(cfg, "discord_training.live_subdir", "live")).strip() or "live"
    live_dir = output_root / live_subdir
    live_dir.mkdir(parents=True, exist_ok=True)
    state_file = live_dir / str(cfg_get(cfg, "discord_training.state_filename", "collector_state.json")).strip()
    state = load_state(state_file)
    files_state: Dict[str, Any] = state.get("files", {}) if isinstance(state.get("files"), dict) else {}
    seen_ids_list: List[str] = []
    seen_ids_set: Set[str] = set()
    for item in state.get("seen_ids", []):
        sid = normalize_space(item)
        if not sid or sid in seen_ids_set:
            continue
        seen_ids_set.add(sid)
        seen_ids_list.append(sid)

    files = discover_input_files(cfg, root=root)
    changed_files: List[Path] = []
    current_file_state: Dict[str, Any] = {}
    for p in files:
        fp = file_fingerprint(p)
        key = str(p.resolve())
        current_file_state[key] = fp
        if files_state.get(key) != fp:
            changed_files.append(p)

    parsed_all: List[Dict[str, Any]] = []
    for p in changed_files:
        parsed_all.extend(parse_input_file(p))
    parsed_all.sort(key=_sort_key)

    relevant = [m for m in parsed_all if message_is_relevant(m, cfg)]
    new_messages: List[Dict[str, Any]] = []
    for msg in relevant:
        msg_id = normalize_space(msg.get("id"))
        if msg_id and msg_id in seen_ids_set:
            continue
        if msg_id:
            seen_ids_set.add(msg_id)
            seen_ids_list.append(msg_id)
        new_messages.append(msg)

    max_seen = int(cfg_get(cfg, "discord_training.max_seen_ids", 50000))
    if max_seen > 0 and len(seen_ids_list) > max_seen:
        seen_ids_list = seen_ids_list[-max_seen:]

    (run_dir / "discord_changed_files.json").write_text(
        safe_json([str(p) for p in changed_files]),
        encoding="utf-8",
    )
    (run_dir / "discord_new_messages.json").write_text(
        safe_json(new_messages),
        encoding="utf-8",
    )

    prompt_path = run_dir / "discord_prompt.txt"
    gemini_status = "skipped"
    parsed_resp: Dict[str, Any] = {}
    policy_updates: List[str] = []

    min_new = int(cfg_get(cfg, "discord_training.min_new_messages_for_gemini", 1))
    max_messages_in_prompt = int(cfg_get(cfg, "discord_training.max_messages_in_prompt", 350))
    max_chars_per_message = int(cfg_get(cfg, "discord_training.max_chars_per_message", 900))
    prompt_messages = new_messages[-max_messages_in_prompt:] if max_messages_in_prompt > 0 else new_messages
    prompt_text = build_gemini_prompt(prompt_messages, max_chars_per_message=max_chars_per_message)
    prompt_path.write_text(prompt_text, encoding="utf-8")

    native_rules = []
    rules_db_path = root / "rules_db.json"
    rules_db = {}
    if rules_db_path.exists():
        try:
            rules_db = json.loads(rules_db_path.read_text(encoding="utf-8"))
        except BaseException:
            pass

    patterns = [
        re.compile(r"(?i)^(?:golden rule|new rule|update):\s*(.*)"),
        re.compile(r"(?i)^(never\s+.*)"),
    ]

    for msg in prompt_messages:
        content = normalize_space(msg.get("content", ""))
        for line in content.split('\n'):
            line = line.strip()
            for p in patterns:
                m = p.match(line)
                if m:
                    r_text = m.group(1).strip()
                    if r_text:
                        native_rules.append(r_text)
                    break

    new_native_policy_updates = []
    for r in native_rules:
        tokens = " ".join(sorted(set(re.findall(r"[a-z]{3,}", r.lower()))))
        if not tokens:
            continue
        h = hashlib.md5(tokens.encode("utf-8")).hexdigest()
        if h not in rules_db:
            rules_db[h] = r
            new_native_policy_updates.append(r)

    if new_native_policy_updates:
        rules_db_path.write_text(json.dumps(rules_db, indent=2), encoding="utf-8")
        policy_updates = new_native_policy_updates
        gemini_status = "skipped_regex_sufficient"
        (run_dir / "native_discord_parsed.json").write_text(safe_json(new_native_policy_updates), encoding="utf-8")
    elif not skip_gemini and len(prompt_messages) >= max(1, min_new):
        try:
            resp = call_gemini_discord_summary(cfg, prompt_text)
            parsed_resp = resp.get("parsed", {}) if isinstance(resp, dict) else {}
            (run_dir / "gemini_discord_response.json").write_text(safe_json(resp), encoding="utf-8")
            (run_dir / "gemini_discord_parsed.json").write_text(safe_json(parsed_resp), encoding="utf-8")
            policy_updates = normalize_policy_updates(parsed_resp)
            gemini_status = "ok"
        except Exception as exc:
            (run_dir / "gemini_discord_error.txt").write_text(str(exc), encoding="utf-8")
            gemini_status = "error"
    else:
        gemini_status = "skipped_no_new_messages"

    policy_sync = apply_policy_sync(
        cfg=cfg,
        root=root,
        policy_updates=policy_updates,
        sources_count=len(prompt_messages),
    )
    (run_dir / "discord_policy_updates.json").write_text(safe_json(policy_updates), encoding="utf-8")
    (run_dir / "policy_sync_result.json").write_text(safe_json(policy_sync), encoding="utf-8")

    new_state = {
        "files": current_file_state,
        "seen_ids": seen_ids_list,
    }
    save_state(state_file, new_state)

    index = {
        "run_dir": str(run_dir),
        "generated_at": datetime.now().isoformat(),
        "export_status": export_meta.get("status", "skipped"),
        "files_scanned": len(files),
        "files_changed": len(changed_files),
        "messages_parsed": len(parsed_all),
        "messages_relevant": len(relevant),
        "messages_new": len(new_messages),
        "messages_sent_to_gemini": len(prompt_messages),
        "gemini_status": gemini_status,
        "policy_updates_count": len(policy_updates),
        "policy_override_file": policy_sync.get("override_file", ""),
        "main_policy_file": policy_sync.get("main_policy_file", ""),
        "main_policy_updated": bool(policy_sync.get("main_policy_updated", False)),
        "prompt_path": str(prompt_path),
    }
    (run_dir / "INDEX.json").write_text(safe_json(index), encoding="utf-8")
    return index


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="sample_web_auto_solver.yaml")
    parser.add_argument("--continuous", action="store_true")
    parser.add_argument("--interval-sec", type=int, default=None)
    parser.add_argument("--max-cycles", type=int, default=None)
    parser.add_argument("--skip-gemini", action="store_true")
    args = parser.parse_args()

    root = Path.cwd()
    cfg = load_config(root / args.config)
    if not bool(cfg_get(cfg, "discord_training.enabled", True)):
        raise RuntimeError("discord_training.enabled is false in config.")

    output_root_cfg = str(cfg_get(cfg, "discord_training.root_dir", "outputs/training_feedback/discord")).strip()
    output_root = Path(output_root_cfg)
    if not output_root.is_absolute():
        output_root = (root / output_root).resolve()
    runs_subdir = str(cfg_get(cfg, "discord_training.runs_subdir", "runs")).strip() or "runs"
    runs_root = output_root / runs_subdir
    output_root.mkdir(parents=True, exist_ok=True)
    runs_root.mkdir(parents=True, exist_ok=True)

    continuous = bool(args.continuous or cfg_get(cfg, "discord_training.continuous", False))
    interval_sec = int(
        args.interval_sec if args.interval_sec is not None else cfg_get(cfg, "discord_training.interval_sec", 900)
    )
    max_cycles = int(args.max_cycles if args.max_cycles is not None else cfg_get(cfg, "discord_training.max_cycles", 0))

    cycle = 0
    while True:
        cycle += 1
        run_dir = unique_run_dir(runs_root, prefix="discord_updates")
        try:
            index = collect_cycle(
                cfg=cfg,
                root=root,
                run_dir=run_dir,
                skip_gemini=bool(args.skip_gemini),
            )
            index["cycle"] = cycle
            (output_root / "latest.json").write_text(safe_json(index), encoding="utf-8")
            with (output_root / "runs_manifest.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(index, ensure_ascii=False))
                f.write("\n")
            print(f"[discord] saved: {run_dir}")
            print(f"[discord] new_messages: {index['messages_new']}")
            print(f"[discord] gemini_status: {index['gemini_status']}")
            print(f"[discord] policy_updates_count: {index['policy_updates_count']}")
        except Exception as exc:
            err = {
                "cycle": cycle,
                "status": "error",
                "error": str(exc),
                "generated_at": datetime.now().isoformat(),
                "run_dir": str(run_dir),
            }
            (run_dir / "RUN_ERROR.json").write_text(safe_json(err), encoding="utf-8")
            (output_root / "latest.json").write_text(safe_json(err), encoding="utf-8")
            with (output_root / "runs_manifest.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(err, ensure_ascii=False))
                f.write("\n")
            print(f"[discord] cycle failed: {exc}")

        if not continuous:
            break
        if max_cycles > 0 and cycle >= max_cycles:
            print(f"[discord] reached max_cycles={max_cycles}.")
            break
        wait_s = max(10, interval_sec)
        print(f"[discord] waiting {wait_s}s before next cycle...")
        time.sleep(wait_s)


if __name__ == "__main__":
    main()
