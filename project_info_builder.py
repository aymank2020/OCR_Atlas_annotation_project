"""
Build project-level documentation snapshots under ./project_info.

Optional Gemini step can generate a high-level technical summary using the
latest runtime evidence (solver/feedback/whatsapp).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import requests
import yaml


DEFAULTS: Dict[str, Any] = {
    "gemini": {
        "model": "gemini-2.5-flash",
        "connect_timeout_sec": 30,
        "request_timeout_sec": 300,
    },
    "project_info": {
        "root_dir": "project_info",
        "runs_subdir": "runs",
        "max_log_tail_lines": 120,
    },
}


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
    raw = {}
    if path.exists():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raw = {}
    return deep_merge(DEFAULTS, raw)


def resolve_gemini_key(cfg: Dict[str, Any]) -> str:
    explicit = str(cfg_get(cfg, "gemini.api_key", "")).strip()
    if explicit:
        return explicit
    for env_name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        val = os.environ.get(env_name, "").strip()
        if val:
            return val
    return ""


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def latest_file(root: Path, pattern: str) -> Path | None:
    items = [p for p in root.glob(pattern) if p.is_file()]
    if not items:
        return None
    items.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return items[0]


def tail_lines(path: Path, max_lines: int) -> str:
    if not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return ""
    if max_lines > 0 and len(lines) > max_lines:
        lines = lines[-max_lines:]
    return "\n".join(lines)


def collect_repo_tree(root: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for item in sorted(root.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
        if item.name in {".git", "__pycache__"}:
            continue
        entry = {
            "name": item.name,
            "type": "dir" if item.is_dir() else "file",
            "size_bytes": item.stat().st_size if item.is_file() else 0,
            "mtime": datetime.fromtimestamp(item.stat().st_mtime).isoformat(),
        }
        if item.is_dir():
            try:
                entry["children_count"] = len(list(item.iterdir()))
            except Exception:
                entry["children_count"] = 0
        out.append(entry)
    return out


def run_git_status(root: Path) -> Dict[str, Any]:
    try:
        cp = subprocess.run(
            ["git", "status", "--short"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        lines = [ln for ln in (cp.stdout or "").splitlines() if ln.strip()]
        return {"ok": True, "lines": lines[:400], "count": len(lines)}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "lines": [], "count": 0}


def call_gemini_project_summary(cfg: Dict[str, Any], prompt: str) -> Dict[str, Any]:
    key = resolve_gemini_key(cfg)
    if not key:
        raise RuntimeError("Missing Gemini API key in env (GEMINI_API_KEY/GOOGLE_API_KEY).")
    model = str(cfg_get(cfg, "gemini.model", "gemini-2.5-flash"))
    connect_timeout = int(cfg_get(cfg, "gemini.connect_timeout_sec", 30))
    request_timeout = int(cfg_get(cfg, "gemini.request_timeout_sec", 300))
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {"Content-Type": "application/json", "X-goog-api-key": key}
    payload = {
        "systemInstruction": {
            "parts": [
                {
                    "text": (
                        "You are a software project analyst. "
                        "Produce concise and operational documentation updates."
                    )
                }
            ]
        },
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=(connect_timeout, request_timeout))
    if resp.status_code != 200:
        raise RuntimeError(f"Gemini failed: HTTP {resp.status_code}: {(resp.text or '')[:500]}")
    data = resp.json()
    text = ""
    try:
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join([str(p.get("text", "")) for p in parts if isinstance(p, dict)])
    except Exception:
        text = ""
    parsed: Dict[str, Any] = {}
    if text.strip():
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = {"raw_text": text.strip()}
    return {"http_status": 200, "raw": data, "parsed": parsed}


def build_markdown(snapshot: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# OCR_annotation_Atlas - Project Snapshot")
    lines.append("")
    lines.append(f"- Generated at: `{snapshot.get('generated_at', '')}`")
    lines.append(f"- Root: `{snapshot.get('root', '')}`")
    lines.append("")
    lines.append("## Runtime Status")
    lines.append(f"- Solver latest log: `{snapshot.get('solver_latest_log', '')}`")
    lines.append(f"- Feedback latest: `{snapshot.get('feedback_latest', '')}`")
    lines.append(f"- WhatsApp latest: `{snapshot.get('whatsapp_latest', '')}`")
    lines.append("")
    lines.append("## Key Config")
    key_cfg = snapshot.get("key_config", {})
    for k in sorted(key_cfg.keys()):
        lines.append(f"- `{k}`: `{key_cfg[k]}`")
    lines.append("")
    lines.append("## Top-Level Tree")
    for entry in snapshot.get("repo_tree", [])[:200]:
        kind = "dir" if entry.get("type") == "dir" else "file"
        lines.append(f"- `{entry.get('name')}` ({kind})")
    lines.append("")
    if snapshot.get("git_status", {}).get("ok"):
        lines.append("## Git Status")
        for ln in snapshot["git_status"].get("lines", [])[:120]:
            lines.append(f"- `{ln}`")
    else:
        lines.append("## Git Status")
        lines.append(f"- unavailable: {snapshot.get('git_status', {}).get('error', 'unknown')}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="sample_web_auto_solver.yaml")
    parser.add_argument("--with-gemini", action="store_true")
    parser.add_argument("--max-log-lines", type=int, default=None)
    args = parser.parse_args()

    root = Path.cwd()
    cfg = load_config(root / args.config)
    info_root_cfg = str(cfg_get(cfg, "project_info.root_dir", "project_info")).strip() or "project_info"
    runs_subdir = str(cfg_get(cfg, "project_info.runs_subdir", "runs")).strip() or "runs"
    max_log_lines = int(
        args.max_log_lines
        if args.max_log_lines is not None
        else cfg_get(cfg, "project_info.max_log_tail_lines", 120)
    )

    info_root = Path(info_root_cfg) if Path(info_root_cfg).is_absolute() else root / info_root_cfg
    runs_root = info_root / runs_subdir
    info_root.mkdir(parents=True, exist_ok=True)
    runs_root.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = runs_root / f"project_info_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)

    outputs_dir = root / "outputs"
    feedback_latest_path = outputs_dir / "training_feedback" / "latest.json"
    whatsapp_latest_path = outputs_dir / "training_feedback" / "whatsapp" / "latest.json"
    solver_latest_log = latest_file(outputs_dir, "solver_live_*.log")

    feedback_latest = read_json(feedback_latest_path, {})
    whatsapp_latest = read_json(whatsapp_latest_path, {})
    solver_tail = tail_lines(solver_latest_log, max_log_lines) if solver_latest_log else ""

    snapshot: Dict[str, Any] = {
        "generated_at": datetime.now().isoformat(),
        "root": str(root),
        "config_path": str(root / args.config),
        "repo_tree": collect_repo_tree(root),
        "git_status": run_git_status(root),
        "feedback_latest": str(feedback_latest_path) if feedback_latest_path.exists() else "",
        "whatsapp_latest": str(whatsapp_latest_path) if whatsapp_latest_path.exists() else "",
        "solver_latest_log": str(solver_latest_log) if solver_latest_log else "",
        "feedback_latest_data": feedback_latest,
        "whatsapp_latest_data": whatsapp_latest,
        "solver_latest_tail": solver_tail,
        "key_config": {
            "run.max_episodes_per_run": cfg_get(cfg, "run.max_episodes_per_run", ""),
            "run.keep_alive_when_idle": cfg_get(cfg, "run.keep_alive_when_idle", ""),
            "run.enable_quality_review_submit": cfg_get(cfg, "run.enable_quality_review_submit", ""),
            "run.enable_structural_actions": cfg_get(cfg, "run.enable_structural_actions", ""),
            "training_feedback.continuous": cfg_get(cfg, "training_feedback.continuous", ""),
            "training_feedback.track_t4_disputes": cfg_get(cfg, "training_feedback.track_t4_disputes", ""),
            "whatsapp_training.continuous": cfg_get(cfg, "whatsapp_training.continuous", ""),
            "whatsapp_training.use_chrome_profile": cfg_get(cfg, "whatsapp_training.use_chrome_profile", ""),
            "whatsapp_training.attach_media_to_gemini": cfg_get(cfg, "whatsapp_training.attach_media_to_gemini", ""),
            "gemini.model": cfg_get(cfg, "gemini.model", ""),
        },
    }

    (run_dir / "project_snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    overview_md = build_markdown(snapshot)
    (run_dir / "PROJECT_OVERVIEW.md").write_text(overview_md, encoding="utf-8")

    gemini_status = "skipped"
    if args.with_gemini:
        prompt = (
            "Generate a complete project explainer from this JSON snapshot. "
            "Focus on current architecture, active automations, known runtime risks, and next actions.\n\n"
            + json.dumps(snapshot, ensure_ascii=False)[:120000]
        )
        try:
            resp = call_gemini_project_summary(cfg, prompt)
            (run_dir / "gemini_project_info_response.json").write_text(
                json.dumps(resp, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (run_dir / "gemini_project_info_parsed.json").write_text(
                json.dumps(resp.get("parsed", {}), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            gemini_status = "ok"
        except Exception as exc:
            (run_dir / "gemini_project_info_error.txt").write_text(str(exc), encoding="utf-8")
            gemini_status = "error"

    run_index = {
        "generated_at": datetime.now().isoformat(),
        "run_dir": str(run_dir),
        "snapshot_json": str(run_dir / "project_snapshot.json"),
        "overview_md": str(run_dir / "PROJECT_OVERVIEW.md"),
        "gemini_status": gemini_status,
    }
    (run_dir / "INDEX.json").write_text(json.dumps(run_index, ensure_ascii=False, indent=2), encoding="utf-8")
    (info_root / "latest.json").write_text(json.dumps(run_index, ensure_ascii=False, indent=2), encoding="utf-8")
    with (info_root / "runs_manifest.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(run_index, ensure_ascii=False))
        f.write("\n")

    print(f"[project_info] saved: {run_dir}")
    print(f"[project_info] gemini_status: {gemini_status}")


if __name__ == "__main__":
    main()

