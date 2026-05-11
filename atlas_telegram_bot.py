"""
Atlas Telegram Bot — Remote VPS Control
==========================================
Telegram bot for controlling Atlas pipeline on the VPS.
Supports: /status, /pull, /logs, /run, /stop, /help

Setup:
  1. Create bot via @BotFather on Telegram
  2. Set TELEGRAM_BOT_TOKEN in .env
  3. Set TELEGRAM_ALLOWED_CHATS in .env (comma-separated chat IDs)
  4. pip install python-telegram-bot
  5. python atlas_telegram_bot.py

Security: Only responds to whitelisted chat IDs.
"""

import os
import sys
import subprocess
import logging
from pathlib import Path
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Config ──────────────────────────────────────────────────────────
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_CHATS = [
    int(x.strip()) for x in os.getenv("TELEGRAM_ALLOWED_CHATS", "").split(",")
    if x.strip().lstrip("-").isdigit()
]
PROJECT_ROOT = Path(__file__).parent
VPS_PROJECT_DIR = "/root/OCR_annotation_Atlas"

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("telegram-bot")


# ── Shell Helpers ───────────────────────────────────────────────────
def run_cmd(cmd: str, timeout: int = 60) -> str:
    """Run a shell command and return output."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=str(PROJECT_ROOT),
            encoding="utf-8", errors="replace",
        )
        output = (result.stdout or "") + (result.stderr or "")
        return output.strip()[:3000]  # Telegram message limit ~4096
    except subprocess.TimeoutExpired:
        return "⏰ Command timed out"
    except Exception as e:
        return f"❌ Error: {e}"


# ── Command Handlers ────────────────────────────────────────────────
async def cmd_help(update, context):
    """Show available commands."""
    help_text = """🏛️ *Atlas VPS Commander*

Available commands:

📊 `/status` — System status (disk, memory, uptime, solver)
🔄 `/pull` — Git pull latest code from GitHub
📋 `/logs [N]` — Show last N lines of production.log (default: 30)
🚀 `/run [episodes]` — Start solver (default: 1 episode)
🛑 `/stop` — Stop running solver
🔍 `/check` — Check if solver process is running
💾 `/disk` — Disk usage breakdown
🆘 `/help` — Show this message

