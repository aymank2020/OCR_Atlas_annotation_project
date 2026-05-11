"""
Atlas Scribe â€” Real-Time Audio Intelligence Engine
====================================================
Captures system audio (loopback) + microphone simultaneously,
transcribes with Faster-Whisper on CUDA, enriches with Gemini.

Hardware target: RTX 4050 6GB, i7-13700H, 16GB RAM
"""

import json
import os
import sys
import time
import asyncio
import queue
import threading
import logging
import uuid
from pathlib import Path
from collections import deque
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any, Deque

import numpy as np
import yaml

from atlas_realtime_ws_clients import DeepgramStreamingClient, StreamingEvent, float32_to_pcm16le

# â”€â”€ Logging â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("scribe")

# â”€â”€ Soundcard Library Patch (MUST run before any import soundcard) â”€â”€
# ÙŠØµÙ„Ø­ Ù…Ø´ÙƒÙ„Ø© COM S_FALSE (Error 0x100000001) ÙˆÙ…Ø´ÙƒÙ„Ø© numpy.fromstring
try:
    import soundcard_patch
    soundcard_patch.apply()
    log.info("Soundcard patch applied successfully")
except Exception as _patch_err:
    log.warning("Could not apply soundcard patch: %s", _patch_err)

# â”€â”€ Paths â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
PROJECT_ROOT = Path(__file__).parent
CONFIG_FILE = PROJECT_ROOT / "atlas_scribe_config.yaml"
DEFAULT_SESSIONS_DIR = PROJECT_ROOT / "scribe_sessions"


# â”€â”€ COM Helper (Windows) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _com_initialize():
    """Initialize COM for the current thread on Windows.
    
    soundcard uses WASAPI which requires COM. Each thread that uses
    soundcard must call CoInitializeEx. We use COINIT_MULTITHREADED (0)
    which is compatible with WASAPI's threading model.
    Returns True if COM was initialized, False otherwise.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        # COINIT_MULTITHREADED = 0x0
        hr = ctypes.windll.ole32.CoInitializeEx(None, 0)
        # S_OK = 0, S_FALSE = 1 (already initialized), both are success
        if hr < 0:
            # Fallback: try simple CoInitialize (STA)
            ctypes.windll.ole32.CoInitialize(None)
        return True
    except Exception as e:
        log.debug("COM init warning: %s", e)
        return False


def _com_uninitialize():
    """Uninitialize COM for the current thread on Windows."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.ole32.CoUninitialize()
    except Exception:
        pass


# â”€â”€ Data Classes â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@dataclass
class TranscriptSegment:
    """A single transcribed segment."""
    start: float           # seconds since session start
    end: float
    text: str
    source: str            # "system" | "mic"
    language: str = ""
    confidence: float = 0.0
    timestamp_utc: str = ""
    segment_id: str = ""
    is_final: bool = True
    stability: float = 1.0
    translation: str = ""
    translation_language: str = ""
    translation_is_final: bool = False
    provider: str = "faster_whisper"
    latency_ms: float = 0.0

    def to_dict(self):
        return asdict(self)


@dataclass
class InterimTranscript:
    """Live, mutable transcript state shown before finalization."""
    segment_id: str
    source: str
    text: str = ""
    language: str = ""
    confidence: float = 0.0
    stability: float = 0.0
    start: float = 0.0
    updated_at: str = ""
    translation: str = ""
    translation_language: str = ""
    translation_is_final: bool = False
    provider: str = "local_whisper"
    latency_ms: float = 0.0
    revision: int = 0

    def to_dict(self):
        return asdict(self)


@dataclass
class BufferedUtterance:
    """Per-source rolling speech buffer for interim/final decoding."""
    source: str
    prefix_frames: Deque[np.ndarray]
    active_frames: List[np.ndarray] = field(default_factory=list)
    in_speech: bool = False
    segment_id: str = ""
    speech_started_wall: float = 0.0
    last_voice_wall: float = 0.0
    last_interim_wall: float = 0.0
    start_offset_sec: float = 0.0
    total_audio_sec: float = 0.0
    silence_sec: float = 0.0
    vad_score: float = 0.0
    speech_frame_count: int = 0

    def reset(self):
        self.active_frames = []
        self.in_speech = False
        self.segment_id = ""
        self.speech_started_wall = 0.0
        self.last_voice_wall = 0.0
        self.last_interim_wall = 0.0
        self.start_offset_sec = 0.0
        self.total_audio_sec = 0.0
        self.silence_sec = 0.0
        self.vad_score = 0.0
        self.speech_frame_count = 0


class StreamingSpeechGate:
    """Hybrid VAD: prefers Silero when installed, falls back to RMS gating."""

    def __init__(self, sample_rate: int, config: dict):
        self.sample_rate = sample_rate
        self.config = config
        self.backend = "energy"
        self.last_score = 0.0
        self._silero_model = None
        self._torch = None
        self._window_size = int(config.get("window_size_samples", 512))

        backend = str(config.get("backend", "silero")).lower().strip()
        if backend in {"silero", "auto"}:
            try:
                import torch
                from silero_vad import load_silero_vad

                torch.set_num_threads(1)
                self._torch = torch
                self._silero_model = load_silero_vad()
                self.backend = "silero"
            except Exception as exc:
                log.info("Silero VAD unavailable, falling back to RMS gate: %s", exc)
                self._silero_model = None

    def reset(self):
        if self._silero_model is not None:
            try:
                self._silero_model.reset_states()
            except Exception:
                pass

    def is_speech(self, frame: np.ndarray, rms: float) -> bool:
        if self._silero_model is not None and self._torch is not None:
            try:
                tensor = self._torch.from_numpy(frame.astype(np.float32, copy=False))
                if tensor.ndim > 1:
                    tensor = tensor.mean(dim=1)
                if tensor.numel() < self._window_size:
                    pad = self._window_size - int(tensor.numel())
                    tensor = self._torch.nn.functional.pad(tensor, (0, pad))
                elif tensor.numel() > self._window_size:
                    tensor = tensor[-self._window_size:]
                self.last_score = float(self._silero_model(tensor, self.sample_rate).item())
                return self.last_score >= float(self.config.get("threshold", 0.5))
            except Exception as exc:
                log.debug("Silero VAD frame inference failed, using RMS fallback: %s", exc)

        energy_floor = float(self.config.get("energy_threshold", 0.008))
        scaling = max(energy_floor, 1e-6)
        self.last_score = min(1.0, rms / (scaling * 3.0))
        return rms >= energy_floor


