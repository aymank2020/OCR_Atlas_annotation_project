"""
atlas_drive_indexer.py
────────────────────────
Indexes Google Drive videos folder as a golden dataset reference.

Connects to the Drive folder, extracts video metadata (and labels if available),
and saves to golden_index.jsonl for use by atlas_dynamic_rag.py.

Usage:
  python atlas_drive_indexer.py \\
      --folder-id 1e85SR-tY2PC6Q-LlkUOf2JllMxiIE4ys \\
      --credentials-file path/to/credentials.json

Output: outputs/knowledge/golden_index.jsonl
"""

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

OUTPUT_PATH = "outputs/knowledge/golden_index.jsonl"


def _build_service(credentials_path: str):
    """
    Build Google Drive API service using a service account or OAuth credentials.
    Requires: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib
    """
    try:
        from googleapiclient.discovery import build
        from google.oauth2 import service_account
        from google.oauth2.credentials import Credentials

        creds_path = Path(credentials_path)
        if not creds_path.exists():
            raise FileNotFoundError(f"Credentials file not found: {credentials_path}")

        with open(creds_path) as f:
            creds_data = json.load(f)

        if creds_data.get("type") == "service_account":
            scopes = ["https://www.googleapis.com/auth/drive.readonly"]
            creds = service_account.Credentials.from_service_account_file(
                str(creds_path), scopes=scopes
            )
        else:
            # Assume OAuth token
            creds = Credentials.from_authorized_user_file(str(creds_path))

        service = build("drive", "v3", credentials=creds)
        return service

    except ImportError:
        print("[drive-indexer] ❌ Missing dependencies. Run: pip install google-api-python-client google-auth-oauthlib")
        raise


def _list_files(service: Any, folder_id: str, depth: int = 0) -> List[Dict[str, Any]]:
    """Recursively list all files in a Drive folder."""
    if depth > 5:  # Prevent infinite loops
        return []
        
    results = []
    page_token = None
    query = f"'{folder_id}' in parents and trashed = false"
    fields = "nextPageToken, files(id, name, mimeType, size, createdTime, modifiedTime, webViewLink)"

    if depth == 0:
        print(f"[drive-indexer] Scanning origin folder: {folder_id}")
        
    while True:
        try:
            resp = service.files().list(
                q=query,
                fields=fields,
                pageToken=page_token or "",
                pageSize=100,
            ).execute()
        except Exception as e:
            print(f"[drive-indexer]   ⚠ Error listing {folder_id}: {e}")
            break
            
        files = resp.get("files", [])
        
        for f in files:
            is_folder = f.get("mimeType") == "application/vnd.google-apps.folder"
            if is_folder:
                print(f"[drive-indexer]   ... entering subfolder: {f.get('name')}")
                # Recursively fetch files inside the subfolder
                sub_files = _list_files(service, f["id"], depth + 1)
                results.extend(sub_files)
            else:
                results.append(f)
                
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    if depth == 0:
        print(f"[drive-indexer] Found {len(results)} total files across all folders.")
    return results


def _extract_video_keywords(filename: str) -> List[str]:
    """
    Derive activity keywords from video filename.
    e.g. "sewing_fabric_coiling_011.mp4" -> ["sewing", "fabric", "coiling"]
    """
    name = Path(filename).stem
    tokens = re.findall(r"[a-zA-Z]+", name)
    stop_words = {"mp4", "mov", "avi", "mkv", "video", "clip",
                  "part", "segment", "ep", "episode"}
    return [t.lower() for t in tokens if t.lower() not in stop_words and len(t) > 2]


def _index_folder(
    folder_id: str,
    credentials_path: str,
    output_path: str = OUTPUT_PATH,
) -> int:
    """Index the Drive folder and write golden_index.jsonl."""
    service = _build_service(credentials_path)
    files = _list_files(service, folder_id)

    video_mimes = {
        "video/mp4", "video/quicktime", "video/x-msvideo",
        "video/x-matroska", "video/mpeg", "video/webm",
    }

    # Pair videos with their JSON label files (same name, .json extension)
    file_map = {f["name"]: f for f in files}
    count = 0

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as out:
        for f in files:
            if f.get("mimeType") not in video_mimes:
                continue

            video_name = f["name"]
            drive_id = f["id"]
            keywords = _extract_video_keywords(video_name)

            # Check if there's a labels JSON file with the same stem
            stem = Path(video_name).stem
            label_file = file_map.get(f"{stem}.json") or file_map.get(f"{stem}_labels.json")
            labels_data = {}
            labels_drive_id = None

            if label_file:
                labels_drive_id = label_file["id"]
                # Download and parse labels JSON from Drive
                try:
                    from googleapiclient.http import MediaIoBaseDownload
                    import io
                    request = service.files().get_media(fileId=labels_drive_id)
                    buf = io.BytesIO()
                    downloader = MediaIoBaseDownload(buf, request)
                    done = False
                    while not done:
                        _, done = downloader.next_chunk()
                    buf.seek(0)
                    labels_data = json.loads(buf.read().decode("utf-8"))
                    print(f"[drive-indexer]   ✔ Labels found for: {video_name}")
                except Exception as e:
                    print(f"[drive-indexer]   ⚠ Could not download labels for {video_name}: {e}")

            record = {
                "drive_id": drive_id,
                "filename": video_name,
                "drive_link": f.get("webViewLink", ""),
                "mime_type": f.get("mimeType", ""),
                "size_bytes": int(f.get("size", 0) or 0),
                "created_time": f.get("createdTime", ""),
                "modified_time": f.get("modifiedTime", ""),
                "keywords": keywords,
                "has_labels": bool(labels_data),
                "labels_drive_id": labels_drive_id,
                "labels": labels_data,
                "indexed_at": datetime.now(timezone.utc).isoformat(),
            }

            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1

    print(f"[drive-indexer] ✅ Indexed {count} videos → {output_path}")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Atlas Drive Folder Indexer (Golden Dataset)")
    parser.add_argument(
        "--folder-id",
        default=os.environ.get("ATLAS_DRIVE_FOLDER_ID", "1e85SR-tY2PC6Q-LlkUOf2JllMxiIE4ys"),
        help="Google Drive folder ID (can also be set via ATLAS_DRIVE_FOLDER_ID)",
    )
    parser.add_argument(
        "--credentials-file",
        default="",
        help="Path to Google service account JSON or OAuth credentials",
    )
    parser.add_argument(
        "--output",
        default=OUTPUT_PATH,
        help="Output path for golden_index.jsonl",
    )
    args = parser.parse_args()

    # Auto-detect credentials from environment
    creds = args.credentials_file
    if not creds:
        # Try known locations
        for candidate in [
            "secrets/service_account.json",
            os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", ""),
        ]:
            if candidate and Path(candidate).exists():
                creds = candidate
                break

    if not creds:
        print("[drive-indexer] ❌ No credentials found.")
        print("   Set --credentials-file or GOOGLE_APPLICATION_CREDENTIALS")
        return

    count = _index_folder(
        folder_id=args.folder_id,
        credentials_path=creds,
        output_path=args.output,
    )
    print(f"[drive-indexer] Done. {count} entries in golden dataset index.")


if __name__ == "__main__":
    main()
