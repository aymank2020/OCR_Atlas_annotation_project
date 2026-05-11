"""
Atlas Browser Harvester — LOCAL-ONLY Stealth Playwright Discord Scraper
========================================================================
⚠️  WARNING: This script MUST ONLY run on your LOCAL MACHINE (Windows).
⚠️  NEVER deploy this on a VPS/server — it uses your personal Discord
⚠️  session which violates Discord ToS if automated from a datacenter IP.

✅  SAFE ARCHITECTURE:
    - LOCAL (this machine):  Playwright stealth browser → scrape channels
    - VPS (157.245.186.95):  Commander Bot (atlas_vps_commander.py) → Bot Token

Usage (LOCAL ONLY):
  python atlas_browser_harvester.py --headed       # First run (solve CAPTCHA)
  python atlas_browser_harvester.py                # Headless after first login
  python atlas_browser_harvester.py --loop         # Continuous (every 6 hours)

Account: danatimmer2050@gmail.com (DanaTimmer2050)
"""
import argparse
import asyncio
import datetime
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# Fix Windows console encoding for emoji/unicode
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
else:
    # SAFETY GUARD: Abort if not on Windows (i.e. running on Linux VPS)
    print("=" * 60)
    print("[SAFETY] ⛔ This script is LOCAL-ONLY (Windows).")
    print("[SAFETY] Running on a VPS/server violates Discord ToS")
    print("[SAFETY] and WILL get your account permanently banned.")
    print("[SAFETY] Use atlas_vps_commander.py with Bot Token on VPS.")
    print("=" * 60)
    sys.exit(1)

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("[harvester] FATAL: pip install playwright && playwright install chromium")
    sys.exit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    print("[harvester] FATAL: pip install python-dotenv")
    sys.exit(1)

load_dotenv()

# ─── Config ──────────────────────────────────────────────────────
DISCORD_EMAIL = os.getenv("DISCORD_EMAIL", "").strip().strip('"')
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip().strip('"')

# Guild and Channel IDs
GUILD_ID = os.getenv("DISCORD_GUILD_ID", "1448492968528052358").strip().strip('"')

CHANNELS = {
    "COMMAND_CHANNEL":     os.getenv("COMMAND_CHANNEL_ID", "1485540323584118877").strip().strip('"'),
    "LEVEL3_ANNOUNCEMENT": os.getenv("LEVEL3_ANNOUNCMENT", "1458584003605954717").strip().strip('"'),
    "LEVEL3_QUESTION":     os.getenv("LEVEL3_QUESTION", "1455689224593477674").strip().strip('"'),
    "ATLAS_ANNOUNCEMENT":  os.getenv("ATLAS_ANNOUNCMENT", "1453232420634624234").strip().strip('"'),
}

DATE_FILTER = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)

PROJECT_ROOT = Path(__file__).parent
GOLDEN_RULES = PROJECT_ROOT / "prompts" / "golden_rules.md"
SYSTEM_PROMPT = PROJECT_ROOT / "prompts" / "system_prompt.txt"
VERTEX_CONTEXT = PROJECT_ROOT / "prompts" / "atlas_vertex_context_pack.txt"
HISTORY_DIR = PROJECT_ROOT / "outputs" / "discord_browser_history"
RULES_LOG = PROJECT_ROOT / "outputs" / "harvested_rules_log.json"
STATS_FILE = PROJECT_ROOT / "outputs" / "browser_harvest_stats.json"
SESSION_FILE = PROJECT_ROOT / "outputs" / ".discord_session"

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

NOISE_KEYWORDS = [
    "payment", "wallet", "crypto", "gift card", "impersonation",
    "security notice", "ban", "suspended", "otp", "2fa",
    "boost", "nitro", "role", "color",
]


