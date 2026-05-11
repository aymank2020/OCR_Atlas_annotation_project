"""Tests for atlas/infra/config.py — Pydantic configuration validation."""
import os
import pytest
from unittest.mock import patch

from atlas.infra.config import AtlasConfig, GeminiConfig, VertexConfig, DiscordConfig, reset_config, get_config


# ── Unit Tests ───────────────────────────────────────────────────

def test_gemini_config_requires_api_key():
    """GeminiConfig fails fast without api_key."""
    with pytest.raises(Exception):
        GeminiConfig(api_key="")  # min_length=10


def test_gemini_config_all_keys():
    """all_keys returns non-empty keys."""
    cfg = GeminiConfig(api_key="1234567890", api_key_fallback="abcdefghij", api_key_secondary="")
    assert len(cfg.all_keys) == 2
    assert "1234567890" in cfg.all_keys


def test_vertex_config_defaults():
    """VertexConfig has sensible defaults."""
    cfg = VertexConfig(project="test-project")
    assert cfg.location == "us-central1"
    assert cfg.model == "gemini-2.5-pro"


def test_atlas_config_from_env():
    """AtlasConfig.from_env() loads from environment variables."""
    env = {
        "GEMINI_API_KEY": "test_key_1234567890",
        "GOOGLE_CLOUD_PROJECT": "my-project-123",
        "ATLAS_EMAIL": "test@test.com",
        "PASS_SCORE_THRESHOLD": "90",
        "STRICT_GATE": "0",
    }
    with patch.dict(os.environ, env, clear=False):
        reset_config()
        cfg = get_config()
        assert cfg.gemini.api_key == "test_key_1234567890"
        assert cfg.vertex.project == "my-project-123"
        assert cfg.pass_score_threshold == 90
        assert cfg.strict_gate is False
        reset_config()


def test_atlas_config_threshold_bounds():
    """pass_score_threshold must be 0-100."""
    with pytest.raises(Exception):
        AtlasConfig(
            gemini=GeminiConfig(api_key="test_key_1234567890"),
            vertex=VertexConfig(project="proj"),
            discord=DiscordConfig(),
            pass_score_threshold=200,  # out of bounds
        )
