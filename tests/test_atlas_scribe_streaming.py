from collections import deque

import numpy as np
import pytest

from atlas_realtime_ws_clients import DeepgramStreamingClient, StreamingEvent, float32_to_pcm16le
from atlas_scribe import BufferedUtterance, ScribeEngine, ScribeSession, load_config


def test_scribe_streaming_defaults_present():
    cfg = load_config()
    assert cfg["streaming"]["enabled"] is True
    assert cfg["streaming"]["frame_ms"] <= 40
    assert cfg["vad"]["backend"] in {"silero", "auto", "energy"}
    assert "translation" in cfg


def test_scribe_enqueue_interim_and_commit_final():
    cfg = load_config()
    cfg["recording"]["output_dir"] = "./tmp_scribe_test"
    engine = ScribeEngine(config=cfg)
    engine.current_session = ScribeSession(session_id="sess", started_at="2026-04-03T00:00:00")

    state = BufferedUtterance(source="mic", prefix_frames=deque(maxlen=4))
    state.segment_id = "seg-1"
    state.start_offset_sec = 1.25
    state.last_voice_wall = 10.0
    state.active_frames = [np.ones(320, dtype=np.float32), np.ones(320, dtype=np.float32)]

    engine._enqueue_decode_job(state, is_final=False, reason="interim")
    job = engine._audio_queue.get_nowait()
    assert job["segment_id"] == "seg-1"
    assert job["mode"] == "interim"
    assert job["audio_duration_sec"] > 0

    engine._update_interim_state(
        job,
        {"text": "hello from the live stream", "language": "en", "confidence": 0.88},
        latency_ms=120.0,
    )
    interims = engine.get_live_interims_snapshot()
    assert interims["mic"].text.startswith("hello")
    assert interims["mic"].latency_ms == 120.0

    final_job = dict(job)
    final_job["mode"] = "final"
    engine._commit_final_segment(
        final_job,
        {"text": "hello from the live stream", "language": "en", "confidence": 0.93},
        latency_ms=180.0,
    )
    segments = engine.get_live_segments_snapshot()
    assert len(segments) == 1
    assert segments[0].is_final is True
    assert segments[0].segment_id == "seg-1"
    assert engine.current_session.segment_count == 1


def test_pcm_encoder_outputs_bytes():
    pcm = float32_to_pcm16le(np.array([0.0, 0.5, -0.5], dtype=np.float32))
    assert isinstance(pcm, bytes)
    assert len(pcm) == 6


def test_scribe_resolves_deepgram_provider(monkeypatch):
    cfg = load_config()
    cfg["streaming"]["provider"] = "deepgram"
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-key")
    engine = ScribeEngine(config=cfg)
    assert engine._resolve_transcription_provider() == "deepgram"


def test_deepgram_normalizes_results_payload():
    client = DeepgramStreamingClient(api_key="test-key")
    event = client.normalize_message(
        """
        {
          "type": "Results",
          "is_final": false,
          "start": 0.4,
          "duration": 0.8,
          "channel": {
            "alternatives": [
              {
                "transcript": "hello atlas",
                "confidence": 0.91,
                "languages": ["en-US"]
              }
            ]
          }
        }
        """
    )
    assert event is not None
    assert event.text == "hello atlas"
    assert event.language == "en-US"
    assert event.is_final is False
    assert event.start_sec == 0.4
    assert event.duration_sec == 0.8


def test_fastapi_bridge_serializes_streaming_event():
    pytest.importorskip("fastapi")
    from atlas_scribe_realtime_api import _serialize_event

    payload = _serialize_event(
        StreamingEvent(
            provider="deepgram",
            text="hello atlas",
            is_final=True,
            event_type="Results",
            language="en-US",
            confidence=0.92,
            start_sec=0.0,
            duration_sec=1.1,
            raw={"speech_final": True},
        )
    )
    assert payload["type"] == "transcript"
    assert payload["event_id"].startswith("evt-")
    assert payload["provider"] == "deepgram"
    assert payload["is_final"] is True
    assert payload["duration_sec"] == 1.1


def test_fastapi_bridge_accepts_explicit_event_id():
    pytest.importorskip("fastapi")
    from atlas_scribe_realtime_api import _serialize_event

    payload = _serialize_event(
        StreamingEvent(provider="deepgram", text="ping", is_final=False),
        event_id="evt-manual",
    )
    assert payload["event_id"] == "evt-manual"


def test_utterance_end_commits_pending_interim():
    cfg = load_config()
    engine = ScribeEngine(config=cfg)
    engine.current_session = ScribeSession(session_id="sess", started_at="2026-04-03T00:00:00")
    engine._update_interim_state(
        {
            "segment_id": "seg-utterance",
            "source": "mic",
            "start_offset_sec": 2.0,
            "provider": "deepgram",
        },
        {"text": "partial deepgram text", "language": "en-US", "confidence": 0.77},
        latency_ms=90.0,
    )

    engine._handle_deepgram_event(
        source="mic",
        segment_id="seg-utterance",
        start_offset_sec=2.0,
        event=StreamingEvent(provider="deepgram", text="", is_final=True, event_type="UtteranceEnd"),
        last_audio_wall=10.0,
    )

    segments = engine.get_live_segments_snapshot()
    assert len(segments) == 1
    assert segments[0].text == "partial deepgram text"
    assert segments[0].provider == "deepgram"


def test_stale_deepgram_interim_is_ignored():
    cfg = load_config()
    engine = ScribeEngine(config=cfg)
    current = type("SessionStub", (), {"segment_id": "seg-new"})()
    engine._provider_sessions["mic"] = current  # type: ignore[assignment]
    engine._update_interim_state(
        {
            "segment_id": "seg-new",
            "source": "mic",
            "start_offset_sec": 3.0,
            "provider": "deepgram",
        },
        {"text": "new utterance", "language": "en-US", "confidence": 0.9},
        latency_ms=50.0,
    )

    engine._handle_deepgram_event(
        source="mic",
        segment_id="seg-old",
        start_offset_sec=1.0,
        event=StreamingEvent(provider="deepgram", text="late interim", is_final=False, event_type="Results"),
        last_audio_wall=10.0,
    )

    interims = engine.get_live_interims_snapshot()
    assert interims["mic"].segment_id == "seg-new"
    assert interims["mic"].text == "new utterance"
