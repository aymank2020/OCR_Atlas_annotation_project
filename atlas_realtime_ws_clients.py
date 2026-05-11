"""
Reference asyncio WebSocket clients for low-latency speech streaming.

These clients are intentionally decoupled from the Streamlit engine so they can
be reused by FastAPI, Flask, CLI workers, or a browser bridge later.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Optional
from urllib.parse import urlencode

import numpy as np


@dataclass
class StreamingEvent:
    provider: str
    text: str
    is_final: bool
    event_type: str = "Results"
    language: str = ""
    confidence: float = 0.0
    start_sec: float = 0.0
    duration_sec: float = 0.0
    raw: Dict[str, Any] = field(default_factory=dict)


def float32_to_pcm16le(audio: np.ndarray) -> bytes:
    """Convert mono float32 [-1, 1] audio to PCM16 little-endian bytes."""
    clipped = np.clip(audio.astype(np.float32, copy=False), -1.0, 1.0)
    return (clipped * 32767.0).astype("<i2").tobytes()


class BaseRealtimeWSClient:
    provider_name = "base"

    def __init__(self, url: str, headers: Optional[Dict[str, str]] = None):
        self.url = url
        self.headers = headers or {}
        self._ws = None

    async def connect(self):
        import websockets

        self._ws = await websockets.connect(self.url, additional_headers=self.headers, max_size=None)
        return self

    async def close(self):
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def send_audio(self, audio_chunk: bytes):
        if self._ws is None:
            raise RuntimeError("WebSocket is not connected")
        await self._ws.send(audio_chunk)

    async def send_json(self, payload: Dict[str, Any]):
        if self._ws is None:
            raise RuntimeError("WebSocket is not connected")
        await self._ws.send(json.dumps(payload))

    async def finalize(self):
        """Provider-specific flush hook."""
        return None

    async def send_keepalive(self):
        await self.send_json({"type": "KeepAlive"})

    async def close_stream(self):
        await self.send_json({"type": "CloseStream"})

    def normalize_message(self, raw_message: str) -> Optional[StreamingEvent]:
        raise NotImplementedError

    async def iter_events(self) -> AsyncIterator[StreamingEvent]:
        if self._ws is None:
            raise RuntimeError("WebSocket is not connected")
        async for raw_message in self._ws:
            if isinstance(raw_message, bytes):
                continue
            event = self.normalize_message(raw_message)
            if event is not None:
                yield event


class DeepgramStreamingClient(BaseRealtimeWSClient):
    provider_name = "deepgram"

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "nova-3",
        sample_rate: int = 16000,
        encoding: str = "linear16",
        interim_results: bool = True,
        endpointing_ms: int = 300,
        utterance_end_ms: int = 1000,
    ):
        query = urlencode(
            {
                "model": model,
                "encoding": encoding,
                "sample_rate": sample_rate,
                "interim_results": str(interim_results).lower(),
                "endpointing": endpointing_ms,
                "utterance_end_ms": utterance_end_ms,
                "vad_events": "true",
            }
        )
        super().__init__(
            f"wss://api.deepgram.com/v1/listen?{query}",
            headers={"Authorization": f"Token {api_key}"},
        )

    async def finalize(self):
        await self.send_json({"type": "Finalize"})

    def normalize_message(self, raw_message: str) -> Optional[StreamingEvent]:
        payload = json.loads(raw_message)
        message_type = str(payload.get("type", ""))
        if message_type != "Results":
            if message_type in {"SpeechStarted", "UtteranceEnd"}:
                return StreamingEvent(
                    provider=self.provider_name,
                    text="",
                    is_final=message_type == "UtteranceEnd",
                    event_type=message_type,
                    raw=payload,
                )
            return None

        alternative = ((payload.get("channel") or {}).get("alternatives") or [{}])[0]
        transcript = str(alternative.get("transcript", "")).strip()
        if not transcript:
            return None

        confidence = alternative.get("confidence", 0.0)
        languages = alternative.get("languages") or []
        language = str(languages[0]) if languages else str(payload.get("metadata", {}).get("language", ""))
        return StreamingEvent(
            provider=self.provider_name,
            text=transcript,
            is_final=bool(payload.get("is_final")),
            event_type=message_type,
            language=language,
            confidence=float(confidence or 0.0),
            start_sec=float(payload.get("start") or 0.0),
            duration_sec=float(payload.get("duration") or 0.0),
            raw=payload,
        )


class AssemblyAIStreamingClient(BaseRealtimeWSClient):
    provider_name = "assemblyai"

    def __init__(
        self,
        api_key: str,
        *,
        sample_rate: int = 16000,
        speech_model: str = "universal-streaming-english",
        encoding: str = "pcm_s16le",
    ):
        query = urlencode(
            {
                "sample_rate": sample_rate,
                "speech_model": speech_model,
                "encoding": encoding,
            }
        )
        super().__init__(
            f"wss://streaming.assemblyai.com/v3/ws?{query}",
            headers={"Authorization": api_key},
        )

    async def finalize(self):
        await self.send_json({"type": "Terminate"})

    def normalize_message(self, raw_message: str) -> Optional[StreamingEvent]:
        payload = json.loads(raw_message)
        transcript = str(payload.get("transcript", "")).strip()
        if not transcript:
            return None

        return StreamingEvent(
            provider=self.provider_name,
            text=transcript,
            is_final=bool(payload.get("end_of_turn") or payload.get("turn_is_formatted")),
            event_type=str(payload.get("type", "Results")),
            language=str(payload.get("language", "")),
            confidence=float(payload.get("confidence") or 0.0),
            raw=payload,
        )


async def stream_audio_queue(
    audio_queue: "asyncio.Queue[Optional[bytes]]",
    client: BaseRealtimeWSClient,
    on_event: Callable[[StreamingEvent], Awaitable[None]],
):
    """
    Forward PCM audio chunks from an asyncio queue to a provider and consume events.

    Send `None` into the queue to flush and terminate the session gracefully.
    """

    import asyncio

    await client.connect()
    receiver = asyncio.create_task(_consume_provider_events(client, on_event))
    try:
        while True:
            chunk = await audio_queue.get()
            if chunk is None:
                await client.finalize()
                break
            await client.send_audio(chunk)
    finally:
        await client.close()
        receiver.cancel()


async def _consume_provider_events(
    client: BaseRealtimeWSClient,
    on_event: Callable[[StreamingEvent], Awaitable[None]],
):
    async for event in client.iter_events():
        await on_event(event)
