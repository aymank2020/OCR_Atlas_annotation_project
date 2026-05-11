"""
Atlas Discord Harvester v2 — Full Server Scanner + Context Auto-Updater
=======================================================================
Scans ALL text channels in the Atlas server from 1/1/2026.
Auto-detects labeling rules and updates:
  - prompts/golden_rules.md (master rules)
  - prompts/system_prompt.txt (AI prompt injection)
  - prompts/atlas_vertex_context_pack.txt (Vertex context)

Production commands:
  # On VPS (157.245.186.95):
  tmux new -s harvester
  python3 atlas_discord_harvester.py
  # Ctrl+B, D to detach

  # Check status:
  tmux attach -t harvester
  # Or from Discord command channel: status / rescan

  # Check logs:
  tail -f /tmp/harvester.log
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
    print("[harvester] pip3 install --break-system-packages discord.py python-dotenv")
    sys.exit(1)

load_dotenv()

# ─── Config ──────────────────────────────────────────────────────
TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip().strip('"')
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "0").strip().strip('"'))
COMMAND_CHANNEL_ID = int(os.getenv("COMMAND_CHANNEL_ID", "0").strip().strip('"'))

# Date filter: only messages from 2026-01-01 onwards
DATE_FILTER = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)

PROJECT_ROOT = Path(__file__).parent
GOLDEN_RULES = PROJECT_ROOT / "prompts" / "golden_rules.md"
SYSTEM_PROMPT = PROJECT_ROOT / "prompts" / "system_prompt.txt"
VERTEX_CONTEXT = PROJECT_ROOT / "prompts" / "atlas_vertex_context_pack.txt"
NEGATIVE_EXAMPLES = PROJECT_ROOT / "prompts" / "negative_examples.json"
RULES_LOG = PROJECT_ROOT / "outputs" / "harvested_rules_log.json"
HISTORY_DIR = PROJECT_ROOT / "outputs" / "discord_history"
STATS_FILE = PROJECT_ROOT / "outputs" / "harvest_stats.json"

# ─── Labeling Rule Detection ────────────────────────────────────
LABELING_KEYWORDS = [
    "hold", "label", "segment", "annotation", "annotate", "labeling",
    "gripper", "ego", "action", "coarse", "dense", "granularity",
    "must be labeled", "must label", "must annotate", "required",
    "not acceptable", "key rule", "effective immediately",
    "clarification", "example", "correct", "incorrect",
    "acceptable", "unacceptable", "merge", "split",
    "no action", "intent", "loosen", "remove", "place",
    "pick up", "put down", "screw", "unscrew", "attach", "detach",
    "continue", "duration", "60 seconds", "60s", "timestamp",
    "overlap", "gap", "consecutive", "identical",
]

# Non-labeling keywords (security, payment, etc. — filter these OUT)
NOISE_KEYWORDS = [
    "payment", "wallet", "crypto", "gift card", "impersonation",
    "security notice", "ban", "suspended", "otp", "2fa",
    "boost", "nitro", "role", "color",
]


def is_labeling_rule(content: str, author_roles: list = None) -> bool:
    """Detect if message contains LABELING rules (not admin/ops)."""
    lower = content.lower()
    if len(lower) < 50:
        return False

    # Reject noise
    noise_hits = sum(1 for nk in NOISE_KEYWORDS if nk in lower)
    if noise_hits >= 2:
        return False

    # Count labeling keyword hits
    hits = sum(1 for kw in LABELING_KEYWORDS if kw in lower)
    if hits >= 4:
        return True
    # Admins need fewer hits
    if author_roles and hits >= 2:
        admin_check = ["admin", "mod", "reviewer", "trainer", "atlas"]
        for role in author_roles:
            if any(ac in role.lower() for ac in admin_check):
                return True
    return False


def clean_content(content: str) -> str:
    """Clean Discord message for storage."""
    text = re.sub(r"<@[!&]?\d+>", "", content)
    text = re.sub(r"@(?:everyone|here)", "", text)
    text = re.sub(r"<:\w+:\d+>", "", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ─── Storage ─────────────────────────────────────────────────────

def load_harvested_ids() -> set:
    """Load already-harvested message IDs."""
    try:
        if RULES_LOG.exists():
            log = json.loads(RULES_LOG.read_text(encoding="utf-8"))
            return {str(e.get("msg_id")) for e in log}
    except Exception:
        pass
    return set()


def log_rule(msg_id, author, channel, content):
    """Log harvested rule for deduplication."""
    try:
        RULES_LOG.parent.mkdir(parents=True, exist_ok=True)
        log = []
        if RULES_LOG.exists():
            log = json.loads(RULES_LOG.read_text(encoding="utf-8"))
        log.append({
            "msg_id": str(msg_id),
            "author": str(author),
            "channel": str(channel),
            "content": content[:300],
            "harvested_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        })
        RULES_LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[harvester] Log error: {e}")


def append_to_golden_rules(content, author, channel, msg_id) -> bool:
    """Append rule to golden_rules.md."""
    try:
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        clean = clean_content(content)
        entry = f"\n\n### AUTO-HARVESTED from #{channel} by {author} ({ts})\n"
        entry += f"<!-- msg_id: {msg_id} -->\n"
        entry += f"{clean}\n"
        GOLDEN_RULES.parent.mkdir(parents=True, exist_ok=True)
        with open(GOLDEN_RULES, "a", encoding="utf-8") as f:
            f.write(entry)
        return True
    except Exception as e:
        print(f"[harvester] Write error: {e}")
        return False


def update_ai_contexts():
    """Update system_prompt.txt and vertex context with harvested rules summary."""
    if not GOLDEN_RULES.exists():
        return

    rules_text = GOLDEN_RULES.read_text(encoding="utf-8")

    # Count rules
    auto_rules = rules_text.count("### AUTO-HARVESTED")
    manual_rules = rules_text.count("## RULE-")
    discord_rules = rules_text.count("### Discord Rule")
    total = auto_rules + manual_rules + discord_rules

    # Build injection block
    injection = f"""
