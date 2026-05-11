"""
atlas_repair_loop.py — Deterministic repair loop for the 4-way flow.

When the submit gate blocks an episode, this module:
1. Extracts the best failing candidate (winner or highest scorer)
2. Runs validator.py to get structured error report
3. Builds a repair payload via repair_payload_builder.py
4. Calls Gemini to repair the annotation guided by exact errors
5. Re-validates the repaired result
6. If it passes the gate → returns approved annotation
7. After max_attempts → writes to manual_queue.jsonl and returns None

This closes the gap between "judge diagnoses problem" and "problem gets fixed".
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import yaml


# ---------------------------------------------------------------------------
# Config & Result types
# ---------------------------------------------------------------------------

@dataclass
class RepairLoopConfig:
    max_attempts: int = 2
    repair_model: str = "gemini-2.5-flash"
    repair_auth_mode: str = "api_key"          # api_key | vertex_ai
    vertex_project: str = ""
    vertex_location: str = "us-central1"
    vertex_credentials_path: str = ""
    gemini_api_key: str = ""
    temperature: float = 0.0
    request_timeout_sec: int = 120
    retry_base_delay_sec: float = 2.0
    min_pass_score: int = 95

    @classmethod
    def from_yaml_cfg(cls, cfg: Dict[str, Any], min_pass_score: int = 95) -> "RepairLoopConfig":
        gem = cfg.get("gemini", {}) if isinstance(cfg, dict) else {}
        if not isinstance(gem, dict):
            gem = {}
        import os
        return cls(
            max_attempts=int(gem.get("repair_max_attempts", 2) or 2),
            repair_model=str(
                gem.get("repair_model") or gem.get("model") or "gemini-2.5-flash"
            ).strip(),
            repair_auth_mode=str(gem.get("repair_auth_mode") or gem.get("auth_mode") or "api_key").strip(),
            vertex_project=str(gem.get("vertex_project") or os.environ.get("GOOGLE_CLOUD_PROJECT", "") or "").strip(),
            vertex_location=str(gem.get("vertex_location") or "us-central1").strip(),
            vertex_credentials_path=str(
                gem.get("vertex_credentials_path") or
                os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "") or ""
            ).strip(),
            gemini_api_key=str(
                gem.get("api_key") or
                os.environ.get("GEMINI_API_KEY") or
                os.environ.get("GOOGLE_API_KEY") or ""
            ).strip(),
            temperature=float(gem.get("repair_temperature") or gem.get("temperature") or 0.0),
            request_timeout_sec=int(gem.get("repair_timeout_sec") or 120),
            retry_base_delay_sec=float(gem.get("retry_base_delay_sec") or 2.0),
            min_pass_score=min_pass_score,
        )


@dataclass
class RepairAttempt:
    attempt_number: int
    input_major_fails: List[str]
    repaired_segments: Optional[List[Dict[str, Any]]]
    validator_ok: Optional[bool]
    validator_major_fails: List[str]
    gate_passed: bool
    error: str = ""
    model_used: str = ""
    duration_sec: float = 0.0


@dataclass
class RepairLoopResult:
    episode_id: str
    success: bool
    final_segments: Optional[List[Dict[str, Any]]]
    attempts: List[RepairAttempt] = field(default_factory=list)
    total_duration_sec: float = 0.0
    failure_reason: str = ""
    queued_for_manual: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "success": self.success,
            "final_segments": self.final_segments,
            "attempts": [
                {
                    "attempt_number": a.attempt_number,
                    "input_major_fails": a.input_major_fails,
                    "validator_ok": a.validator_ok,
                    "validator_major_fails": a.validator_major_fails,
                    "gate_passed": a.gate_passed,
                    "error": a.error,
                    "model_used": a.model_used,
                    "duration_sec": round(a.duration_sec, 2),
                }
                for a in self.attempts
            ],
            "total_duration_sec": round(self.total_duration_sec, 2),
            "failure_reason": self.failure_reason,
            "queued_for_manual": self.queued_for_manual,
        }


# ---------------------------------------------------------------------------
# Repair prompt builder
# ---------------------------------------------------------------------------

REPAIR_SYSTEM_PROMPT = """You are a strict Atlas annotation repair engine.
You receive:
1. A list of annotation segments with their EXACT validator errors
2. The policy rules that were violated

