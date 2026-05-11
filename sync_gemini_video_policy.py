#!/usr/bin/env python3
"""
Sync Gemini video quality/cost policy across config YAML files.

Usage:
  python sync_gemini_video_policy.py
  python sync_gemini_video_policy.py --root /root/OCR_annotation_Atlas
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, Any, List

import yaml


FLOOR_SURFACE_GUARD = (
    "If floor mat vs table is unclear, do not guess raised furniture; "
    "use neutral location wording."
)


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def apply_policy(cfg: Dict[str, Any]) -> bool:
    changed = False
    gem = cfg.setdefault("gemini", {})
    if not isinstance(gem, dict):
        cfg["gemini"] = {}
        gem = cfg["gemini"]
        changed = True

    defaults = {
        "optimize_video_for_upload": True,
        "optimize_video_target_mb": 4.0,
        "optimize_video_target_fps": 10.0,
        "optimize_video_min_fps": 8.0,
        "optimize_video_min_width": 320,
        "optimize_video_min_short_side": 320,
        "reference_frames_enabled": True,
        "reference_frames_always": False,
        "reference_frame_attach_when_video_mb_le": 2.5,
        "reference_frame_count": 2,
        "reference_frame_positions": [0.2, 0.55, 0.85],
        "reference_frame_max_side": 960,
        "reference_frame_jpeg_quality": 82,
        "reference_frame_max_total_kb": 420,
    }

    for key, value in defaults.items():
        if key not in gem:
            gem[key] = value
            changed = True

    target_mb = min(50.0, max(1.0, _as_float(gem.get("optimize_video_target_mb", 4.0), 4.0)))
    if _as_float(gem.get("optimize_video_target_mb", 4.0), 4.0) != target_mb:
        gem["optimize_video_target_mb"] = target_mb
        changed = True

    min_fps = max(8.0, _as_float(gem.get("optimize_video_min_fps", 8.0), 8.0))
    target_fps = max(min_fps, _as_float(gem.get("optimize_video_target_fps", 10.0), 10.0))
    if _as_float(gem.get("optimize_video_min_fps", 8.0), 8.0) != min_fps:
        gem["optimize_video_min_fps"] = min_fps
        changed = True
    if _as_float(gem.get("optimize_video_target_fps", 10.0), 10.0) != target_fps:
        gem["optimize_video_target_fps"] = target_fps
        changed = True

    min_width = max(320, _as_int(gem.get("optimize_video_min_width", 320), 320))
    min_short = max(320, _as_int(gem.get("optimize_video_min_short_side", 320), 320))
    if _as_int(gem.get("optimize_video_min_width", 320), 320) != min_width:
        gem["optimize_video_min_width"] = min_width
        changed = True
    if _as_int(gem.get("optimize_video_min_short_side", 320), 320) != min_short:
        gem["optimize_video_min_short_side"] = min_short
        changed = True

    extra = str(gem.get("extra_instructions", "") or "").strip()
    if FLOOR_SURFACE_GUARD.lower() not in extra.lower():
        gem["extra_instructions"] = f"{extra}\n{FLOOR_SURFACE_GUARD}".strip() if extra else FLOOR_SURFACE_GUARD
        changed = True

    return changed


def iter_targets(root: Path) -> List[Path]:
    patterns = [
        "config_account*.yaml",
        "sample_web_auto_solver*.yaml",
    ]
    out: List[Path] = []
    seen = set()
    for pat in patterns:
        for p in sorted(root.glob(pat)):
            if p.is_file() and p not in seen:
                seen.add(p)
                out.append(p)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Gemini video policy across YAML configs.")
    parser.add_argument("--root", default=".", help="Project root directory (default: current directory)")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    targets = iter_targets(root)
    updated = 0

    for path in targets:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(data, dict):
                print(f"skip(non-object): {path}")
                continue
            if apply_policy(data):
                path.write_text(
                    yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
                    encoding="utf-8",
                )
                updated += 1
                print(f"updated: {path}")
            else:
                print(f"ok: {path}")
        except Exception as exc:
            print(f"error: {path} -> {exc}")

    print(f"done: updated={updated}, scanned={len(targets)}")


if __name__ == "__main__":
    main()
