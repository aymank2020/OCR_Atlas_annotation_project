"""
Atlas Command Hub — Unified Service Dashboard
=================================================
The master control panel for all Atlas services.
One URL to rule them all: http://localhost:8500

Run:  streamlit run atlas_command_hub.py --server.port 8500
"""

import os
import sys
import socket
import signal
import subprocess
import time
import platform
from pathlib import Path
from datetime import datetime

import yaml
import streamlit as st

# Fix encoding on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Paths ───────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent
HUB_CONFIG = PROJECT_ROOT / "atlas_hub_config.yaml"

# ── Load Config ─────────────────────────────────────────────────────
@st.cache_data(ttl=30)
def load_hub_config():
    if HUB_CONFIG.exists():
        with open(HUB_CONFIG, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def get_services(config):
    return config.get("services", {})


# ── Port Status Check ───────────────────────────────────────────────
def is_port_alive(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    """Check if a port is accepting connections."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False


# ── Process Management ──────────────────────────────────────────────
def start_service(key: str, svc: dict):
    """Start a service as a background subprocess."""
    cmd = svc.get("command", "")
    if not cmd:
        return False, "No command configured"

    # Check if already running
    if is_port_alive(svc["port"]):
        return False, "Already running"

    try:
        # Build environment
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"

        # Get the python/streamlit from the current venv
        venv_python = sys.executable
        venv_dir = Path(venv_python).parent

        # Adjust PATH to include venv Scripts
        env["PATH"] = str(venv_dir) + os.pathsep + env.get("PATH", "")

        log_dir = PROJECT_ROOT / "logs"
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / f"{key}.log"
        
        # Parse and run command
        with open(log_file, "a", encoding="utf-8") as lf:
            lf.write(f"\n--- Service Start: {datetime.now()} ---\n")
            if sys.platform == "win32":
                proc = subprocess.Popen(
                    cmd,
                    shell=True,
                    cwd=str(PROJECT_ROOT),
                    env=env,
                    stdout=lf,
                    stderr=lf,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
                )
            else:
                proc = subprocess.Popen(
                    cmd,
                    shell=True,
                    cwd=str(PROJECT_ROOT),
                    env=env,
                    stdout=lf,
                    stderr=lf,
                    start_new_session=True,
                )

        # Track PID
        if "pids" not in st.session_state:
            st.session_state.pids = {}
        st.session_state.pids[key] = proc.pid

        return True, f"Started (PID: {proc.pid})"
    except Exception as e:
        return False, str(e)


def stop_service(key: str, svc: dict):
    """Stop a running service."""
    pid = st.session_state.get("pids", {}).get(key)

    # Try killing by PID first
    if pid:
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                               capture_output=True, timeout=10)
            else:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            st.session_state.pids.pop(key, None)
            return True, f"Stopped (PID: {pid})"
        except Exception:
            pass

    # Fallback: kill by port
    port = svc["port"]
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                f'for /f "tokens=5" %a in (\'netstat -aon ^| findstr :{port} ^| findstr LISTENING\') do taskkill /F /PID %a',
                shell=True, capture_output=True, timeout=10,
            )
        return True, f"Stopped service on port {port}"
    except Exception as e:
        return False, str(e)


# ── System Metrics ──────────────────────────────────────────────────
def get_system_metrics():
    """Get CPU, RAM, Disk metrics."""
    metrics = {"cpu_pct": 0, "ram_pct": 0, "ram_used_gb": 0, "ram_total_gb": 0,
               "disk_pct": 0, "disk_used_gb": 0, "disk_total_gb": 0, "gpu_name": "N/A"}
    try:
        import psutil
        metrics["cpu_pct"] = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        metrics["ram_pct"] = mem.percent
        metrics["ram_used_gb"] = round(mem.used / (1024**3), 1)
        metrics["ram_total_gb"] = round(mem.total / (1024**3), 1)
        disk = psutil.disk_usage("E:\\" if sys.platform == "win32" else "/")
        metrics["disk_pct"] = disk.percent
        metrics["disk_used_gb"] = round(disk.used / (1024**3), 1)
        metrics["disk_total_gb"] = round(disk.total / (1024**3), 1)
    except ImportError:
        pass

    # GPU detection
    try:
        import torch
        if torch.cuda.is_available():
            metrics["gpu_name"] = torch.cuda.get_device_name(0)
    except ImportError:
        pass

    return metrics


# ── Page Config ─────────────────────────────────────────────────────
st.set_page_config(
    page_title="Atlas Command Hub",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Premium CSS ─────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
    --bg-primary: #06060b;
    --bg-card: rgba(14, 14, 24, 0.9);
    --bg-card-hover: rgba(22, 22, 38, 0.95);
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
    --gradient-hero: linear-gradient(135deg, #667eea 0%, #764ba2 50%, #f093fb 100%);
    --gradient-card: linear-gradient(145deg, rgba(79,143,255,0.08) 0%, rgba(167,139,250,0.05) 100%);
    --shadow-glow: 0 0 40px rgba(79, 143, 255, 0.08);
}

html, body, [data-testid="stAppViewContainer"] {
    font-family: 'Inter', -apple-system, sans-serif !important;
    background: var(--bg-primary) !important;
    color: var(--text-primary) !important;
}

[data-testid="stAppViewContainer"] {
    background:
        radial-gradient(ellipse at 15% 0%, rgba(102,126,234,0.12) 0%, transparent 50%),
        radial-gradient(ellipse at 85% 100%, rgba(118,75,162,0.08) 0%, transparent 50%),
        radial-gradient(ellipse at 50% 50%, rgba(240,147,251,0.03) 0%, transparent 70%),
        var(--bg-primary) !important;
}

[data-testid="stHeader"] { background: transparent !important; }
#MainMenu, footer, header { visibility: hidden; }

/* ── Service Card ──────────────────────────────── */
.service-card {
    background: var(--bg-card);
    border: 1px solid var(--border-glass);
    border-radius: 20px;
    padding: 28px;
    backdrop-filter: blur(30px);
    -webkit-backdrop-filter: blur(30px);
    box-shadow: var(--shadow-glow);
    transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
    position: relative;
    overflow: hidden;
}
.service-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 3px;
    background: var(--gradient-hero);
    opacity: 0;
    transition: opacity 0.4s ease;
}
.service-card:hover {
    background: var(--bg-card-hover);
    border-color: rgba(79,143,255,0.2);
    transform: translateY(-4px);
    box-shadow: 0 12px 40px rgba(79,143,255,0.12);
}
.service-card:hover::before { opacity: 1; }

.service-icon { font-size: 42px; margin-bottom: 12px; }
.service-name {
    font-size: 18px;
    font-weight: 700;
    color: var(--text-primary);
    margin-bottom: 4px;
}
.service-desc {
    font-size: 13px;
    color: var(--text-secondary);
    line-height: 1.5;
    margin-bottom: 16px;
}
.service-port {
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    color: var(--accent-cyan);
    background: rgba(6,182,212,0.1);
    padding: 3px 10px;
    border-radius: 6px;
    display: inline-block;
    margin-bottom: 12px;
}

/* ── Status Indicators ─────────────────────────── */
.status-dot {
    display: inline-block;
    width: 10px; height: 10px;
    border-radius: 50%;
    margin-right: 8px;
}
.status-running {
    background: var(--accent-green);
    box-shadow: 0 0 8px rgba(34,197,94,0.5);
    animation: pulse-dot 2s ease-in-out infinite;
}
.status-stopped {
    background: var(--text-muted);
}
@keyframes pulse-dot {
    0%, 100% { box-shadow: 0 0 4px rgba(34,197,94,0.3); }
    50% { box-shadow: 0 0 12px rgba(34,197,94,0.6); }
}

/* ── Hero Section ──────────────────────────────── */
.hero-title {
    font-size: 48px;
    font-weight: 900;
    background: var(--gradient-hero);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    text-align: center;
    margin-bottom: 0;
    letter-spacing: -1px;
}
.hero-subtitle {
    font-size: 16px;
    color: var(--text-secondary);
    text-align: center;
    margin-top: 4px;
    letter-spacing: 2px;
    text-transform: uppercase;
}

/* ── System Metrics ────────────────────────────── */
.metric-bar-container {
    background: rgba(255,255,255,0.05);
    border-radius: 8px;
    height: 8px;
    overflow: hidden;
    margin: 4px 0 8px;
}
.metric-bar {
    height: 100%;
    border-radius: 8px;
    transition: width 0.6s ease;
}

/* ── Buttons ───────────────────────────────────── */
.stButton > button {
    border-radius: 12px !important;
    font-weight: 600 !important;
    transition: all 0.3s ease !important;
    border: 1px solid var(--border-glass) !important;
}
.stButton > button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 6px 20px rgba(79,143,255,0.15) !important;
}

/* ── Scrollbar ─────────────────────────────────── */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(79,143,255,0.2); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: rgba(79,143,255,0.4); }

/* ── Category Label ────────────────────────────── */
.category-label {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: var(--text-muted);
    margin-bottom: 16px;
    padding-left: 4px;
}
</style>
""", unsafe_allow_html=True)


# ── Session State Init ──────────────────────────────────────────────
if "pids" not in st.session_state:
    st.session_state.pids = {}
if "messages" not in st.session_state:
    st.session_state.messages = []


def add_message(msg: str, level: str = "info"):
    ts = datetime.now().strftime("%H:%M:%S")
    st.session_state.messages.append({"ts": ts, "msg": msg, "level": level})
    if len(st.session_state.messages) > 50:
        st.session_state.messages = st.session_state.messages[-50:]


# ── Load Data ───────────────────────────────────────────────────────
config = load_hub_config()
services = get_services(config)
metrics = get_system_metrics()

# ── Hero Header ─────────────────────────────────────────────────────
st.markdown('<p class="hero-title">🏛️ Atlas Command Hub</p>', unsafe_allow_html=True)
st.markdown('<p class="hero-subtitle">Unified Service Dashboard</p>', unsafe_allow_html=True)
st.markdown("<br>", unsafe_allow_html=True)

# ── System Metrics Bar ──────────────────────────────────────────────
met_cols = st.columns(4)

def metric_color(pct):
    if pct > 85: return "#ef4444"
    if pct > 60: return "#f59e0b"
    return "#22c55e"

with met_cols[0]:
    c = metric_color(metrics["cpu_pct"])
    st.markdown(f"""<div style="text-align:center">
        <span style="font-size:12px;color:var(--text-secondary)">🖥️ CPU</span><br>
        <span style="font-size:24px;font-weight:800;color:{c}">{metrics['cpu_pct']}%</span>
        <div class="metric-bar-container"><div class="metric-bar" style="width:{metrics['cpu_pct']}%;background:{c}"></div></div>
    </div>""", unsafe_allow_html=True)

with met_cols[1]:
    c = metric_color(metrics["ram_pct"])
    st.markdown(f"""<div style="text-align:center">
        <span style="font-size:12px;color:var(--text-secondary)">🧠 RAM</span><br>
        <span style="font-size:24px;font-weight:800;color:{c}">{metrics['ram_used_gb']}/{metrics['ram_total_gb']}GB</span>
        <div class="metric-bar-container"><div class="metric-bar" style="width:{metrics['ram_pct']}%;background:{c}"></div></div>
    </div>""", unsafe_allow_html=True)

with met_cols[2]:
    c = metric_color(metrics["disk_pct"])
    st.markdown(f"""<div style="text-align:center">
        <span style="font-size:12px;color:var(--text-secondary)">💾 Disk</span><br>
        <span style="font-size:24px;font-weight:800;color:{c}">{metrics['disk_used_gb']}/{metrics['disk_total_gb']}GB</span>
        <div class="metric-bar-container"><div class="metric-bar" style="width:{metrics['disk_pct']}%;background:{c}"></div></div>
    </div>""", unsafe_allow_html=True)

with met_cols[3]:
    st.markdown(f"""<div style="text-align:center">
        <span style="font-size:12px;color:var(--text-secondary)">🎮 GPU</span><br>
        <span style="font-size:14px;font-weight:600;color:var(--accent-purple)">{metrics['gpu_name']}</span>
    </div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── Service Cards Grid ──────────────────────────────────────────────
# Group services by category
categories = {}
for key, svc in services.items():
    cat = svc.get("category", "General")
    if cat not in categories:
        categories[cat] = []
    categories[cat].append((key, svc))

for cat_name, cat_services in categories.items():
    st.markdown(f'<div class="category-label">{cat_name}</div>', unsafe_allow_html=True)

    cols = st.columns(min(len(cat_services), 3))

    for idx, (key, svc) in enumerate(cat_services):
        col = cols[idx % len(cols)]
        port = svc["port"]
        alive = is_port_alive(port)
        status_class = "status-running" if alive else "status-stopped"
        status_text = "Running" if alive else "Stopped"
        status_color = "#22c55e" if alive else "#55556e"

        with col:
            st.markdown(f"""
            <div class="service-card">
                <div class="service-icon">{svc.get('icon', '📦')}</div>
                <div class="service-name">{svc['name']}</div>
                <div class="service-desc">{svc.get('description', '')}</div>
                <div class="service-port">:{port}</div>
                <div style="margin-top:8px">
                    <span class="status-dot {status_class}"></span>
                    <span style="font-size:13px;color:{status_color};font-weight:600">{status_text}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # Action buttons
            btn_cols = st.columns(3)
            with btn_cols[0]:
                if alive:
                    if st.button("⏹️ Stop", key=f"stop_{key}", use_container_width=True):
                        ok, msg = stop_service(key, svc)
                        add_message(f"{'✅' if ok else '❌'} {svc['name']}: {msg}",
                                    "success" if ok else "error")
                        time.sleep(1)
                        st.rerun()
                else:
                    if st.button("▶️ Start", key=f"start_{key}", use_container_width=True):
                        ok, msg = start_service(key, svc)
                        add_message(f"{'✅' if ok else '❌'} {svc['name']}: {msg}",
                                    "success" if ok else "error")
                        time.sleep(2)
                        st.rerun()

            with btn_cols[1]:
                if alive:
                    st.link_button("🔗 Open", f"http://localhost:{port}", use_container_width=True)
                else:
                    st.button("🔗 Open", key=f"open_{key}", disabled=True, use_container_width=True)

            with btn_cols[2]:
                if st.button("🔄", key=f"refresh_{key}", use_container_width=True):
                    st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)


# ── Messaging Status ───────────────────────────────────────────────
st.markdown("---")
st.markdown('<div class="category-label">📡 Messaging Integrations</div>', unsafe_allow_html=True)

msg_cols = st.columns(3)

with msg_cols[0]:
    # Discord (existing)
    discord_token = os.getenv("DISCORD_BOT_TOKEN", "")
    discord_status = "✅ Configured" if discord_token else "❌ Not configured"
    st.markdown(f"""<div class="service-card" style="padding:20px">
        <div style="font-size:28px;margin-bottom:8px">💬</div>
        <div class="service-name" style="font-size:15px">Discord Bot</div>
        <div style="font-size:12px;color:{'#22c55e' if discord_token else '#ef4444'}">{discord_status}</div>
        <div style="font-size:11px;color:var(--text-muted);margin-top:4px">atlas_vps_commander.py</div>
    </div>""", unsafe_allow_html=True)

with msg_cols[1]:
    # Telegram
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    tg_status = "✅ Configured" if tg_token else "⚠️ Token needed"
    st.markdown(f"""<div class="service-card" style="padding:20px">
        <div style="font-size:28px;margin-bottom:8px">🤖</div>
        <div class="service-name" style="font-size:15px">Telegram Bot</div>
        <div style="font-size:12px;color:{'#22c55e' if tg_token else '#f59e0b'}">{tg_status}</div>
        <div style="font-size:11px;color:var(--text-muted);margin-top:4px">atlas_telegram_bot.py</div>
    </div>""", unsafe_allow_html=True)

with msg_cols[2]:
    # WhatsApp
    wa_token = os.getenv("WHATSAPP_TOKEN", "")
    wa_status = "✅ Configured" if wa_token else "⚠️ Token needed"
    st.markdown(f"""<div class="service-card" style="padding:20px">
        <div style="font-size:28px;margin-bottom:8px">📱</div>
        <div class="service-name" style="font-size:15px">WhatsApp Alerts</div>
        <div style="font-size:12px;color:{'#22c55e' if wa_token else '#f59e0b'}">{wa_status}</div>
        <div style="font-size:11px;color:var(--text-muted);margin-top:4px">atlas_whatsapp_notifier.py</div>
    </div>""", unsafe_allow_html=True)


# ── Data Pipeline ───────────────────────────────────────────────────
st.markdown("---")
st.markdown('<div class="category-label">🧹 Data Pipeline</div>', unsafe_allow_html=True)

pipe_cols = st.columns(3)
with pipe_cols[0]:
    st.markdown(f"""<div class="service-card" style="padding:20px">
        <div style="font-size:28px;margin-bottom:8px">🧠</div>
        <div class="service-name" style="font-size:15px">AI Purifier</div>
        <div style="font-size:12px;color:var(--text-secondary)">Process Discord chats into Golden Rules</div>
        <div style="font-size:11px;color:var(--text-muted);margin-top:4px">knowledge_builder.py</div>
    </div>""", unsafe_allow_html=True)
    
    if st.button("▶️ Run Purifier Now", use_container_width=True):
        # Get the python executable
        venv_python = sys.executable
        log_file = PROJECT_ROOT / "outputs" / "purifier.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(log_file, "w", encoding="utf-8") as f:
                subprocess.Popen(
                    [venv_python, "src/purify/knowledge_builder.py", "--dir", "discord", "--sync"],
                    stdout=f, 
                    stderr=subprocess.STDOUT,
                    cwd=str(PROJECT_ROOT)
                )
            add_message("✅ AI Purifier started in background. Check outputs/purifier.log", "success")
            st.toast("Purifier started asynchronously! 🚀")
        except Exception as e:
            add_message(f"❌ Purifier Error: {e}", "error")
            st.error(f"Error: {e}", icon="❌")

# ── Activity Log ────────────────────────────────────────────────────
if st.session_state.messages:
    st.markdown("---")
    st.markdown('<div class="category-label">📋 Activity Log</div>', unsafe_allow_html=True)
    for msg_entry in reversed(st.session_state.messages[-10:]):
        icon = {"success": "✅", "error": "❌", "info": "ℹ️"}.get(msg_entry["level"], "ℹ️")
        st.caption(f"`{msg_entry['ts']}` {icon} {msg_entry['msg']}")


# ── Footer ──────────────────────────────────────────────────────────
st.markdown("---")
st.markdown(f"""<div style="text-align:center;color:var(--text-muted);font-size:12px;padding:16px 0">
    Atlas Command Hub v1.0 · {datetime.now().strftime('%Y-%m-%d %H:%M')} · Port 8500
</div>""", unsafe_allow_html=True)

# ── Auto Refresh ────────────────────────────────────────────────────
refresh_sec = config.get("hub", {}).get("auto_refresh_sec", 5)
