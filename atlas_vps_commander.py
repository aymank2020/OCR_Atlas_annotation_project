"""
Atlas VPS Commander Bot — Discord Bot for 24/7 Rule Ingestion

Runs on DigitalOcean VPS and listens for commands from your private Discord channel.
Accepts rules, corrections, and triggers sync pipelines.

Commands:
  rule: <text>        → Add a new golden rule
  correction: <text>  → Add a correction from QA review
  sync                → Trigger git pull + vertex cache update
  status              → Show bot status and rule count

Setup:
  1. Create .env with DISCORD_BOT_TOKEN and COMMAND_CHANNEL_ID
  2. pip install discord.py python-dotenv
  3. tmux new -s atlas_bot && python atlas_vps_commander.py
"""
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    import discord
    from dotenv import load_dotenv
except ImportError:
    print("[commander] ERROR: Install deps: pip install discord.py python-dotenv")
    sys.exit(1)

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip().strip('"')
COMMAND_CHANNEL_ID = int(os.getenv("COMMAND_CHANNEL_ID", "0").strip().strip('"'))

# Channels to harvest (ID -> name)
HARVEST_CHANNELS = {
    int(os.getenv("COMMAND_CHANNEL_ID", "0").strip().strip('"')): "COMMAND_CHANNEL",
    int(os.getenv("LEVEL3_ANNOUNCMENT", "0").strip().strip('"')): "LEVEL3_ANNOUNCEMENT",
    int(os.getenv("LEVEL3_QUESTION", "0").strip().strip('"')): "LEVEL3_QUESTION",
    int(os.getenv("ATLAS_ANNOUNCMENT", "0").strip().strip('"')): "ATLAS_ANNOUNCEMENT",
}
# Remove any 0-ID entries
HARVEST_CHANNELS = {k: v for k, v in HARVEST_CHANNELS.items() if k}

DATE_FILTER = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)

PROJECT_ROOT = Path(__file__).parent
GOLDEN_RULES_FILE = PROJECT_ROOT / "prompts" / "golden_rules.md"
NEGATIVE_EXAMPLES_FILE = PROJECT_ROOT / "prompts" / "negative_examples.json"
CONTEXT_PACK_FILE = PROJECT_ROOT / "prompts" / "atlas_vertex_context_pack.txt"
SYSTEM_PROMPT_FILE = PROJECT_ROOT / "prompts" / "system_prompt.txt"
HISTORY_DIR = PROJECT_ROOT / "outputs" / "discord_bot_history"
RULES_LOG = PROJECT_ROOT / "outputs" / "harvested_rules_log.json"

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# ─── Labeling Rule Detection ────────────────────────────────────
LABELING_KEYWORDS = [
    "hold", "label", "segment", "annotation", "annotate", "labeling",
    "ego", "action", "coarse", "dense", "granularity",
    "must be labeled", "must label", "required",
    "key rule", "effective immediately",
    "clarification", "example", "correct", "incorrect",
    "merge", "split", "no action", "loosen", "remove", "place",
    "pick up", "timestamp", "overlap", "consecutive",
]

NOISE_KEYWORDS = [
    "payment", "wallet", "crypto", "gift card", 
    "boost", "nitro", "otp", "2fa", "ban",
]

def is_labeling_rule(content: str) -> bool:
    """Detect if message contains labeling rules."""
    lower = content.lower()
    if len(lower) < 50:
        return False
    if sum(1 for nk in NOISE_KEYWORDS if nk in lower) >= 2:
        return False
    return sum(1 for kw in LABELING_KEYWORDS if kw in lower) >= 3


