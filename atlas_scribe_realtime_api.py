"""
FastAPI bridge for browser audio streaming into Deepgram-style real-time STT.

Run:
    uvicorn atlas_scribe_realtime_api:app --host 0.0.0.0 --port 8765
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

from atlas_realtime_ws_clients import DeepgramStreamingClient, StreamingEvent


PROJECT_ROOT = Path(__file__).parent
DEMO_PAGE = PROJECT_ROOT / "atlas_scribe_realtime_demo.html"


app = FastAPI(title="Atlas Scribe Realtime Bridge", version="1.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@dataclass
class BridgeTranslationRuntime:
    enabled: bool = False
    target_language: str = "ar"
    model: str = "gemini-2.5-flash"
    api_key_env: str = "GEMINI_API_KEY"
    debounce_ms: int = 350
    min_chars: int = 8
    _counter: int = 0
    _client: Any = None
    _pending_tasks: Set[asyncio.Task] = field(default_factory=set)
    _last_interim_text: str = ""
    _last_interim_started_at: float = 0.0

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "BridgeTranslationRuntime":
        translation_cfg = dict(config.get("translation") or {})
        return cls(
            enabled=bool(translation_cfg.get("enabled", False)),
            target_language=str(translation_cfg.get("target_language", "ar")),
            model=str(translation_cfg.get("model", "gemini-2.5-flash")),
            api_key_env=str(translation_cfg.get("api_key_env", "GEMINI_API_KEY")),
            debounce_ms=int(translation_cfg.get("debounce_ms", 350)),
            min_chars=int(translation_cfg.get("min_chars", 8)),
        )

    def next_event_id(self) -> str:
        self._counter += 1
        return f"evt-{self._counter}"

    def maybe_schedule(self, websocket: WebSocket, payload: Dict[str, Any]):
        if not self.enabled:
            return
        text = str(payload.get("text", "")).strip()
        if len(text) < self.min_chars:
            return

        if not payload.get("is_final"):
            now = time.monotonic()
            if text == self._last_interim_text and (now - self._last_interim_started_at) * 1000.0 < self.debounce_ms:
                return
            self._last_interim_text = text
            self._last_interim_started_at = now

        task = asyncio.create_task(self._translate_and_send(websocket, payload))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def shutdown(self):
        if not self._pending_tasks:
            return
        for task in list(self._pending_tasks):
            task.cancel()
        await asyncio.gather(*list(self._pending_tasks), return_exceptions=True)
        self._pending_tasks.clear()

    async def _translate_and_send(self, websocket: WebSocket, payload: Dict[str, Any]):
        try:
            translation = await asyncio.to_thread(
                self._translate_sync,
                str(payload.get("text", "")).strip(),
                bool(payload.get("is_final")),
            )
            if not translation:
                return
            await websocket.send_json(
                {
                    "type": "translation",
                    "event_id": payload["event_id"],
                    "translation": translation,
                    "target_language": self.target_language,
                    "is_final": bool(payload.get("is_final")),
                }
            )
        except Exception:
            return

    def _translate_sync(self, text: str, is_final: bool) -> Optional[str]:
        api_key = os.getenv(self.api_key_env, "").strip()
        if not api_key:
            return None

        try:
            from google import genai
        except Exception:
            return None

        if self._client is None:
            self._client = genai.Client(api_key=api_key)

        mode = "final" if is_final else "interim"
        prompt = (
            f"Translate the following {mode} live speech transcript into {self.target_language}. "
            "Return only the translated text. Preserve unfinished phrasing if the input is partial.\n\n"
            f"Transcript:\n{text}"
        )
        try:
            response = self._client.models.generate_content(model=self.model, contents=prompt)
            value = str(getattr(response, "text", "")).strip()
            return value or None
        except Exception:
            return None


@app.get("/", include_in_schema=False)
async def root():
    return await demo_page()


@app.get("/demo", include_in_schema=False)
async def demo_page():
    if DEMO_PAGE.exists():
        return FileResponse(DEMO_PAGE)
    return HTMLResponse("<h1>Atlas Scribe demo page is missing.</h1>", status_code=404)


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "service": "atlas-scribe-realtime-bridge",
        "version": app.version,
        "deepgram_configured": bool(os.getenv("DEEPGRAM_API_KEY", "").strip()),
        "gemini_configured": bool(os.getenv("GEMINI_API_KEY", "").strip()),
        "demo_available": DEMO_PAGE.exists(),
    }


@app.websocket("/ws/realtime")
async def realtime_bridge(websocket: WebSocket):
    await websocket.accept()
    client = None
    receiver_task = None
    translator = BridgeTranslationRuntime()

    try:
        raw_config = await websocket.receive_text()
        config_message = json.loads(raw_config)
        if str(config_message.get("type", "")).lower() not in {"start", "config"}:
            await websocket.send_json({"type": "error", "message": "First message must be a start/config payload."})
            return

        provider = str(config_message.get("provider", "deepgram")).lower().strip()
        if provider != "deepgram":
            await websocket.send_json({"type": "error", "message": f"Unsupported provider: {provider}"})
            return

        bridge_cfg = dict(config_message.get("config") or {})
        translator = BridgeTranslationRuntime.from_config(bridge_cfg)
        api_key = os.getenv(str(bridge_cfg.get("api_key_env", "DEEPGRAM_API_KEY")), "").strip()
        if not api_key:
            await websocket.send_json({"type": "error", "message": "Missing Deepgram API key in environment."})
            return

        client = DeepgramStreamingClient(
            api_key=api_key,
            model=str(bridge_cfg.get("model", "nova-3")),
            sample_rate=int(bridge_cfg.get("sample_rate", 16000)),
            encoding=str(bridge_cfg.get("encoding", "linear16")),
            interim_results=bool(bridge_cfg.get("interim_results", True)),
            endpointing_ms=int(bridge_cfg.get("endpointing_ms", 300)),
            utterance_end_ms=int(bridge_cfg.get("utterance_end_ms", 1000)),
        )
        language = str(bridge_cfg.get("language", "")).strip()
        if language:
            client.url += f"&language={language}"

        await client.connect()
        await websocket.send_json(
            {
                "type": "ready",
                "provider": provider,
                "sample_rate": int(bridge_cfg.get("sample_rate", 16000)),
                "encoding": str(bridge_cfg.get("encoding", "linear16")),
                "translation_enabled": translator.enabled,
                "translation_target_language": translator.target_language,
                "translation_configured": bool(os.getenv(translator.api_key_env, "").strip()),
            }
        )

        async def _forward_events():
            async for event in client.iter_events():
                payload = _serialize_event(event, event_id=translator.next_event_id())
                await websocket.send_json(payload)
                translator.maybe_schedule(websocket, payload)

        receiver_task = asyncio.create_task(_forward_events())

        while True:
            message = await websocket.receive()
            if "bytes" in message and message["bytes"] is not None:
                await client.send_audio(message["bytes"])
                continue

            if "text" not in message or message["text"] is None:
                continue

            payload = json.loads(message["text"])
            message_type = str(payload.get("type", "")).lower()
            if message_type == "finalize":
                await client.finalize()
                await websocket.send_json({"type": "ack", "action": "finalize"})
            elif message_type == "keepalive":
                await client.send_keepalive()
            elif message_type == "close":
                try:
                    await client.close_stream()
                except Exception:
                    pass
                break
            elif message_type == "ping":
                await websocket.send_json({"type": "pong"})
            else:
                await websocket.send_json({"type": "warn", "message": f"Unknown control message: {message_type}"})

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        await translator.shutdown()
        if receiver_task is not None:
            receiver_task.cancel()
            await asyncio.gather(receiver_task, return_exceptions=True)
        if client is not None:
            try:
                await client.close()
            except Exception:
                pass


def _serialize_event(event: StreamingEvent, event_id: Optional[str] = None) -> Dict[str, Any]:
    return {
        "type": "transcript",
        "event_id": event_id or f"evt-{uuid.uuid4().hex[:10]}",
        "source": "mic",
        "provider": event.provider,
        "event_type": event.event_type,
        "text": event.text,
        "is_final": event.is_final,
        "language": event.language,
        "confidence": event.confidence,
        "start_sec": event.start_sec,
        "duration_sec": event.duration_sec,
        "raw": event.raw,
    }
