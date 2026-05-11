"""Local bridge between the Atlas Chrome shell and the OCR core."""

from __future__ import annotations

import copy
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import pipeline_runner
from src.infra import solver_config as _solver_config
from src.policy import context_manager as policy_context
from src.rules import labels as _labels
from src.rules import policy_gate as _policy_gate

BRIDGE_VERSION = "2026-04-21.core-extension-bridge"
DEFAULT_HOST = os.environ.get("ATLAS_BRIDGE_HOST", "127.0.0.1").strip() or "127.0.0.1"
DEFAULT_PORT = int(os.environ.get("ATLAS_BRIDGE_PORT", "8766") or "8766")
REPO_ROOT = Path(__file__).resolve().parent
MESSAGE_RE = re.compile(r"^segment\s+(?P<idx>\d+):\s*(?P<message>.+)$", re.IGNORECASE)
DEFAULT_PROVIDER_MODELS = {
    "anthropic": "claude-3-5-sonnet-20241022",
    "gemini": "gemini-2.5-pro",
    "openai": "gpt-4o-mini",
}
SELECTOR_KEYS = [
    "segment_rows",
    "segment_label",
    "segment_start",
    "segment_end",
    "edit_button_in_row",
    "split_button_in_row",
    "merge_button_in_row",
    "action_confirm_button",
    "label_input",
    "save_button",
]


class CleanLabelRequest(BaseModel):
    label: str = ""
    source_label: str = ""
    segment_index: int = 1
    start_sec: float = 0.0
    end_sec: float = 1.0


class ReviewRow(BaseModel):
    segment_index: int
    label: str = ""
    start_sec: float = 0.0
    end_sec: float = 0.0
    row_text: str = ""


class ReviewRequest(BaseModel):
    provider: str = ""
    model: str = ""
    mode: str = "review_batch"
    rows: List[ReviewRow] = Field(default_factory=list)


def _load_bridge_config() -> Dict[str, Any]:
    config_path_raw = os.environ.get("ATLAS_BRIDGE_CONFIG", "").strip()
    if config_path_raw:
        config_path = Path(config_path_raw)
        if not config_path.is_absolute():
            config_path = (REPO_ROOT / config_path).resolve()
        return _solver_config.load_config(config_path)

    cfg = copy.deepcopy(_solver_config.DEFAULT_CONFIG)
    selector_overrides = _solver_config._load_selectors_yaml(str(REPO_ROOT / "selectors.yaml"))
    if selector_overrides:
        atlas_cfg = cfg.setdefault("atlas", {})
        selectors_cfg = atlas_cfg.setdefault("selectors", {})
        selectors_cfg.update(selector_overrides)
    return cfg


def _selector_bundle_version() -> str:
    selectors_path = REPO_ROOT / "selectors.yaml"
    if selectors_path.exists():
        return f"{_solver_config._SCRIPT_BUILD}:{int(selectors_path.stat().st_mtime)}"
    return _solver_config._SCRIPT_BUILD


def _provider_status() -> Dict[str, Dict[str, Any]]:
    status: Dict[str, Dict[str, Any]] = {}
    for provider in ("anthropic", "gemini", "openai"):
        env_name = pipeline_runner._provider_env_name(provider)
        api_key = pipeline_runner._resolve_key("", env_name)
        if provider == "gemini" and not api_key:
            api_key = pipeline_runner._resolve_key("", "GOOGLE_API_KEY")
        status[provider] = {
            "has_api_key": bool(api_key),
            "default_model": DEFAULT_PROVIDER_MODELS[provider],
        }
    return status


def _default_provider(status: Dict[str, Dict[str, Any]]) -> str:
    for provider in ("anthropic", "gemini", "openai"):
        if status.get(provider, {}).get("has_api_key"):
            return provider
    return "anthropic"


def _build_source_segments(rows: List[ReviewRow]) -> List[Dict[str, Any]]:
    source_segments: List[Dict[str, Any]] = []
    for pos, row in enumerate(rows, start=1):
        segment_index = int(row.segment_index or pos)
        start_sec = float(row.start_sec or 0.0)
        end_sec = float(row.end_sec or 0.0)
        if end_sec <= start_sec:
            end_sec = start_sec + 1.0
        source_segments.append(
            {
                "segment_index": segment_index,
                "start_sec": round(start_sec, 3),
                "end_sec": round(end_sec, 3),
                "current_label": str(row.label or "").strip(),
                "raw_text": str(row.row_text or "").strip(),
            }
        )
    return source_segments


