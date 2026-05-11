from __future__ import annotations

from typing import Any, Dict

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

import atlas_local_bridge as bridge


def _bridge_config() -> Dict[str, Any]:
    return {
        "run": {
            "max_segment_duration_sec": 10.0,
            "structural_allow_merge": True,
            "auto_continuity_merge_enabled": True,
            "auto_continuity_merge_min_run_segments": 3,
            "auto_continuity_merge_min_token_overlap": 1,
            "auto_continuity_merge_max_combined_duration_sec": 0.0,
        },
        "atlas": {
            "selectors": {
                "segment_rows": "[data-testid='segment-row']",
                "segment_label": "[data-testid='segment-label']",
                "segment_start": "[data-testid='segment-start']",
                "segment_end": "[data-testid='segment-end']",
                "edit_button_in_row": "[data-testid='segment-edit']",
                "split_button_in_row": "[data-testid='segment-split']",
                "merge_button_in_row": "[data-testid='segment-merge']",
                "action_confirm_button": "[data-testid='confirm']",
                "label_input": "[data-testid='label-input']",
                "save_button": "[data-testid='save']",
            }
        },
    }


def _provider_status() -> Dict[str, Dict[str, Any]]:
    return {
        "anthropic": {"has_api_key": True, "default_model": bridge.DEFAULT_PROVIDER_MODELS["anthropic"]},
        "gemini": {"has_api_key": False, "default_model": bridge.DEFAULT_PROVIDER_MODELS["gemini"]},
        "openai": {"has_api_key": False, "default_model": bridge.DEFAULT_PROVIDER_MODELS["openai"]},
    }


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(bridge, "_load_bridge_config", lambda: _bridge_config())
    monkeypatch.setattr(bridge, "_provider_status", lambda: _provider_status())
    monkeypatch.setattr(bridge, "_selector_bundle_version", lambda: "bundle-test")
    return TestClient(bridge.app)


def test_health_reports_bridge_defaults_and_provider_status(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["bridge_version"] == bridge.BRIDGE_VERSION
    assert payload["selector_bundle_version"] == "bundle-test"
    assert payload["defaults"]["provider"] == "anthropic"
    assert payload["defaults"]["model"] == bridge.DEFAULT_PROVIDER_MODELS["anthropic"]
    assert payload["defaults"]["auto_apply_cleaning"] is True
    assert payload["providers"]["anthropic"]["has_api_key"] is True


def test_atlas_config_returns_selector_bundle_and_defaults(client: TestClient) -> None:
    response = client.get("/v1/atlas-config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["selector_bundle_version"] == "bundle-test"
    assert payload["selectors"]["segment_rows"] == "[data-testid='segment-row']"
    assert payload["selectors"]["save_button"] == "[data-testid='save']"
    assert payload["defaults"]["provider"] == "anthropic"
    assert payload["feature_flags"]["preview_ai_suggestions"] is True


def test_clean_label_matches_core_normalization(client: TestClient) -> None:
    cfg = _bridge_config()
    source_segments = [
        {
            "segment_index": 3,
            "start_sec": 0.0,
            "end_sec": 4.0,
            "current_label": "pick up cup",
            "raw_text": "",
        }
    ]
    expected = bridge._plan_from_source_segments(source_segments, cfg)[3]["label"]

    response = client.post(
        "/v1/labels/clean",
        json={
            "label": "pick up cup",
            "source_label": "pick up cup",
            "segment_index": 3,
            "start_sec": 0.0,
            "end_sec": 4.0,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["cleaned_label"] == expected
    assert payload["issues"] == []


def test_review_segments_clean_only_uses_core_cleaning_without_model_call(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _unexpected_call(**_: Any) -> Dict[str, Any]:
        raise AssertionError("model dispatch should not run in clean_only mode")

    monkeypatch.setattr(bridge.pipeline_runner, "call_model_json", _unexpected_call)

    response = client.post(
        "/v1/segments/review",
        json={
            "mode": "clean_only",
            "rows": [
                {
                    "segment_index": 1,
                    "label": "pick up cup",
                    "start_sec": 0.0,
                    "end_sec": 4.0,
                    "row_text": "pick up cup",
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["rows"][0]["cleaned_label"] == "pick up cup"
    assert payload["rows"][0]["suggested_label"] == ""
    assert payload["operations"] == []
    assert payload["policy_report"]["ok"] is True


def test_review_segments_review_batch_dispatches_provider_and_returns_split_preview(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: Dict[str, Any] = {}

    def _fake_resolve(provider: str, model: str) -> tuple[str, str, str]:
        calls["resolved_provider"] = provider
        calls["resolved_model"] = model
        return "anthropic", "claude-test", "secret"

    def _fake_call_model_json(
        provider: str,
        api_key: str,
        model: str,
        system_prompt: str,
        user_text: str,
    ) -> Dict[str, Any]:
        calls["provider"] = provider
        calls["api_key"] = api_key
        calls["model"] = model
        calls["system_prompt"] = system_prompt
        calls["user_text"] = user_text
        return {
            "segments": [
                {
                    "segment_index": 1,
                    "label": "place cup on table",
                    "start_sec": 0.0,
                    "end_sec": 12.2,
                }
            ]
        }

    monkeypatch.setattr(bridge, "_resolve_provider_request", _fake_resolve)
    monkeypatch.setattr(bridge.pipeline_runner, "call_model_json", _fake_call_model_json)

    response = client.post(
        "/v1/segments/review",
        json={
            "mode": "review_batch",
            "provider": "",
            "model": "",
            "rows": [
                {
                    "segment_index": 1,
                    "label": "pick up cup",
                    "start_sec": 0.0,
                    "end_sec": 12.2,
                    "row_text": "pick up cup",
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert calls["provider"] == "anthropic"
    assert calls["api_key"] == "secret"
    assert calls["model"] == "claude-test"
    assert "Return JSON only" in calls["system_prompt"]
    assert "segment_index" in calls["user_text"]
    assert payload["rows"][0]["suggested_label"] == "place cup on table"
    assert payload["rows"][0]["apply_safe"] is False
    assert payload["operations"] == [{"action": "split", "segment_index": 1}]
    assert payload["policy_report"]["ok"] is False
