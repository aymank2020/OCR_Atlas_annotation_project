"""
Group episode artifacts into per-episode folders before Google Drive upload.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable


EPISODE_ID_RE = re.compile(r"(?<![0-9a-f])([0-9a-f]{24})(?![0-9a-f])")
EPISODE_FILE_PREFIXES = (
    "correction_",
    "gemini_labels_cache_",
    "labels_",
    "prompt_",
    "segments_",
    "task_state_",
    "text_",
    "validation_",
    "video_",
)
SKIP_DIR_NAMES = {"live_episode_bundles"}


def parse_age_to_seconds(value: str) -> int:
    clean = str(value or "").strip().lower()
    if not clean:
        return 0
    match = re.fullmatch(r"(\d+)([smhd]?)", clean)
    if not match:
        raise ValueError(f"Unsupported age format: {value!r}")
    amount = int(match.group(1))
    unit = match.group(2) or "s"
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return amount * multipliers[unit]


def extract_episode_id(filename: str) -> str | None:
    match = EPISODE_ID_RE.search(filename or "")
    if not match:
        return None
    return match.group(1)


def is_episode_artifact(path: Path) -> bool:
    name = path.name
    if not path.is_file() or name.startswith(".") or name.endswith((".log", ".part")):
        return False
    return any(name.startswith(prefix) for prefix in EPISODE_FILE_PREFIXES) and bool(extract_episode_id(name))


@dataclass
class OrganizeResult:
    scanned_files: int = 0
    matched_files: int = 0
    moved_files: int = 0
    skipped_recent: int = 0
    skipped_collisions: int = 0
    skipped_nested: int = 0

    def as_dict(self) -> Dict[str, int]:
        return {
            "scanned_files": self.scanned_files,
            "matched_files": self.matched_files,
            "moved_files": self.moved_files,
            "skipped_recent": self.skipped_recent,
            "skipped_collisions": self.skipped_collisions,
            "skipped_nested": self.skipped_nested,
        }


def _iter_candidate_files(root_dir: Path) -> Iterable[Path]:
    for path in root_dir.rglob("*"):
        if path.is_file():
            yield path


def organize_episode_outputs(
    root_dir: Path,
    *,
    destination_dir_name: str = "episodes",
    min_age_seconds: int = 0,
    now_ts: float | None = None,
) -> Dict[str, Any]:
    root_dir = Path(root_dir)
    result = OrganizeResult()
    moved_paths: list[str] = []
    collision_paths: list[str] = []
    episode_dirs: set[str] = set()
    now_ts = float(now_ts if now_ts is not None else datetime.now(timezone.utc).timestamp())

    for path in _iter_candidate_files(root_dir):
        result.scanned_files += 1
        relative_parts = path.relative_to(root_dir).parts[:-1]
        if destination_dir_name in relative_parts or any(part in SKIP_DIR_NAMES for part in relative_parts):
            result.skipped_nested += 1
            continue
        if not is_episode_artifact(path):
            continue

        result.matched_files += 1
        if min_age_seconds > 0 and now_ts - path.stat().st_mtime < min_age_seconds:
            result.skipped_recent += 1
            continue

        episode_id = extract_episode_id(path.name)
        if not episode_id:
            continue
        target_dir = path.parent / destination_dir_name / episode_id
        target_path = target_dir / path.name
        if target_path.exists():
            result.skipped_collisions += 1
            collision_paths.append(str(target_path))
            continue

        target_dir.mkdir(parents=True, exist_ok=True)
        path.replace(target_path)
        result.moved_files += 1
        episode_dirs.add(str(target_dir))
        moved_paths.append(str(target_path))

    summary = result.as_dict()
    summary.update(
        {
            "root_dir": str(root_dir),
            "destination_dir_name": destination_dir_name,
            "min_age_seconds": min_age_seconds,
            "episode_dirs_created": sorted(episode_dirs),
            "moved_paths": moved_paths,
            "collision_paths": collision_paths,
        }
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Organize Atlas output files into per-episode folders.")
    parser.add_argument("--root", default="outputs", help="Root outputs directory to scan.")
    parser.add_argument("--destination-dir-name", default="episodes", help="Folder name to create per episode.")
    parser.add_argument("--min-age", default="0s", help="Only organize files older than this age, e.g. 30m.")
    args = parser.parse_args()

    summary = organize_episode_outputs(
        Path(args.root),
        destination_dir_name=args.destination_dir_name,
        min_age_seconds=parse_age_to_seconds(args.min_age),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
