from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from xml.etree import ElementTree as ET


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def safe_load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def resolve_existing_path(raw: Any, root: Path) -> Optional[Path]:
    if not raw:
        return None
    txt = str(raw).strip()
    if not txt:
        return None
    p = Path(txt)
    if p.exists():
        return p
    q = root / txt
    if q.exists():
        return q
    return None


def rel_path(path: Optional[Path], root: Path) -> str:
    if path is None:
        return ""
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except Exception:
        return str(path)


def latest_by_mtime(paths: Iterable[Path]) -> Optional[Path]:
    xs = [p for p in paths if p is not None and p.exists()]
    if not xs:
        return None
    return max(xs, key=lambda p: p.stat().st_mtime)


def pick_latest(paths: List[Path], pred) -> Optional[Path]:
    return latest_by_mtime([p for p in paths if p.exists() and pred(p.name.lower())])


def issue_to_text(item: Any) -> str:
    if isinstance(item, str):
        return normalize_space(item)
    if isinstance(item, dict):
        for k in ("message", "error", "warning", "detail", "reason"):
            if item.get(k):
                return normalize_space(str(item.get(k)))
        if "segment_index" in item:
            return normalize_space(f"segment {item.get('segment_index')}: {json.dumps(item, ensure_ascii=False)}")
        return normalize_space(json.dumps(item, ensure_ascii=False))
    if item is None:
        return ""
    return normalize_space(str(item))


def normalize_issues(value: Any) -> List[str]:
    if isinstance(value, list):
        src = value
    elif value in (None, ""):
        src = []
    else:
        src = [value]
    out = []
    for item in src:
        txt = issue_to_text(item)
        if txt:
            out.append(txt)
    return out


def parse_validation(path: Optional[Path]) -> Dict[str, Any]:
    if path is None:
        return {"ok": None, "segment_count": 0, "errors": [], "warnings": [], "error_count": 0, "warning_count": 0}
    data = safe_load_json(path, {})
    errors = normalize_issues(data.get("errors"))
    warnings = normalize_issues(data.get("warnings"))
    ok_raw = data.get("ok")
    ok = bool(ok_raw) if ok_raw is not None else (len(errors) == 0)
    return {
        "ok": ok,
        "segment_count": to_int(data.get("segment_count"), 0),
        "errors": errors,
        "warnings": warnings,
        "error_count": len(errors),
        "warning_count": len(warnings),
    }


def parse_labels(path: Optional[Path]) -> Dict[str, Any]:
    if path is None:
        return {"segment_count": 0, "operations_count": 0, "model": ""}
    data = safe_load_json(path, {})
    segs = data.get("segments")
    ops = data.get("operations")
    return {
        "segment_count": len(segs) if isinstance(segs, list) else 0,
        "operations_count": len(ops) if isinstance(ops, list) else 0,
        "model": str((data.get("_meta") or {}).get("model", "")).strip(),
    }


def parse_feedback_status(text: str) -> str:
    low = (text or "").lower()
    if "no feedback" in low:
        return "No feedback"
    if "awaiting t2" in low:
        return "Awaiting T2"
    if "disputed" in low:
        return "Disputed"
    if "both ok" in low:
        return "Both OK"
    m = re.search(r"episode\s+[a-f0-9]{6,}\s+t\d+\s+(.+?)\s+(today|yesterday|view)\b", text, flags=re.I)
    if m:
        return normalize_space(m.group(1))
    return normalize_space(text)[:80] or "Unknown"


def video_id_from_name(name: str) -> str:
    m = re.match(r"video_([a-f0-9]+)(?:_upload_opt(?:_s\d+)?)?\.mp4$", name.lower())
    return m.group(1) if m else ""


def fallback_video_paths(outputs_dir: Path, episode_id: str) -> Tuple[Optional[Path], Optional[Path]]:
    eid = (episode_id or "").lower().strip()
    raw: List[Path] = []
    opt: List[Path] = []
    for p in outputs_dir.glob("video_*.mp4"):
        vid = video_id_from_name(p.name)
        if not vid or not vid.endswith(eid):
            continue
        if "_upload_opt" in p.name.lower():
            opt.append(p)
        else:
            raw.append(p)
    return latest_by_mtime(raw), latest_by_mtime(opt)