Your job: rewrite ONLY the segments that have errors.
Rules you MUST follow:
- Every label MUST start with an allowed action verb (pick up, place, move, adjust, etc.)
- NO numerals (write "two" not "2")
- NO intent language (prepare to / try to / about to)
- NO body part references (hand, finger, thumb)
- NO narrative fillers (then, another, continue, next, again)
- NO "place" without a location (place X on Y, not just "place X")
- Max 2 atomic actions per label
- "No Action" only for true inactivity
- Keep timestamps EXACTLY as given — do NOT change start_sec or end_sec
- Keep the JSON structure identical — only change the "label" field

Output ONLY a valid JSON array of ALL segments (repaired + unchanged).
No markdown, no explanation, no preamble.
"""

def _build_repair_prompt(
    segments: List[Dict[str, Any]],
    validator_report: Dict[str, Any],
    tier2_reference: str = "",
) -> str:
    """Build a structured repair prompt from segment errors."""
    seg_reports = validator_report.get("segment_reports", [])

    # Build error map: segment_index → list of errors
    error_map: Dict[int, Dict[str, Any]] = {}
    for rep in seg_reports:
        if not isinstance(rep, dict):
            continue
        idx = int(rep.get("segment_index", 0) or 0)
        errs = rep.get("errors", [])
        if errs:
            error_map[idx] = {
                "label": rep.get("label", ""),
                "errors": errs,
            }

    if not error_map:
        return ""  # Nothing to repair

    # Format segments with errors highlighted
    segs_text_parts = ["Segments to review (repair ONLY segments marked ERROR):"]
    for idx, seg in enumerate(segments):
        label = str(seg.get("label", "") or "").strip()
        start = seg.get("start_sec", 0)
        end = seg.get("end_sec", 0)
        if idx in error_map:
            errs = error_map[idx]["errors"]
            segs_text_parts.append(
                f"  [{idx}] {start:.1f}→{end:.1f} | LABEL: \"{label}\" | "
                f"*** ERRORS: {', '.join(errs)} ***"
            )
        else:
            segs_text_parts.append(
                f"  [{idx}] {start:.1f}→{end:.1f} | LABEL: \"{label}\" | OK"
            )

    major_fails = validator_report.get("major_fail_triggers", [])
    episode_errors = validator_report.get("episode_errors", [])

    prompt = (
        f"Episode major policy failures: {', '.join(major_fails) or 'none'}\n"
        f"Episode structural errors: {', '.join(episode_errors) or 'none'}\n\n"
        + "\n".join(segs_text_parts)
    )

    if tier2_reference:
        prompt += f"\n\nTier2 reference (employee's original — use for context only):\n{tier2_reference[:2000]}"

    prompt += (
        "\n\nRepair all ERROR segments and return the complete segment array as JSON. "
        "Keep timestamps unchanged. Output only the JSON array."
    )
    return prompt


# ---------------------------------------------------------------------------
# Gemini repair call
# ---------------------------------------------------------------------------

def _get_bearer_token(cfg: RepairLoopConfig) -> str:
    """Get Vertex AI bearer token from service account credentials."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_file(
            cfg.vertex_credentials_path,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        creds.refresh(Request())
        return str(getattr(creds, "token", "") or "").strip()
    except Exception as exc:
        raise RuntimeError(f"Failed to get Vertex bearer token: {exc}") from exc