_Only authorized users can use this bot._"""
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def cmd_status(update, context):
    """Show VPS / System status."""
    await update.message.reply_text("⏳ Gathering status...")

    if sys.platform == "win32":
        output = run_cmd(
            "echo 📊 System Status && echo ═══════════════ && "
            "echo. && echo 💾 Disk: && wmic logicaldisk get size,freespace,caption | findstr /V Size && "
            "echo. && echo 🧠 Memory: && wmic OS get FreePhysicalMemory,TotalVisibleMemorySize /Value && "
            "echo. && echo 🤖 Solver: && "
            "(tasklist /FI \"IMAGENAME eq python.exe\" /V | findstr atlas_web_auto_solver || echo Not running) && "
            "echo. && echo 📦 Git: && git log --oneline -1"
        )
    else:
        output = run_cmd(
            "echo '📊 System Status' && echo '═══════════════' && "
            "echo '' && echo '💾 Disk:' && df -h / | tail -1 && "
            "echo '' && echo '🧠 Memory:' && free -h | head -2 && "
            "echo '' && echo '⏱️ Uptime:' && uptime && "
            "echo '' && echo '🤖 Solver:' && "
            "(ps aux | grep atlas_web_auto_solver | grep -v grep | head -1 || echo 'Not running') && "
            "echo '' && echo '📦 Git:' && git log --oneline -1"
        )
    await update.message.reply_text(f"```\n{output}\n```", parse_mode="Markdown")


async def cmd_pull(update, context):
    """Git pull on VPS."""
    await update.message.reply_text("⏳ Running git pull...")
    output = run_cmd("git pull origin main 2>&1")
    await update.message.reply_text(f"🔄 Git Pull:\n```\n{output}\n```", parse_mode="Markdown")


async def cmd_logs(update, context):
    """Show production log tail."""
    n = 30
    if context.args:
        try:
            n = min(int(context.args[0]), 100)
        except ValueError:
            pass

    await update.message.reply_text(f"⏳ Fetching last {n} log lines...")
    output = run_cmd(f"tail -n {n} production.log 2>/dev/null || echo 'No production.log found'")
    # Split into chunks if too long
    if len(output) > 3500:
        output = output[-3500:]
    await update.message.reply_text(f"📋 Logs ({n} lines):\n```\n{output}\n```", parse_mode="Markdown")


async def cmd_run(update, context):
    """Start solver in background."""
    episodes = 1
    if context.args:
        try:
            episodes = min(int(context.args[0]), 20)
        except ValueError:
            pass

    await update.message.reply_text(f"🚀 Starting solver for {episodes} episodes...")
    if sys.platform == "win32":
        output = run_cmd(
            f"start /b python atlas_web_auto_solver.py "
            f"--config sample_web_auto_solver_production.yaml "
            f"--execute --max-episodes {episodes} "
            f"> production.log 2>&1"
            f" && echo Solver started in background"
        )
    else:
        output = run_cmd(
            f"nohup xvfb-run python atlas_web_auto_solver.py "
            f"--config sample_web_auto_solver_production.yaml "
            f"--execute --max-episodes {episodes} "
            f"> production.log 2>&1 &"
            f" && echo 'Solver started in background (PID: '$(pgrep -f atlas_web_auto_solver)')'"
        )
    await update.message.reply_text(f"```\n{output}\n```", parse_mode="Markdown")


async def cmd_stop(update, context):
    """Stop solver process."""
    await update.message.reply_text("🛑 Stopping solver...")
    if sys.platform == "win32":
        output = run_cmd("taskkill /F /IM python.exe /FI \"WINDOWTITLE eq atlas_web_auto_solver*\" && echo ✅ Solver stopped || echo No solver process found")
    else:
        output = run_cmd("pkill -f 'atlas_web_auto_solver' && echo '✅ Solver stopped' || echo 'No solver process found'")
    await update.message.reply_text(output)


async def cmd_check(update, context):
    """Check solver process status."""
    if sys.platform == "win32":
        output = run_cmd(
            "tasklist /FI \"IMAGENAME eq python.exe\" /V | findstr atlas_web_auto_solver || echo ❌ Solver is NOT running"
        )
    else:
        output = run_cmd(
            "ps aux | grep atlas_web_auto_solver | grep -v grep | head -3 || echo '❌ Solver is NOT running'"
        )
    await update.message.reply_text(f"🔍 Process Check:\n```\n{output}\n```", parse_mode="Markdown")


async def cmd_disk(update, context):
    """Disk usage breakdown."""
    if sys.platform == "win32":
        output = run_cmd(
            "echo 💾 Disk Usage && echo ═══════════════ && "
            "wmic logicaldisk get size,freespace,caption | findstr /V Size"
        )
    else:
        output = run_cmd(
            "echo '💾 Disk Usage' && echo '═══════════════' && "
            "df -h / | tail -1 && echo '' && "
            "echo 'Directory sizes:' && "
            "du -sh outputs/ 2>/dev/null && "
            "du -sh .venv/ 2>/dev/null && "
            "du -sh scribe_sessions/ 2>/dev/null && "
            "du -sh .git/ 2>/dev/null"
        )
    await update.message.reply_text(f"```\n{output}\n```", parse_mode="Markdown")


# ── Security Middleware ─────────────────────────────────────────────
def is_authorized(update) -> bool:
    """Check if the message sender is authorized."""
    chat_id = update.effective_chat.id
    if ALLOWED_CHATS and chat_id not in ALLOWED_CHATS:
        log.warning("Unauthorized access attempt from chat_id=%s", chat_id)
        return False
    return True


async def security_check(update, context):
    """Middleware to check authorization before processing commands."""
    if not is_authorized(update):
        return  # Silently ignore unauthorized users
    # Get the command handler
    command = update.message.text.split()[0].lstrip("/").split("@")[0]
    handlers = {
        "help": cmd_help,
        "start": cmd_help,
        "status": cmd_status,
        "pull": cmd_pull,
        "logs": cmd_logs,
        "run": cmd_run,
        "stop": cmd_stop,
        "check": cmd_check,
        "disk": cmd_disk,
    }
    handler = handlers.get(command)
    if handler:
        await handler(update, context)
    else:
        await update.message.reply_text(
            f"❓ Unknown command: `/{command}`\nUse /help to see available commands.",
            parse_mode="Markdown"
        )


# ── Standalone ID helper ───────────────────────────────────────────
async def cmd_myid(update, context):
    """Tell user their chat ID (useful for setup)."""
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"Your chat ID is: `{chat_id}`\n\n"
        f"Add this to your `.env` file:\n"
        f"`TELEGRAM_ALLOWED_CHATS={chat_id}`",
        parse_mode="Markdown"
    )


# ── Main ────────────────────────────────────────────────────────────
def main():
    if not TOKEN:
        print("=" * 60)
        print("❌ TELEGRAM_BOT_TOKEN not set!")
        print()
        print("Setup instructions:")
        print("  1. Open Telegram and search for @BotFather")
        print("  2. Send /newbot")
        print("  3. Choose a name (e.g., 'Atlas VPS Commander')")
        print("  4. Choose a username (e.g., 'atlas_vps_bot')")
        print("  5. Copy the token and add to .env:")
        print("     TELEGRAM_BOT_TOKEN=your_token_here")
        print()
        print("  6. Send any message to your bot, then visit:")
        print("     https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates")
        print("     to find your chat_id, then add to .env:")
        print("     TELEGRAM_ALLOWED_CHATS=your_chat_id")
        print("=" * 60)
        sys.exit(1)

    try:
        from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
    except ImportError:
        print("❌ python-telegram-bot not installed!")
        print("   Run: pip install python-telegram-bot")
        sys.exit(1)

    log.info("🤖 Starting Atlas Telegram Bot...")
    if ALLOWED_CHATS:
        log.info("   Authorized chats: %s", ALLOWED_CHATS)
    else:
        log.warning("   ⚠️ No TELEGRAM_ALLOWED_CHATS set — bot responds to EVERYONE!")

    app = ApplicationBuilder().token(TOKEN).build()

    # /myid is always public (needed for setup)
    app.add_handler(CommandHandler("myid", cmd_myid))

    # All other commands go through security check
    for cmd in ["help", "start", "status", "pull", "logs", "run", "stop", "check", "disk"]:
        app.add_handler(CommandHandler(cmd, security_check))

    # Handle unknown commands
    app.add_handler(MessageHandler(filters.COMMAND, security_check))

    log.info("✅ Bot ready! Listening for commands...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