def build_episode_record(
    ep: Dict[str, Any],
    run_name: str,
    run_dir: Path,
    run_generated_at: str,
    root: Path,
    outputs_dir: Path,
) -> Optional[Dict[str, Any]]:
    episode_id = str(ep.get("episode_id", "")).lower().strip()
    if not episode_id:
        return None

    art = ep.get("artifacts") or {}
    detail_html = resolve_existing_path(art.get("html"), root)
    detail_text = resolve_existing_path(art.get("text"), root)
    detail_png = resolve_existing_path(art.get("screenshot"), root)

    raw_files = ep.get("copied_output_files") or ep.get("matched_output_files") or []
    matched: List[Path] = []
    for raw in raw_files:
        p = resolve_existing_path(raw, root)
        if p is not None and p.exists():
            matched.append(p)

    fallback = run_dir / "episodes" / episode_id / "matched_outputs"
    if fallback.exists():
        for p in fallback.iterdir():
            if p.is_file():
                matched.append(p)

    dedup = {str(p): p for p in matched}
    matched = list(dedup.values())

    labels_file = pick_latest(matched, lambda n: n.startswith("labels_") and n.endswith(".json"))
    validation_file = pick_latest(matched, lambda n: n.startswith("validation_") and n.endswith(".json"))
    prompt_file = pick_latest(matched, lambda n: n.startswith("prompt_") and n.endswith(".txt"))
    segments_file = pick_latest(matched, lambda n: n.startswith("segments_") and n.endswith(".json"))
    text_current = pick_latest(matched, lambda n: n.startswith("text_") and n.endswith("_current.txt"))
    text_update = pick_latest(matched, lambda n: n.startswith("text_") and n.endswith("_update.txt"))

    video_raw = pick_latest(matched, lambda n: n.startswith("video_") and n.endswith(".mp4") and "_upload_opt" not in n)
    video_opt = pick_latest(matched, lambda n: n.startswith("video_") and n.endswith(".mp4") and "_upload_opt" in n)
    if video_raw is None or video_opt is None:
        f_raw, f_opt = fallback_video_paths(outputs_dir, episode_id)
        if video_raw is None:
            video_raw = f_raw
        if video_opt is None:
            video_opt = f_opt

    val = parse_validation(validation_file)
    lbl = parse_labels(labels_file)
    files = [
        detail_html,
        detail_text,
        detail_png,
        labels_file,
        validation_file,
        prompt_file,
        segments_file,
        text_current,
        text_update,
        video_raw,
        video_opt,
    ]
    ts_list = [p.stat().st_mtime for p in files if p is not None and p.exists()]
    updated_ts = max(ts_list) if ts_list else run_dir.stat().st_mtime
    top_issues = (val["errors"] + val["warnings"])[:3]

    return {
        "episode_id": episode_id,
        "source_run": run_name,
        "run_generated_at": run_generated_at,
        "source_href": str(ep.get("source_href", "")).strip(),
        "status_state": str((ep.get("status_snapshot") or {}).get("state", "")).strip(),
        "validation_ok": val["ok"],
        "error_count": val["error_count"],
        "warning_count": val["warning_count"],
        "validation_errors": val["errors"],
        "validation_warnings": val["warnings"],
        "segment_count": val["segment_count"],
        "label_segments": lbl["segment_count"],
        "operations_count": lbl["operations_count"],
        "model": lbl["model"],
        "top_issue": top_issues[0] if top_issues else "",
        "top_issues": top_issues,
        "detail_html": detail_html,
        "detail_text": detail_text,
        "labels_file": labels_file,
        "validation_file": validation_file,
        "prompt_file": prompt_file,
        "segments_file": segments_file,
        "text_current": text_current,
        "text_update": text_update,
        "video_raw": video_raw,
        "video_opt": video_opt,
        "updated_ts": updated_ts,
        "updated_at": datetime.fromtimestamp(updated_ts).isoformat(timespec="seconds"),
    }