def _call_repair_model(
    cfg: RepairLoopConfig,
    prompt: str,
) -> str:
    """Call Gemini with repair prompt, return raw text response."""
    if cfg.repair_auth_mode == "vertex_ai":
        token = _get_bearer_token(cfg)
        loc = cfg.vertex_location or "us-central1"
        host = "aiplatform.googleapis.com" if loc == "global" else f"{loc}-aiplatform.googleapis.com"
        url = (
            f"https://{host}/v1/projects/{cfg.vertex_project}"
            f"/locations/{loc}/publishers/google/models/{cfg.repair_model}:generateContent"
        )
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
    else:
        api_key = cfg.gemini_api_key
        if not api_key:
            raise RuntimeError("Missing GEMINI_API_KEY for repair call")
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{cfg.repair_model}:generateContent?key={api_key}"
        )
        headers = {"Content-Type": "application/json"}

    payload = {
        "systemInstruction": {"parts": [{"text": REPAIR_SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": cfg.temperature,
            "responseMimeType": "application/json",
        },
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=cfg.request_timeout_sec)
    if resp.status_code != 200:
        raise RuntimeError(f"Repair API error HTTP {resp.status_code}: {resp.text[:400]}")

    data = resp.json()
    for cand in data.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
    raise RuntimeError(f"No text in repair response: {str(data)[:300]}")


def _parse_repaired_segments(raw_text: str) -> Optional[List[Dict[str, Any]]]:
    """Parse JSON array from repair response."""
    import re
    clean = re.sub(r"```json|```", "", raw_text or "", flags=re.IGNORECASE).strip()
    # Find outermost array
    start = clean.find("[")
    end = clean.rfind("]")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(clean[start:end + 1])
            if isinstance(parsed, list) and all(isinstance(s, dict) for s in parsed):
                return parsed
        except Exception:
            pass
    # Try object with segments key
    start2 = clean.find("{")
    end2 = clean.rfind("}")
    if start2 >= 0 and end2 > start2:
        try:
            obj = json.loads(clean[start2:end2 + 1])
            segs = obj.get("segments") or obj.get("labels") or []
            if isinstance(segs, list):
                return segs
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# Main repair loop
# ---------------------------------------------------------------------------

def run_repair_loop(
    *,
    episode_id: str,
    segments: List[Dict[str, Any]],
    config_path: str,
    outputs_dir: Path,
    tier2_reference: str = "",
    min_pass_score: int = 95,
    video_duration_sec: float = 0.0,
) -> RepairLoopResult:
    """
    Run repair loop on failing segments.

    Args:
        episode_id: Atlas episode ID
        segments: parsed segments from the failing winner candidate
        config_path: path to sample_web_auto_solver.yaml
        outputs_dir: Path to outputs directory
        tier2_reference: raw text of Tier2 draft (for context)
        min_pass_score: minimum score threshold
        video_duration_sec: video duration for validator

    Returns:
        RepairLoopResult with success=True and final_segments if repaired
    """
    import validator as val_module  # type: ignore

    eid = str(episode_id or "").strip().lower()
    t_start = time.time()

    # Load config
    cfg_path = Path(config_path).resolve()
    raw_cfg: Dict[str, Any] = {}
    if cfg_path.exists():
        try:
            raw_cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        except Exception:
            pass
    loop_cfg = RepairLoopConfig.from_yaml_cfg(raw_cfg, min_pass_score=min_pass_score)

    attempts: List[RepairAttempt] = []
    current_segments = list(segments)

    for attempt_num in range(1, loop_cfg.max_attempts + 1):
        t_attempt = time.time()
        print(f"[repair-loop] attempt={attempt_num}/{loop_cfg.max_attempts} episode={eid}")

        # Step A: validate current segments
        annotation = {
            "episode_id": eid,
            "video_duration_sec": video_duration_sec,
            "segments": [
                {
                    "segment_index": i,
                    "start_sec": float(s.get("start_sec", s.get("start", 0.0)) or 0.0),
                    "end_sec": float(s.get("end_sec", s.get("end", 0.0)) or 0.0),
                    "label": str(s.get("label", "") or "").strip(),
                    "duration_sec": max(0.0,
                        float(s.get("end_sec", s.get("end", 0.0)) or 0.0) -
                        float(s.get("start_sec", s.get("start", 0.0)) or 0.0)
                    ),
                }
                for i, s in enumerate(current_segments)
            ],
        }
        val_report = val_module.validate_episode(annotation)
        major_fails = list(val_report.get("major_fail_triggers") or [])
        validator_ok = bool(val_report.get("ok"))

        if validator_ok:
            # Already passes validator — check score threshold too
            attempt = RepairAttempt(
                attempt_number=attempt_num,
                input_major_fails=major_fails,
                repaired_segments=current_segments,
                validator_ok=True,
                validator_major_fails=[],
                gate_passed=True,
                duration_sec=time.time() - t_attempt,
            )
            attempts.append(attempt)
            print(f"[repair-loop] validator_ok=True on attempt={attempt_num}, episode={eid}")
            return RepairLoopResult(
                episode_id=eid,
                success=True,
                final_segments=current_segments,
                attempts=attempts,
                total_duration_sec=time.time() - t_start,
            )

        # Step B: build repair prompt
        repair_prompt = _build_repair_prompt(current_segments, val_report, tier2_reference)
        if not repair_prompt:
            attempt = RepairAttempt(
                attempt_number=attempt_num,
                input_major_fails=major_fails,
                repaired_segments=None,
                validator_ok=False,
                validator_major_fails=major_fails,
                gate_passed=False,
                error="no_repair_prompt_built",
                duration_sec=time.time() - t_attempt,
            )
            attempts.append(attempt)
            break

        # Step C: call repair model
        repaired_segments: Optional[List[Dict[str, Any]]] = None
        error_msg = ""
        model_used = loop_cfg.repair_model

        for api_attempt in range(1, 3):
            try:
                raw_response = _call_repair_model(loop_cfg, repair_prompt)
                repaired_segments = _parse_repaired_segments(raw_response)
                if repaired_segments:
                    break
                error_msg = "parse_failed: no valid segments in response"
            except Exception as exc:
                error_msg = str(exc)
                low = error_msg.lower()
                is_transient = any(t in low for t in ("429", "500", "502", "503", "timeout"))
                if is_transient and api_attempt < 2:
                    time.sleep(loop_cfg.retry_base_delay_sec * api_attempt)
                    continue
                break

        if not repaired_segments:
            attempt = RepairAttempt(
                attempt_number=attempt_num,
                input_major_fails=major_fails,
                repaired_segments=None,
                validator_ok=False,
                validator_major_fails=major_fails,
                gate_passed=False,
                error=error_msg or "repair_api_failed",
                model_used=model_used,
                duration_sec=time.time() - t_attempt,
            )
            attempts.append(attempt)
            print(f"[repair-loop] api_failed attempt={attempt_num} episode={eid}: {error_msg[:120]}")
            if attempt_num < loop_cfg.max_attempts:
                time.sleep(loop_cfg.retry_base_delay_sec)
            continue

        # Step D: re-validate repaired result
        repaired_annotation = dict(annotation)
        repaired_annotation["segments"] = [
            {
                "segment_index": i,
                "start_sec": float(s.get("start_sec", s.get("start", 0.0)) or 0.0),
                "end_sec": float(s.get("end_sec", s.get("end", 0.0)) or 0.0),
                "label": str(s.get("label", "") or "").strip(),
                "duration_sec": max(0.0,
                    float(s.get("end_sec", s.get("end", 0.0)) or 0.0) -
                    float(s.get("start_sec", s.get("start", 0.0)) or 0.0)
                ),
            }
            for i, s in enumerate(repaired_segments)
        ]
        new_report = val_module.validate_episode(repaired_annotation)
        new_ok = bool(new_report.get("ok"))
        new_major_fails = list(new_report.get("major_fail_triggers") or [])

        attempt = RepairAttempt(
            attempt_number=attempt_num,
            input_major_fails=major_fails,
            repaired_segments=repaired_segments,
            validator_ok=new_ok,
            validator_major_fails=new_major_fails,
            gate_passed=new_ok,
            model_used=model_used,
            duration_sec=time.time() - t_attempt,
        )
        attempts.append(attempt)

        if new_ok:
            # Preserve original timestamps, only update labels
            if len(repaired_segments) != len(current_segments):
                print(
                    f"[repair-loop] reject_repair_shape episode={eid} "
                    f"expected={len(current_segments)} got={len(repaired_segments)}"
                )
                # Do NOT accept mismatched segments, fail this attempt
                attempt.validator_ok = False
                attempt.gate_passed = False
                attempt.error = f"segment_count_mismatch(expected={len(current_segments)}, got={len(repaired_segments)})"
                continue
            merged = []
            for idx, orig in enumerate(current_segments):
                rep = repaired_segments[idx]
                merged.append({
                    **orig,
                    "label": str(rep.get("label", orig.get("label", "")) or "").strip(),
                })
            print(f"[repair-loop] SUCCESS attempt={attempt_num} episode={eid}")
            return RepairLoopResult(
                episode_id=eid,
                success=True,
                final_segments=merged,
                attempts=attempts,
                total_duration_sec=time.time() - t_start,
            )

        print(f"[repair-loop] still_failing attempt={attempt_num} episode={eid} "
              f"major_fails={new_major_fails}")
        current_segments = repaired_segments  # use repaired version for next attempt

    # All attempts exhausted
    _write_repair_log(outputs_dir, eid, attempts)
    return RepairLoopResult(
        episode_id=eid,
        success=False,
        final_segments=None,
        attempts=attempts,
        total_duration_sec=time.time() - t_start,
        failure_reason=f"max_attempts_reached ({loop_cfg.max_attempts})",
        queued_for_manual=True,
    )


def _write_repair_log(outputs_dir: Path, episode_id: str, attempts: List[RepairAttempt]) -> None:
    """Log repair attempt history to outputs/repair_history.jsonl."""
    log_path = outputs_dir / "repair_history.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "episode_id": episode_id,
        "total_attempts": len(attempts),
        "attempts": [
            {
                "attempt_number": a.attempt_number,
                "input_major_fails": a.input_major_fails,
                "validator_ok": a.validator_ok,
                "validator_major_fails": a.validator_major_fails,
                "gate_passed": a.gate_passed,
                "error": a.error,
            }
            for a in attempts
        ],
    }
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Integration helper for atlas_triplet_batch.py
# ---------------------------------------------------------------------------

def attempt_repair_for_episode(
    *,
    episode_id: str,
    gate_result: Any,        # SubmitGateResult from submit_gate.py
    inputs: Dict[str, Any],
    config_path: str,
    outputs_dir: Path,
    min_pass_score: int = 95,
) -> Optional[List[Dict[str, Any]]]:
    """
    Entry point called from atlas_triplet_batch.py when gate blocks an episode.

    Returns repaired segment list if successful, None if failed.
    """
    winner = str(getattr(gate_result, "winner", "") or "").strip().lower()
    if not winner or winner == "none":
        return None

    # Resolve winner file path
    path_map = {
        "tier2": "tier2_path",
        "api": "api_path",
        "chat": "chat_path",
        "vertex_chat": "vertex_chat_path",
    }
    winner_path_str = str(inputs.get(path_map.get(winner, ""), "") or "").strip()
    if not winner_path_str:
        return None

    # Parse segments from winner file
    try:
        from atlas_triplet_compare import parse_timed_segments_text  # type: ignore
        content = Path(winner_path_str).read_text(encoding="utf-8", errors="replace")
        segments = parse_timed_segments_text(content)
    except Exception:
        return None

    if not segments:
        return None

    # Load Tier2 as reference
    tier2_ref = ""
    try:
        t2_path = str(inputs.get("tier2_path", "") or "").strip()
        if t2_path and Path(t2_path).exists():
            tier2_ref = Path(t2_path).read_text(encoding="utf-8", errors="replace")[:3000]
    except Exception:
        pass

    result = run_repair_loop(
        episode_id=episode_id,
        segments=segments,
        config_path=config_path,
        outputs_dir=outputs_dir,
        tier2_reference=tier2_ref,
        min_pass_score=min_pass_score,
    )

    if result.success and result.final_segments:
        print(f"[repair-loop] repaired episode={episode_id} in "
              f"{len(result.attempts)} attempt(s) ({result.total_duration_sec:.1f}s)")
        # Save repaired file for downstream use
        repaired_dir = outputs_dir / "repaired"
        repaired_dir.mkdir(parents=True, exist_ok=True)
        repaired_path = repaired_dir / f"repaired_{episode_id}.json"
        repaired_path.write_text(
            json.dumps({"episode_id": episode_id, "segments": result.final_segments},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return result.final_segments

    # Queue for manual review
    try:
        from submit_gate import append_to_manual_queue  # type: ignore
        append_to_manual_queue(
            outputs_dir,
            gate_result,
            extra_meta={
                "repair_attempted": True,
                "repair_attempts": len(result.attempts),
                "repair_failure_reason": result.failure_reason,
            },
        )
    except Exception as exc:
        import logging
        logging.error(f"[repair-loop] CRITICAL: Failed to append to manual queue for {episode_id}: {exc}", exc_info=True)
        print(f"[repair-loop] CRITICAL: Failed to append to manual queue for {episode_id}: {exc}")

    return None
