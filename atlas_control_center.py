"""
Atlas Control Center — Unified Command Dashboard
==================================================
A Streamlit-based dashboard for managing the entire Atlas OCR pipeline.
Run locally: streamlit run atlas_control_center.py
"""

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    import paramiko
    HAS_PARAMIKO = True
except ImportError:
    HAS_PARAMIKO = False

# ── Config ──────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent
VPS_IP = os.getenv("SERVER_IPV4", "157.245.186.95").strip().strip('"')
VPS_USER = "root"
VPS_PROJECT_DIR = "/root/OCR_annotation_Atlas"
QUEUE_FILE = PROJECT_ROOT / "questions_queue.json"

# ── Sidebar Health Check ────────────────────────────────────────────
def check_vps_status():
    """Quick ping/ssh test for the VPS."""
    if not HAS_PARAMIKO:
        return "⚠️ Error: paramiko not installed", "status-err"
    
    # Try a very fast SSH connect
    try:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2.0)
            if s.connect_ex((VPS_IP, 22)) == 0:
                return f"✅ VPS Online: {VPS_IP}", "status-ok"
            else:
                return f"❌ VPS Offline: {VPS_IP}", "status-err"
    except Exception as e:
        return f"❌ Connection Error: {e}", "status-err"

# ── Page Setup ──────────────────────────────────────────────────────
st.set_page_config(
    page_title="Atlas Control Center",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

with st.sidebar:
    st.image("https://img.icons8.com/isometric/100/control-panel.png", width=80)
    st.title("Atlas Sidebar")
    
    st.markdown("### 🌐 Server Status")
    status_msg, status_class = check_vps_status()
    st.markdown(f'<p class="{status_class}">{status_msg}</p>', unsafe_allow_html=True)
    
    st.divider()
    st.markdown("### 🛠️ Quick Actions")
    if st.button("🔄 Rerun Dashboard"):
        st.rerun()

# ── Custom Styling ──────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
* { font-family: 'Inter', sans-serif; }
.main { background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%); }
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%);
}
h1 { 
    background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    font-weight: 700;
}
h2, h3 {
    color: #a78bfa;
}
.stButton > button {
    border-radius: 12px;
    font-weight: 600;
    padding: 0.6rem 1.2rem;
    transition: all 0.3s ease;
    border: 1px solid rgba(167, 139, 250, 0.3);
}
.stButton > button:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 25px rgba(102, 126, 234, 0.3);
}
div[data-testid="stExpander"] {
    border: 1px solid rgba(167, 139, 250, 0.2);
    border-radius: 12px;
}
.log-terminal {
    background: #0d1117;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 16px;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 13px;
    color: #c9d1d9;
    max-height: 500px;
    overflow-y: auto;
}
.status-ok { color: #3fb950; font-weight: 600; }
.status-err { color: #f85149; font-weight: 600; }
.status-warn { color: #d29922; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

# ── Session State Init ──────────────────────────────────────────────
if "log_lines" not in st.session_state:
    st.session_state.log_lines = ["[system] Atlas Control Center ready. Waiting for commands..."]
if "cmd_running" not in st.session_state:
    st.session_state.cmd_running = False


def append_log(line: str):
    """Add a line to the session log."""
    ts = datetime.now().strftime("%H:%M:%S")
    st.session_state.log_lines.append(f"[{ts}] {line}")
    # Keep last 500 lines
    if len(st.session_state.log_lines) > 500:
        st.session_state.log_lines = st.session_state.log_lines[-500:]


def run_local_cmd(cmd: list, label: str = "", timeout: int = 300, placeholder=None):
    """Run a local command and yield output to the log in real-time."""
    import time
    append_log(f"🖥️ LOCAL: {label or ' '.join(cmd)}")
    
    # Use Popen to stream output
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(PROJECT_ROOT),
            encoding="utf-8",
            errors="replace",
            bufsize=1
        )
        
        start_time = time.time()
        output_full = []
        
        # Read output line-by-line
        while True:
            # Check for timeout
            if (time.time() - start_time) > timeout:
                process.terminate()
                append_log(f"⏰ {label or 'Command'} timed out ({timeout}s).")
                return False, "Timeout"
                
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                clean = line.rstrip()
                output_full.append(clean)
                append_log(f"  {clean}")
                
                # If a placeholder was provided, update it real-time in the UI
                if placeholder:
                    with placeholder.container():
                        st.text("\n".join(output_full[-10:])) # Show last 10 lines
        
        exit_code = process.poll()
        output = "\n".join(output_full)
        
        if exit_code == 0:
            append_log(f"✅ {label or 'Command'} completed successfully.")
        else:
            append_log(f"❌ {label or 'Command'} failed (exit {exit_code}).")
        return exit_code == 0, output
        
    except Exception as e:
        append_log(f"❌ Error: {e}")
        return False, str(e)


def run_vps_cmd(cmd: str, label: str = "", timeout: int = 300):
    """Run a command on the VPS via SSH and return output."""
    if not HAS_PARAMIKO:
        append_log("❌ paramiko not installed. Run: pip install paramiko")
        return False, "paramiko not installed"

    append_log(f"☁️ VPS: {label or cmd}")
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        # Try key-based auth first, then password
        try:
            ssh.connect(VPS_IP, username=VPS_USER, timeout=10)
        except Exception:
            vps_pass = os.getenv("VPS_PASS", os.getenv("DIGITALOCEAN_PASSWORD", "0Ak@1593570$$$0A"))
            if vps_pass:
                ssh.connect(VPS_IP, username=VPS_USER, password=vps_pass, timeout=10)
            else:
                ssh.connect(VPS_IP, username=VPS_USER, timeout=10)

        full_cmd = f"cd {VPS_PROJECT_DIR} && {cmd}"
        stdin, stdout, stderr = ssh.exec_command(full_cmd, timeout=timeout, get_pty=True)

        output_lines = []
        for line in stdout:
            clean = line.rstrip()
            output_lines.append(clean)
            append_log(f"  {clean}")

        err = stderr.read().decode("utf-8", errors="replace").strip()
        if err:
            for line in err.splitlines():
                append_log(f"  ⚠ {line}")

        exit_code = stdout.channel.recv_exit_status()
        ssh.close()

        output = "\n".join(output_lines)
        if exit_code == 0:
            append_log(f"✅ {label or 'VPS Command'} completed.")
        else:
            append_log(f"❌ {label or 'VPS Command'} failed (exit {exit_code}).")
        return exit_code == 0, output

    except Exception as e:
        append_log(f"❌ SSH Error: {e}")
        return False, str(e)


# ══════════════════════════════════════════════════════════════════════
# HEADER
# ══════════════════════════════════════════════════════════════════════
st.title("🏛️ Atlas Control Center")
st.caption(f"VPS: `{VPS_IP}` · Project: `{VPS_PROJECT_DIR}` · Local: `{PROJECT_ROOT}`")

# ══════════════════════════════════════════════════════════════════════
# SIDEBAR — Status & Quick Info
# ══════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.header("📊 System Status")

    # Build version
    try:
        solver_text = (PROJECT_ROOT / "atlas_web_auto_solver.py").read_text(encoding="utf-8", errors="replace")
        import re
        build_match = re.search(r'_SCRIPT_BUILD\s*=\s*"([^"]+)"', solver_text)
        build_ver = build_match.group(1) if build_match else "unknown"
    except Exception:
        build_ver = "unknown"
    st.metric("Build Version", build_ver)

    # Questions queue
    try:
        queue = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
        pending = sum(1 for q in queue if q.get("status") == "pending")
        sent = sum(1 for q in queue if q.get("status") == "sent")
        answered = sum(1 for q in queue if q.get("status") == "answered")
    except Exception:
        pending, sent, answered = 0, 0, 0
    
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Pending", pending)
    col_b.metric("Sent", sent)
    col_c.metric("Answered", answered)

    st.divider()
    st.header("🔗 Quick Links")
    st.markdown("[Atlas Platform](https://audit.atlascapture.io/dashboard)")
    st.markdown("[GitHub Repo](https://github.com/aymank2020/OCR_Annotation_Atlas)")
    st.markdown(f"[Discord #LEVEL3_QUESTION](https://discord.com/channels/{os.getenv('DISCORD_GUILD_ID', '')}/{os.getenv('LEVEL3_QUESTION', '')})")

# ══════════════════════════════════════════════════════════════════════
# MAIN TABS
# ══════════════════════════════════════════════════════════════════════
tab_deploy, tab_solver, tab_discord, tab_tools, tab_logs = st.tabs([
    "🚀 Deploy & Sync",
    "🤖 Solver Control",
    "💬 Discord Questions",
    "🔧 Tools & Utils",
    "📋 Live Logs",
])

# ────────────────────────────────────────────────────────────────────
# TAB 1: Deploy & Sync
# ────────────────────────────────────────────────────────────────────
with tab_deploy:
    st.subheader("🚀 Deployment & Synchronization")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### 💻 Local (Windows)")

        if st.button("📤 Git Push to GitHub", key="git_push", use_container_width=True):
            run_local_cmd(["git", "add", "."], "Git Add")
            run_local_cmd(["git", "commit", "-m", f"update from control center {datetime.now().strftime('%H:%M')}"], "Git Commit")
            run_local_cmd(["git", "push", "origin", "main"], "Git Push")

        if st.button("📊 Git Status", key="git_status", use_container_width=True):
            run_local_cmd(["git", "status", "--short"], "Git Status")

        if st.button("📜 Git Log (last 5)", key="git_log", use_container_width=True):
            run_local_cmd(["git", "log", "--oneline", "-5"], "Git Log")

    with col2:
        st.markdown("#### ☁️ VPS (Ubuntu)")

        if st.button("🔄 Pull Updates on VPS", key="vps_pull", use_container_width=True):
            run_vps_cmd("git reset --hard origin/main && git pull origin main", "VPS Git Pull")

        if st.button("🔍 Check Build Version on VPS", key="vps_build", use_container_width=True):
            run_vps_cmd('grep "_SCRIPT_BUILD =" atlas_web_auto_solver.py', "Check Build")

        if st.button("💾 Check Disk Space", key="vps_disk", use_container_width=True):
            run_vps_cmd("df -h / && echo '---' && du -sh outputs/", "Disk Space")

# ────────────────────────────────────────────────────────────────────
# TAB 2: Solver Control
# ────────────────────────────────────────────────────────────────────
with tab_solver:
    st.subheader("🤖 Atlas Auto-Solver")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### ▶️ Run Solver")

        episodes = st.number_input("Max Episodes", min_value=1, max_value=50, value=1, key="episodes")

        if st.button("🧪 Run Test (Dry Run)", key="run_dry", use_container_width=True, type="secondary"):
            run_vps_cmd(
                f"xvfb-run python atlas_web_auto_solver.py --config sample_web_auto_solver_production.yaml --max-episodes {episodes}",
                f"Dry Run ({episodes} episodes)",
            )

        if st.button("🚀 Run Production (Execute)", key="run_prod", use_container_width=True, type="primary"):
            run_vps_cmd(
                f"nohup xvfb-run python atlas_web_auto_solver.py --config sample_web_auto_solver_production.yaml --execute --max-episodes {episodes} > production.log 2>&1 &",
                f"Production Run ({episodes} episodes) — background",
            )
            append_log("💡 Process running in background. Use 'View Production Log' to monitor.")

        if st.button("🛑 Stop Solver", key="stop_solver", use_container_width=True):
            run_vps_cmd("pkill -f 'atlas_web_auto_solver' || echo 'No solver process found'", "Stop Solver")

    with col2:
        st.markdown("#### 📊 Monitor")

        if st.button("📋 View Production Log (last 80)", key="view_log", use_container_width=True):
            run_vps_cmd("tail -n 80 production.log 2>/dev/null || echo 'No production.log found'", "Production Log")

        if st.button("🔎 Check Solver Status", key="check_status", use_container_width=True):
            run_vps_cmd("ps aux | grep atlas_web_auto_solver | grep -v grep || echo 'Solver is NOT running'", "Solver Status")

        if st.button("📈 Latest Validation Report", key="val_report", use_container_width=True):
            run_vps_cmd("ls -t outputs/validation_*.json 2>/dev/null | head -1 | xargs cat 2>/dev/null || echo 'No validation reports'", "Validation Report")

        if st.button("🏷️ Latest Labels", key="labels", use_container_width=True):
            run_vps_cmd("ls -t outputs/labels_*.json 2>/dev/null | head -1 | xargs cat 2>/dev/null || echo 'No labels'", "Latest Labels")

# ────────────────────────────────────────────────────────────────────
# TAB 3: Discord Questions
# ────────────────────────────────────────────────────────────────────
with tab_discord:
    st.subheader("💬 Discord Question Manager")

    # Show current queue
    try:
        queue = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
    except Exception:
        queue = []

    if queue:
        for i, q in enumerate(queue):
            status_icon = {"pending": "⏳", "sent": "📤", "answered": "✅"}.get(q.get("status", ""), "❓")
            with st.expander(f"{status_icon} [{q.get('status', '?').upper()}] {q.get('rule_topic', 'Unknown')}"):
                st.text(q.get("question", q.get("question_text", "")))
                if q.get("admin_reply"):
                    st.success(f"**Admin Reply:** {q['admin_reply']}")

    st.divider()
    st.markdown("#### ➕ Add New Question")

    new_topic = st.text_input("Topic", placeholder="e.g., Dough rolling body-part rules", key="q_topic")
    new_question = st.text_area(
        "Question Text",
        height=200,
        placeholder="Type your question for the #LEVEL3_QUESTION channel...",
        key="q_text",
        value="""Hi team, I need clarification on a specific labeling scenario for a Tier-3 task.

**Video context:** The entire 100s video shows a person repeatedly picking up pieces of dough from a tray, splitting them, rolling them into strips (using their hands/palms), and placing them back in the tray. This cycle repeats ~27 times with no tool changes or goal changes.

**Current employee labels use:** "pick up split dough, roll split dough between palms to form a strip, place stripped dough in tray"

**My questions:**

1. **Body parts:** The phrase "between palms" appears 18+ times. Should we remove ALL body-part references and just say "roll dough"?

2. **Max actions per label:** Many segments have 3 actions (pick up, roll, place). Should we keep all 3 or limit to 2?

3. **Intent language:** Should "to form a strip" be removed as intent language?

4. **Over-segmentation:** Since this is the same repeating action for 100 seconds, should it be fewer coarse segments?

Thanks for any guidance!""",
    )

    if st.button("💾 Add to Queue", key="add_q", use_container_width=True):
        if new_topic and new_question:
            new_item = {
                "rule_topic": new_topic,
                "question": new_question,
                "question_text": new_question,
                "context": "Added from Atlas Control Center",
                "source_type": "control_center",
                "source_reference": "",
                "status": "pending",
                "timestamp": int(time.time()),
                "id": f"cc_{int(time.time())}",
            }
            queue.append(new_item)
            QUEUE_FILE.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")
            append_log(f"💬 Added question to queue: {new_topic}")
            st.success(f"✅ Question added! Total queue: {len(queue)}")
            st.rerun()
        else:
            st.warning("Please fill in both Topic and Question.")

    st.divider()
    st.markdown("#### 📤 Dispatch Questions to Discord")
    st.caption("⚠️ Requires Chrome running with Discord open (Run_Atlas_Chrome.bat)")

    if st.button("🌐 Start Atlas Chrome Session", key="run_chrome", use_container_width=True):
        run_local_cmd(["cmd.exe", "/c", "start", "Run_Atlas_Chrome.bat"], "Launch Atlas Chrome")

    if st.button("📤 Send Pending Questions (Dry Run)", key="dispatch_dry", use_container_width=True):
        run_local_cmd(["python", "atlas_question_dispatcher.py", "--dry-run", "--max", "1"], "Discord Dispatch (Dry)")

    if st.button("📤 Send Questions (LIVE)", key="dispatch_live", use_container_width=True, type="primary"):
        run_local_cmd(["python", "atlas_question_dispatcher.py", "--max", "1", "--wait", "5"], "Discord Dispatch (Live)")

    if st.button("📥 Harvest Admin Replies Only", key="harvest", use_container_width=True):
        run_local_cmd(["python", "atlas_question_dispatcher.py", "--harvest-only"], "Harvest Discord Replies")

    st.divider()
    st.markdown("#### 📥 Download Full Chat History")
    st.caption("Pull all messages within a specific date range and save to JSON for AI Purification.")
    
    col_from, col_to = st.columns(2)
    with col_from:
        harvest_from = st.date_input("From Date:", datetime.today() - timedelta(days=7))
    with col_to:
        harvest_to = st.date_input("To Date (End):", datetime.today())
        
    if st.button("💾 Download Chat Range to JSON", key="harvest_full", use_container_width=True, type="secondary"):
        f_str = harvest_from.strftime("%Y-%m-%d")
        t_str = harvest_to.strftime("%Y-%m-%d")
        range_label = f"{f_str}_to_{t_str}"
        
        with st.spinner(f"📥 Downloading Discord chat from {f_str} to {t_str}... Please wait (takes ~1 sec per 100 messages)."):
            cmd = ["python", "atlas_question_dispatcher.py", "--pull-chat-since", f_str, "--pull-chat-until", t_str]
            success, out = run_local_cmd(cmd, f"Harvest Chat ({range_label})", timeout=1200)
            
        if success:
            st.success(f"✅ Chat downloaded successfully! Check the 'discord' folder for harvest_{range_label}.json")
            st.toast(f"✅ Chat Harvest Complete!", icon="🎉")
        else:
            st.error("❌ Failed to download chat. Check recent activity logs.")

    st.divider()
    st.markdown("#### 🧠 Local AI Purification")
    st.caption("Process newly downloaded chat logs locally to extract Golden Rules.")
    
    if st.button("🧹 Run AI Purifier (Local)", key="run_purifier_local", use_container_width=True, type="primary"):
        status_area = st.empty()
        with st.spinner("✨ AI is distilling knowledge from local chat logs..."):
            success, out = run_local_cmd(["python", "src/purify/knowledge_builder.py"], "Local AI Purifier", timeout=3600, placeholder=status_area)
        status_area.empty()
        if success:
            st.success("✅ Knowledge distilled and added to atlas_vertex_context_pack.txt!")
            st.toast("✅ Knowledge Base Updated!", icon="🧠")
        else:
            st.error("❌ AI Purification failed. Is your GEMINI_API_KEY set?")

# ────────────────────────────────────────────────────────────────────
# TAB 4: Tools & Utils
# ────────────────────────────────────────────────────────────────────
with tab_tools:
    st.subheader("🔧 Utility Tools")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### 📥 Download from VPS")

        if st.button("📥 Download Latest Video", key="dl_video", use_container_width=True):
            run_vps_cmd(
                "ls -t outputs/video_*.mp4 2>/dev/null | head -1",
                "Find Latest Video",
            )
            append_log("💡 Use SCP to download: scp root@" + VPS_IP + ":~/OCR_annotation_Atlas/outputs/<filename> ./outputs/")

        if st.button("📥 Download Latest Outputs", key="dl_outputs", use_container_width=True):
            run_vps_cmd("ls -lt outputs/ | head -15", "List Latest Outputs")

        if st.button("✂️ Cut Video Clip (first 15s)", key="cut_video", use_container_width=True):
            run_vps_cmd(
                "LATEST=$(ls -t outputs/video_*.mp4 2>/dev/null | head -1) && "
                "ffmpeg -y -i \"$LATEST\" -t 15 -c copy outputs/clip_15s.mp4 2>&1 | tail -5 && "
                "echo \"Clip saved: outputs/clip_15s.mp4\" && ls -lh outputs/clip_15s.mp4",
                "Cut 15s Video Clip",
            )

    with col2:
        st.markdown("#### 🛠️ VPS Maintenance")

        if st.button("🧹 Clean Old Outputs (>7 days)", key="clean_outputs", use_container_width=True):
            run_vps_cmd(
                "find outputs/ -name '*.json' -mtime +7 -delete 2>/dev/null; "
                "find outputs/ -name '*.txt' -mtime +7 -delete 2>/dev/null; "
                "echo 'Cleaned old output files'",
                "Clean Old Outputs",
            )

        if st.button("📊 System Resources", key="sys_res", use_container_width=True):
            run_vps_cmd("free -h && echo '---' && uptime", "System Resources")

        if st.button("🔑 Test SSH Connection", key="test_ssh", use_container_width=True):
            run_vps_cmd("echo 'SSH OK' && hostname && uname -a", "Test SSH")

    st.divider()
    st.markdown("#### 🖥️ Custom Command")

    cmd_target = st.radio("Run on:", ["VPS", "Local"], horizontal=True, key="cmd_target")
    custom_cmd = st.text_input("Command:", placeholder="e.g., tail -n 20 production.log", key="custom_cmd")

    if st.button("▶️ Execute", key="exec_custom", use_container_width=True):
        if custom_cmd:
            if cmd_target == "VPS":
                run_vps_cmd(custom_cmd, f"Custom: {custom_cmd[:60]}")
            else:
                # Split for local
                import shlex
                try:
                    parts = shlex.split(custom_cmd)
                except ValueError:
                    parts = custom_cmd.split()
                run_local_cmd(parts, f"Custom: {custom_cmd[:60]}")

# ────────────────────────────────────────────────────────────────────
# TAB 5: Live Logs
# ────────────────────────────────────────────────────────────────────
with tab_logs:
    st.subheader("📋 Live Terminal Logs")

    col_btn1, col_btn2 = st.columns([1, 5])
    with col_btn1:
        if st.button("🗑️ Clear Logs", key="clear_logs"):
            st.session_state.log_lines = ["[system] Logs cleared."]
            st.rerun()

    # Render logs
    log_text = "\n".join(st.session_state.log_lines[-200:])
    st.code(log_text, language="bash", line_numbers=False)

# ══════════════════════════════════════════════════════════════════════
# BOTTOM LOG BAR — Always visible
# ══════════════════════════════════════════════════════════════════════
st.divider()
with st.expander("🖥️ Recent Activity (click to expand)", expanded=False):
    recent = st.session_state.log_lines[-15:]
    st.code("\n".join(recent), language="bash")
