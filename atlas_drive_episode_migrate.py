"""
Migrate already-uploaded flat Drive episode artifacts into episodes/<episode_id>/ folders.
"""

from __future__ import annotations

import argparse
import configparser
import json
import os
import time
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List

import requests

from atlas_drive_episode_layout import EPISODE_FILE_PREFIXES, extract_episode_id


DEFAULT_REMOTE_NAME = "gdrive"
DEFAULT_ROOT_FOLDER_ID = os.getenv("GDRIVE_ROOT_FOLDER_ID", "1kLe9Ai7swxh9Nx2NifD9Fcodf85AfyAG")
DEFAULT_DRIVE_CHAIN = ("OCR_annotation_Atlas", "vps_outputs")
DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"


def _is_episode_remote_filename(name: str) -> bool:
    clean = os.path.basename(str(name or ""))
    if not clean or clean.startswith(".") or clean.endswith((".log", ".part")):
        return False
    return any(clean.startswith(prefix) for prefix in EPISODE_FILE_PREFIXES) and bool(extract_episode_id(clean))


def normalize_remote_listing_entry(remote_entry: str, subdir: str = "") -> str:
    clean = str(remote_entry or "").strip().strip("/")
    if not clean:
        return ""
    wanted = str(subdir or "").strip().strip("/")
    if not wanted:
        return clean
    if clean.startswith(f"{wanted}/"):
        return clean[len(wanted) + 1 :]
    needle = f"/{wanted}/"
    if needle in clean:
        return clean.split(needle, 1)[1]
    return ""


def should_migrate_remote_path(relative_path: str) -> bool:
    clean = str(relative_path or "").strip().strip("/")
    if not clean:
        return False
    path = PurePosixPath(clean)
    if clean.endswith("/") or "episodes" in path.parts:
        return False
    if len(path.parts) != 1:
        return False
    return _is_episode_remote_filename(path.name)


def build_episode_target(relative_path: str) -> str:
    clean = str(relative_path or "").strip().strip("/")
    episode_id = extract_episode_id(clean)
    if not episode_id:
        raise ValueError(f"No episode id found in path: {relative_path!r}")
    return f"episodes/{episode_id}/{PurePosixPath(clean).name}"


def plan_remote_migration(relative_paths: Iterable[str]) -> List[Dict[str, str]]:
    moves: List[Dict[str, str]] = []
    seen_targets: set[str] = set()
    for relative_path in relative_paths:
        clean = str(relative_path or "").strip()
        if not should_migrate_remote_path(clean):
            continue
        target = build_episode_target(clean)
        if target in seen_targets:
            continue
        seen_targets.add(target)
        moves.append({"source": clean.strip("/"), "target": target})
    return moves


def _load_rclone_access_token(remote_name: str = DEFAULT_REMOTE_NAME) -> str:
    config_path = Path.home() / "AppData/Roaming/rclone/rclone.conf"
    parser = configparser.ConfigParser()
    parser.read(config_path, encoding="utf-8")
    if not parser.has_section(remote_name):
        raise RuntimeError(f"rclone remote {remote_name!r} not found in {config_path}")
    token_blob = parser[remote_name].get("token", "")
    if not token_blob:
        raise RuntimeError(f"rclone remote {remote_name!r} has no OAuth token.")
    token_payload = json.loads(token_blob)
    access_token = str(token_payload.get("access_token", "")).strip()
    if not access_token:
        raise RuntimeError(f"rclone remote {remote_name!r} token has no access_token.")
    return access_token


def _drive_request(
    method: str,
    path: str,
    *,
    access_token: str,
    params: Dict[str, Any] | None = None,
    json_body: Dict[str, Any] | None = None,
    retries: int = 6,
) -> requests.Response:
    url = f"{DRIVE_API_BASE}{path}"
    headers = {"Authorization": f"Bearer {access_token}"}
    backoff = 2.0
    for attempt in range(retries):
        response = requests.request(method, url, headers=headers, params=params, json=json_body, timeout=60)
        if response.status_code < 400:
            return response
        text = response.text[:800]
        if response.status_code in {403, 429} and ("rateLimitExceeded" in text or "RATE_LIMIT_EXCEEDED" in text or "quota" in text.lower()):
            time.sleep(backoff)
            backoff = min(backoff * 2.0, 30.0)
            continue
        raise RuntimeError(f"Drive API {method} {path} failed {response.status_code}: {text}")
    raise RuntimeError(f"Drive API {method} {path} exhausted retries after rate limiting.")


def _list_children(access_token: str, parent_id: str, *, folders_only: bool = False) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    page_token = ""
    mime_filter = " and mimeType = 'application/vnd.google-apps.folder'" if folders_only else ""
    while True:
        params = {
            "q": f"'{parent_id}' in parents and trashed = false{mime_filter}",
            "fields": "nextPageToken, files(id, name, mimeType, parents)",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
            "pageSize": 1000,
        }
        if page_token:
            params["pageToken"] = page_token
        response = _drive_request("GET", "/files", access_token=access_token, params=params)
        payload = response.json()
        items.extend(payload.get("files", []))
        page_token = str(payload.get("nextPageToken", "") or "")
        if not page_token:
            break
    return items