def is_labeling_rule(content: str) -> bool:
    """Detect if message contains labeling rules (not admin/ops noise)."""
    lower = content.lower()
    if len(lower) < 50:
        return False
    noise_hits = sum(1 for nk in NOISE_KEYWORDS if nk in lower)
    if noise_hits >= 2:
        return False
    hits = sum(1 for kw in LABELING_KEYWORDS if kw in lower)
    return hits >= 3


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
        return 0

    rules_text = GOLDEN_RULES.read_text(encoding="utf-8")
    auto_rules = rules_text.count("### AUTO-HARVESTED")
    manual_rules = rules_text.count("## RULE-")
    discord_rules = rules_text.count("### Discord Rule")
    total = auto_rules + manual_rules + discord_rules

    injection = f"""
# === HARVESTED DISCORD RULES (auto-updated) ===
# Total rules: {total} (Manual: {manual_rules}, Discord: {discord_rules}, Auto-harvested: {auto_rules})
# Source: golden_rules.md — updated by atlas_browser_harvester.py
"""
    for line in rules_text.split("\n"):
        if line.startswith("## RULE-") or line.startswith("### Discord Rule"):
            injection += f"# - {line.strip('#').strip()}\n"
        elif line.startswith("### AUTO-HARVESTED"):
            injection += f"# - {line.strip('#').strip()}\n"
    injection += "# === END HARVESTED RULES ===\n"

    for filepath in [SYSTEM_PROMPT, VERTEX_CONTEXT]:
        if filepath.exists():
            text = filepath.read_text(encoding="utf-8")
            text = re.sub(
                r"\n# === HARVESTED DISCORD RULES.*?# === END HARVESTED RULES ===\n",
                "", text, flags=re.DOTALL
            )
            text += injection
            filepath.write_text(text, encoding="utf-8")

    return total