def collect_run_records(runs_root: Path, root: Path) -> List[Dict[str, Any]]:
    records = []
    if not runs_root.exists():
        return records
    dirs = [p for p in runs_root.iterdir() if p.is_dir()]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for run_dir in dirs:
        idx = safe_load_json(run_dir / "INDEX.json", {})
        err = safe_load_json(run_dir / "RUN_ERROR.json", {})
        rec = {
            "run_name": run_dir.name,
            "path": rel_path(run_dir, root),
            "mtime": datetime.fromtimestamp(run_dir.stat().st_mtime).isoformat(timespec="seconds"),
            "status": "unknown",
            "generated_at": "",
            "episodes_collected": 0,
            "feedback_entries_found": 0,
            "gemini_status": "",
            "error": "",
        }
        if idx:
            rec["status"] = "ok"
            rec["generated_at"] = str(idx.get("generated_at", "")).strip()
            rec["episodes_collected"] = to_int(idx.get("episodes_collected"), 0)
            rec["feedback_entries_found"] = to_int(idx.get("feedback_entries_found"), 0)
            rec["gemini_status"] = str(idx.get("gemini_status", "")).strip()
            if rec["gemini_status"].lower() == "error":
                rec["status"] = "warning"
        if err:
            rec["status"] = "error"
            rec["error"] = normalize_space(str(err.get("error", "") or json.dumps(err, ensure_ascii=False)))
            rec["generated_at"] = str(err.get("generated_at", "")).strip() or rec["generated_at"]
        records.append(rec)
    return records


def collect_episodes(runs_root: Path, root: Path, outputs_dir: Path) -> Tuple[List[Dict[str, Any]], Counter, Counter]:
    chosen: Dict[str, Dict[str, Any]] = {}
    states: Counter = Counter()
    feedback: Counter = Counter()
    if not runs_root.exists():
        return [], states, feedback
    dirs = [p for p in runs_root.iterdir() if p.is_dir() and (p / "training_dataset.json").exists()]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    for run_dir in dirs:
        data = safe_load_json(run_dir / "training_dataset.json", {})
        run_generated_at = str(data.get("generated_at", "")).strip()
        eps = data.get("episodes") if isinstance(data.get("episodes"), list) else []
        for ep in eps:
            if not isinstance(ep, dict):
                continue
            rec = build_episode_record(ep, run_dir.name, run_dir, run_generated_at, root, outputs_dir)
            if rec is None:
                continue
            states[rec["status_state"] or "unknown"] += 1
            old = chosen.get(rec["episode_id"])
            if old is None or rec["updated_ts"] > old["updated_ts"]:
                chosen[rec["episode_id"]] = rec

        items = data.get("feedback_entries") if isinstance(data.get("feedback_entries"), list) else []
        for item in items:
            if isinstance(item, dict):
                feedback[parse_feedback_status(str(item.get("text", "")))] += 1

    rows = list(chosen.values())
    rows.sort(key=lambda x: x["updated_ts"], reverse=True)
    return rows, states, feedback


def docx_excerpt(path: Path, max_chars: int = 1200) -> str:
    try:
        with zipfile.ZipFile(path, "r") as zf:
            xml_bytes = zf.read("word/document.xml")
    except Exception:
        return ""
    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return ""
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    parts = [n.text for n in root.findall(".//w:t", ns) if n.text]
    return normalize_space(" ".join(parts))[:max_chars]


def collect_docs(root: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    skip_prefixes = (".git/", ".venv/", "__pycache__/", "outputs/training_feedback/")
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = str(p.relative_to(root)).replace("\\", "/")
        if rel.startswith(skip_prefixes):
            continue
        ext = p.suffix.lower()
        if ext not in {".pdf", ".docx"}:
            continue
        rows.append(
            {
                "path": rel,
                "extension": ext,
                "size_bytes": p.stat().st_size,
                "modified_at": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),
                "excerpt": docx_excerpt(p) if ext == ".docx" else "",
            }
        )
    rows.sort(key=lambda x: (x["extension"], x["path"]))
    return rows


