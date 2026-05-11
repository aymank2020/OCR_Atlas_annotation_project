"""Tests for atlas/domain/models.py — Pydantic domain models."""
import pytest
from atlas.domain.models import (
    Segment, Episode, Candidate, JudgeResult, ValidationReport,
    GateDecisionRecord, Granularity, SolveMethod, GateDecision,
    SegmentReport, RepairPayload, GoldSample,
)


# ── Segment Tests ────────────────────────────────────────────────

def test_segment_valid():
    seg = Segment(segment_index=1, start_sec=0.0, end_sec=3.0, label="pick up tool")
    assert seg.segment_index == 1
    assert seg.label == "pick up tool"


def test_segment_auto_duration():
    seg = Segment(segment_index=1, start_sec=1.0, end_sec=4.0, label="action")
    assert seg.duration_sec == 3.0


def test_segment_rejects_empty_label():
    with pytest.raises(Exception):
        Segment(segment_index=1, start_sec=0.0, end_sec=1.0, label="")


def test_segment_rejects_negative_start():
    with pytest.raises(Exception):
        Segment(segment_index=1, start_sec=-1.0, end_sec=1.0, label="action")


# ── Episode Tests ────────────────────────────────────────────────

def test_episode_valid():
    ep = Episode(
        episode_id="ep_001",
        video_duration_sec=10.0,
        segments=[Segment(segment_index=1, start_sec=0.0, end_sec=5.0, label="test action")],
    )
    assert ep.episode_id == "ep_001"
    assert len(ep.segments) == 1


def test_episode_rejects_invalid_id():
    with pytest.raises(Exception):
        Episode(episode_id="ep with spaces!", video_duration_sec=5.0)


# ── Candidate Tests ──────────────────────────────────────────────

def test_candidate_methods():
    c = Candidate(method=SolveMethod.TIER3_API, model_name="gemini-2.5-pro")
    assert c.method == SolveMethod.TIER3_API


# ── JudgeResult Tests ────────────────────────────────────────────

def test_judge_result_quality():
    jr = JudgeResult(
        winner=SolveMethod.VERTEX_CHAT,
        winner_score=98.5,
        quality_pass=True,
        scores={"tier3_api": 92.0, "vertex_chat": 98.5},
    )
    assert jr.quality_pass is True
    assert jr.winner_score == 98.5


# ── Gate Decision Tests ──────────────────────────────────────────

def test_gate_decision_record():
    gdr = GateDecisionRecord(
        episode_id="ep_001",
        decision=GateDecision.PASS,
        score=97.0,
        validator_ok=True,
    )
    assert gdr.decision == GateDecision.PASS


# ── Granularity Enum ─────────────────────────────────────────────

def test_granularity_enum():
    assert Granularity.COARSE.value == "coarse"
    assert Granularity.DENSE.value == "dense"


# ── Validation Report ────────────────────────────────────────────

def test_validation_report():
    vr = ValidationReport(
        ok=False,
        episode_id="ep_001",
        segment_reports=[SegmentReport(segment_index=1, errors=["verb_error"])],
        episode_errors=["gap_detected"],
    )
    assert not vr.ok
    assert len(vr.segment_reports) == 1
    assert "verb_error" in vr.segment_reports[0].errors