def clean_content(content: str) -> str:
    """Clean Discord message for storage."""
    text = re.sub(r"<@[!&]?\d+>", "", content)
    text = re.sub(r"@(?:everyone|here)", "", text)
    text = re.sub(r"<:\w+:\d+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def append_rule(rule_text: str, category: str = "RULE") -> bool:
    """Append a new rule to golden_rules.md."""
    try:
        timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        entry = f"\n## {category}-DISCORD: {rule_text[:60]}\n"
        entry += f"- {rule_text}\n"
        entry += f"- Source: Discord VPS Commander, {timestamp}\n"

        GOLDEN_RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(GOLDEN_RULES_FILE, "a", encoding="utf-8") as f:
            f.write(entry)
        return True
    except Exception as e:
        print(f"[commander] Error writing rule: {e}")
        return False


def append_correction(correction_text: str) -> bool:
    """Append a correction to negative_examples.json."""
    try:
        examples = []
        if NEGATIVE_EXAMPLES_FILE.exists():
            examples = json.loads(NEGATIVE_EXAMPLES_FILE.read_text(encoding="utf-8"))

        examples.append({
            "episode_id": "discord_manual",
            "date": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
            "rule_violated": "DISCORD-CORRECTION",
            "ai_label": "",
            "corrected_label": correction_text,
            "explanation": f"Manual correction via Discord Commander",
            "segment_index": "N/A",
            "severity": "MEDIUM",
        })

        NEGATIVE_EXAMPLES_FILE.write_text(
            json.dumps(examples, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return True
    except Exception as e:
        print(f"[commander] Error writing correction: {e}")
        return False


def trigger_sync() -> str:
    """Run git add/commit/push and optionally update vertex cache."""
    logs = []
    try:
        # Git sync
        result = subprocess.run(
            ["git", "add", "-A"],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=30,
        )
        logs.append(f"git add: {result.returncode}")

        result = subprocess.run(
            ["git", "commit", "-m", f"[VPS Commander] Auto-update rules {datetime.datetime.utcnow():%Y-%m-%d %H:%M}"],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=30,
        )
        logs.append(f"git commit: {result.returncode}")

        result = subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=60,
        )
        logs.append(f"git push: {result.returncode}")

        # Optional: Vertex cache update
        cache_script = PROJECT_ROOT / "vertex_create_cache.py"
        if cache_script.exists():
            logs.append("Vertex cache update available (run manually)")

        return "\n".join(logs)
    except Exception as e:
        return f"Sync error: {e}"


def get_status() -> str:
    """Return bot status info."""
    rule_count = 0
    if GOLDEN_RULES_FILE.exists():
        rule_count = GOLDEN_RULES_FILE.read_text(encoding="utf-8").count("## RULE")

    neg_count = 0
    if NEGATIVE_EXAMPLES_FILE.exists():
        try:
            neg_count = len(json.loads(NEGATIVE_EXAMPLES_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass

    return (
        f"**Atlas VPS Commander Status**\n"
        f"- Golden Rules: {rule_count}\n"
        f"- Negative Examples: {neg_count}\n"
        f"- Uptime: {datetime.datetime.utcnow():%Y-%m-%d %H:%M UTC}\n"
        f"- Project: {PROJECT_ROOT}\n"
    )


@client.event
async def on_ready():
    print("=" * 50)
    print(f"[VPS COMMANDER] Online as: {client.user}")
    print(f"[VPS COMMANDER] Listening to channel: {COMMAND_CHANNEL_ID}")
    print("=" * 50)


@client.event
async def on_message(message):
    # Only respond in the command channel, ignore own messages
    if message.author == client.user:
        return
    if message.channel.id != COMMAND_CHANNEL_ID:
        return

    content = message.content.strip()

    # Rule command
    if content.lower().startswith("rule:"):
        rule_text = content[5:].strip()
        if not rule_text:
            await message.reply("Usage: `rule: <rule text>`")
            return
        await message.add_reaction("\u23f3")  # hourglass
        if append_rule(rule_text):
            sync_log = trigger_sync()
            await message.reply(
                f"Rule saved & synced!\n```\n{rule_text}\n```\nSync:\n```\n{sync_log}\n```"
            )
            await message.add_reaction("\u2705")  # checkmark
        else:
            await message.reply("Failed to save rule. Check server logs.")
            await message.add_reaction("\u274c")  # X

    # Correction command
    elif content.lower().startswith("correction:"):
        correction_text = content[11:].strip()
        if not correction_text:
            await message.reply("Usage: `correction: <correction text>`")
            return
        await message.add_reaction("\u23f3")
        if append_correction(correction_text):
            sync_log = trigger_sync()
            await message.reply(
                f"Correction saved & synced!\n```\n{correction_text}\n```\nSync:\n```\n{sync_log}\n```"
            )
            await message.add_reaction("\u2705")
        else:
            await message.reply("Failed to save correction.")
            await message.add_reaction("\u274c")

    # Sync command
    elif content.lower() == "sync":
        await message.add_reaction("\u23f3")
        sync_log = trigger_sync()
        await message.reply(f"Sync complete!\n```\n{sync_log}\n```")
        await message.add_reaction("\u2705")

    # Status command
    elif content.lower() == "status":
        status = get_status()
        await message.reply(status)

    # Harvest command — read channel history using Bot Token (SAFE)
    elif content.lower().startswith("harvest"):
        await message.add_reaction("\u23f3")
        await message.reply("Starting harvest of all channels since 2026-01-01...")
        total_msgs = 0
        total_rules = 0
        results = []

        for ch_id, ch_name in HARVEST_CHANNELS.items():
            try:
                channel = client.get_channel(ch_id)
                if not channel:
                    channel = await client.fetch_channel(ch_id)
                if not channel:
                    results.append(f"\u274c #{ch_name}: channel not found")
                    continue
                    
                msgs = []
                async for msg in channel.history(limit=None, after=DATE_FILTER, oldest_first=True):
                    msgs.append({
                        "id": str(msg.id),
                        "author": str(msg.author),
                        "timestamp": msg.created_at.isoformat(),
                        "content": msg.content,
                        "embeds": [e.description or "" for e in msg.embeds if e.description],
                    })

                total_msgs += len(msgs)

                # Save history
                HISTORY_DIR.mkdir(parents=True, exist_ok=True)
                history_path = HISTORY_DIR / f"{ch_name}.json"
                history_path.write_text(
                    json.dumps(msgs, ensure_ascii=False, indent=2), encoding="utf-8"
                )

                # Detect rules
                ch_rules = 0
                existing_ids = set()
                if RULES_LOG.exists():
                    try:
                        for entry in json.loads(RULES_LOG.read_text(encoding="utf-8")):
                            existing_ids.add(str(entry.get("msg_id")))
                    except Exception:
                        pass

                for m in msgs:
                    if m["id"] not in existing_ids and is_labeling_rule(m.get("content", "")):
                        clean = clean_content(m.get("content", ""))
                        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                        entry_text = f"\n\n### AUTO-HARVESTED from #{ch_name} by {m['author']} ({ts})\n"
                        entry_text += f"<!-- msg_id: {m['id']} -->\n"
                        entry_text += f"{clean}\n"
                        with open(GOLDEN_RULES_FILE, "a", encoding="utf-8") as f:
                            f.write(entry_text)
                        # Log
                        log = []
                        if RULES_LOG.exists():
                            try:
                                log = json.loads(RULES_LOG.read_text(encoding="utf-8"))
                            except Exception:
                                pass
                        log.append({"msg_id": m["id"], "author": m["author"], "channel": ch_name,
                                    "content": m.get("content", "")[:300],
                                    "harvested_at": datetime.datetime.now(datetime.timezone.utc).isoformat()})
                        RULES_LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
                        existing_ids.add(m["id"])
                        ch_rules += 1

                total_rules += ch_rules
                results.append(f"\u2705 #{ch_name}: {len(msgs)} msgs, {ch_rules} rules")
            except Exception as ex:
                results.append(f"\u274c #{ch_name}: {str(ex)[:100]}")

        # Sync if rules found
        if total_rules > 0:
            trigger_sync()

        summary = f"**Harvest Complete**\n"
        summary += f"Total: {total_msgs} messages, {total_rules} new rules\n\n"
        summary += "\n".join(results)
        await message.reply(summary)
        await message.add_reaction("\u2705")


if __name__ == "__main__":
    if not TOKEN:
        print("[commander] CRITICAL: DISCORD_BOT_TOKEN not set in .env")
        sys.exit(1)
    if not COMMAND_CHANNEL_ID:
        print("[commander] CRITICAL: COMMAND_CHANNEL_ID not set in .env")
        sys.exit(1)
    client.run(TOKEN)