def collect_drive_files(paths: List[str], max_depth: int, max_files: int, timeout_sec: int) -> Tuple[List[Dict[str, Any]], List[str]]:
    rows: List[Dict[str, Any]] = []
    errs: List[str] = []
    for remote in paths:
        cmd = ["rclone", "lsjson", remote, "--recursive", "--files-only", "--fast-list"]
        if max_depth > 0:
            cmd += ["--max-depth", str(max_depth)]
        try:
            cp = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec, check=False)
        except FileNotFoundError:
            errs.append("rclone not found in PATH.")
            break
        except Exception as exc:
            errs.append(f"{remote}: {exc}")
            continue
        if cp.returncode != 0:
            msg = (cp.stderr or cp.stdout or "").strip()
            errs.append(f"{remote}: {msg[:300]}")
            continue
        try:
            items = json.loads(cp.stdout or "[]")
        except Exception as exc:
            errs.append(f"{remote}: invalid json ({exc})")
            continue
        if not isinstance(items, list):
            errs.append(f"{remote}: unexpected payload type")
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            path = str(item.get("Path", "")).strip()
            if not path:
                continue
            rows.append(
                {
                    "remote": remote,
                    "path": path,
                    "size_bytes": to_int(item.get("Size"), 0),
                    "modified_at": str(item.get("ModTime", "")).strip(),
                    "extension": Path(path).suffix.lower(),
                }
            )
            if max_files > 0 and len(rows) >= max_files:
                return rows, errs
    return rows, errs


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_csv(path: Path, rows: List[Dict[str, Any]], fields: List[str]) -> None:
    ensure_parent(path)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fields})


