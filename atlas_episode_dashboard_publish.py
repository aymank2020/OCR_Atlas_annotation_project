"""
Sync live Atlas episode artifacts, rebuild review outputs, and publish them to Google Drive.
"""

from __future__ import annotations

import argparse
import csv
import json
import mimetypes
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from atlas_os_dashboard import _segment_compare_rows, write_dashboard
from atlas_review_builder import build_index
from atlas_review_viewer_gen import generate_viewer


DEFAULT_REMOTE_HOST = "root@167.235.253.229"
DEFAULT_REMOTE_OUTPUTS_DIR = "/srv/atlas/OCR_annotation_Atlas/outputs/danatimer"
DEFAULT_LOCAL_BUNDLES_DIR = Path("outputs/live_episode_bundles")
DEFAULT_OUTPUTS_DIR = Path("outputs")
DEFAULT_REVIEW_INDEX = DEFAULT_OUTPUTS_DIR / "episodes_review_index.json"
DEFAULT_REVIEW_VIEWER = DEFAULT_OUTPUTS_DIR / "atlas_review_viewer.html"
DEFAULT_DASHBOARD = DEFAULT_OUTPUTS_DIR / "atlas_os_dashboard.html"
DEFAULT_CREDENTIALS_FILE = Path("project-1e9e05a3-c200-4e5d-87f-ef0c6d55bd1f.json")
DEFAULT_DRIVE_FOLDER_ID = "1kLe9Ai7swxh9Nx2NifD9Fcodf85AfyAG"

REMOTE_FILE_PATTERNS = [
    "video_{episode_id}.mp4",
    "video_{episode_id}_segchunk_01_upload_opt.mp4",
    "text_{episode_id}_current.txt",
    "text_{episode_id}_update.txt",
    "validation_{episode_id}.json",
    "task_state_{episode_id}.json",
    "segments_{episode_id}.json",
    "labels_{episode_id}.json",
    "prompt_{episode_id}.txt",
]


def _run(args: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), check=check, text=True, capture_output=True)


def _sync_remote_episode_bundle(
    episode_id: str,
    remote_host: str,
    remote_outputs_dir: str,
    local_bundles_dir: Path,
) -> Path:
    bundle_dir = local_bundles_dir / episode_id
    bundle_dir.mkdir(parents=True, exist_ok=True)
    for pattern in REMOTE_FILE_PATTERNS:
        remote_path = f"{remote_host}:{remote_outputs_dir}/{pattern.format(episode_id=episode_id)}"
        _run(["scp", remote_path, str(bundle_dir)], check=False)
    return bundle_dir


def _load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return ""


