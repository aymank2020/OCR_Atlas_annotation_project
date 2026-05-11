"""
Atlas Scribe Dashboard — Real-Time Audio Intelligence
=======================================================
Premium Streamlit dashboard for live transcription,
session history, and Gemini AI enrichment.

Run:  streamlit run atlas_scribe_dashboard.py --server.port 8501
"""

import os
import sys
import json
import time
import html
from pathlib import Path
from datetime import datetime

import streamlit as st

# Fix encoding on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from atlas_scribe import ScribeEngine
from atlas_scribe import CONFIG_FILE

def _save_config_to_yaml(engine):
    """Helper to save configuration dict back to yaml."""
    import yaml
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            yaml.dump(engine.config, f, allow_unicode=True, sort_keys=False)
    except Exception as e:
        st.error(f"Failed to save config: {e}")

# ── Page Config ─────────────────────────────────────────────────────
st.set_page_config(
    page_title="Atlas Scribe",
    page_icon="🎙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Premium CSS ─────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500&display=swap');

/* ── Global ─────────────────────────────────── */
:root {
    --bg-primary: #0a0a0f;
    --bg-card: rgba(17, 17, 28, 0.85);
    --bg-card-hover: rgba(25, 25, 40, 0.95);
    --border-glass: rgba(255, 255, 255, 0.06);
    --text-primary: #e8e8f0;
    --text-secondary: #8888a8;
    --text-muted: #55556e;
    --accent-blue: #4f8fff;
    --accent-green: #22c55e;
    --accent-orange: #f59e0b;
    --accent-red: #ef4444;
    --accent-purple: #a78bfa;
    --accent-cyan: #06b6d4;
    --gradient-1: linear-gradient(135deg, #4f8fff 0%, #a78bfa 100%);
    --gradient-2: linear-gradient(135deg, #22c55e 0%, #06b6d4 100%);
    --shadow-glow: 0 0 30px rgba(79, 143, 255, 0.1);
}

html, body, [data-testid="stAppViewContainer"] {
    font-family: 'Inter', -apple-system, sans-serif !important;
    background: var(--bg-primary) !important;
    color: var(--text-primary) !important;
}

[data-testid="stAppViewContainer"] {
    background: radial-gradient(ellipse at 20% 0%, rgba(79,143,255,0.07) 0%, transparent 50%),
                radial-gradient(ellipse at 80% 100%, rgba(167,139,250,0.05) 0%, transparent 50%),
                var(--bg-primary) !important;
}

[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0d0d15 0%, #0a0a12 100%) !important;
    border-right: 1px solid var(--border-glass) !important;
}

[data-testid="stHeader"] { background: transparent !important; }

/* Hide default streamlit elements */
#MainMenu, footer, header { visibility: hidden; }

/* ── Cards ──────────────────────────────────────── */
.glass-card {
    background: var(--bg-card);
    border: 1px solid var(--border-glass);
    border-radius: 16px;
    padding: 24px;
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    box-shadow: var(--shadow-glow);
    transition: all 0.3s ease;
}
.glass-card:hover {
    background: var(--bg-card-hover);
    border-color: rgba(79,143,255,0.15);
}

/* ── Status Badge ───────────────────────────────── */
.status-badge {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 6px 16px;
    border-radius: 20px;
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.5px;
}
.status-idle {
    background: rgba(85,85,110,0.2);
    color: var(--text-secondary);
    border: 1px solid rgba(85,85,110,0.3);
}
.status-capturing {
    background: rgba(34,197,94,0.15);
    color: var(--accent-green);
    border: 1px solid rgba(34,197,94,0.3);
    animation: pulse-green 2s ease-in-out infinite;
}
.status-paused {
    background: rgba(245,158,11,0.15);
    color: var(--accent-orange);
    border: 1px solid rgba(245,158,11,0.3);
}
.status-loading {
    background: rgba(79,143,255,0.15);
    color: var(--accent-blue);
    border: 1px solid rgba(79,143,255,0.3);
    animation: pulse-blue 1.5s ease-in-out infinite;
}

@keyframes pulse-green {
    0%, 100% { box-shadow: 0 0 0 0 rgba(34,197,94,0.3); }
    50% { box-shadow: 0 0 12px 4px rgba(34,197,94,0.15); }
}
@keyframes pulse-blue {
    0%, 100% { box-shadow: 0 0 0 0 rgba(79,143,255,0.3); }
    50% { box-shadow: 0 0 12px 4px rgba(79,143,255,0.15); }
}

/* ── Audio Level Bars ───────────────────────────── */
.level-bar-container {
    background: rgba(255,255,255,0.05);
    border-radius: 6px;
    height: 10px;
    overflow: hidden;
    margin: 4px 0;
}
.level-bar {
    height: 100%;
    border-radius: 6px;
    transition: width 0.3s ease;
}
.level-bar-system {
    background: var(--gradient-2);
}
.level-bar-mic {
    background: var(--gradient-1);
}

/* ── Transcript Segment ─────────────────────────── */
.transcript-seg {
    padding: 10px 16px;
    margin: 4px 0;
    border-radius: 10px;
    border-left: 3px solid;
    font-size: 14px;
    line-height: 1.6;
    transition: background 0.2s;
}
.transcript-seg:hover {
    background: rgba(255,255,255,0.03);
}
.seg-system {
    border-color: var(--accent-green);
    background: rgba(34,197,94,0.04);
}
.seg-mic {
    border-color: var(--accent-blue);
    background: rgba(79,143,255,0.04);
}
.seg-time {
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    color: var(--text-muted);
    margin-right: 10px;
}
.seg-source {
    font-size: 12px;
    margin-right: 6px;
}
.seg-lang {
    font-size: 10px;
    color: var(--accent-purple);
    margin-left: 8px;
    padding: 1px 6px;
    background: rgba(167,139,250,0.1);
    border-radius: 4px;
}
.seg-translation {
    display: block;
    margin-top: 8px;
    color: rgba(232, 232, 240, 0.78);
    font-size: 13px;
}
.interim-card {
    border: 1px dashed rgba(79,143,255,0.28);
    background: linear-gradient(135deg, rgba(79,143,255,0.09), rgba(167,139,250,0.06));
}
.interim-label {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--accent-cyan);
    margin-bottom: 8px;
}
.interim-text {
    font-size: 18px;
    line-height: 1.7;
    color: rgba(232,232,240,0.82);
    font-style: italic;
}
.interim-translation {
    margin-top: 12px;
    font-size: 14px;
    color: rgba(232,232,240,0.68);
}
.micro-stat {
    display: inline-block;
    margin-right: 10px;
    padding: 3px 8px;
    border-radius: 999px;
    background: rgba(255,255,255,0.05);
    color: var(--text-secondary);
    font-size: 11px;
}

/* ── Metric Cards ───────────────────────────────── */
.metric-card {
    text-align: center;
    padding: 20px;
}
.metric-value {
    font-size: 32px;
    font-weight: 800;
    background: var(--gradient-1);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}
.metric-label {
    font-size: 12px;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-top: 4px;
}

/* ── Buttons ────────────────────────────────────── */
.stButton > button {
    border-radius: 12px !important;
    font-weight: 600 !important;
    padding: 8px 24px !important;
    transition: all 0.3s ease !important;
    border: 1px solid var(--border-glass) !important;
}
.stButton > button:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 4px 20px rgba(79,143,255,0.2) !important;
}

/* ── Tabs ───────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
    gap: 4px;
    background: rgba(17,17,28,0.5);
    border-radius: 12px;
    padding: 4px;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 10px !important;
    color: var(--text-secondary) !important;
    font-weight: 500 !important;
}
.stTabs [aria-selected="true"] {
    background: rgba(79,143,255,0.15) !important;
    color: var(--accent-blue) !important;
}

/* ── Session History Card ───────────────────────── */
.session-card {
    background: var(--bg-card);
    border: 1px solid var(--border-glass);
    border-radius: 12px;
    padding: 16px 20px;
    margin: 8px 0;
    cursor: pointer;
    transition: all 0.3s ease;
}
.session-card:hover {
    border-color: rgba(79,143,255,0.3);
    background: var(--bg-card-hover);
    transform: translateX(4px);
}

/* ── Title ──────────────────────────────────────── */
.scribe-title {
    font-size: 28px;
    font-weight: 800;
    background: var(--gradient-1);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin-bottom: 0;
}
.scribe-subtitle {
    font-size: 13px;
    color: var(--text-muted);
    letter-spacing: 2px;
    text-transform: uppercase;
}

/* ── Error Banner ──────────────────────────────── */
.error-banner {
    background: rgba(239,68,68,0.1);
    border: 1px solid rgba(239,68,68,0.3);
    border-radius: 10px;
    padding: 12px 16px;
    color: var(--accent-red);
    font-size: 13px;
    margin: 8px 0;
}

/* ── Scrollbar ──────────────────────────────────── */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
    background: rgba(79,143,255,0.2);
    border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover { background: rgba(79,143,255,0.4); }
</style>
""", unsafe_allow_html=True)


# ── Engine Init ─────────────────────────────────────────────────────
@st.cache_resource
def init_engine():
    """Initialize ScribeEngine once (persists across reruns)."""
    from atlas_scribe import ScribeEngine
    return ScribeEngine()


engine = init_engine()
    
# ── Auto-Load Whisper AI ───────────────────────────────────────
if 'startup_done' not in st.session_state:
    st.session_state.startup_done = False

if not st.session_state.startup_done:
    if not engine.model:
        with st.sidebar:
            with st.status("🚀 Preparing Whisper AI...", expanded=True) as status:
                st.write(f"Loading model: **{engine.config.get('whisper', {}).get('model_size', 'medium')}**")
                try:
                    engine.load_model()
                    status.update(label="✅ Whisper AI Ready!", state="complete", expanded=False)
                except Exception as e:
                    status.update(label="❌ Load Failed", state="error", expanded=True)
                    st.error(f"Startup error: {e}")
    st.session_state.startup_done = True


# ── Helper: Calculate elapsed time ──────────────────────────────────
def _calc_elapsed(engine) -> float:
    """Calculate elapsed session time accounting for pauses."""
    if not engine._session_start_time:
        return 0.0
    elapsed = time.time() - engine._session_start_time - engine._total_paused_duration
    if engine.is_paused and engine._last_pause_start > 0:
        elapsed -= (time.time() - engine._last_pause_start)
    return max(0.0, elapsed)


def _format_duration(seconds: float) -> str:
    """Format seconds as HH:MM:SS."""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# ── Sidebar ─────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<p class="scribe-title">🎙️ Atlas Scribe</p>', unsafe_allow_html=True)
    st.markdown('<p class="scribe-subtitle">Real-Time Audio Intelligence</p>', unsafe_allow_html=True)
    st.markdown("---")

    # Status
    status = engine.status
    status_map = {
        "idle": ("⚪ Idle", "status-idle"),
        "loading": ("🔄 Loading Model...", "status-loading"),
        "capturing": ("🔴 LIVE", "status-capturing"),
        "paused": ("⏸️ Paused", "status-paused"),
        "error": ("❌ Error", "status-idle"),
    }
    label, css_class = status_map.get(status, ("⚪ Unknown", "status-idle"))
    st.markdown(f'<div class="status-badge {css_class}">{label}</div>', unsafe_allow_html=True)

    if engine.status_detail:
        st.caption(engine.status_detail)
    if engine.error_message:
        st.markdown(f'<div class="error-banner">⚠️ {engine.error_message}</div>', unsafe_allow_html=True)

    st.markdown("---")

    # Controls
    st.markdown("##### Controls")
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("▶️ Start", use_container_width=True, disabled=engine.is_capturing):
            with st.spinner("Starting..."):
                engine.start()
            st.rerun()
    with col2:
        if engine.is_capturing and not engine.is_paused:
            if st.button("⏸️ Pause", use_container_width=True):
                engine.pause()
                st.rerun()
        elif engine.is_paused:
            if st.button("▶️ Resume", use_container_width=True):
                engine.resume()
                st.rerun()
    with col3:
        if st.button("⏹️ Stop", use_container_width=True, disabled=not engine.is_capturing):
            with st.spinner("Stopping & saving..."):
                engine.stop()
            st.rerun()
            
    # Add a Clear/Reset button
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🗑️ Clear / Reset", use_container_width=True, help="Clear current session from screen before a new recording"):
        if engine.is_capturing:
            st.warning("Please stop the recording before clearing.")
        else:
            with engine._lock:
                engine.live_segments = []
                engine.current_session = None
            st.rerun()

    st.markdown("---")

    # Audio Levels
    if engine.is_capturing:
        st.markdown("##### Audio Levels")
        sys_pct = min(int(engine.audio_level_system * 1000), 100)
        mic_pct = min(int(engine.audio_level_mic * 1000), 100)

        st.markdown(f"""
        <div style="margin-bottom:8px">
            <span style="font-size:12px;color:#22c55e">🔊 System: {sys_pct}%</span>
            <div class="level-bar-container">
                <div class="level-bar level-bar-system" style="width:{sys_pct}%"></div>
            </div>
        </div>
        <div>
            <span style="font-size:12px;color:#4f8fff">🎤 Mic: {mic_pct}%</span>
            <div class="level-bar-container">
                <div class="level-bar level-bar-mic" style="width:{mic_pct}%"></div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    # Session info
    if engine.current_session:
        elapsed = _calc_elapsed(engine)
        # Use thread-safe snapshot for count
        seg_count = len(engine.get_live_segments_snapshot())
        st.markdown(f"##### Current Session")
        st.markdown(f"⏱️ `{_format_duration(elapsed)}`")
        st.markdown(f"📊 `{seg_count}` segments")

    st.markdown("---")
    runtime = engine.get_runtime_snapshot()
    if engine.is_capturing or runtime.get("active_interims"):
        st.markdown("##### Low-Latency")
        st.caption(
            f"Provider: {runtime.get('provider', 'local_whisper')} | "
            f"VAD: {runtime.get('vad_backend', 'energy')} | "
            f"Avg: {runtime.get('avg_latency_ms', 0):.0f} ms"
        )
        st.caption(
            f"Queue: {runtime.get('queue_depth', 0)} | "
            f"Ghost lines: {runtime.get('active_interims', 0)} | "
            f"Streams: {runtime.get('provider_sessions', 0)} | "
            f"Drops: {runtime.get('drops', 0)}"
        )
        st.markdown("---")

    # Transcription Settings
    st.markdown("##### Transcription Settings")
    target_lang = st.selectbox("🌍 Target Language", options=["auto", "ar", "en", "tr", "fr", "de", "es", "ru", "zh", "ja", "ko"], index=0)
    task_type = st.radio("🎯 Task", options=["transcribe", "translate"], horizontal=True)
    
    # Update engine config if changed
    if "whisper" not in engine.config: engine.config["whisper"] = {}
    engine.config["whisper"]["language"] = None if target_lang == "auto" else target_lang
    engine.config["whisper"]["task"] = task_type
    if "translation" not in engine.config:
        engine.config["translation"] = {}
    live_translation = st.toggle(
        "Live Translation",
        value=engine.config["translation"].get("enabled", False),
        help="Translate interim and final text in the background with Gemini Flash.",
    )
    translation_lang_options = ["ar", "en", "tr", "fr", "de", "es"]
    current_translation_lang = engine.config["translation"].get("target_language", "ar")
    translation_target = st.selectbox(
        "Live Translation Target",
        options=translation_lang_options,
        index=translation_lang_options.index(current_translation_lang) if current_translation_lang in translation_lang_options else 0,
    )
    engine.config["translation"]["enabled"] = live_translation
    engine.config["translation"]["target_language"] = translation_target

    # Model info
    if engine.model_info:
        st.markdown("---")
        st.markdown(f"##### Model")
        st.caption(f"🧠 {engine.model_info}")


# ── Main Content ────────────────────────────────────────────────────
tab_live, tab_history, tab_ai, tab_rules, tab_settings = st.tabs([
    "🎙️ Live Transcript",
    "📚 History",
    "🤖 AI Insights",
    "🧠 Rule Intelligence",
    "⚙️ Settings",
])


# ── TAB: Live Transcript ───────────────────────────────────────────
with tab_live:
    # Use thread-safe snapshot
    segments_snapshot = engine.get_live_segments_snapshot()
    interims_snapshot = engine.get_live_interims_snapshot()
    runtime_snapshot = engine.get_runtime_snapshot()

    if not engine.is_capturing and not segments_snapshot and not interims_snapshot:
        # Welcome screen
        st.markdown("""
        <div class="glass-card" style="text-align:center; padding:60px 40px;">
            <div style="font-size:72px; margin-bottom:20px;">🎙️</div>
            <div class="scribe-title" style="font-size:36px;">Atlas Scribe</div>
            <p style="color:var(--text-secondary); font-size:16px; margin:16px 0 30px;">
                Real-time audio transcription powered by Whisper AI + Gemini
            </p>
            <div style="display:flex; justify-content:center; gap:40px; margin-top:20px;">
                <div class="metric-card">
                    <div style="font-size:28px;">🔊</div>
                    <div style="color:var(--text-secondary); font-size:12px; margin-top:4px;">System Audio</div>
                </div>
                <div class="metric-card">
                    <div style="font-size:28px;">🎤</div>
                    <div style="color:var(--text-secondary); font-size:12px; margin-top:4px;">Microphone</div>
                </div>
                <div class="metric-card">
                    <div style="font-size:28px;">🌍</div>
                    <div style="color:var(--text-secondary); font-size:12px; margin-top:4px;">All Languages</div>
                </div>
                <div class="metric-card">
                    <div style="font-size:28px;">🤖</div>
                    <div style="color:var(--text-secondary); font-size:12px; margin-top:4px;">Gemini AI</div>
                </div>
            </div>
            <p style="color:var(--text-muted); font-size:13px; margin-top:30px;">
                Press <strong>▶️ Start</strong> in the sidebar to begin capturing
            </p>
        </div>
        """, unsafe_allow_html=True)
    else:
        # Live transcript view
        # Metrics row
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.markdown(f"""<div class="glass-card metric-card">
                <div class="metric-value">{len(segments_snapshot)}</div>
                <div class="metric-label">Segments</div>
            </div>""", unsafe_allow_html=True)
        with col2:
            elapsed = _calc_elapsed(engine)
            time_str = _format_duration(elapsed) if engine._session_start_time else "00:00:00"
            st.markdown(f"""<div class="glass-card metric-card">
                <div class="metric-value">{time_str}</div>
                <div class="metric-label">Duration</div>
            </div>""", unsafe_allow_html=True)
        with col3:
            avg_latency = runtime_snapshot.get("avg_latency_ms", 0.0)
            st.markdown(f"""<div class="glass-card metric-card">
                <div class="metric-value" style="font-size:24px;">{avg_latency:.0f} ms</div>
                <div class="metric-label">Avg Latency</div>
            </div>""", unsafe_allow_html=True)
        with col4:
            langs = set(s.language for s in segments_snapshot if s.language)
            langs.update(i.language for i in interims_snapshot.values() if getattr(i, "language", ""))
            lang_str = ", ".join(langs) if langs else "—"
            st.markdown(f"""<div class="glass-card metric-card">
                <div class="metric-value" style="font-size:20px;">{lang_str}</div>
                <div class="metric-label">Languages</div>
            </div>""", unsafe_allow_html=True)
        with col5:
            sys_count = sum(1 for s in segments_snapshot if s.source == "system")
            mic_count = len(segments_snapshot) - sys_count
            st.markdown(f"""<div class="glass-card metric-card">
                <div class="metric-value" style="font-size:18px;">🔊{sys_count} 🎤{mic_count}</div>
                <div class="metric-label">Sources</div>
            </div>""", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        if interims_snapshot:
            st.markdown("##### Live Ghost Writing")
            for source_key, interim in interims_snapshot.items():
                source_label = "System" if source_key == "system" else "Microphone"
                source_icon = "🔊" if source_key == "system" else "🎤"
                interim_text = html.escape(interim.text or "...")
                translation_html = ""
                if getattr(interim, "translation", ""):
                    translation_html = f'<div class="interim-translation">{html.escape(interim.translation)}</div>'
                stats_html = (
                    f'<span class="micro-stat">stability {int(float(getattr(interim, "stability", 0.0)) * 100)}%</span>'
                    f'<span class="micro-stat">latency {float(getattr(interim, "latency_ms", 0.0)):.0f} ms</span>'
                    f'<span class="micro-stat">{html.escape(getattr(interim, "language", "") or "auto")}</span>'
                )
                st.markdown(
                    f"""
                    <div class="glass-card interim-card" style="margin-bottom:14px;">
                        <div class="interim-label">{source_icon} {source_label} interim</div>
                        <div class="interim-text">{interim_text}</div>
                        {translation_html}
                        <div style="margin-top:12px;">{stats_html}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        # Transcript container
        transcript_container = st.container(height=500)
        with transcript_container:
            if not segments_snapshot and not interims_snapshot:
                st.markdown("""
                <div style="text-align:center; padding:40px; color:var(--text-muted);">
                    <div style="font-size:36px; margin-bottom:12px;">👂</div>
                    Listening... waiting for speech
                </div>
                """, unsafe_allow_html=True)
            elif not segments_snapshot and interims_snapshot:
                st.markdown("""
                <div style="text-align:center; padding:32px; color:var(--text-secondary);">
                    Interim speech detected. Waiting for the first finalized segment...
                </div>
                """, unsafe_allow_html=True)
            else:
                for seg in segments_snapshot:
                    m, s = divmod(int(seg.start), 60)
                    h, m2 = divmod(m, 60)
                    time_str = f"{h:02d}:{m2:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"
                    css_class = "seg-system" if seg.source == "system" else "seg-mic"
                    icon = "🔊" if seg.source == "system" else "🎤"
                    lang_html = f'<span class="seg-lang">{seg.language}</span>' if seg.language else ""
                    text_html = html.escape(seg.text)
                    translation_html = (
                        f'<span class="seg-translation">{html.escape(seg.translation)}</span>'
                        if getattr(seg, "translation", "")
                        else ""
                    )

                    st.markdown(f"""
                    <div class="transcript-seg {css_class}">
                        <span class="seg-time">{time_str}</span>
                        <span class="seg-source">{icon}</span>
                        {text_html}{lang_html}
                        {translation_html}
                    </div>
                    """, unsafe_allow_html=True)

        # --- Combined Article View ---
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("##### 📝 النص المتصل (الفقرة الكاملة)")
        if segments_snapshot:
            full_text = " ".join([seg.text.strip() for seg in segments_snapshot])
            st.markdown(f"""
            <div style="background: rgba(255,255,255,0.05); padding: 20px; border-radius: 12px; margin-top: 10px; line-height: 1.8; font-size: 17px; font-weight: 500; border: 1px solid var(--border-glass); direction: rtl; text-align: right;">
                {full_text}
            </div>
            """, unsafe_allow_html=True)

        # Auto-refresh when capturing
        if engine.is_capturing or interims_snapshot:
            refresh_sec = engine.config.get("dashboard", {}).get("auto_refresh_sec", 2)
            time.sleep(refresh_sec)
            st.rerun()


# ── TAB: History ───────────────────────────────────────────────────
with tab_history:
    st.markdown("### 📚 Session History")

    sessions = engine.get_saved_sessions()

    if not sessions:
        st.markdown("""
        <div class="glass-card" style="text-align:center; padding:40px;">
            <div style="font-size:48px; margin-bottom:12px;">📭</div>
            <p style="color:var(--text-secondary);">No saved sessions yet.<br>
            Start a recording to see sessions here.</p>
        </div>
        """, unsafe_allow_html=True)
    else:
        for sess in sessions:
            sid = sess["session_id"]
            started = sess.get("started_at", "")[:19].replace("T", " ")
            seg_count = sess.get("segment_count", 0)
            duration = sess.get("duration_sec", 0)
            m, s = divmod(int(duration), 60)
            h, m = divmod(m, 60)
            dur_str = f"{h}h {m}m {s}s" if h else f"{m}m {s}s"
            has_summary = "🤖" if sess.get("has_summary") else ""

            with st.expander(f"📅 {started}  |  ⏱️ {dur_str}  |  📊 {seg_count} segments {has_summary}"):
                col1, col2, col3 = st.columns([2, 1, 1])

                with col1:
                    # Load and show transcript
                    transcript = engine.load_session_transcript(sid)
                    if transcript:
                        for seg in transcript.get("segments", [])[:50]:
                            m2, s2 = divmod(int(seg.get("start", 0)), 60)
                            icon = "🔊" if seg.get("source") == "system" else "🎤"
                            st.caption(f"`{m2:02d}:{s2:02d}` {icon} {seg.get('text', '')}")
                        if len(transcript.get("segments", [])) > 50:
                            st.caption(f"... and {len(transcript['segments']) - 50} more segments")

                with col2:
                    # Summary
                    summary = engine.load_session_summary(sid)
                    if summary:
                        st.markdown("**AI Summary:**")
                        st.markdown(summary[:500])
                    else:
                        if st.button(f"🤖 Analyze with Gemini", key=f"enrich_{sid}"):
                            with st.spinner("Running Gemini analysis..."):
                                result = engine.enrich_session_now(sid)
                            if result:
                                st.success("✅ Analysis complete!")
                                st.rerun()
                            else:
                                st.error("Analysis failed")

                with col3:
                    # Export options
                    st.markdown("**Export:**")
                    session_dir = engine.sessions_dir / sid

                    json_file = session_dir / "transcript.json"
                    if json_file.exists():
                        st.download_button(
                            "📥 JSON",
                            json_file.read_text(encoding="utf-8"),
                            file_name=f"scribe_{sid}.json",
                            mime="application/json",
                            key=f"dl_json_{sid}",
                        )

                    txt_file = session_dir / "transcript.txt"
                    if txt_file.exists():
                        st.download_button(
                            "📥 TXT",
                            txt_file.read_text(encoding="utf-8"),
                            file_name=f"scribe_{sid}.txt",
                            mime="text/plain",
                            key=f"dl_txt_{sid}",
                        )

                    srt_file = session_dir / "transcript.srt"
                    if srt_file.exists():
                        st.download_button(
                            "📥 SRT",
                            srt_file.read_text(encoding="utf-8"),
                            file_name=f"scribe_{sid}.srt",
                            mime="text/plain",
                            key=f"dl_srt_{sid}",
                        )


# ── TAB: AI Insights ───────────────────────────────────────────────
with tab_ai:
    st.markdown("### 🤖 AI Insights — Gemini Enrichment")

    gcfg = engine.config.get("gemini", {})
    api_key = os.getenv(gcfg.get("api_key_env", "GEMINI_API_KEY"), "")

    if not api_key:
        st.warning("⚠️ Gemini API key not found. Set `GEMINI_API_KEY` in your `.env` file.")
    else:
        st.success(f"✅ Gemini API connected ({gcfg.get('model', 'gemini-3.1-pro-preview')})")

    # Live analysis of current session
    live_segs = engine.get_live_segments_snapshot()
    if live_segs:
        st.markdown("---")
        st.markdown("#### 📝 Analyze Current Session")
        if st.button("🤖 Run Gemini Analysis Now", key="live_gemini"):
            # Build transcript from live segments
            lines = []
            for s in live_segs:
                m, sec = divmod(int(s.start), 60)
                src = "System" if s.source == "system" else "Mic"
                lines.append(f"[{m:02d}:{sec:02d}] ({src}) {s.text}")
            transcript_text = "\n".join(lines)

            if transcript_text.strip() and api_key:
                with st.spinner("🤖 Analyzing with Gemini..."):
                    try:
                        from google import genai

                        client = genai.Client(api_key=api_key)
                        lang = gcfg.get("summary_language", "ar")
                        lang_inst = "باللغة العربية" if lang == "ar" else "in English"

                        response = client.models.generate_content(
                            model=gcfg.get("model", "gemini-3.1-pro-preview"),
                            contents=f"""Analyze this live transcript and provide a detailed summary {lang_inst}.
Include: key topics, important points, and any action items.

Transcript:
{transcript_text}""",
                        )
                        st.markdown("#### 📊 Analysis Result")
                        st.markdown(response.text)
                    except Exception as e:
                        st.error(f"Gemini error: {e}")

    # Past session analysis
    st.markdown("---")
    st.markdown("#### 📚 Analyze Past Session")
    sessions = engine.get_saved_sessions()
    if sessions:
        session_options = {
            f"{s['session_id']} ({s.get('segment_count', 0)} segments)": s["session_id"]
            for s in sessions
        }
        selected = st.selectbox("Select session:", options=list(session_options.keys()))
        if selected:
            sid = session_options[selected]
            summary = engine.load_session_summary(sid)
            if summary:
                st.markdown("#### 📋 Existing Analysis")
                st.markdown(summary)
            else:
                if st.button("🤖 Analyze This Session", key="past_gemini"):
                    with st.spinner("Running analysis..."):
                        result = engine.enrich_session_now(sid)
                    if result:
                        st.success("✅ Done!")
                        st.json(result)
                    else:
                        st.error("Analysis failed")
    else:
        st.info("No past sessions to analyze.")


# ── TAB: Rule Intelligence ─────────────────────────────────────────
with tab_rules:
    st.markdown("### 🧠 Rule Intelligence — Discord Automation")
    
    rules_path = Path("prompts/atlas_discord_updates.md")
    
    if rules_path.exists():
        st.success("✅ Dynamic Rule File Found")
        mod_time = datetime.fromtimestamp(rules_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        st.caption(f"Last Intelligence Sync: **{mod_time}**")
        
        content = rules_path.read_text(encoding="utf-8")
        st.markdown("---")
        st.markdown(content)
        
        if st.button("➕ Merge into Core (Manual)", help="Safely append these rules to the core context pack"):
            core_path = Path("prompts/atlas_vertex_context_pack.txt")
            if core_path.exists():
                core_text = core_path.read_text(encoding="utf-8")
                # Append if not already there
                if content[:100] not in core_text:
                    with open(core_path, "a", encoding="utf-8") as f:
                        f.write("\n\n" + content)
                    st.success("Rules merged into core context pack.")
                else:
                    st.info("Rules appear to be already present in core.")
    else:
        st.info("⏳ No dynamic rules extracted yet. The Stealth Daemon will update this automatically every 8 hours.")
        st.markdown("""
        How it works:
        1. **Atlas Stealth Daemon** scrapes Discord every 8h.
        2. **Gemini Flash** cleans and extracts the technical rules.
        3. **Gemini Pro 3.1** merges them into the intelligence pool.
        4. **Auto-Solver** automatically injects these rules into every prompt.
        """)

# ── TAB: Settings ──────────────────────────────────────────────────

    st.markdown("#### 🔊 Audio Devices")
    st.caption("Select your audio devices. This will resolve the Windows Audio Capture error you experienced.")
    
    try:
        devices = engine.get_audio_devices()
        if devices.get("error"):
            st.markdown(f"""
            <div class="error-banner">
                <strong>Audio Detection Issue:</strong> {devices['error']}<br>
                <span style="font-size:11px; color:var(--text-secondary);">
                    This may be a temporary COM error. Try restarting the dashboard or check your audio drivers.
                </span>
            </div>
            """, unsafe_allow_html=True)
            
            # Still show the manual config option
            st.markdown("**Manual Configuration:**")
            manual_speaker = st.text_input("Speaker Device Name", value=engine.config.get("audio", {}).get("loopback_device", ""))
            manual_mic = st.text_input("Microphone Device Name", value=engine.config.get("audio", {}).get("microphone_device", ""))
            
            if st.button("💾 Save Manual Audio Settings"):
                if "audio" not in engine.config:
                    engine.config["audio"] = {}
                engine.config["audio"]["loopback_device"] = manual_speaker
                engine.config["audio"]["microphone_device"] = manual_mic
                _save_config_to_yaml(engine)
                st.success("✅ Audio settings saved! Restart recording to apply.")
        else:
            speakers = ["Default"] + devices.get("speakers", [])
            mics = ["Default"] + devices.get("microphones", [])
            
            # Load current from config
            curr_speaker = engine.config.get("audio", {}).get("loopback_device", "")
            curr_speaker_idx = speakers.index(curr_speaker) if curr_speaker in speakers else 0
            
            curr_mic = engine.config.get("audio", {}).get("microphone_device", "")
            curr_mic_idx = mics.index(curr_mic) if curr_mic in mics else 0
            
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**🔊 Speaker (System Loopback)**")
                st.caption(f"Default: {devices.get('default_speaker', 'N/A')}")
                selected_speaker = st.selectbox("Speaker Device", options=speakers, index=curr_speaker_idx)
                
            with col2:
                st.markdown("**🎤 Microphone**")
                st.caption(f"Default: {devices.get('default_mic', 'N/A')}")
                selected_mic = st.selectbox("Microphone Device", options=mics, index=curr_mic_idx)
                
            if st.button("💾 Save Audio Settings"):
                if "audio" not in engine.config:
                    engine.config["audio"] = {}
                engine.config["audio"]["loopback_device"] = "" if selected_speaker == "Default" else selected_speaker
                engine.config["audio"]["microphone_device"] = "" if selected_mic == "Default" else selected_mic
                _save_config_to_yaml(engine)
                st.success("✅ Audio settings saved! Restart recording to apply.")
                
    except Exception as e:
        st.error(f"Cannot detect devices: {e}")

    st.markdown("---")
    st.markdown("#### 🧠 Whisper Model")
    wcfg = engine.config.get("whisper", {})
    st.markdown(f"""<div class="glass-card">
        <strong>Model:</strong> {wcfg.get('model_size', 'medium')}<br>
        <strong>Device:</strong> {wcfg.get('device', 'cuda')}<br>
        <strong>Compute:</strong> {wcfg.get('compute_type', 'float16')}<br>
        <strong>Beam Size:</strong> {wcfg.get('beam_size', 5)}<br>
        <strong>VAD Filter:</strong> {'✅' if wcfg.get('vad_filter') else '❌'}<br>
        <strong>Status:</strong> {'✅ Loaded — ' + engine.model_info if engine.model else '⏳ Not loaded yet'}
    </div>""", unsafe_allow_html=True)

    if not engine.model:
        if st.button("📦 Pre-load Model Now"):
            with st.spinner("Loading Whisper model (may download ~1.5GB on first run)..."):
                engine.load_model()
            st.success(f"✅ Model loaded: {engine.model_info}")
            st.rerun()

    st.markdown("---")
    st.markdown("#### 🤖 Gemini Configuration")
    gemini_cfg = engine.config.get("gemini", {})
    st.markdown(f"""<div class="glass-card">
        <strong>Enabled:</strong> {'✅' if gemini_cfg.get('enabled') else '❌'}<br>
        <strong>Model:</strong> {gemini_cfg.get('model', 'gemini-3.1-pro-preview')}<br>
        <strong>Auto-summarize:</strong> {'✅' if gemini_cfg.get('auto_summarize_on_stop') else '❌'}<br>
        <strong>Summary Language:</strong> {gemini_cfg.get('summary_language', 'ar')}<br>
        <strong>Extract Rules:</strong> {'✅' if gemini_cfg.get('extract_rules') else '❌'}<br>
        <strong>API Key:</strong> {'✅ Set' if api_key else '❌ Not set'}
    </div>""", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("#### 📁 Storage")
    st.markdown(f"""<div class="glass-card">
        <strong>Sessions Directory:</strong> <code>{engine.sessions_dir}</code><br>
        <strong>Saved Sessions:</strong> {len(engine.get_saved_sessions())}<br>
        <strong>Config File:</strong> <code>atlas_scribe_config.yaml</code>
    </div>""", unsafe_allow_html=True)


# ── Config Save Helper ──────────────────────────────────────────────
def _save_config_to_yaml(engine):
    """Persist current audio config to the YAML file."""
    try:
        import yaml
        cfg_path = Path("atlas_scribe_config.yaml")
        if cfg_path.exists():
            with open(cfg_path, "r", encoding="utf-8") as f:
                full_cfg = yaml.safe_load(f) or {}
        else:
            full_cfg = {}
            
        if "scribe" not in full_cfg:
            full_cfg["scribe"] = {}
        if "audio" not in full_cfg["scribe"]:
            full_cfg["scribe"]["audio"] = {}
            
        full_cfg["scribe"]["audio"]["loopback_device"] = engine.config["audio"]["loopback_device"]
        full_cfg["scribe"]["audio"]["microphone_device"] = engine.config["audio"]["microphone_device"]
        
        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.dump(full_cfg, f, default_flow_style=False, allow_unicode=True)
    except Exception as e:
        st.error(f"Failed to save settings: {e}")