def _plan_from_source_segments(source_segments: List[Dict[str, Any]], cfg: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    payload = {
        "segments": [
            {
                "segment_index": int(seg["segment_index"]),
                "label": str(seg.get("current_label", "") or "").strip(),
                "start_sec": float(seg.get("start_sec", 0.0) or 0.0),
                "end_sec": float(seg.get("end_sec", 0.0) or 0.0),
            }
            for seg in source_segments
        ]
    }
    return _labels._normalize_segment_plan(payload, source_segments, cfg=cfg)


def _policy_messages_by_segment(report: Dict[str, Any], key: str) -> Dict[int, List[str]]:
    out: Dict[int, List[str]] = {}
    for item in report.get(key, []) or []:
        raw = str(item or "").strip()
        match = MESSAGE_RE.match(raw)
        if not match:
            continue
        idx = int(match.group("idx"))
        out.setdefault(idx, []).append(match.group("message"))
    return out


def _resolve_provider_request(provider: str, model: str) -> Tuple[str, str, str]:
    status = _provider_status()
    requested_provider = pipeline_runner._canonical_provider(provider or "")
    if requested_provider not in status:
        requested_provider = _default_provider(status)

    resolved_model = str(model or "").strip() or DEFAULT_PROVIDER_MODELS[requested_provider]
    env_name = pipeline_runner._provider_env_name(requested_provider)
    api_key = pipeline_runner._resolve_key("", env_name)
    if requested_provider == "gemini" and not api_key:
        api_key = pipeline_runner._resolve_key("", "GOOGLE_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail=f"No API key configured for provider '{requested_provider}'.",
        )
    return requested_provider, resolved_model, api_key


def _build_review_prompt(rows: List[ReviewRow]) -> Tuple[str, str]:
    policy_summary = policy_context.build_policy_prompt_summary().strip()
    system_prompt = (
        "You are an Atlas row review assistant.\n"
        "Improve existing labels conservatively.\n"
        "Return JSON only in this shape: "
        '{"segments":[{"segment_index":1,"label":"pick up item"}]}\n'
        "Do not include explanations, timestamps, or extra keys.\n"
        "Each label must be concise, imperative, and policy compliant.\n"
    )
    if policy_summary:
        system_prompt += f"\nPolicy summary:\n{policy_summary}\n"

    user_rows = [
        {
            "segment_index": int(row.segment_index),
            "label": str(row.label or "").strip(),
            "start_sec": float(row.start_sec or 0.0),
            "end_sec": float(row.end_sec or 0.0),
            "row_text": str(row.row_text or "").strip()[:400],
        }
        for row in rows
    ]
    user_text = (
        "Review these Atlas rows and return corrected labels only.\n"
        f"{user_rows}"
    )
    return system_prompt, user_text


def _suggested_plan_for_rows(
    rows: List[ReviewRow],
    cfg: Dict[str, Any],
    provider: str,
    model: str,
) -> Dict[int, Dict[str, Any]]:
    source_segments = _build_source_segments(rows)
    system_prompt, user_text = _build_review_prompt(rows)
    _, resolved_model, api_key = _resolve_provider_request(provider, model)
    payload = pipeline_runner.call_model_json(
        provider=provider,
        api_key=api_key,
        model=resolved_model,
        system_prompt=system_prompt,
        user_text=user_text,
    )
    return _labels._normalize_segment_plan(payload, source_segments, cfg=cfg)


def _row_payloads(
    rows: List[ReviewRow],
    cleaned_plan: Dict[int, Dict[str, Any]],
    suggested_plan: Dict[int, Dict[str, Any]],
    policy_report: Dict[str, Any],
) -> List[Dict[str, Any]]:
    errors_by_segment = _policy_messages_by_segment(policy_report, "errors")
    warnings_by_segment = _policy_messages_by_segment(policy_report, "warnings")
    payload_rows: List[Dict[str, Any]] = []
    for row in rows:
        segment_index = int(row.segment_index)
        payload_rows.append(
            {
                "segment_index": segment_index,
                "cleaned_label": str(cleaned_plan.get(segment_index, {}).get("label", row.label)).strip(),
                "suggested_label": str(suggested_plan.get(segment_index, {}).get("label", "")).strip(),
                "apply_safe": not bool(errors_by_segment.get(segment_index)),
                "errors": errors_by_segment.get(segment_index, []),
                "warnings": warnings_by_segment.get(segment_index, []),
            }
        )
    return payload_rows


def _structural_operations_for_plan(
    plan: Dict[int, Dict[str, Any]],
    cfg: Dict[str, Any],
) -> List[Dict[str, Any]]:
    max_duration_sec = max(0.1, float(_solver_config._cfg_get(cfg, "run.max_segment_duration_sec", 10.0)))
    split_ops: List[Dict[str, Any]] = []
    for idx in sorted(plan):
        item = plan[idx]
        start_sec = float(item.get("start_sec", 0.0) or 0.0)
        end_sec = float(item.get("end_sec", start_sec) or start_sec)
        if end_sec - start_sec > max_duration_sec + 0.05:
            split_ops.append({"action": "split", "segment_index": int(idx)})

    merge_ops = _labels._build_auto_continuity_merge_operations(plan, cfg)
    out: List[Dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for op in split_ops + merge_ops:
        key = (str(op.get("action", "")).strip().lower(), int(op.get("segment_index", 0) or 0))
        if key in seen or key[1] <= 0:
            continue
        seen.add(key)
        out.append({"action": key[0], "segment_index": key[1]})
    return out


app = FastAPI(title="Atlas Local Bridge", version=BRIDGE_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> Dict[str, Any]:
    cfg = _load_bridge_config()
    status = _provider_status()
    default_provider = _default_provider(status)
    return {
        "ok": True,
        "bridge_version": BRIDGE_VERSION,
        "host": DEFAULT_HOST,
        "port": DEFAULT_PORT,
        "selector_bundle_version": _selector_bundle_version(),
        "providers": status,
        "defaults": {
            "provider": default_provider,
            "model": DEFAULT_PROVIDER_MODELS[default_provider],
            "mode": "review_batch",
            "auto_apply_cleaning": True,
            "preview_ai_suggestions": True,
            "preview_structural_operations": True,
            "allow_delete_operations": False,
            "allow_split_operations": True,
            "allow_merge_operations": True,
            "max_segment_duration_sec": float(_solver_config._cfg_get(cfg, "run.max_segment_duration_sec", 10.0)),
        },
    }


@app.get("/v1/atlas-config")
def atlas_config() -> Dict[str, Any]:
    cfg = _load_bridge_config()
    selectors = dict(_solver_config._cfg_get(cfg, "atlas.selectors", {}) or {})
    provider_status = _provider_status()
    default_provider = _default_provider(provider_status)
    return {
        "selector_bundle_version": _selector_bundle_version(),
        "selectors": {key: str(selectors.get(key, "") or "").strip() for key in SELECTOR_KEYS},
        "feature_flags": {
            "auto_apply_cleaning": True,
            "preview_ai_suggestions": True,
            "preview_structural_operations": True,
            "allow_delete_operations": False,
            "allow_split_operations": True,
            "allow_merge_operations": True,
            "max_segment_duration_sec": float(_solver_config._cfg_get(cfg, "run.max_segment_duration_sec", 10.0)),
        },
        "defaults": {
            "provider": default_provider,
            "model": DEFAULT_PROVIDER_MODELS[default_provider],
            "mode": "review_batch",
        },
    }


@app.post("/v1/labels/clean")
def clean_label(request: CleanLabelRequest) -> Dict[str, Any]:
    cfg = _load_bridge_config()
    row = ReviewRow(
        segment_index=int(request.segment_index or 1),
        label=str(request.label or "").strip(),
        start_sec=float(request.start_sec or 0.0),
        end_sec=float(request.end_sec or 0.0),
        row_text="",
    )
    source_segments = [
        {
            "segment_index": int(request.segment_index or 1),
            "start_sec": float(request.start_sec or 0.0),
            "end_sec": float(request.end_sec or 1.0) if float(request.end_sec or 0.0) > float(request.start_sec or 0.0) else float(request.start_sec or 0.0) + 1.0,
            "current_label": str(request.source_label or request.label or "").strip(),
            "raw_text": "",
        }
    ]
    cleaned_plan = _plan_from_source_segments(source_segments, cfg)
    if str(request.label or "").strip() and str(request.label or "").strip() != str(request.source_label or "").strip():
        cleaned_plan = _labels._normalize_segment_plan(
            {
                "segments": [
                    {
                        "segment_index": int(request.segment_index or 1),
                        "label": str(request.label or "").strip(),
                        "start_sec": float(source_segments[0]["start_sec"]),
                        "end_sec": float(source_segments[0]["end_sec"]),
                    }
                ]
            },
            source_segments,
            cfg=cfg,
        )
    policy_report = _policy_gate._validate_segment_plan_against_policy(cfg, source_segments, cleaned_plan)
    row_payload = _row_payloads([row], cleaned_plan, {}, policy_report)[0]
    return {
        "cleaned_label": row_payload["cleaned_label"],
        "issues": row_payload["errors"],
        "warnings": row_payload["warnings"],
    }


@app.post("/v1/segments/review")
def review_segments(request: ReviewRequest) -> Dict[str, Any]:
    mode = str(request.mode or "review_batch").strip().lower()
    if mode not in {"clean_only", "suggest_only", "review_batch"}:
        raise HTTPException(status_code=400, detail=f"Unsupported review mode: {request.mode}")
    if not request.rows:
        raise HTTPException(status_code=400, detail="At least one row is required.")

    cfg = _load_bridge_config()
    source_segments = _build_source_segments(request.rows)
    cleaned_plan = _plan_from_source_segments(source_segments, cfg)

    suggested_plan: Dict[int, Dict[str, Any]] = {}
    target_plan = cleaned_plan
    if mode in {"suggest_only", "review_batch"}:
        provider_status = _provider_status()
        provider = pipeline_runner._canonical_provider(request.provider or "")
        if provider not in provider_status:
            provider = _default_provider(provider_status)
        suggested_plan = _suggested_plan_for_rows(request.rows, cfg, provider, request.model)
        target_plan = suggested_plan

    policy_report = _policy_gate._validate_segment_plan_against_policy(cfg, source_segments, target_plan)
    operations = _structural_operations_for_plan(target_plan, cfg)

    return {
        "rows": _row_payloads(request.rows, cleaned_plan, suggested_plan, policy_report),
        "operations": operations,
        "policy_report": policy_report,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=DEFAULT_HOST, port=DEFAULT_PORT)