def _write_episode_comparison(bundle_dir: Path, episode_id: str) -> Dict[str, Path]:
    current_path = bundle_dir / f"text_{episode_id}_current.txt"
    update_path = bundle_dir / f"text_{episode_id}_update.txt"
    validation_path = bundle_dir / f"validation_{episode_id}.json"
    task_state_path = bundle_dir / f"task_state_{episode_id}.json"
    comparison_rows = _segment_compare_rows(_read_text(current_path), _read_text(update_path))
    validation = _load_json(validation_path, {}) or {}
    task_state = _load_json(task_state_path, {}) or {}
    manifest = {
        "episode_id": episode_id,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "current_text_path": str(current_path),
        "update_text_path": str(update_path),
        "validation_path": str(validation_path),
        "task_state_path": str(task_state_path),
        "comparison_rows": comparison_rows,
        "changed_count": sum(1 for row in comparison_rows if row["status"] != "same"),
        "validation": validation,
        "task_state": task_state,
        "bundle_files": sorted(path.name for path in bundle_dir.iterdir() if path.is_file()),
    }
    manifest_path = bundle_dir / f"episode_bundle_manifest_{episode_id}.json"
    comparison_json_path = bundle_dir / f"comparison_{episode_id}.json"
    comparison_csv_path = bundle_dir / f"comparison_{episode_id}.csv"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    comparison_json_path.write_text(json.dumps(comparison_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    with comparison_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["index", "window", "old_label", "new_label", "status"])
        writer.writeheader()
        writer.writerows(comparison_rows)
    return {
        "manifest": manifest_path,
        "comparison_json": comparison_json_path,
        "comparison_csv": comparison_csv_path,
    }


def _build_drive_service(credentials_file: Path):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(
        str(credentials_file),
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    return build("drive", "v3", credentials=creds)


def _create_drive_folder(service: Any, name: str, parent_id: str) -> Dict[str, Any]:
    body = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    return service.files().create(body=body, fields="id,name,webViewLink").execute()


def _upload_file(service: Any, path: Path, parent_id: str) -> Dict[str, Any]:
    from googleapiclient.http import MediaFileUpload

    mime_type, _ = mimetypes.guess_type(path.name)
    media = MediaFileUpload(str(path), mimetype=mime_type or "application/octet-stream", resumable=False)
    body = {"name": path.name, "parents": [parent_id]}
    return service.files().create(body=body, media_body=media, fields="id,name,webViewLink,mimeType").execute()


def _publish_to_drive(
    credentials_file: Path,
    parent_folder_id: str,
    root_name: str,
    dashboard_path: Path,
    review_index_path: Path,
    review_viewer_path: Path,
    bundle_dirs: Sequence[Path],
) -> Dict[str, Any]:
    service = _build_drive_service(credentials_file)
    root_folder = _create_drive_folder(service, root_name, parent_folder_id)
    uploaded: List[Dict[str, Any]] = []

    for file_path in [dashboard_path, review_index_path, review_viewer_path]:
        if file_path.exists():
            uploaded.append(_upload_file(service, file_path, root_folder["id"]))

    for bundle_dir in bundle_dirs:
        episode_folder = _create_drive_folder(service, bundle_dir.name, root_folder["id"])
        for file_path in sorted(bundle_dir.iterdir()):
            if not file_path.is_file():
                continue
            uploaded.append(_upload_file(service, file_path, episode_folder["id"]))

    result = {
        "root_folder": root_folder,
        "uploaded_files": uploaded,
    }
    return result


def _flatten_episode_ids(values: Iterable[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for value in values:
        clean = str(value or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        ordered.append(clean)
    return ordered


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish episode dashboard artifacts to Google Drive.")
    parser.add_argument("--episode-id", action="append", default=[], help="Episode id to sync and publish. Repeat for multiple.")
    parser.add_argument("--remote-host", default=DEFAULT_REMOTE_HOST)
    parser.add_argument("--remote-outputs-dir", default=DEFAULT_REMOTE_OUTPUTS_DIR)
    parser.add_argument("--local-bundles-dir", default=str(DEFAULT_LOCAL_BUNDLES_DIR))
    parser.add_argument("--outputs-dir", default=str(DEFAULT_OUTPUTS_DIR))
    parser.add_argument("--review-index", default=str(DEFAULT_REVIEW_INDEX))
    parser.add_argument("--review-viewer", default=str(DEFAULT_REVIEW_VIEWER))
    parser.add_argument("--dashboard", default=str(DEFAULT_DASHBOARD))
    parser.add_argument("--credentials-file", default=str(DEFAULT_CREDENTIALS_FILE))
    parser.add_argument("--drive-folder-id", default=DEFAULT_DRIVE_FOLDER_ID)
    parser.add_argument("--skip-sync", action="store_true")
    parser.add_argument("--skip-upload", action="store_true")
    args = parser.parse_args()

    episode_ids = _flatten_episode_ids(args.episode_id)
    if not episode_ids and not args.skip_sync:
        raise SystemExit("At least one --episode-id is required unless --skip-sync is used.")

    local_bundles_dir = Path(args.local_bundles_dir)
    outputs_dir = Path(args.outputs_dir)
    review_index_path = Path(args.review_index)
    review_viewer_path = Path(args.review_viewer)
    dashboard_path = Path(args.dashboard)
    bundle_dirs: List[Path] = []

    for episode_id in episode_ids:
        bundle_dir = local_bundles_dir / episode_id
        if not args.skip_sync:
            bundle_dir = _sync_remote_episode_bundle(
                episode_id=episode_id,
                remote_host=args.remote_host,
                remote_outputs_dir=args.remote_outputs_dir,
                local_bundles_dir=local_bundles_dir,
            )
        bundle_dirs.append(bundle_dir)
        _write_episode_comparison(bundle_dir, episode_id)

    review_index = build_index(outputs_dir=outputs_dir, probe_atlas_status="off")
    review_index_path.parent.mkdir(parents=True, exist_ok=True)
    review_index_path.write_text(json.dumps(review_index, ensure_ascii=False, indent=2), encoding="utf-8")
    generate_viewer(review_index_path.resolve(), review_viewer_path.resolve(), title="Atlas Episode Review Viewer")
    write_dashboard(
        output_path=dashboard_path,
        outputs_dir=outputs_dir,
        review_index_path=review_index_path,
    )

    publish_result: Dict[str, Any] = {}
    if not args.skip_upload:
        root_name = f"atlas_episode_publish_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        publish_result = _publish_to_drive(
            credentials_file=Path(args.credentials_file),
            parent_folder_id=str(args.drive_folder_id),
            root_name=root_name,
            dashboard_path=dashboard_path,
            review_index_path=review_index_path,
            review_viewer_path=review_viewer_path,
            bundle_dirs=bundle_dirs,
        )

    summary = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "episode_ids": episode_ids,
        "dashboard_path": str(dashboard_path),
        "review_index_path": str(review_index_path),
        "review_viewer_path": str(review_viewer_path),
        "bundle_dirs": [str(path) for path in bundle_dirs],
        "drive_publish": publish_result,
    }
    summary_path = outputs_dir / "episode_dashboard_publish_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