def git_sync():
    """Commit and push."""
    try:
        subprocess.run(["git", "add", "-A"], cwd=str(PROJECT_ROOT),
                        capture_output=True, timeout=30)
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
        subprocess.run(
            ["git", "commit", "-m", f"[BrowserHarvester] Auto-update rules {ts}"],
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


# ─── Browser Automation ─────────────────────────────────────────

async def discord_login(page, email: str):
    """Log into Discord web manually or via token."""
    print("[harvester] Navigating to Discord login...")
    await page.goto("https://discord.com/login", wait_until="networkidle", timeout=60000)
    await asyncio.sleep(2)

    if DISCORD_TOKEN:
        print("[harvester] Attempting token injection login...")
        success = await page.evaluate(f"""
            (token) => {{
                function login(token) {{
                    setInterval(() => {{
                        document.body.appendChild(document.createElement `iframe`).contentWindow.localStorage.token = `"${{token}}"`;
                    }}, 50);
                    setTimeout(() => {{
                        location.reload();
                    }}, 2500);
                }}
                login(token);
                return true;
            }}
        """, DISCORD_TOKEN)
        await asyncio.sleep(5)
        if "/login" not in page.url:
            print("[harvester] ✅ Token injection seems to have worked!")
            return True

    print("[harvester] ⚠️ No DISCORD_TOKEN provided and session expired.")
    print("[harvester] Manual login required - please run with --headed to enter credentials.")
    return False


async def navigate_to_channel(page, guild_id: str, channel_id: str):
    """Navigate to a specific Discord channel."""
    url = f"https://discord.com/channels/{guild_id}/{channel_id}"
    print(f"[harvester] Navigating to channel {channel_id}...")
    await page.goto(url, wait_until="networkidle", timeout=30000)
    await asyncio.sleep(3)


def parse_discord_date(date_str: str) -> datetime.datetime | None:
    """Parse Discord date strings like 'Today at 10:00 AM', '03/26/2026', etc."""
    if not date_str:
        return None

    date_str = date_str.strip()
    now = datetime.datetime.now(datetime.timezone.utc)

    # Handle "Today at HH:MM AM/PM"
    if date_str.lower().startswith("today"):
        return now

    # Handle "Yesterday at HH:MM AM/PM"
    if date_str.lower().startswith("yesterday"):
        return now - datetime.timedelta(days=1)

    # Handle MM/DD/YYYY format
    try:
        dt = datetime.datetime.strptime(date_str.split(" ")[0], "%m/%d/%Y")
        return dt.replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        pass

    # Handle DD/MM/YYYY format
    try:
        dt = datetime.datetime.strptime(date_str.split(" ")[0], "%d/%m/%Y")
        return dt.replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        pass

    # Handle YYYY-MM-DD format
    try:
        dt = datetime.datetime.strptime(date_str.split(" ")[0], "%Y-%m-%d")
        return dt.replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        pass

    return None


async def scroll_to_load_history(page, max_scrolls: int = 80):
    """Scroll up to trigger Discord API message loading."""
    print("[harvester] Scrolling up to trigger message loading...")
    scroll_count = 0
    for i in range(max_scrolls):
        try:
            await page.evaluate("""
                const scroller = document.querySelector('div[class*="scroller"]')
                    || document.querySelector('main [class*="scroller"]');
                if (scroller) scroller.scrollTop = 0;
            """)
        except Exception:
            pass
        await asyncio.sleep(0.8)
        scroll_count += 1
        if scroll_count % 20 == 0:
            print(f"[harvester]   ... scrolled {scroll_count} times")
    return scroll_count


def filter_messages_by_date(messages: list[dict], min_date: datetime.datetime) -> list[dict]:
    """Filter messages to only those after min_date."""
    filtered = []
    for msg in messages:
        ts = msg.get("timestamp", "")
        if ts:
            try:
                dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt >= min_date:
                    filtered.append(msg)
                continue
            except (ValueError, TypeError):
                pass
            dt = parse_discord_date(ts)
            if dt and dt >= min_date:
                filtered.append(msg)
        else:
            filtered.append(msg)
    return filtered


async def harvest_channel(page, guild_id: str, channel_id: str, channel_name: str,
                           harvested_ids: set, dry_run: bool = False) -> dict:
    """Harvest a single channel using API response interception.
    
    Instead of scraping the DOM (which doesn't work with headless Chrome),
    we intercept Discord's internal API calls to /api/v*/channels/*/messages
    which return raw JSON message data.
    """
    stats = {"messages": 0, "rules": 0, "errors": []}
    intercepted_messages = []

    # Set up API response interception BEFORE navigating
    async def on_response(response):
        """Callback: intercept Discord message API responses."""
        url = response.url
        if f"/channels/{channel_id}/messages" in url and response.status == 200:
            try:
                data = await response.json()
                if isinstance(data, list):
                    for msg in data:
                        intercepted_messages.append({
                            "id": str(msg.get("id", "")),
                            "author": msg.get("author", {}).get("username", "Unknown"),
                            "timestamp": msg.get("timestamp", ""),
                            "content": msg.get("content", ""),
                            "embeds": [e.get("description", "") for e in msg.get("embeds", []) if e.get("description")],
                        })
            except Exception:
                pass

    page.on("response", on_response)

    try:
        # Navigate to channel (this triggers initial message API call)
        url = f"https://discord.com/channels/{guild_id}/{channel_id}"
        print(f"[harvester] Navigating to channel {channel_id}...")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"[harvester] Navigation warning: {e}")
        
        await asyncio.sleep(5)  # Wait for Discord to make API calls

        # Scroll up to trigger more message API calls
        await scroll_to_load_history(page, max_scrolls=80)
        await asyncio.sleep(3)

        # If interception didn't capture messages, try direct API fetch
        if len(intercepted_messages) == 0:
            print("[harvester] No messages via interception, trying direct API fetch...")
            try:
                api_msgs = await page.evaluate("""
                    async (channelId) => {
                        const msgs = [];
                        let before = null;
                        
                        for (let batch = 0; batch < 5; batch++) {
                            let url = `/api/v9/channels/${channelId}/messages?limit=100`;
                            if (before) url += `&before=${before}`;
                            
                            try {
                                const resp = await fetch(url, {
                                    headers: {
                                        'Authorization': localStorage.getItem('token')?.replace(/"/g, '') || '',
                                        'Content-Type': 'application/json',
                                    }
                                });
                                if (!resp.ok) break;
                                const data = await resp.json();
                                if (!data.length) break;
                                
                                for (const msg of data) {
                                    msgs.push({
                                        id: String(msg.id || ''),
                                        author: (msg.author || {}).username || 'Unknown',
                                        timestamp: msg.timestamp || '',
                                        content: msg.content || '',
                                        embeds: (msg.embeds || []).map(e => e.description || '').filter(Boolean),
                                    });
                                }
                                before = data[data.length - 1].id;
                            } catch (e) {
                                break;
                            }
                        }
                        return msgs;
                    }
                """, channel_id)
                if api_msgs:
                    intercepted_messages.extend(api_msgs)
                    print(f"[harvester] Direct API fetch: {len(api_msgs)} messages")
            except Exception as e:
                print(f"[harvester] Direct API fetch failed: {e}")

        # Deduplicate by ID
        seen_ids = set()
        unique_messages = []
        for msg in intercepted_messages:
            mid = msg.get("id", "")
            if mid and mid not in seen_ids:
                seen_ids.add(mid)
                # Combine content + embeds
                full_content = msg.get("content", "")
                for embed_desc in msg.get("embeds", []):
                    full_content += f"\n[Embed] {embed_desc}"
                msg["content"] = full_content
                unique_messages.append(msg)

        print(f"[harvester] Captured {len(unique_messages)} unique messages")

        # Filter by date
        filtered = filter_messages_by_date(unique_messages, DATE_FILTER)
        stats["messages"] = len(filtered)
        print(f"[harvester] #{channel_name}: {len(unique_messages)} total, {len(filtered)} since {DATE_FILTER.date()}")

        # Save raw history
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        history_path = HISTORY_DIR / f"{channel_name}.json"
        history_path.write_text(
            json.dumps(filtered, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # Detect and save rules
        for msg in filtered:
            msg_id = msg.get("id", "")
            content = msg.get("content", "")
            author = msg.get("author", "Unknown")

            if msg_id and msg_id not in harvested_ids and is_labeling_rule(content):
                if dry_run:
                    print(f"[harvester] [DRY-RUN] Would save rule from {author}: {content[:80]}...")
                    stats["rules"] += 1
                else:
                    if append_to_golden_rules(content, author, channel_name, msg_id):
                        log_rule(msg_id, author, channel_name, content)
                        harvested_ids.add(msg_id)
                        stats["rules"] += 1
                        print(f"[harvester] ✅ New rule from {author} in #{channel_name}")

    except Exception as e:
        print(f"[harvester] ❌ Error in #{channel_name}: {e}")
        stats["errors"].append(str(e))
    finally:
        # Remove the response listener
        page.remove_listener("response", on_response)

    return stats


async def run_harvester(dry_run: bool = False, headed: bool = False):
    """Main harvester loop."""
    print("=" * 60)
    print("[BROWSER HARVESTER] Atlas Stealth Discord Scraper v1.0")
    print(f"[BROWSER HARVESTER] Guild: {GUILD_ID}")
    print(f"[BROWSER HARVESTER] Channels: {len(CHANNELS)}")
    print(f"[BROWSER HARVESTER] Date filter: >= {DATE_FILTER.date()}")
    print(f"[BROWSER HARVESTER] Mode: {'DRY-RUN' if dry_run else 'PRODUCTION'}")
    print(f"[BROWSER HARVESTER] Headed: {headed}")
    print("=" * 60)

    if not DISCORD_EMAIL and not DISCORD_TOKEN:
        print("[harvester] WARNING: Neither DISCORD_EMAIL nor DISCORD_TOKEN set. Relying on saved cookies.")

    async with async_playwright() as p:
        # Launch browser with stealth settings
        browser = await p.chromium.launch(
            headless=not headed,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-web-security",
                "--disable-features=VizDisplayCompositor",
            ]
        )

        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            locale="en-US",
            timezone_id="America/New_York",
        )

        # Stealth: remove webdriver detection
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            window.chrome = { runtime: {} };
        """)

        # Load saved session cookies if available
        if SESSION_FILE.exists():
            try:
                cookies = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
                await context.add_cookies(cookies)
                print("[harvester] Loaded saved session cookies")
            except Exception:
                pass

        page = await context.new_page()

        # Try to access Discord directly (may work with saved cookies)
        await page.goto(f"https://discord.com/channels/{GUILD_ID}", timeout=30000)
        await asyncio.sleep(5)

        # Check if we need to login
        current_url = page.url
        if "/login" in current_url or "discord.com/login" in current_url:
            print("[harvester] Session expired — attempting recovery...")
            success = await discord_login(page, DISCORD_EMAIL)
            if not success:
                print("[harvester] FATAL: Authentication failed. If not using a token, run with --headed to login manually.")
                await browser.close()
                sys.exit(1)

            # Save session cookies
            cookies = await context.cookies()
            SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
            SESSION_FILE.write_text(json.dumps(cookies, indent=2), encoding="utf-8")
            print("[harvester] Session cookies saved for reuse")
        else:
            print("[harvester] ✅ Session still valid (cookies worked)")

        # Wait for Discord to fully load
        await asyncio.sleep(5)

        # Harvest each channel
        harvested_ids = load_harvested_ids()
        total_messages = 0
        total_rules = 0
        channel_stats = {}

        for ch_name, ch_id in CHANNELS.items():
            if not ch_id or ch_id == "0":
                print(f"[harvester] Skipping {ch_name}: no channel ID configured")
                continue

            print(f"\n{'─' * 40}")
            print(f"[harvester] Scanning: {ch_name} ({ch_id})")
            print(f"{'─' * 40}")

            stats = await harvest_channel(page, GUILD_ID, ch_id, ch_name,
                                           harvested_ids, dry_run=dry_run)
            total_messages += stats["messages"]
            total_rules += stats["rules"]
            channel_stats[ch_name] = stats

            # Human-like delay between channels
            await asyncio.sleep(3)

        # Update AI contexts
        if total_rules > 0 and not dry_run:
            total_context_rules = update_ai_contexts()
            git_sync()
            print(f"\n[harvester] ✅ {total_rules} new rules → AI contexts updated + Git synced")
        else:
            total_context_rules = 0

        # Save stats
        stats_data = {
            "scan_date": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "channels_scanned": len(CHANNELS),
            "total_messages": total_messages,
            "new_rules_extracted": total_rules,
            "total_rules_in_context": total_context_rules,
            "channel_stats": {k: {"messages": v["messages"], "rules": v["rules"]}
                              for k, v in channel_stats.items()},
        }
        save_stats(stats_data)

        # Print summary
        print(f"\n{'=' * 60}")
        print(f"[BROWSER HARVESTER] SCAN COMPLETE")
        print(f"  Channels scanned: {len(channel_stats)}")
        print(f"  Total messages (since 2026-01-01): {total_messages}")
        print(f"  New rules extracted: {total_rules}")
        for ch_name, st in channel_stats.items():
            print(f"    #{ch_name}: {st['messages']} msgs, {st['rules']} rules"
                  + (f" ⚠️ {st['errors']}" if st.get('errors') else ""))
        print(f"{'=' * 60}")

        await browser.close()


# ─── Entry Point ─────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Atlas Browser Discord Harvester")
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't write rules, just print what would be saved")
    parser.add_argument("--headed", action="store_true",
                        help="Run browser in visible (headed) mode for debugging")
    parser.add_argument("--loop", action="store_true",
                        help="Run continuously (scrape every 6 hours)")
    args = parser.parse_args()

    if args.loop:
        while True:
            print(f"\n[harvester] Starting scan at {datetime.datetime.now()}")
            asyncio.run(run_harvester(dry_run=args.dry_run, headed=args.headed))
            print(f"[harvester] Next scan in 6 hours...")
            time.sleep(6 * 3600)
    else:
        asyncio.run(run_harvester(dry_run=args.dry_run, headed=args.headed))


if __name__ == "__main__":
    main()