def write_json(path: Path, data: Any) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    ensure_parent(path)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Build practical study pack from Atlas artifacts.")
    ap.add_argument("--project-root", default=".")
    ap.add_argument("--training-root", default="outputs/training_feedback")
    ap.add_argument("--outputs-dir", default="outputs")
    ap.add_argument("--out-dir", default="study_pack")
    ap.add_argument("--max-cases", type=int, default=80)
    ap.add_argument("--drive-path", action="append", default=[])
    ap.add_argument("--drive-max-depth", type=int, default=2)
    ap.add_argument("--drive-max-files", type=int, default=3000)
    ap.add_argument("--drive-timeout-sec", type=int, default=180)
    args = ap.parse_args()

    root = Path(args.project_root).resolve()
    training_root = (root / args.training_root).resolve()
    runs_root = training_root / "runs"
    outputs_dir = (root / args.outputs_dir).resolve()
    out_dir = (root / args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    drive_paths = list(args.drive_path) or [
        "gdrive:OCR_annotation_Atlas/vps_outputs",
        "gdrive:OCR_annotation_Atlas/local_outputs/outputs",
    ]

    runs = collect_run_records(runs_root, root)
    episodes, episode_states, feedback_freq = collect_episodes(runs_root, root, outputs_dir)
    docs = collect_docs(root)
    drive_files, drive_errors = collect_drive_files(
        drive_paths, args.drive_max_depth, args.drive_max_files, args.drive_timeout_sec
    )

    issue_counter: Counter = Counter()
    issue_example: Dict[Tuple[str, str], str] = {}
    for ep in episodes:
        for msg in ep["validation_errors"]:
            key = ("error", msg)
            issue_counter[key] += 1
            issue_example.setdefault(key, ep["episode_id"])
        for msg in ep["validation_warnings"]:
            key = ("warning", msg)
            issue_counter[key] += 1
            issue_example.setdefault(key, ep["episode_id"])

    issues = []
    for (sev, msg), cnt in issue_counter.most_common():
        issues.append({"severity": sev, "message": msg, "count": cnt, "example_episode": issue_example[(sev, msg)]})

    episode_rows = []
    for ep in episodes:
        episode_rows.append(
            {
                "episode_id": ep["episode_id"],
                "source_run": ep["source_run"],
                "run_generated_at": ep["run_generated_at"],
                "source_href": ep["source_href"],
                "status_state": ep["status_state"],
                "validation_ok": ep["validation_ok"],
                "error_count": ep["error_count"],
                "warning_count": ep["warning_count"],
                "segment_count": ep["segment_count"],
                "label_segments": ep["label_segments"],
                "operations_count": ep["operations_count"],
                "model": ep["model"],
                "top_issue": ep["top_issue"],
                "detail_text": rel_path(ep["detail_text"], root),
                "detail_html": rel_path(ep["detail_html"], root),
                "labels_json": rel_path(ep["labels_file"], root),
                "validation_json": rel_path(ep["validation_file"], root),
                "prompt_txt": rel_path(ep["prompt_file"], root),
                "segments_json": rel_path(ep["segments_file"], root),
                "text_current": rel_path(ep["text_current"], root),
                "text_update": rel_path(ep["text_update"], root),
                "video_raw": rel_path(ep["video_raw"], root),
                "video_upload_opt": rel_path(ep["video_opt"], root),
                "updated_at": ep["updated_at"],
            }
        )

    case_src = sorted(
        episodes,
        key=lambda x: (x["error_count"], x["warning_count"], x["segment_count"], x["updated_ts"]),
        reverse=True,
    )
    practice = []
    for ep in case_src[: max(1, args.max_cases)]:
        if ep["error_count"] > 0:
            focus = "Policy error fixing"
            steps = [
                "Open validation JSON and list failing segments.",
                "Compare text current/update and explain why update is better.",
                "Rewrite at least 3 failed labels with explicit object/action/place.",
            ]
        elif ep["warning_count"] > 0:
            focus = "Warning reduction"
            steps = [
                "Review warning messages and identify recurring drift patterns.",
                "Check timestamp/segment alignment carefully before apply.",
                "Create a checklist and run it on this case.",
            ]
        else:
            focus = "Strong baseline"
            steps = [
                "Use this case as a reference template.",
                "Note wording patterns that keep labels concise and explicit.",
                "Rewatch the linked video and self-audit your labels.",
            ]
        practice.append(
            {
                "episode_id": ep["episode_id"],
                "focus": focus,
                "error_count": ep["error_count"],
                "warning_count": ep["warning_count"],
                "segment_count": ep["segment_count"],
                "top_issues": ep["top_issues"],
                "artifacts": {
                    "labels_json": rel_path(ep["labels_file"], root),
                    "validation_json": rel_path(ep["validation_file"], root),
                    "text_current": rel_path(ep["text_current"], root),
                    "text_update": rel_path(ep["text_update"], root),
                    "video_raw": rel_path(ep["video_raw"], root),
                    "video_upload_opt": rel_path(ep["video_opt"], root),
                },
                "study_steps": steps,
            }
        )

    write_csv(
        out_dir / "runs_manifest.csv",
        runs,
        ["run_name", "status", "generated_at", "episodes_collected", "feedback_entries_found", "gemini_status", "error", "mtime", "path"],
    )
    write_csv(
        out_dir / "episodes_manifest.csv",
        episode_rows,
        [
            "episode_id",
            "source_run",
            "run_generated_at",
            "source_href",
            "status_state",
            "validation_ok",
            "error_count",
            "warning_count",
            "segment_count",
            "label_segments",
            "operations_count",
            "model",
            "top_issue",
            "detail_text",
            "detail_html",
            "labels_json",
            "validation_json",
            "prompt_txt",
            "segments_json",
            "text_current",
            "text_update",
            "video_raw",
            "video_upload_opt",
            "updated_at",
        ],
    )
    write_csv(out_dir / "top_policy_issues.csv", issues, ["severity", "message", "count", "example_episode"])
    write_jsonl(out_dir / "practice_cases.jsonl", practice)
    write_csv(
        out_dir / "feedback_status_frequency.csv",
        [{"status": k, "count": v} for k, v in feedback_freq.most_common()],
        ["status", "count"],
    )
    write_csv(
        out_dir / "episode_state_frequency.csv",
        [{"state": k, "count": v} for k, v in episode_states.most_common()],
        ["state", "count"],
    )
    write_csv(out_dir / "docs_index.csv", docs, ["path", "extension", "size_bytes", "modified_at", "excerpt"])
    write_csv(out_dir / "drive_index.csv", drive_files, ["remote", "path", "size_bytes", "modified_at", "extension"])

    err_eps = sum(1 for e in episodes if e["error_count"] > 0)
    warn_eps = sum(1 for e in episodes if e["warning_count"] > 0)
    raw_v = sum(1 for e in episodes if e["video_raw"] is not None)
    opt_v = sum(1 for e in episodes if e["video_opt"] is not None)
    run_errs = sum(1 for r in runs if r["status"] == "error")
    summary = {
        "generated_at": now_iso(),
        "project_root": str(root),
        "training_root": str(training_root),
        "out_dir": str(out_dir),
        "runs_total": len(runs),
        "runs_error": run_errs,
        "episodes_unique": len(episodes),
        "episodes_with_errors": err_eps,
        "episodes_with_warnings": warn_eps,
        "local_video_raw_linked": raw_v,
        "local_video_opt_linked": opt_v,
        "docs_count": len(docs),
        "pdf_count": sum(1 for d in docs if d["extension"] == ".pdf"),
        "docx_count": sum(1 for d in docs if d["extension"] == ".docx"),
        "drive_files_indexed": len(drive_files),
        "drive_errors": drive_errors,
        "top_issues_preview": issues[:10],
    }
    write_json(out_dir / "summary.json", summary)

    top_lines = [f"- [{r['severity']}] {r['message']} (x{r['count']})" for r in issues[:10]]
    if not top_lines:
        top_lines = ["- No validation issues found."]
    md = (
        "# Atlas Study Pack\n\n"
        f"- Generated at: `{summary['generated_at']}`\n"
        f"- Unique episodes: **{len(episodes)}**\n"
        f"- Episodes with errors: **{err_eps}**\n"
        f"- Episodes with warnings: **{warn_eps}**\n"
        f"- Local videos linked (raw/opt): **{raw_v}/{opt_v}**\n"
        f"- Local docs indexed (PDF/DOCX): **{len(docs)}**\n"
        f"- Drive files indexed: **{len(drive_files)}**\n\n"
        "## Practical Study Order\n\n"
        "1. Read `top_policy_issues.csv` and memorize repeated mistakes.\n"
        "2. Solve `practice_cases.jsonl` from top to bottom.\n"
        "3. For each case, compare `text_*_current` vs `text_*_update`.\n"
        "4. Rewatch linked `video_*.mp4` for hard cases.\n"
        "5. Use `episodes_manifest.csv` as your exam revision tracker.\n\n"
        "## Top Repeated Issues\n\n"
        + "\n".join(top_lines)
        + "\n\n## Files\n\n"
        "- `summary.json`\n"
        "- `runs_manifest.csv`\n"
        "- `episodes_manifest.csv`\n"
        "- `top_policy_issues.csv`\n"
        "- `practice_cases.jsonl`\n"
        "- `feedback_status_frequency.csv`\n"
        "- `episode_state_frequency.csv`\n"
        "- `docs_index.csv`\n"
        "- `drive_index.csv`\n"
    )
    (out_dir / "INDEX.md").write_text(md, encoding="utf-8")

    print(f"[study-pack] done: {out_dir}")
    print(f"[study-pack] episodes={len(episodes)} issues={len(issues)} docs={len(docs)} drive_files={len(drive_files)}")
    if drive_errors:
        print(f"[study-pack] drive warnings: {len(drive_errors)}")


if __name__ == "__main__":
    main()
