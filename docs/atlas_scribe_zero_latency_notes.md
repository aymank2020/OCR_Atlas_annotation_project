# Atlas Scribe Zero-Latency Notes

## What changed

- Capture now runs in micro-frames instead of waiting for multi-second chunks.
- Speech windows are assembled with local VAD and emitted as `interim` plus `final`.
- The dashboard now shows ghost-writing interim text, latency telemetry, and optional live translation.
- A standalone asyncio WebSocket module is included for cloud STT migration.
- Deepgram can now be activated directly in the engine with `streaming.provider: deepgram`.
- A FastAPI WebSocket bridge is available for browser-to-server live audio streaming.
- A browser demo page now streams microphone audio through an `AudioWorklet` and renders interim plus final transcript events live.

## Runtime path

1. Capture 20ms-40ms frames from microphone or loopback.
2. Gate silence locally with Silero VAD when available, or energy fallback.
3. Stream PCM frames directly to Deepgram when `streaming.provider` resolves to `deepgram`.
4. Surface `interim` transcripts immediately and solidify them as `final`.
5. Translate interim/final text in a background worker when enabled.

## Migration path

- Current desktop engine default: `deepgram` when `DEEPGRAM_API_KEY` is present, otherwise automatic fallback to `local_whisper`
- Cloud provider scaffold: `atlas_realtime_ws_clients.py`
- Browser bridge: `atlas_scribe_realtime_api.py`
- To activate Deepgram in the desktop engine, set `streaming.provider` to `deepgram` and provide `DEEPGRAM_API_KEY`.
- To run the browser bridge, use `run_atlas_scribe_realtime_bridge.ps1` or start `uvicorn atlas_scribe_realtime_api:app --host 127.0.0.1 --port 8765`.
- Open `http://127.0.0.1:8765/demo` to use the browser microphone demo.
- If `GEMINI_API_KEY` is present, the browser bridge can emit `translation` events alongside transcript events.
