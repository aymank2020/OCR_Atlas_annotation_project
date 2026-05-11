"""
Generate a practical Atlas example with Gemini API and Gemini Chat, then
compare both outputs using the current canonical policy validator.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List

import yaml

import prompts
import validator
from atlas_triplet_compare import generate_gemini_chat_timed_labels, parse_timed_segments_payload, segments_to_timed_text


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_VIDEO = PROJECT_ROOT / "data" / "f01.mp4"
DEFAULT_DRAFT = PROJECT_ROOT / "data" / "f01.json"
DEFAULT_CONFIG = PROJECT_ROOT / "sample_web_auto_solver_production.yaml"
DEFAULT_STORAGE_STATE = PROJECT_ROOT / ".state" / "gemini_chat_storage_state.json"
DEFAULT_OUT_DIR = PROJECT_ROOT / "outputs" / "example_compare"
DEFAULT_API_MODEL = "gemini-2.5-flash"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_yaml(path: Path) -> Dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise RuntimeError("Config root must be a YAML object.")
    return payload


def _write_yaml(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _draft_duration_seconds(draft_path: Path) -> float:
    payload = _load_json(draft_path)
    max_end = 0.0
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            end_raw = item.get("end") or item.get("end_sec") or item.get("stop")
            if end_raw is None:
                continue
            text = str(end_raw)
            if ":" in text:
                parts = text.split(":")
                if len(parts) == 2:
                    seconds = float(parts[0]) * 60.0 + float(parts[1])
                elif len(parts) == 3:
                    seconds = float(parts[0]) * 3600.0 + float(parts[1]) * 60.0 + float(parts[2])
                else:
                    seconds = 0.0
            else:
                seconds = float(end_raw)
            max_end = max(max_end, seconds)
    return max_end


def _coerce_annotation(path: Path, *, episode_id: str, video_duration_sec: float) -> Dict[str, Any]:
    payload = _load_json(path)
    segments = parse_timed_segments_payload(payload)
    if not segments:
        raise RuntimeError(f"No parseable segments found in {path}")
    return {
        "episode_id": episode_id,
        "video_duration_sec": video_duration_sec,
        "segments": segments,
    }


def _make_upload_opt_video(video_path: Path, out_dir: Path) -> Path | None:
    if shutil.which("ffmpeg") is None:
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{video_path.stem}_upload_opt.mp4"
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vf",
        "scale='min(960,iw)':-2:flags=lanczos,fps=8",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "30",
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=600)
    except Exception:
        return None
    return out_path if out_path.exists() else None


def _segment_error_count(report: Dict[str, Any]) -> int:
    count = 0
    for item in report.get("segment_reports", []) or []:
        if isinstance(item, dict):
            count += len(item.get("errors", []) or [])
    return count


def _score_report(report: Dict[str, Any]) -> int:
    score = 100
    score -= 25 * len(report.get("episode_errors", []) or [])
    score -= 10 * len(report.get("major_fail_triggers", []) or [])
    score -= 2 * _segment_error_count(report)
    score -= len(report.get("episode_warnings", []) or [])
    return max(0, score)


def _report_summary(report: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "ok": bool(report.get("ok", False)),
        "score": _score_report(report),
        "episode_errors": report.get("episode_errors", []) or [],
        "major_fail_triggers": report.get("major_fail_triggers", []) or [],
        "episode_warnings": report.get("episode_warnings", []) or [],
        "segment_error_count": _segment_error_count(report),
        "segment_count": len(report.get("normalized_annotation", {}).get("segments", []) or []),
    }


def _build_markdown_report(
    *,
    episode_id: str,
    policy_version: str,
    prompt_summary: str,
    api_text: str,
    chat_text: str,
    api_summary: Dict[str, Any],
    chat_summary: Dict[str, Any],
    winner: str,
) -> str:
    lines: List[str] = []
    lines.append(f"# Atlas Example Compare: {episode_id}")
    lines.append("")
    lines.append(f"- Policy version: `{policy_version}`")
    lines.append(f"- Winner: `{winner}`")
    lines.append("")
    lines.append("## Canonical Policy Snapshot")
    for line in prompt_summary.splitlines():
        lines.append(f"- {line.lstrip('- ').strip()}")
    lines.append("")
    lines.append("## Validator Summary")
    lines.append(f"- API ok: `{api_summary['ok']}` | score: `{api_summary['score']}` | segments: `{api_summary['segment_count']}`")
    lines.append(f"- Chat ok: `{chat_summary['ok']}` | score: `{chat_summary['score']}` | segments: `{chat_summary['segment_count']}`")
    lines.append(f"- API major fail triggers: `{', '.join(api_summary['major_fail_triggers']) or 'none'}`")
    lines.append(f"- Chat major fail triggers: `{', '.join(chat_summary['major_fail_triggers']) or 'none'}`")
    lines.append(f"- API episode errors: `{', '.join(api_summary['episode_errors']) or 'none'}`")
    lines.append(f"- Chat episode errors: `{', '.join(chat_summary['episode_errors']) or 'none'}`")
    lines.append("")
    lines.append("## API Output")
    lines.append("```text")
    lines.append(api_text.strip())
    lines.append("```")
    lines.append("")
    lines.append("## Chat Output")
    lines.append("```text")
    lines.append(chat_text.strip())
    lines.append("```")
    return "\n".join(lines).rstrip() + "\n"


def run_compare(
    *,
    video_path: Path,
    draft_path: Path,
    config_path: Path,
    chat_storage_state: Path,
    out_dir: Path,
    episode_id: str,
    api_model: str,
) -> Dict[str, Any]:
    base_cfg = _load_yaml(config_path)
    gem_cfg = dict(base_cfg.get("gemini", {}) or {})
    gem_cfg["chat_web_storage_state"] = str(chat_storage_state)
    gem_cfg["chat_web_headless"] = True
    gem_cfg["hybrid_chat_refine_enabled"] = False
    base_cfg["gemini"] = gem_cfg

    upload_opt_video = _make_upload_opt_video(video_path, out_dir)
    primary_video = upload_opt_video or video_path

    runtime_config_path = out_dir / f"{episode_id}_runtime_config.yaml"
    _write_yaml(runtime_config_path, base_cfg)

    api_json = out_dir / f"{episode_id}_api.json"
    api_txt = out_dir / f"{episode_id}_api.txt"
    chat_json = out_dir / f"{episode_id}_chat.json"
    chat_txt = out_dir / f"{episode_id}_chat.txt"

    api_result = generate_gemini_chat_timed_labels(
        config_path=str(runtime_config_path),
        video_path=str(primary_video),
        video_path_limit="",
        cache_dir=str(out_dir / "cache_api"),
        out_txt=str(api_txt),
        out_json=str(api_json),
        episode_id=episode_id,
        auth_mode_override="api_key",
        prompt_scope="timed_labels",
        tier2_draft_path=str(draft_path),
        model=api_model,
    )
    chat_result = generate_gemini_chat_timed_labels(
        config_path=str(runtime_config_path),
        video_path=str(primary_video),
        video_path_limit="",
        cache_dir=str(out_dir / "cache_chat"),
        out_txt=str(chat_txt),
        out_json=str(chat_json),
        episode_id=episode_id,
        auth_mode_override="chat_web",
        prompt_scope="timed_labels",
        tier2_draft_path=str(draft_path),
    )

    video_duration_sec = _draft_duration_seconds(draft_path)
    api_annotation = _coerce_annotation(api_json, episode_id=episode_id, video_duration_sec=video_duration_sec)
    chat_annotation = _coerce_annotation(chat_json, episode_id=episode_id, video_duration_sec=video_duration_sec)

    prompts.refresh_policy_assets()
    validator.refresh_policy_constraints()

    api_report = validator.validate_episode(api_annotation)
    chat_report = validator.validate_episode(chat_annotation)
    api_summary = _report_summary(api_report)
    chat_summary = _report_summary(chat_report)

    if api_summary["score"] > chat_summary["score"]:
        winner = "api"
    elif chat_summary["score"] > api_summary["score"]:
        winner = "chat"
    else:
        winner = "tie"

    policy = prompts.policy_context.load_current_policy() if hasattr(prompts, "policy_context") else None
    policy_version = str(getattr(prompts, "POLICY_VERSION", "") or (policy or {}).get("policy_version", "unknown"))
    prompt_summary = str(getattr(prompts, "POLICY_PROMPT_SUMMARY", "") or "")
    if not prompt_summary and hasattr(prompts, "policy_context"):
        prompt_summary = prompts.policy_context.build_policy_prompt_summary(policy=policy or prompts.policy_context.load_current_policy())

    api_text = segments_to_timed_text(api_annotation["segments"])
    chat_text = segments_to_timed_text(chat_annotation["segments"])

    compare_payload = {
        "generated_at_utc": datetime_now_utc(),
        "episode_id": episode_id,
        "video_path": str(video_path),
        "draft_path": str(draft_path),
        "upload_opt_video_path": str(upload_opt_video) if upload_opt_video else "",
        "api_model": api_model,
        "policy_version": policy_version,
        "winner": winner,
        "api_generation": api_result,
        "chat_generation": chat_result,
        "api_summary": api_summary,
        "chat_summary": chat_summary,
        "api_report": api_report,
        "chat_report": chat_report,
        "api_text": api_text,
        "chat_text": chat_text,
    }
    json_report_path = out_dir / f"{episode_id}_compare_report.json"
    md_report_path = out_dir / f"{episode_id}_compare_report.md"
    json_report_path.write_text(json.dumps(compare_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_report_path.write_text(
        _build_markdown_report(
            episode_id=episode_id,
            policy_version=policy_version,
            prompt_summary=prompt_summary,
            api_text=api_text,
            chat_text=chat_text,
            api_summary=api_summary,
            chat_summary=chat_summary,
            winner=winner,
        ),
        encoding="utf-8",
    )
    compare_payload["json_report_path"] = str(json_report_path)
    compare_payload["markdown_report_path"] = str(md_report_path)
    return compare_payload


def datetime_now_utc() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and compare Gemini API vs Gemini Chat on a local Atlas example.")
    parser.add_argument("--video-path", default=str(DEFAULT_VIDEO))
    parser.add_argument("--draft-path", default=str(DEFAULT_DRAFT))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--chat-storage-state", default=str(DEFAULT_STORAGE_STATE))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--episode-id", default="f01_demo")
    parser.add_argument("--api-model", default=DEFAULT_API_MODEL)
    args = parser.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = run_compare(
        video_path=Path(args.video_path).resolve(),
        draft_path=Path(args.draft_path).resolve(),
        config_path=Path(args.config).resolve(),
        chat_storage_state=Path(args.chat_storage_state).resolve(),
        out_dir=out_dir,
        episode_id=str(args.episode_id or "f01_demo").strip() or "f01_demo",
        api_model=str(args.api_model or DEFAULT_API_MODEL).strip() or DEFAULT_API_MODEL,
    )
    print(f"[example-compare] winner={payload['winner']}")
    print(f"[example-compare] json={payload['json_report_path']}")
    print(f"[example-compare] markdown={payload['markdown_report_path']}")


if __name__ == "__main__":
    main()