class DeepgramUtteranceSession:
    """Owns one Deepgram WebSocket session for a single speech window."""

    def __init__(
        self,
        engine: "ScribeEngine",
        source: str,
        segment_id: str,
        start_offset_sec: float,
    ):
        self.engine = engine
        self.source = source
        self.segment_id = segment_id
        self.start_offset_sec = start_offset_sec
        self.audio_queue: "queue.Queue[Optional[bytes]]" = queue.Queue(maxsize=256)
        self.thread: Optional[threading.Thread] = None
        self.closed = False
        self.last_audio_wall = time.time()

    def start(self):
        self.thread = threading.Thread(
            target=self._run_thread,
            daemon=True,
            name=f"deepgram-{self.source}-{self.segment_id[:8]}",
        )
        self.thread.start()

    def send_frame(self, frame: np.ndarray):
        if self.closed:
            return
        self.last_audio_wall = time.time()
        payload = float32_to_pcm16le(frame)
        try:
            self.audio_queue.put_nowait(payload)
        except queue.Full:
            self.engine._queue_drop_count += 1
            with self.engine._lock:
                self.engine._runtime_stats["drops"] = self.engine._queue_drop_count
            log.debug("Deepgram audio queue full; dropping %s frame", self.source)

    def finalize(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.audio_queue.put_nowait(None)
        except queue.Full:
            pass

    def join(self, timeout: float = 2.0):
        if self.thread:
            self.thread.join(timeout=timeout)

    def _run_thread(self):
        try:
            asyncio.run(self._run_async())
        except Exception as exc:
            self.engine.error_message = f"Deepgram session failed ({self.source}): {exc}"
            log.error("Deepgram session failed (%s): %s", self.source, exc, exc_info=True)
        finally:
            with self.engine._lock:
                current = self.engine._provider_sessions.get(self.source)
                if current is self:
                    self.engine._provider_sessions.pop(self.source, None)
                self.engine._runtime_stats["provider_sessions"] = len(self.engine._provider_sessions)

    async def _run_async(self):
        dcfg = self.engine.config.get("deepgram", {})
        api_key = os.getenv(dcfg.get("api_key_env", "DEEPGRAM_API_KEY"), "")
        if not api_key:
            raise RuntimeError("Missing Deepgram API key")

        language = str(dcfg.get("language", "")).strip()
        client = DeepgramStreamingClient(
            api_key=api_key,
            model=str(dcfg.get("model", "nova-3")),
            sample_rate=int(self.engine.config["audio"]["sample_rate"]),
            encoding=str(dcfg.get("encoding", "linear16")),
            interim_results=bool(dcfg.get("interim_results", True)),
            endpointing_ms=int(dcfg.get("endpointing_ms", 300)),
            utterance_end_ms=int(dcfg.get("utterance_end_ms", 1000)),
        )
        if language:
            client.url += f"&language={language}"

        final_seen = asyncio.Event()
        idle_keepalive_sec = float(dcfg.get("idle_keepalive_sec", 4.0))
        finalize_timeout_sec = float(dcfg.get("finalize_timeout_sec", 1.5))

        await client.connect()

        async def _receiver():
            async for event in client.iter_events():
                self.engine._handle_deepgram_event(
                    source=self.source,
                    segment_id=self.segment_id,
                    start_offset_sec=self.start_offset_sec,
                    event=event,
                    last_audio_wall=self.last_audio_wall,
                )
                if event.is_final and (
                    bool(event.raw.get("speech_final"))
                    or bool(event.raw.get("from_finalize"))
                    or event.event_type == "UtteranceEnd"
                ):
                    final_seen.set()

        receiver_task = asyncio.create_task(_receiver())
        try:
            while True:
                try:
                    audio_chunk = await asyncio.wait_for(
                        asyncio.to_thread(self.audio_queue.get),
                        timeout=idle_keepalive_sec,
                    )
                except asyncio.TimeoutError:
                    await client.send_keepalive()
                    continue

                if audio_chunk is None:
                    await client.finalize()
                    try:
                        await asyncio.wait_for(final_seen.wait(), timeout=finalize_timeout_sec)
                    except asyncio.TimeoutError:
                        pass
                    try:
                        await client.close_stream()
                    except Exception:
                        pass
                    break

                await client.send_audio(audio_chunk)
        finally:
            receiver_task.cancel()
            await client.close()


@dataclass
class ScribeSession:
    """A recording session with its transcript."""
    session_id: str
    started_at: str
    ended_at: Optional[str] = None
    segments: List[TranscriptSegment] = field(default_factory=list)
    summary: Optional[str] = None
    gemini_analysis: Optional[Dict[str, Any]] = None
    # Actual wall-clock duration (computed at stop, NOT a property)
    actual_duration_sec: float = 0.0

    @property
    def duration_sec(self) -> float:
        """Duration from segments, or actual_duration_sec if set."""
        if self.actual_duration_sec > 0:
            return self.actual_duration_sec
        if not self.segments:
            return 0.0
        return self.segments[-1].end

    @property
    def segment_count(self) -> int:
        return len(self.segments)

    def to_dict(self) -> dict:
        """JSON-safe dict representation."""
        return {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "segment_count": self.segment_count,
            "duration_sec": round(self.duration_sec, 1),
            "summary": self.summary,
            "gemini_analysis": self.gemini_analysis,
            "segments": [s.to_dict() for s in self.segments],
        }


# â”€â”€ Config Loader â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def load_config(path: Path = CONFIG_FILE) -> dict:
    """Load YAML config with sensible defaults."""
    defaults = {
        "scribe": {
            "audio": {
                "source": "both",
                "sample_rate": 16000,
                "chunk_duration_sec": 0.04,
                "silence_threshold": 0.001,
                "loopback_device": "",
                "microphone_device": "",
            },
            "streaming": {
                "enabled": True,
                "provider": "deepgram",
                "frame_ms": 40,
                "interim_min_audio_ms": 240,
                "interim_emit_ms": 350,
                "final_silence_ms": 480,
                "max_utterance_ms": 6500,
                "prefix_padding_ms": 160,
                "max_buffer_ms": 9000,
            },
            "deepgram": {
                "api_key_env": "DEEPGRAM_API_KEY",
                "model": "nova-3",
                "language": "",
                "encoding": "linear16",
                "interim_results": True,
                "endpointing_ms": 300,
                "utterance_end_ms": 1000,
                "finalize_timeout_sec": 1.5,
                "idle_keepalive_sec": 4.0,
            },
            "vad": {
                "enabled": True,
                "backend": "silero",
                "threshold": 0.5,
                "energy_threshold": 0.008,
                "window_size_samples": 512,
                "min_speech_ms": 120,
            },
            "whisper": {
                "model_size": "medium",
                "device": "cuda",
                "compute_type": "float16",
                "beam_size": 5,
                "vad_filter": True,
                "vad_min_silence_ms": 300,
                "vad_speech_pad_ms": 200,
            },
            "recording": {
                "enabled": True,
                "output_dir": "./scribe_sessions",
                "auto_export": True,
                "max_session_hours": 8,
                "export_formats": ["json", "txt", "srt"],
            },
            "gemini": {
                "enabled": True,
                "model": "gemini-3.1-pro-preview",
                "api_key_env": "GEMINI_API_KEY",
                "auto_summarize_on_stop": True,
                "summary_language": "ar",
                "extract_rules": True,
            },
            "translation": {
                "enabled": False,
                "provider": "gemini",
                "model": "gemini-2.5-flash",
                "api_key_env": "GEMINI_API_KEY",
                "target_language": "ar",
                "debounce_ms": 400,
                "min_chars": 8,
                "max_chars": 600,
            },
            "dashboard": {
                "port": 8501,
                "auto_refresh_sec": 0.4,
                "max_live_segments": 200,
                "theme": "dark",
            },
        }
    }

    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                user_cfg = yaml.safe_load(f) or {}
            # Deep merge user config over defaults
            _deep_merge(defaults, user_cfg)
        except Exception as e:
            log.warning("Config load error, using defaults: %s", e)

    return defaults["scribe"]


def _deep_merge(base: dict, override: dict):
    """Recursively merge override into base."""
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


# â”€â”€ Thread-safe Audio Device Detection â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _detect_devices_threaded() -> Dict[str, Any]:
    """Run soundcard device detection in a dedicated thread.
    
    soundcard (Windows WASAPI) needs its own COM initialization.
    Running in a fresh thread avoids COM conflicts with Streamlit.
    """
    result: Dict[str, Any] = {"speakers": [], "microphones": [], "error": None}

    def _worker():
        com_init = _com_initialize()
        try:
            # Ø§Ù„Ø±Ù‚Ø¹Ø© Ø§ØªØ·Ø¨Ù‚Øª Ø¨Ø§Ù„ÙØ¹Ù„ Ø¹Ù†Ø¯ Ø¨Ø¯Ø§ÙŠØ© Ø§Ù„Ø¨Ø±Ù†Ø§Ù…Ø¬
            import soundcard as sc
            speakers = sc.all_speakers()
            mics = sc.all_microphones(include_loopback=False)
            loopbacks = sc.all_microphones(include_loopback=True)
            result["speakers"] = [s.name for s in speakers]
            result["microphones"] = [m.name for m in mics]
            # Ø£Ø¬Ù‡Ø²Ø© Loopback = Ø§Ù„ÙƒÙ„ - Ø§Ù„Ù…Ø§ÙŠÙƒØ§Øª = Ø£Ø¬Ù‡Ø²Ø© Ø§Ù„Ù†Ø¸Ø§Ù…
            loopback_only = [lb for lb in loopbacks if lb not in mics]
            result["loopback_devices"] = [lb.name for lb in loopback_only]
            try:
                result["default_speaker"] = sc.default_speaker().name
            except Exception:
                result["default_speaker"] = speakers[0].name if speakers else "N/A"
            try:
                result["default_mic"] = sc.default_microphone().name
            except Exception:
                result["default_mic"] = mics[0].name if mics else "N/A"
        except Exception as e:
            log.error("Device detection error: %s", e)
            result["error"] = str(e)
        finally:
            if com_init:
                _com_uninitialize()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=10)
    if t.is_alive():
        result["error"] = "Device detection timed out"
    return result