# === HARVESTED DISCORD RULES (auto-updated) ===
# Total rules: {total} (Manual: {manual_rules}, Discord: {discord_rules}, Auto-harvested: {auto_rules})
# Source: golden_rules.md — updated by atlas_discord_harvester.py
# Key labeling rules from Discord (injected for context):
"""
    # Extract the actual rule headers for summary
    for line in rules_text.split("\n"):
        if line.startswith("## RULE-") or line.startswith("### Discord Rule"):
            injection += f"# - {line.strip('#').strip()}\n"
        elif line.startswith("### AUTO-HARVESTED"):
            injection += f"# - {line.strip('#').strip()}\n"

    injection += "# === END HARVESTED RULES ===\n"

    # Update system_prompt.txt — append summary if not already there
    if SYSTEM_PROMPT.exists():
        sp = SYSTEM_PROMPT.read_text(encoding="utf-8")
        # Remove old injection block
        sp = re.sub(r"\n# === HARVESTED DISCORD RULES.*?# === END HARVESTED RULES ===\n",
                     "", sp, flags=re.DOTALL)
        sp += injection
        SYSTEM_PROMPT.write_text(sp, encoding="utf-8")

    # Update vertex context
    if VERTEX_CONTEXT.exists():
        vc = VERTEX_CONTEXT.read_text(encoding="utf-8")
        vc = re.sub(r"\n# === HARVESTED DISCORD RULES.*?# === END HARVESTED RULES ===\n",
                     "", vc, flags=re.DOTALL)
        vc += injection
        VERTEX_CONTEXT.write_text(vc, encoding="utf-8")

    return total


def git_sync():
    """Commit and push."""
    try:
        subprocess.run(["git", "add", "-A"], cwd=str(PROJECT_ROOT),
                       capture_output=True, timeout=30)
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
        subprocess.run(
            ["git", "commit", "-m", f"[Harvester] Auto-update rules {ts}"],
            cwd=str(PROJECT_ROOT), capture_output=True, timeout=30)
        subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=str(PROJECT_ROOT), capture_output=True, timeout=60)
        return True
    except Exception:
        return False


def save_stats(stats):
    """Save harvest stats."""
    try:
        STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATS_FILE.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


# ─── Discord Bot ─────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
client = discord.Client(intents=intents)


@client.event
async def on_ready():
    print("=" * 60)
    print(f"[HARVESTER v2] Online as: {client.user}")
    print(f"[HARVESTER v2] Guild: {GUILD_ID}")
    print(f"[HARVESTER v2] Date filter: >= {DATE_FILTER.date()}")
    print("=" * 60)

    # Find guild
    print(f"[HARVESTER] Searching for guild ID: {GUILD_ID}...")
    guild = client.get_guild(GUILD_ID)
    if not guild:
        try:
            guild = await client.fetch_guild(GUILD_ID)
            print(f"[HARVESTER] Guild found via fetch: {guild.name}")
        except Exception as e:
            print(f"[harvester] ERROR: Guild {GUILD_ID} not found or no access! ({e})")
            # Log available guilds for debugging
            if client.guilds:
                print(f"[HARVESTER] Available guilds: {[(g.id, g.name) for g in client.guilds]}")
            else:
                print("[HARVESTER] No guilds available in cache. Bot might not be joined to any server.")
            return
    else:
        print(f"[HARVESTER] Guild found in cache: {guild.name}")

    # Scan ALL text channels
    text_channels = [ch for ch in guild.channels if isinstance(ch, discord.TextChannel)]
    print(f"\n[HARVESTER] Found {len(text_channels)} text channels to scan")

    harvested_ids = load_harvested_ids()
    total_messages = 0
    total_rules = 0
    channel_stats = {}

    for ch in text_channels:
        try:
            msg_count = 0
            rule_count = 0
            history_msgs = []

            async for message in ch.history(limit=None, after=DATE_FILTER):
                msg_count += 1
                history_msgs.append({
                    "id": str(message.id),
                    "author": str(message.author),
                    "content": message.content[:500],
                    "timestamp": message.created_at.isoformat(),
                })

                if str(message.id) not in harvested_ids:
                    roles = [r.name for r in message.author.roles] if hasattr(message.author, 'roles') else []
                    if is_labeling_rule(message.content, roles):
                        if append_to_golden_rules(message.content, str(message.author), ch.name, str(message.id)):
                            log_rule(str(message.id), str(message.author), ch.name, message.content)
                            harvested_ids.add(str(message.id))
                            rule_count += 1

            if history_msgs:
                save_dir = HISTORY_DIR / ch.category.name if ch.category else HISTORY_DIR
                save_dir.mkdir(parents=True, exist_ok=True)
                path = save_dir / f"{ch.name}.json"
                path.write_text(json.dumps(history_msgs, ensure_ascii=False, indent=2), encoding="utf-8")

            status = f"#{ch.name}: {msg_count} msgs, {rule_count} new rules" if msg_count > 0 else f"#{ch.name}: empty"
            print(f"[harvester] {status}")
            total_messages += msg_count
            total_rules += rule_count
            channel_stats[ch.name] = {"messages": msg_count, "rules": rule_count}

        except discord.Forbidden:
            print(f"[harvester] #{ch.name}: NO ACCESS")
            channel_stats[ch.name] = {"messages": 0, "rules": 0, "error": "forbidden"}
        except Exception as e:
            print(f"[harvester] #{ch.name}: ERROR {e}")
            channel_stats[ch.name] = {"messages": 0, "rules": 0, "error": str(e)}

    # Update AI contexts with new rules
    total_context_rules = update_ai_contexts()

    # Calculate stats
    existing_core_rules = 7  # RULE-HOLD, MERGE, NOINTENT, VERB, CONTINUE, LOOSEN, NOACTION
    update_pct = (total_rules / max(total_context_rules, 1)) * 100 if total_context_rules else 0

    stats = {
        "scan_date": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "channels_scanned": len(text_channels),
        "total_messages": total_messages,
        "new_rules_extracted": total_rules,
        "existing_core_rules": existing_core_rules,
        "total_rules_after": total_context_rules,
        "update_percentage": round(update_pct, 1),
        "channel_stats": channel_stats,
    }
    save_stats(stats)

    print(f"\n{'='*60}")
    print(f"[HARVESTER] SCAN COMPLETE")
    print(f"  Channels scanned: {len(text_channels)}")
    print(f"  Total messages (since 2026-01-01): {total_messages}")
    print(f"  New rules extracted: {total_rules}")
    print(f"  Existing core rules: {existing_core_rules}")
    print(f"  Total rules now: {total_context_rules}")
    print(f"  Update %: {update_pct:.1f}%")
    print(f"  Contexts updated: system_prompt.txt + vertex_context_pack.txt")
    print(f"{'='*60}")

    if total_rules > 0:
        if git_sync():
            print("[HARVESTER] Changes synced to GitHub!")

    print("\n[HARVESTER] Listening for new messages in real-time...")


@client.event
async def on_message(message):
    if message.author == client.user:
        return

    # ── Command channel ──
    if message.channel.id == COMMAND_CHANNEL_ID:
        content = message.content.strip().lower()

        if content.startswith("rule:"):
            rule_text = message.content[5:].strip()
            if rule_text and append_to_golden_rules(rule_text, str(message.author), "manual", str(message.id)):
                log_rule(str(message.id), str(message.author), "manual", rule_text)
                update_ai_contexts()
                git_sync()
                await message.reply(f"Rule saved + contexts updated!\n```\n{rule_text[:200]}\n```")
            return

        elif content.startswith("correction:"):
            corr = message.content[11:].strip()
            if corr:
                try:
                    examples = []
                    if NEGATIVE_EXAMPLES.exists():
                        examples = json.loads(NEGATIVE_EXAMPLES.read_text(encoding="utf-8"))
                    examples.append({
                        "date": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"),
                        "rule_violated": "DISCORD-CORRECTION",
                        "corrected_label": corr,
                        "explanation": f"Via Discord by {message.author}",
                    })
                    NEGATIVE_EXAMPLES.write_text(json.dumps(examples, ensure_ascii=False, indent=2), encoding="utf-8")
                    git_sync()
                    await message.reply(f"Correction saved!\n```\n{corr[:200]}\n```")
                except Exception as e:
                    await message.reply(f"Error: {e}")
            return

        elif content == "status":
            stats = {}
            if STATS_FILE.exists():
                stats = json.loads(STATS_FILE.read_text(encoding="utf-8"))
            await message.reply(
                f"**Atlas Harvester v2 Status**\n"
                f"- Last scan: {stats.get('scan_date', 'never')[:16]}\n"
                f"- Channels: {stats.get('channels_scanned', 0)}\n"
                f"- Messages: {stats.get('total_messages', 0)}\n"
                f"- Rules: {stats.get('total_rules_after', 0)} ({stats.get('new_rules_extracted', 0)} new)\n"
                f"- Update %: {stats.get('update_percentage', 0)}%\n"
            )
            return

        elif content == "sync":
            git_sync()
            await message.reply("Git synced!")
            return

        elif content == "rescan":
            await message.reply("Triggering full rescan... check /tmp/harvester.log")
            # The rescan happens via on_ready logic; restart the bot
            return

    # ── Auto-detect rules in ANY guild channel ──
    if message.guild and message.guild.id == GUILD_ID:
        harvested_ids = load_harvested_ids()
        if str(message.id) not in harvested_ids:
            roles = [r.name for r in message.author.roles] if hasattr(message.author, 'roles') else []
            if is_labeling_rule(message.content, roles):
                print(f"[harvester] NEW RULE in #{message.channel.name} by {message.author}")
                if append_to_golden_rules(message.content, str(message.author), message.channel.name, str(message.id)):
                    log_rule(str(message.id), str(message.author), message.channel.name, message.content)
                    update_ai_contexts()
                    git_sync()


if __name__ == "__main__":
    if not TOKEN:
        print("[harvester] CRITICAL: DISCORD_BOT_TOKEN missing")
        sys.exit(1)
    if not GUILD_ID:
        print("[harvester] CRITICAL: DISCORD_GUILD_ID missing")
        sys.exit(1)
    client.run(TOKEN)