def _ensure_child_folder(access_token: str, parent_id: str, name: str, cache: Dict[tuple[str, str], str]) -> str:
    key = (parent_id, name)
    if key in cache:
        return cache[key]
    for item in _list_children(access_token, parent_id, folders_only=True):
        if str(item.get("name", "")) == name:
            cache[key] = str(item["id"])
            return cache[key]
    response = _drive_request(
        "POST",
        "/files",
        access_token=access_token,
        params={"supportsAllDrives": "true", "fields": "id,name,parents"},
        json_body={
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id],
        },
    )
    folder_id = str(response.json()["id"])
    cache[key] = folder_id
    return folder_id


def _resolve_folder_chain(access_token: str, root_folder_id: str, parts: Iterable[str], cache: Dict[tuple[str, str], str]) -> str:
    current = root_folder_id
    for part in parts:
        current = _ensure_child_folder(access_token, current, str(part), cache)
    return current


def _move_file_to_folder(access_token: str, file_id: str, old_parent_id: str, new_parent_id: str) -> None:
    _drive_request(
        "PATCH",
        f"/files/{file_id}",
        access_token=access_token,
        params={
            "addParents": new_parent_id,
            "removeParents": old_parent_id,
            "supportsAllDrives": "true",
            "fields": "id,name,parents",
        },
    )


def list_account_items(access_token: str, root_folder_id: str, drive_chain: Iterable[str], subdir: str, cache: Dict[tuple[str, str], str]) -> tuple[str, List[Dict[str, Any]]]:
    account_folder_id = _resolve_folder_chain(access_token, root_folder_id, [*drive_chain, subdir], cache)
    return account_folder_id, _list_children(access_token, account_folder_id, folders_only=False)


def apply_remote_migration(
    *,
    remote_name: str,
    root_folder_id: str,
    drive_chain: Iterable[str],
    subdir: str,
    moves: Iterable[Dict[str, str]],
    dry_run: bool = False,
) -> Dict[str, Any]:
    access_token = _load_rclone_access_token(remote_name)
    cache: Dict[tuple[str, str], str] = {}
    account_folder_id = _resolve_folder_chain(access_token, root_folder_id, [*drive_chain, subdir], cache)
    episodes_root_id = _ensure_child_folder(access_token, account_folder_id, "episodes", cache)
    item_map = {str(item.get("name", "")): item for item in _list_children(access_token, account_folder_id, folders_only=False)}

    applied: List[Dict[str, str]] = []
    for item in moves:
        source_name = PurePosixPath(item["source"]).name
        file_info = item_map.get(source_name)
        if not file_info:
            continue
        episode_id = extract_episode_id(source_name)
        if not episode_id:
            continue
        episode_folder_id = _ensure_child_folder(access_token, episodes_root_id, episode_id, cache)
        if not dry_run:
            old_parent_id = str((file_info.get("parents") or [account_folder_id])[0])
            _move_file_to_folder(access_token, str(file_info["id"]), old_parent_id, episode_folder_id)
        applied.append(
            {
                "source": f"{subdir}/{source_name}",
                "target": f"{subdir}/episodes/{episode_id}/{source_name}",
            }
        )
        time.sleep(0.2)
    return {
        "remote": remote_name,
        "root_folder_id": root_folder_id,
        "subdir": subdir,
        "moved_count": len(applied),
        "moves": applied,
        "dry_run": dry_run,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate flat Drive episode files into per-episode folders.")
    parser.add_argument("--remote-name", default=DEFAULT_REMOTE_NAME)
    parser.add_argument("--root-folder-id", default=DEFAULT_ROOT_FOLDER_ID)
    parser.add_argument("--drive-chain", default="/".join(DEFAULT_DRIVE_CHAIN))
    parser.add_argument("--subdir", default="danatimer")
    parser.add_argument("--apply", action="store_true", help="Actually move files. Default is dry-run.")
    parser.add_argument("--limit", type=int, default=0, help="Optional max number of planned moves to execute.")
    args = parser.parse_args()

    access_token = _load_rclone_access_token(args.remote_name)
    cache: Dict[tuple[str, str], str] = {}
    _, items = list_account_items(access_token, args.root_folder_id, tuple(part for part in args.drive_chain.split("/") if part), args.subdir, cache)
    planned = plan_remote_migration([str(item.get("name", "")) for item in items])
    if args.limit > 0:
        planned = planned[: args.limit]
    summary = apply_remote_migration(
        remote_name=args.remote_name,
        root_folder_id=args.root_folder_id,
        drive_chain=tuple(part for part in args.drive_chain.split("/") if part),
        subdir=args.subdir,
        moves=planned,
        dry_run=not args.apply,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