# â”€â”€ Scribe Engine â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class ScribeEngine:
    """
    Core engine: captures audio from system + mic,
    transcribes with Whisper, optionally enriches with Gemini.
    Thread-safe for use from Streamlit.
    """

    def __init__(self, config: Optional[dict] = None):
        self.config = config or load_config()
        self.model = None
        self.model_info: str = ""
        self.is_capturing: bool = False
        self.is_paused: bool = False
        self.current_session: Optional[ScribeSession] = None

        sessions_path = self.config["recording"]["output_dir"]
        self.sessions_dir = Path(sessions_path)
        if not self.sessions_dir.is_absolute():
            self.sessions_dir = PROJECT_ROOT / sessions_path
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

        self._session_start_time = 0.0
        self._total_paused_duration = 0.0
        self._last_pause_start = 0.0
        self._audio_queue: queue.Queue = queue.Queue(maxsize=200)
        self._translation_queue: queue.Queue = queue.Queue(maxsize=120)
        self._capture_threads: list = []
        self._transcribe_thread: Optional[threading.Thread] = None
        self._translation_thread: Optional[threading.Thread] = None
        self._provider_sessions: Dict[str, DeepgramUtteranceSession] = {}
        self._stop_event = threading.Event()
        self._lock = threading.RLock()  # Reentrant lock for nested access

        # Live state (read by dashboard)
        self.live_segments: List[TranscriptSegment] = []
        self.live_interims: Dict[str, InterimTranscript] = {}
        self.audio_level_system: float = 0.0
        self.audio_level_mic: float = 0.0
        self.status: str = "idle"
        self.status_detail: str = ""
        self.error_message: str = ""
        self._latency_samples: Deque[float] = deque(maxlen=120)
        self._queue_drop_count: int = 0
        self._translation_client = None
        self._runtime_stats: Dict[str, Any] = {
            "provider": self.config.get("streaming", {}).get("provider", "local_whisper"),
            "vad_backend": self.config.get("vad", {}).get("backend", "energy"),
            "avg_latency_ms": 0.0,
            "last_latency_ms": 0.0,
            "queue_depth": 0,
            "provider_sessions": 0,
            "translation_enabled": bool(self.config.get("translation", {}).get("enabled")),
            "translation_target": self.config.get("translation", {}).get("target_language", ""),
            "drops": 0,
        }
        self._source_buffers: Dict[str, BufferedUtterance] = {}

    # â”€â”€ Thread-safe segment access â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def get_live_segments_snapshot(self) -> List[TranscriptSegment]:
        """Return a thread-safe copy of live_segments."""
        with self._lock:
            return list(self.live_segments)

    def get_live_interims_snapshot(self) -> Dict[str, InterimTranscript]:
        """Return a thread-safe copy of live interim text per source."""
        with self._lock:
            return {key: InterimTranscript(**value.to_dict()) for key, value in self.live_interims.items()}

    def get_runtime_snapshot(self) -> Dict[str, Any]:
        """Return current low-latency runtime metrics."""
        with self._lock:
            snapshot = dict(self._runtime_stats)
            provider_queue_depth = sum(session.audio_queue.qsize() for session in self._provider_sessions.values())
            snapshot["queue_depth"] = self._audio_queue.qsize() + provider_queue_depth
            snapshot["active_interims"] = len(self.live_interims)
            snapshot["live_segments"] = len(self.live_segments)
            snapshot["provider_sessions"] = len(self._provider_sessions)
            return snapshot

    def _resolve_transcription_provider(self) -> str:
        provider = str(self.config.get("streaming", {}).get("provider", "local_whisper")).strip().lower()
        if provider == "deepgram":
            api_key_env = self.config.get("deepgram", {}).get("api_key_env", "DEEPGRAM_API_KEY")
            if os.getenv(api_key_env, "").strip():
                return "deepgram"
            log.warning("Deepgram selected but %s is missing; falling back to local_whisper", api_key_env)
        return "local_whisper"

    # â”€â”€ Model â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def load_model(self):
        """Load Whisper model. Heavy â€” call once with CUDA fallback."""
        if self.model is not None:
            return

        self.status = "loading"
        self.status_detail = "Loading Whisper model..."
        wcfg = self.config["whisper"]
        model_size = wcfg["model_size"]
        device = wcfg["device"]
        compute_type = wcfg["compute_type"]

        # 1. Primary Attempt
        try:
            from faster_whisper import WhisperModel
            
            log.info("ðŸš€ Loading Whisper (%s) on %s...", model_size, device)
            log.info("   â³ Note: Model downloads ~1.5GB to HuggingFace cache on first load and may seem unresponsive.")
            self.model = WhisperModel(model_size, device=device, compute_type=compute_type)
            
            # Critical check: CTranslate2 lazily loads CUDA DLLs on its first compute pass.
            # We run a 1-second silent trace here to force DLL lookup.
            # If cublas64_12.dll or cudnn is missing, this will throw an exception NOW so we can fallback.
            if device == "cuda":
                log.info("   Testing hardware acceleration libraries...")
                dummy_audio = np.zeros(16000, dtype=np.float32)
                # Just consume the generator to force calculation
                list(self.model.transcribe(dummy_audio, vad_filter=False))
            
            self.model_info = f"{model_size} | {device} | {compute_type}"
            self.status = "idle"
            self.status_detail = f"Model ready: {self.model_info}"
            log.info("âœ… Model loaded successfully: %s", self.model_info)
        except Exception as e:
            error_msg = str(e)
            log.warning("âš ï¸ Primary Whisper load failed: %s", error_msg)
            
            # 2. Automatic Fallback to CPU if CUDA libraries are missing
            if device == "cuda" or "cublas" in error_msg.lower() or "cudnn" in error_msg.lower():
                log.info("ðŸ“‰ Fallback: Attempting CPU load due to missing CUDA/DLLs...")
                try:
                    from faster_whisper import WhisperModel as WM
                    self.model = WM(model_size, device="cpu", compute_type="int8")
                    self.model_info = f"{model_size} | cpu (fallback) | int8"
                    self.status = "idle"
                    self.status_detail = f"Model ready: {self.model_info}"
                    log.info("âœ… CPU Fallback successful: %s", self.model_info)
                except Exception as e2:
                    self.status = "error"
                    self.status_detail = "âŒ Model Error"
                    self.error_message = f"Whisper loading failed entirely: {str(e2)}"
                    log.error("âŒ Whisper total failure: %s", e2, exc_info=True)
                    self.model = None
            else:
                self.status = "error"
                self.status_detail = "âŒ Model Error"
                self.error_message = f"Whisper loading failed: {error_msg}"
                log.error("âŒ Whisper loading failed: %s", e, exc_info=True)
                self.model = None

    # â”€â”€ Audio Devices â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def get_audio_devices(self) -> Dict[str, list]:
        """List available audio devices (thread-safe)."""
        return _detect_devices_threaded()

    # â”€â”€ Start / Stop / Pause â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def start(self):
        """Start capturing and transcribing."""
        if self.is_capturing:
            return

        active_provider = self._resolve_transcription_provider()
        if active_provider == "local_whisper":
            self.load_model()

        now = datetime.now()
        session_id = now.strftime("%Y-%m-%d_%H-%M-%S")
        self.current_session = ScribeSession(
            session_id=session_id,
            started_at=now.isoformat(),
        )
        self._session_start_time = time.time()
        self._total_paused_duration = 0.0
        self._last_pause_start = 0.0
        self._stop_event.clear()
        self.is_capturing = True
        self.is_paused = False
        self.status = "capturing"
        self.status_detail = "ðŸŽ™ï¸ Live â€” capturing audio..."
        with self._lock:
            self.live_segments = []
            self.live_interims = {}
        self.error_message = ""
        self._latency_samples.clear()
        self._queue_drop_count = 0
        self._runtime_stats.update({
            "provider": active_provider,
            "vad_backend": self.config.get("vad", {}).get("backend", "energy"),
            "avg_latency_ms": 0.0,
            "last_latency_ms": 0.0,
            "queue_depth": 0,
            "provider_sessions": 0,
            "translation_enabled": bool(self.config.get("translation", {}).get("enabled")),
            "translation_target": self.config.get("translation", {}).get("target_language", ""),
            "drops": 0,
        })

        # Clear queue
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break
        while not self._translation_queue.empty():
            try:
                self._translation_queue.get_nowait()
            except queue.Empty:
                break

        acfg = self.config["audio"]
        scfg = self.config.get("streaming", {})
        source = acfg["source"]
        sr = acfg["sample_rate"]
        chunk = float(scfg.get("frame_ms", 40)) / 1000.0 if scfg.get("enabled", True) else float(acfg["chunk_duration_sec"])
        prefix_frames = max(1, int(float(scfg.get("prefix_padding_ms", 160)) / max(chunk * 1000.0, 1.0)))
        self._source_buffers = {
            "system": BufferedUtterance(source="system", prefix_frames=deque(maxlen=prefix_frames)),
            "mic": BufferedUtterance(source="mic", prefix_frames=deque(maxlen=prefix_frames)),
        }

        # Launch capture thread(s) â€” each gets its own COM + soundcard import
        if source in ("loopback", "both"):
            dev_name = acfg.get("loopback_device", "")
            t = threading.Thread(
                target=self._capture_loop,
                args=("system", sr, chunk, dev_name),
                daemon=True, name="capture-system",
            )
            t.start()
            self._capture_threads.append(t)

        if source in ("microphone", "both"):
            dev_name = acfg.get("microphone_device", "")
            t = threading.Thread(
                target=self._capture_loop,
                args=("mic", sr, chunk, dev_name),
                daemon=True, name="capture-mic",
            )
            t.start()
            self._capture_threads.append(t)

        if active_provider == "local_whisper":
            self._transcribe_thread = threading.Thread(
                target=self._transcribe_loop,
                daemon=True, name="transcribe",
            )
            self._transcribe_thread.start()
        else:
            self._transcribe_thread = None
        if self.config.get("translation", {}).get("enabled"):
            self._ensure_translation_thread()
        log.info("âœ… Scribe started â€” session %s", session_id)

    def pause(self):
        """Pause audio capture threads."""
        if self.is_capturing:
            self.is_paused = True
            self.status = "paused"
            self.status_detail = "â¸ï¸ Paused â€” transcription suspended"
            self._last_pause_start = time.time()
            log.info("Scribe paused.")

    def resume(self):
        """Resume audio capture threads."""
        if self.is_capturing:
            self.is_paused = False
            self.status = "capturing"
            self.status_detail = "ðŸŽ™ï¸ Live â€” capturing audio..."
            if self._last_pause_start > 0:
                self._total_paused_duration += (time.time() - self._last_pause_start)
                self._last_pause_start = 0
            log.info("Scribe resumed.")

    def stop(self):
        """Stop capturing and save session."""
        if not self.is_capturing:
            return

        log.info("Stopping scribe...")
        self._stop_event.set()
        self._flush_active_buffers()
        self.is_capturing = False
        self.is_paused = False

        for session in list(self._provider_sessions.values()):
            session.finalize()

        for t in self._capture_threads:
            t.join(timeout=5)
        if self._transcribe_thread:
            self._transcribe_thread.join(timeout=5)
        if self._translation_thread:
            self._translation_thread.join(timeout=5)
        for session in list(self._provider_sessions.values()):
            session.join(timeout=3)

        self._capture_threads = []
        self._transcribe_thread = None
        self._translation_thread = None
        self._provider_sessions = {}

        # Save session
        if self.current_session and self.current_session.segments:
            self.current_session.ended_at = datetime.now().isoformat()
            
            # Calculate final duration subtracting paused time
            raw_dur = time.time() - self._session_start_time
            paused_dur = self._total_paused_duration
            if self._last_pause_start > 0:
                paused_dur += (time.time() - self._last_pause_start)
            
            # Store as actual_duration_sec (the settable field, not the property)
            self.current_session.actual_duration_sec = max(0.0, raw_dur - paused_dur)
            self.status_detail = "ðŸ’¾ Saving session..."
            self._save_session(self.current_session)

            # Gemini enrichment
            gcfg = self.config["gemini"]
            if gcfg.get("enabled") and gcfg.get("auto_summarize_on_stop"):
                self.status_detail = "ðŸ¤– Running Gemini analysis..."
                try:
                    analysis = self._run_gemini_enrichment(self.current_session)
                    if analysis:
                        self.current_session.gemini_analysis = analysis
                        self.current_session.summary = analysis.get("summary", "")
                        self._save_session(self.current_session)  # re-save with analysis
                except Exception as e:
                    log.error("Gemini enrichment failed: %s", e)

            log.info("âœ… Session saved: %s (%d segments)",
                     self.current_session.session_id,
                     self.current_session.segment_count)
        else:
            log.info("Session had no segments â€” not saved.")

        self.current_session = None
        self.status = "idle"
        self.status_detail = "Ready"
        self.audio_level_system = 0.0
        self.audio_level_mic = 0.0
        with self._lock:
            self.live_interims = {}

    def _record_latency(self, latency_ms: float):
        latency_ms = max(0.0, float(latency_ms))
        with self._lock:
            self._latency_samples.append(latency_ms)
            self._runtime_stats["last_latency_ms"] = round(latency_ms, 1)
            if self._latency_samples:
                self._runtime_stats["avg_latency_ms"] = round(
                    sum(self._latency_samples) / len(self._latency_samples), 1
                )

    def _flush_active_buffers(self):
        """Force any in-flight speech buffers to finalize on stop."""
        active_provider = self._resolve_transcription_provider()
        for state in self._source_buffers.values():
            if state.in_speech and state.active_frames:
                if active_provider == "deepgram":
                    self._finalize_deepgram_session(state.source, state.segment_id)
                else:
                    self._enqueue_decode_job(state, is_final=True, reason="stop")
                state.reset()

    def _ensure_translation_thread(self):
        if not self.config.get("translation", {}).get("enabled"):
            return
        if self._translation_thread and self._translation_thread.is_alive():
            return
        self._translation_thread = threading.Thread(
            target=self._translation_loop,
            daemon=True,
            name="translate-live",
        )
        self._translation_thread.start()

    def _start_deepgram_session(self, source: str, segment_id: str, start_offset_sec: float):
        existing = self._provider_sessions.get(source)
        if existing:
            existing.finalize()
            existing.join(timeout=1.0)
        session = DeepgramUtteranceSession(
            engine=self,
            source=source,
            segment_id=segment_id,
            start_offset_sec=start_offset_sec,
        )
        self._provider_sessions[source] = session
        with self._lock:
            self._runtime_stats["provider_sessions"] = len(self._provider_sessions)
        session.start()

    def _send_deepgram_frame(self, source: str, frame: np.ndarray):
        session = self._provider_sessions.get(source)
        if not session:
            return
        session.send_frame(frame)

    def _finalize_deepgram_session(self, source: str, segment_id: str):
        session = self._provider_sessions.get(source)
        if not session or session.segment_id != segment_id:
            return
        session.finalize()

    def _handle_deepgram_event(
        self,
        source: str,
        segment_id: str,
        start_offset_sec: float,
        event: StreamingEvent,
        last_audio_wall: float,
    ):
        latency_ms = (time.time() - float(last_audio_wall)) * 1000.0
        self._record_latency(latency_ms)
        active_session = self._provider_sessions.get(source)
        is_stale_interim = bool(
            active_session
            and active_session.segment_id != segment_id
            and not (
                event.is_final
                and (
                    bool(event.raw.get("speech_final"))
                    or bool(event.raw.get("from_finalize"))
                    or event.event_type == "UtteranceEnd"
                )
            )
        )
        if is_stale_interim:
            return

        if event.event_type == "UtteranceEnd" and not event.text:
            self._commit_pending_interim(source, segment_id, latency_ms)
            return
        if event.event_type == "SpeechStarted" and not event.text:
            return

        job = {
            "segment_id": segment_id,
            "source": source,
            "audio_duration_sec": float(event.duration_sec or 0.0),
            "start_offset_sec": round(float(start_offset_sec) + float(event.start_sec or 0.0), 3),
            "capture_time": float(last_audio_wall),
            "mode": "final" if event.is_final else "interim",
            "provider": event.provider,
        }
        result = {
            "text": event.text,
            "language": event.language,
            "confidence": event.confidence,
        }

        should_commit = bool(
            event.is_final
            and (
                bool(event.raw.get("speech_final"))
                or bool(event.raw.get("from_finalize"))
                or event.event_type == "UtteranceEnd"
            )
        )

        if should_commit:
            self._commit_final_segment(job, result, latency_ms)
        else:
            self._update_interim_state(job, result, latency_ms)

    def _commit_pending_interim(self, source: str, segment_id: str, latency_ms: float):
        current = self.live_interims.get(source)
        if not current or current.segment_id != segment_id or not current.text.strip():
            return
        self._commit_final_segment(
            {
                "segment_id": segment_id,
                "source": source,
                "audio_duration_sec": 0.0,
                "start_offset_sec": round(float(current.start), 3),
                "capture_time": time.time(),
                "mode": "final",
                "provider": current.provider,
            },
            {
                "text": current.text,
                "language": current.language,
                "confidence": current.confidence,
            },
            latency_ms,
        )

    def _enqueue_decode_job(self, state: BufferedUtterance, is_final: bool, reason: str):
        if not state.active_frames:
            return

        audio = np.concatenate(state.active_frames).astype(np.float32, copy=False)
        max_buffer_ms = float(self.config.get("streaming", {}).get("max_buffer_ms", 9000))
        max_samples = int(self.config["audio"]["sample_rate"] * max_buffer_ms / 1000.0)
        if max_samples > 0 and audio.size > max_samples:
            audio = audio[-max_samples:]

        job = {
            "segment_id": state.segment_id,
            "source": state.source,
            "audio": audio,
            "audio_duration_sec": round(audio.size / float(self.config["audio"]["sample_rate"]), 3),
            "start_offset_sec": round(state.start_offset_sec, 3),
            "capture_time": state.last_voice_wall or time.time(),
            "mode": "final" if is_final else "interim",
            "reason": reason,
            "provider": "local_whisper",
        }

        try:
            self._audio_queue.put_nowait(job)
        except queue.Full:
            self._queue_drop_count += 1
            with self._lock:
                self._runtime_stats["drops"] = self._queue_drop_count
            log.warning("Decode queue full; dropping %s %s job", state.source, job["mode"])

    def _build_context_prompt(self) -> str:
        with self._lock:
            recent = [seg.text for seg in self.live_segments[-4:] if seg.text]
        return " ".join(recent)[-280:]

    def _decode_whisper_job(self, job: dict) -> Dict[str, Any]:
        if self.model is None:
            return {"text": "", "language": "", "confidence": 0.0}

        wcfg = self.config["whisper"]
        req_lang = wcfg.get("language")
        req_task = wcfg.get("task", "transcribe")
        prompt = self._build_context_prompt()
        beam_size = 1 if job["mode"] == "interim" else int(wcfg.get("beam_size", 5))
        text_parts: List[str] = []
        confidences: List[float] = []

        # Developer note:
        # This is the local fallback decode path. To wire a WebSocket STT backend
        # later (Deepgram / OpenAI / Google), normalize provider events into the
        # same {"text","language","confidence"} shape consumed below.
        segments_gen, info = self.model.transcribe(
            job["audio"],
            beam_size=beam_size,
            initial_prompt=prompt or None,
            language=req_lang,
            task=req_task,
            vad_filter=False,
        )

        for seg in segments_gen:
            segment_text = str(getattr(seg, "text", "")).strip()
            if segment_text:
                text_parts.append(segment_text)
            avg_logprob = getattr(seg, "avg_logprob", None)
            if isinstance(avg_logprob, (int, float)):
                normalized = max(0.0, min(1.0, (float(avg_logprob) + 5.0) / 5.0))
                confidences.append(normalized)

        return {
            "text": " ".join(text_parts).strip(),
            "language": getattr(info, "language", "") if info else "",
            "confidence": round(sum(confidences) / len(confidences), 3) if confidences else 0.0,
        }

    def _update_interim_state(self, job: dict, result: Dict[str, Any], latency_ms: float):
        text = str(result.get("text", "")).strip()
        source = job["source"]
        current = self.live_interims.get(source)
        old_translation = current.translation if current and current.segment_id == job["segment_id"] else ""
        old_revision = current.revision if current and current.segment_id == job["segment_id"] else 0

        if not text:
            return

        changed = not current or current.segment_id != job["segment_id"] or current.text != text
        stability = max(0.2, min(0.92, 0.28 + (len(text.split()) * 0.08)))

        entry = InterimTranscript(
            segment_id=job["segment_id"],
            source=source,
            text=text,
            language=str(result.get("language", "")),
            confidence=float(result.get("confidence", 0.0)),
            stability=round(stability, 2),
            start=float(job.get("start_offset_sec", 0.0)),
            updated_at=datetime.now(timezone.utc).isoformat(),
            translation=old_translation,
            translation_language=self.config.get("translation", {}).get("target_language", ""),
            translation_is_final=False,
            provider=str(job.get("provider", "local_whisper")),
            latency_ms=round(latency_ms, 1),
            revision=old_revision + 1 if changed else old_revision,
        )

        with self._lock:
            self.live_interims[source] = entry

        if changed:
            self._queue_translation(
                segment_id=entry.segment_id,
                source=entry.source,
                text=entry.text,
                is_final=False,
                revision=entry.revision,
            )

    def _commit_final_segment(self, job: dict, result: Dict[str, Any], latency_ms: float):
        text = str(result.get("text", "")).strip()
        source = job["source"]
        translation = ""
        translation_lang = ""

        with self._lock:
            current = self.live_interims.get(source)
            if current and current.segment_id == job["segment_id"]:
                translation = current.translation
                translation_lang = current.translation_language
                del self.live_interims[source]

        if not text:
            return

        ts = TranscriptSegment(
            start=round(float(job.get("start_offset_sec", 0.0)), 2),
            end=round(float(job.get("start_offset_sec", 0.0)) + float(job.get("audio_duration_sec", 0.0)), 2),
            text=text,
            source=source,
            language=str(result.get("language", "")),
            confidence=float(result.get("confidence", 0.0)),
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            segment_id=str(job["segment_id"]),
            is_final=True,
            stability=1.0,
            translation=translation,
            translation_language=translation_lang,
            translation_is_final=False,
            provider=str(job.get("provider", "local_whisper")),
            latency_ms=round(latency_ms, 1),
        )

        max_live = int(self.config["dashboard"]["max_live_segments"])
        with self._lock:
            self.live_segments.append(ts)
            if len(self.live_segments) > max_live:
                self.live_segments = self.live_segments[-max_live:]
            if self.current_session:
                self.current_session.segments.append(ts)

        self._queue_translation(
            segment_id=ts.segment_id,
            source=source,
            text=text,
            is_final=True,
            revision=0,
        )

    def _queue_translation(self, segment_id: str, source: str, text: str, is_final: bool, revision: int):
        tcfg = self.config.get("translation", {})
        if not tcfg.get("enabled"):
            return

        self._ensure_translation_thread()
        normalized = str(text).strip()
        if len(normalized) < int(tcfg.get("min_chars", 8)):
            return

        try:
            self._translation_queue.put_nowait({
                "segment_id": segment_id,
                "source": source,
                "text": normalized[: int(tcfg.get("max_chars", 600))],
                "is_final": bool(is_final),
                "revision": int(revision),
            })
        except queue.Full:
            log.debug("Translation queue full; dropping live translation job for %s", source)

    def _translation_loop(self):
        """Low-latency translation worker for interim/final text."""
        while not self._stop_event.is_set() or not self._translation_queue.empty():
            try:
                job = self._translation_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            translated = self._translate_text(job["text"], is_final=job["is_final"])
            if not translated:
                continue

            target_lang = self.config.get("translation", {}).get("target_language", "")
            with self._lock:
                if job["is_final"]:
                    for idx in range(len(self.live_segments) - 1, -1, -1):
                        seg = self.live_segments[idx]
                        if seg.segment_id == job["segment_id"]:
                            seg.translation = translated
                            seg.translation_language = target_lang
                            seg.translation_is_final = True
                            if self.current_session:
                                for session_seg in reversed(self.current_session.segments):
                                    if session_seg.segment_id == job["segment_id"]:
                                        session_seg.translation = translated
                                        session_seg.translation_language = target_lang
                                        session_seg.translation_is_final = True
                                        break
                            break
                else:
                    interim = self.live_interims.get(job["source"])
                    if interim and interim.segment_id == job["segment_id"] and interim.revision == job["revision"]:
                        interim.translation = translated
                        interim.translation_language = target_lang
                        interim.translation_is_final = False

    def _translate_text(self, text: str, is_final: bool) -> Optional[str]:
        tcfg = self.config.get("translation", {})
        api_key_env = tcfg.get("api_key_env") or self.config.get("gemini", {}).get("api_key_env", "GEMINI_API_KEY")
        api_key = os.getenv(api_key_env, "")
        if not api_key:
            return None

        try:
            from google import genai
        except Exception as exc:
            log.debug("Translation provider unavailable: %s", exc)
            return None

        if self._translation_client is None:
            self._translation_client = genai.Client(api_key=api_key)

        target_language = tcfg.get("target_language", "ar")
        mode = "final" if is_final else "interim"
        prompt = (
            f"Translate the following {mode} speech transcript into {target_language}. "
            "Return only the translated text, keep names and numbers accurate, and preserve unfinished thought flow if the input is partial.\n\n"
            f"Transcript:\n{text}"
        )

        try:
            response = self._translation_client.models.generate_content(
                model=tcfg.get("model", "gemini-2.5-flash"),
                contents=prompt,
            )
            translated = str(getattr(response, "text", "")).strip()
            return translated or None
        except Exception as exc:
            log.debug("Live translation request failed: %s", exc)
            return None

    # â”€â”€ Audio Capture Thread â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _capture_loop(self, source_type: str, sample_rate: int,
                      chunk_sec: int, device_name: str):
        """Audio capture loop for a single source.
        
        Each capture thread initializes COM independently and imports
        soundcard fresh to avoid cross-thread COM apartment conflicts.
        Includes automatic retry on transient device errors.
        """
        com_init = _com_initialize()
        max_retries = 3
        retry_count = 0
        vcfg = self.config.get("vad", {})
        scfg = self.config.get("streaming", {})
        threshold = float(self.config["audio"]["silence_threshold"])
        min_speech_frames = max(1, int(np.ceil(float(vcfg.get("min_speech_ms", 120)) / max(chunk_sec * 1000.0, 1.0))))
        interim_min_audio_sec = float(scfg.get("interim_min_audio_ms", 240)) / 1000.0
        interim_emit_sec = float(scfg.get("interim_emit_ms", 350)) / 1000.0
        final_silence_sec = float(scfg.get("final_silence_ms", 480)) / 1000.0
        max_utterance_sec = float(scfg.get("max_utterance_ms", 6500)) / 1000.0
        active_provider = self._resolve_transcription_provider()
        speech_gate = StreamingSpeechGate(sample_rate, vcfg)
        with self._lock:
            self._runtime_stats["vad_backend"] = speech_gate.backend
        state = self._source_buffers.get(source_type)
        if state is None:
            prefix_frames = max(1, int(float(scfg.get("prefix_padding_ms", 160)) / max(chunk_sec * 1000.0, 1.0)))
            state = BufferedUtterance(source=source_type, prefix_frames=deque(maxlen=prefix_frames))
            self._source_buffers[source_type] = state
        
        try:
            # Import soundcard INSIDE the thread after COM is initialized
            import soundcard as sc
            
            while not self._stop_event.is_set() and retry_count < max_retries:
                try:
                    # 1. Device Selection
                    recorder_device = self._select_device(sc, source_type, device_name)
                    if recorder_device is None:
                        log.error("No audio device found for %s", source_type)
                        self.error_message = f"No audio device found for {source_type}"
                        return

                    # 2. Start Capture
                    with recorder_device.recorder(samplerate=sample_rate, channels=1) as recorder:
                        # Reset retry count on successful connection
                        retry_count = 0
                        log.info("âœ… %s capture started on device", source_type)

                        while not self._stop_event.is_set():
                            if self.is_paused:
                                time.sleep(0.1)
                                continue

                            frames = int(sample_rate * chunk_sec)
                            data = recorder.record(numframes=frames)

                            # Mono float32 â€” use np.frombuffer-compatible paths
                            if isinstance(data, (bytes, bytearray)):
                                # Handle raw bytes from some soundcard backends
                                data = np.frombuffer(data, dtype=np.float32)
                            
                            if len(data.shape) > 1:
                                data = data.mean(axis=1)
                            data = data.astype(np.float32)

                            # Audio level (RMS)
                            rms = float(np.sqrt(np.mean(data ** 2)))
                            if source_type == "system":
                                self.audio_level_system = rms
                            else:
                                self.audio_level_mic = rms

                            now_wall = time.time()
                            is_speech = speech_gate.is_speech(data, rms) if vcfg.get("enabled", True) else rms > threshold
                            state.prefix_frames.append(data)

                            if not state.in_speech and is_speech:
                                state.in_speech = True
                                state.segment_id = f"{source_type}-{uuid.uuid4().hex[:8]}"
                                state.active_frames = list(state.prefix_frames)
                                state.speech_started_wall = now_wall
                                state.last_voice_wall = now_wall
                                state.last_interim_wall = 0.0
                                state.start_offset_sec = max(0.0, now_wall - self._session_start_time - (len(state.active_frames) * chunk_sec))
                                state.total_audio_sec = len(state.active_frames) * chunk_sec
                                state.silence_sec = 0.0
                                state.vad_score = speech_gate.last_score
                                state.speech_frame_count = 1
                                if active_provider == "deepgram":
                                    self._start_deepgram_session(source_type, state.segment_id, state.start_offset_sec)
                                    for prefix_frame in state.active_frames:
                                        self._send_deepgram_frame(source_type, prefix_frame)
                            elif state.in_speech:
                                state.active_frames.append(data)
                                state.total_audio_sec = len(state.active_frames) * chunk_sec
                                state.vad_score = speech_gate.last_score
                                if active_provider == "deepgram":
                                    self._send_deepgram_frame(source_type, data)
                                if is_speech or rms > threshold:
                                    state.last_voice_wall = now_wall
                                    state.silence_sec = 0.0
                                    if is_speech:
                                        state.speech_frame_count += 1
                                else:
                                    state.silence_sec += chunk_sec

                            if state.in_speech and state.speech_frame_count >= min_speech_frames:
                                if active_provider == "local_whisper" and (
                                    state.total_audio_sec >= interim_min_audio_sec
                                    and (now_wall - state.last_interim_wall) >= interim_emit_sec
                                ):
                                    self._enqueue_decode_job(state, is_final=False, reason="interim")
                                    state.last_interim_wall = now_wall

                                if state.silence_sec >= final_silence_sec or state.total_audio_sec >= max_utterance_sec:
                                    if active_provider == "deepgram":
                                        self._finalize_deepgram_session(source_type, state.segment_id)
                                    else:
                                        self._enqueue_decode_job(
                                            state,
                                            is_final=True,
                                            reason="silence" if state.silence_sec >= final_silence_sec else "max_utterance",
                                        )
                                    state.reset()
                                    speech_gate.reset()
                            elif state.in_speech and state.silence_sec >= final_silence_sec:
                                # Drop very short VAD spikes instead of letting them keep the buffer open.
                                if active_provider == "deepgram":
                                    self._finalize_deepgram_session(source_type, state.segment_id)
                                state.reset()
                                speech_gate.reset()

                except Exception as e:
                    retry_count += 1
                    msg = f"Capture error ({source_type}), attempt {retry_count}/{max_retries}: {e}"
                    log.error(msg)
                    
                    if retry_count < max_retries and not self._stop_event.is_set():
                        log.info("Retrying %s capture in 2 seconds...", source_type)
                        # Wait before retry, but check stop event
                        for _ in range(20):  # 2 seconds in 0.1s increments
                            if self._stop_event.is_set():
                                return
                            time.sleep(0.1)
                    else:
                        self.error_message = f"Capture failed ({source_type}): {e}"
                        log.error("Max retries reached for %s capture", source_type)

        finally:
            if com_init:
                _com_uninitialize()

    def _select_device(self, sc, source_type: str, device_name: str):
        """Select audio device with fallback. Returns recorder device or None."""
        try:
            if source_type == "system":
                if device_name:
                    # Case-insensitive partial match
                    speakers = [s for s in sc.all_speakers() if device_name.lower() in s.name.lower()]
                    speaker = speakers[0] if speakers else sc.default_speaker()
                else:
                    speaker = sc.default_speaker()
                
                try:
                    recorder_device = sc.get_microphone(speaker.id, include_loopback=True)
                    log.info("System audio (loopback): %s", speaker.name)
                except Exception:
                    # Fallback for devices that don't support loopback natively
                    speaker = sc.default_speaker()
                    recorder_device = sc.get_microphone(speaker.id, include_loopback=True)
                    log.warning("System loopback fallback to default: %s", speaker.name)
                return recorder_device
            else:
                if device_name:
                    mics = [m for m in sc.all_microphones(include_loopback=False)
                            if device_name.lower() in m.name.lower()]
                    recorder_device = mics[0] if mics else sc.default_microphone()
                else:
                    recorder_device = sc.default_microphone()
                log.info("Microphone: %s", recorder_device.name)
                return recorder_device
        except Exception as e:
            log.error("Failed to select audio device (%s): %s. Trying default.", source_type, e)
            try:
                if source_type == "system":
                    speaker = sc.default_speaker()
                    return sc.get_microphone(speaker.id, include_loopback=True)
                else:
                    return sc.default_microphone()
            except Exception as e2:
                log.error("Default device fallback also failed: %s", e2)
                return None

    # â”€â”€ Transcription Thread â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _transcribe_loop(self):
        """Processes audio chunks from queue through Whisper."""
        while not self._stop_event.is_set() or not self._audio_queue.empty():
            try:
                job = self._audio_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if self.model is None:
                log.warning("Whisper model not loaded, skipping transcription")
                continue

            try:
                result = self._decode_whisper_job(job)
                latency_ms = (time.time() - float(job.get("capture_time", time.time()))) * 1000.0
                self._record_latency(latency_ms)
                if job.get("mode") == "interim":
                    self._update_interim_state(job, result, latency_ms)
                else:
                    self._commit_final_segment(job, result, latency_ms)
            except Exception as e:
                log.error("Transcription error: %s", e, exc_info=True)
        return

    # â”€â”€ Session I/O â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _save_session(self, session: ScribeSession):
        """Save session to disk in multiple formats."""
        sdir = self.sessions_dir / session.session_id
        sdir.mkdir(parents=True, exist_ok=True)

        formats = self.config["recording"].get("export_formats", ["json", "txt", "srt"])

        # JSON â€” use the to_dict method for clean serialization
        if "json" in formats:
            data = session.to_dict()
            (sdir / "transcript.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        # Plain text
        if "txt" in formats:
            lines = []
            for s in session.segments:
                m, sec = divmod(int(s.start), 60)
                icon = "ðŸ”Š" if s.source == "system" else "ðŸŽ¤"
                lang = f"[{s.language}]" if s.language else ""
                lines.append(f"[{m:02d}:{sec:02d}] {icon} {lang} {s.text}")
            (sdir / "transcript.txt").write_text("\n".join(lines), encoding="utf-8")

        # SRT subtitles
        if "srt" in formats:
            srt = []
            for i, s in enumerate(session.segments, 1):
                srt.append(str(i))
                srt.append(f"{_fmt_srt_time(s.start)} --> {_fmt_srt_time(s.end)}")
                srt.append(s.text)
                srt.append("")
            (sdir / "transcript.srt").write_text("\n".join(srt), encoding="utf-8")

        # Summary markdown (if Gemini analysis exists)
        if session.gemini_analysis:
            md_lines = [
                f"# Session {session.session_id}",
                f"**Started:** {session.started_at}",
                f"**Duration:** {session.duration_sec:.0f}s | **Segments:** {session.segment_count}",
                "",
                "## Summary",
                session.gemini_analysis.get("summary", "N/A"),
                "",
                "## Key Points",
            ]
            for kp in session.gemini_analysis.get("key_points", []):
                md_lines.append(f"- {kp}")
            md_lines.extend(["", "## Action Items"])
            for ai in session.gemini_analysis.get("action_items", []):
                md_lines.append(f"- [ ] {ai}")
            if session.gemini_analysis.get("rules"):
                md_lines.extend(["", "## Golden Rules Extracted"])
                for r in session.gemini_analysis["rules"]:
                    md_lines.append(f"- ðŸ† {r}")
            (sdir / "summary.md").write_text("\n".join(md_lines), encoding="utf-8")

        # Update index
        self._update_index(session)

    def _update_index(self, session: ScribeSession):
        """Update the master sessions index."""
        idx_file = self.sessions_dir / "scribe_index.json"
        if idx_file.exists():
            try:
                idx = json.loads(idx_file.read_text(encoding="utf-8"))
            except Exception:
                idx = {"sessions": []}
        else:
            idx = {"sessions": []}

        # Avoid duplicates
        existing_ids = {s["session_id"] for s in idx["sessions"]}
        if session.session_id not in existing_ids:
            idx["sessions"].append({
                "session_id": session.session_id,
                "started_at": session.started_at,
                "ended_at": session.ended_at,
                "segment_count": session.segment_count,
                "duration_sec": round(session.duration_sec, 1),
                "has_summary": session.summary is not None,
            })
        else:
            # Update existing entry
            for s in idx["sessions"]:
                if s["session_id"] == session.session_id:
                    s["ended_at"] = session.ended_at
                    s["segment_count"] = session.segment_count
                    s["duration_sec"] = round(session.duration_sec, 1)
                    s["has_summary"] = session.summary is not None

        idx_file.write_text(
            json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def get_saved_sessions(self) -> list:
        """Return list of saved sessions from index (with filesystem fallback)."""
        idx_file = self.sessions_dir / "scribe_index.json"
        
        # 1. Start with index if it exists
        sessions = []
        if idx_file.exists():
            try:
                idx = json.loads(idx_file.read_text(encoding="utf-8"))
                sessions = idx.get("sessions", [])
            except Exception:
                log.error("Failed to read scribe_index.json")

        # 2. Check filesystem for missing sessions (robustness)
        try:
            found_folders = [d for d in self.sessions_dir.iterdir() if d.is_dir()]
        except Exception:
            found_folders = []
        existing_ids = {s["session_id"] for s in sessions}

        for folder in found_folders:
            sid = folder.name
            if sid not in existing_ids:
                # Basic info from folder
                meta_file = folder / "transcript.json"
                if meta_file.exists():
                    try:
                        m = json.loads(meta_file.read_text(encoding="utf-8"))
                        sessions.append({
                            "session_id": sid,
                            "started_at": m.get("started_at"),
                            "ended_at": m.get("ended_at"),
                            "segment_count": m.get("segment_count", 0),
                            "duration_sec": m.get("duration_sec", 0),
                            "has_summary": m.get("gemini_analysis") is not None,
                        })
                    except Exception:
                        pass

        # Sort by started_at desc
        return sorted(sessions, key=lambda x: x.get("started_at", ""), reverse=True)

    def load_session_transcript(self, session_id: str) -> Optional[dict]:
        """Load a saved session's full transcript."""
        fpath = self.sessions_dir / session_id / "transcript.json"
        if fpath.exists():
            return json.loads(fpath.read_text(encoding="utf-8"))
        return None

    def load_session_summary(self, session_id: str) -> Optional[str]:
        """Load session summary markdown."""
        fpath = self.sessions_dir / session_id / "summary.md"
        if fpath.exists():
            return fpath.read_text(encoding="utf-8")
        return None

    # â”€â”€ Gemini Enrichment â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _run_gemini_enrichment(self, session: ScribeSession) -> Optional[dict]:
        """Analyze transcript with Gemini and return structured result."""
        gcfg = self.config["gemini"]
        api_key_env = gcfg.get("api_key_env", "GEMINI_API_KEY")
        api_key = os.getenv(api_key_env, "")
        if not api_key:
            log.warning("Gemini API key not found in env var: %s", api_key_env)
            return None

        # Build transcript text
        lines = []
        for s in session.segments:
            m, sec = divmod(int(s.start), 60)
            src = "System" if s.source == "system" else "Mic"
            lines.append(f"[{m:02d}:{sec:02d}] ({src}) {s.text}")
        transcript_text = "\n".join(lines)

        if not transcript_text.strip():
            return None

        lang = gcfg.get("summary_language", "ar")
        lang_instruction = "Ø¨Ø§Ù„Ù„ØºØ© Ø§Ù„Ø¹Ø±Ø¨ÙŠØ©" if lang == "ar" else "in English"
        extract_rules = gcfg.get("extract_rules", True)

        rules_section = ""
        if extract_rules:
            rules_section = """
5. "rules": A list of any golden rules, guidelines, or important policies mentioned.
   If no rules are found, return an empty list."""

        prompt = f"""Analyze this real-time audio transcript and return a JSON object {lang_instruction} with these fields:

1. "summary": A concise summary (3-5 sentences) of what was discussed.
2. "key_points": A list of the most important points or insights.
3. "action_items": A list of any action items or tasks mentioned.
4. "topics": A list of main topics covered.{rules_section}

IMPORTANT: Return ONLY valid JSON, no markdown code blocks, no extra text.
Use UTF-8 encoding for all text including Arabic characters.

Transcript:
{transcript_text}"""

        response = None  # Initialize before try block
        try:
            from google import genai

            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=gcfg.get("model", "gemini-3.1-pro-preview"),
                contents=prompt,
            )

            # Parse JSON from response
            text = response.text.strip()
            # Strip markdown code fences if present
            if text.startswith("```"):
                # Handle ```json\n...\n``` patterns
                first_newline = text.find("\n")
                if first_newline > -1:
                    text = text[first_newline + 1:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

            result = json.loads(text)
            log.info("âœ… Gemini enrichment complete")
            return result

        except json.JSONDecodeError:
            log.error("Gemini returned invalid JSON")
            fallback_text = response.text if response else "Parse error"
            return {"summary": fallback_text,
                    "key_points": [], "action_items": [], "topics": [], "rules": []}
        except Exception as e:
            log.error("Gemini API error: %s", e)
            return None

    def enrich_session_now(self, session_id: str) -> Optional[dict]:
        """Manually trigger Gemini enrichment on a saved session."""
        transcript = self.load_session_transcript(session_id)
        if not transcript:
            return None

        # Reconstruct a minimal session
        temp_session = ScribeSession(
            session_id=session_id,
            started_at=transcript.get("started_at", ""),
            ended_at=transcript.get("ended_at", ""),
        )
        for seg_data in transcript.get("segments", []):
            # Filter out only the fields that TranscriptSegment expects
            valid_keys = {
                "start",
                "end",
                "text",
                "source",
                "language",
                "confidence",
                "timestamp_utc",
                "segment_id",
                "is_final",
                "stability",
                "translation",
                "translation_language",
                "translation_is_final",
                "provider",
                "latency_ms",
            }
            filtered = {k: v for k, v in seg_data.items() if k in valid_keys}
            temp_session.segments.append(TranscriptSegment(**filtered))

        analysis = self._run_gemini_enrichment(temp_session)
        if analysis:
            temp_session.gemini_analysis = analysis
            temp_session.summary = analysis.get("summary", "")
            self._save_session(temp_session)
        return analysis


# â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _fmt_srt_time(seconds: float) -> str:
    """Format seconds as SRT timestamp: HH:MM:SS,mmm"""
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    ms = int((s - int(s)) * 1000)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{ms:03d}"


# â”€â”€ Singleton for Streamlit â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_engine_instance: Optional[ScribeEngine] = None
_engine_lock = threading.Lock()


def get_engine() -> ScribeEngine:
    """Get or create the singleton ScribeEngine."""
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = ScribeEngine()
    return _engine_instance


# â”€â”€ CLI Test â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    engine = ScribeEngine()

    print("ðŸ” Detecting audio devices...")
    devices = engine.get_audio_devices()
    print(f"  Speakers: {devices.get('speakers', [])}")
    print(f"  Microphones: {devices.get('microphones', [])}")
    print(f"  Default speaker: {devices.get('default_speaker', 'N/A')}")
    print(f"  Default mic: {devices.get('default_mic', 'N/A')}")

    print("\nðŸ“¦ Loading Whisper model... (Takes time on first run to download ~1.5GB)")
    engine.load_model()
    print(f"  Model: {engine.model_info}")

    print("\nðŸŽ™ï¸ Starting capture for 15 seconds...")
    engine.start()
    try:
        for i in range(15):
            time.sleep(1)
            sys_lvl = f"{engine.audio_level_system:.4f}"
            mic_lvl = f"{engine.audio_level_mic:.4f}"
            seg_count = len(engine.live_segments)
            print(f"  [{i+1:2d}s] ðŸ”Š {sys_lvl} | ðŸŽ¤ {mic_lvl} | segments: {seg_count}")
            for seg in engine.live_segments[seg_count - 3:]:
                print(f"        â†’ [{seg.source}] {seg.text}")
    except KeyboardInterrupt:
        pass

    engine.stop()
    print("\nâœ… Done!")
