"""
Atlas Stealth Question Dispatcher — Zero-Trust Annotation Pipeline
===================================================================
Connects to Chrome CDP, opens #LEVEL3_QUESTION channel, and types
questions with human-like delays. Monitors for admin replies in real-time.

Usage:
  python atlas_question_dispatcher.py                    # Send pending questions
  python atlas_question_dispatcher.py --dry-run          # Type but don't press Enter
  python atlas_question_dispatcher.py --max 3            # Send max 3 questions
  python atlas_question_dispatcher.py --wait 10          # 10 min between questions
  python atlas_question_dispatcher.py --harvest-only     # Only check for replies

Requires: Chrome running with --remote-debugging-port=9222
          Run Run_Atlas_Chrome.bat first!
"""

import argparse
import asyncio
import json
import os
import random
import sys
import time
import subprocess
from datetime import datetime, timezone
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Config ──────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent
QUEUE_FILE = PROJECT_ROOT / "questions_queue.json"
CDP_URL = "http://127.0.0.1:9222"

LEVEL3_QUESTION_ID = os.getenv("LEVEL3_QUESTION", "1455689224593477674")
GUILD_ID = os.getenv("DISCORD_GUILD_ID", "1448492968528052358")
DISCORD_CHANNEL_URL = f"https://discord.com/channels/{GUILD_ID}/{LEVEL3_QUESTION_ID}"

# Safety limits
DEFAULT_WAIT_MINUTES = 15
MAX_QUESTIONS_PER_DAY = 10
TYPING_DELAY_MS_MIN = 50
TYPING_DELAY_MS_MAX = 150
POST_TYPE_WAIT_SEC = 2
REPLY_CHECK_INTERVAL_SEC = 300  # Check for replies every 5 minutes


def load_queue() -> list:
    """Load question queue from file."""
    if not QUEUE_FILE.exists():
        print("[dispatch] ERROR: questions_queue.json not found!")
        print("[dispatch] Run: python atlas_question_generator.py first")
        sys.exit(1)
    return json.loads(QUEUE_FILE.read_text(encoding="utf-8"))


def save_queue(queue: list):
    """Save question queue to file."""
    QUEUE_FILE.write_text(
        json.dumps(queue, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def count_sent_today(queue: list) -> int:
    """Count how many questions were sent today."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return sum(
        1 for q in queue
        if q.get("sent_at", "") and q["sent_at"].startswith(today)
    )


async def connect_to_discord():
    """Connect to Chrome via CDP and find/navigate to Discord channel."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("[dispatch] FATAL: pip install playwright")
        sys.exit(1)

    pw_context_manager = async_playwright()
    pw = await pw_context_manager.start()
    
    print(f"[dispatch] Connecting to Chrome CDP at {CDP_URL}...")
    try:
        browser = await pw.chromium.connect_over_cdp(CDP_URL)
    except Exception as e:
        print(f"[dispatch] ERROR: Cannot connect to Chrome: {e}")
        print("[dispatch] Make sure Chrome is running with Run_Atlas_Chrome.bat")
        sys.exit(1)
    
    print("[dispatch] ✅ Connected to Chrome!")
    
    # Find Discord tab
    discord_page = None
    for context in browser.contexts:
        for page in context.pages:
            if "discord.com" in page.url:
                discord_page = page
                break
        if discord_page:
            break
    
    if not discord_page:
        print("[dispatch] No Discord tab found — opening Discord...")
        discord_page = await browser.contexts[0].new_page()
        await discord_page.goto(DISCORD_CHANNEL_URL)
        await asyncio.sleep(5)
    
    # Navigate to the correct channel
    if LEVEL3_QUESTION_ID not in discord_page.url:
        print(f"[dispatch] Navigating to #LEVEL3_QUESTION...")
        await discord_page.goto(DISCORD_CHANNEL_URL)
        await asyncio.sleep(3)
    
    print(f"[dispatch] Discord page: {discord_page.url}")
    return browser, discord_page, pw


async def type_question_humanly(page, text: str, dry_run: bool = False):
    """Type a question character by character with human-like delays."""
    # Find the textbox
    textbox = page.locator("div[role='textbox']").first
    
    # Click to focus
    await textbox.click()
    await asyncio.sleep(1)
    
    # Type character by character
    print(f"[dispatch] Typing ({len(text)} chars)...")
    for i, char in enumerate(text):
        delay = random.randint(TYPING_DELAY_MS_MIN, TYPING_DELAY_MS_MAX) / 1000.0
        await textbox.press_sequentially(char, delay=0)
        await asyncio.sleep(delay)
        
        # Occasional longer pause (simulates thinking)
        if random.random() < 0.05:  # 5% chance of pause
            await asyncio.sleep(random.uniform(0.5, 2.0))
        
        # Progress every 50 chars
        if (i + 1) % 50 == 0:
            print(f"[dispatch]   ...typed {i+1}/{len(text)} chars")
    
    # Wait before sending
    await asyncio.sleep(POST_TYPE_WAIT_SEC)
    
    if dry_run:
        print(f"[dispatch] DRY RUN — NOT pressing Enter")
        # Clear the typed text
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Backspace")
        return None
    
    # Press Enter to send
    await page.keyboard.press("Enter")
    print(f"[dispatch] ✅ Message sent!")
    await asyncio.sleep(2)
    
    # Try to capture the message ID from the last message
    # (We'll use timestamp as identifier since msg ID is in DOM)
    return datetime.now(timezone.utc).isoformat()


async def harvest_replies(page, queue: list) -> int:
    """Check for admin replies to our sent questions."""
    sent_questions = [q for q in queue if q.get("status") == "sent"]
    if not sent_questions:
        return 0
    
    print(f"[dispatch] Checking replies for {len(sent_questions)} sent questions...")
    
    # Use Discord's API via the page context to check for replies
    # This reads recent messages and looks for replies to our messages
    harvest_js = """
    async () => {
        const channelId = '%s';
        const token = (() => {
            let t = null;
            const iframe = document.createElement('iframe');
            iframe.style.display = 'none';
            document.body.appendChild(iframe);
            const ls = iframe.contentWindow.localStorage;
            try { t = JSON.parse(ls.getItem('token')); } catch {}
            iframe.remove();
            return t;
        })();
        
        if (!token) return { ok: false, error: 'no_token' };
        
        const resp = await fetch(
            `https://discord.com/api/v9/channels/${channelId}/messages?limit=50`,
            { headers: { 'Authorization': token } }
        );
        
        if (!resp.ok) return { ok: false, status: resp.status };
        
        const msgs = await resp.json();
        return {
            ok: true,
            messages: msgs.map(m => ({
                id: m.id,
                content: m.content,
                author: m.author.username,
                timestamp: m.timestamp,
                reactions: m.reactions ? m.reactions.map(r => r.emoji.name) : [],
                referenced_message: m.referenced_message ? {
                    id: m.referenced_message.id,
                    content: m.referenced_message.content
                } : null
            }))
        };
    }
    """ % LEVEL3_QUESTION_ID
    
    try:
        result = await page.evaluate(harvest_js)
        if not result.get("ok"):
            print(f"[dispatch] Reply harvest failed: {result}")
            return 0
        
        messages = result.get("messages", [])
        updates = 0
        
        for q in sent_questions:
            q_text_full = q.get("question_text") or q.get("question", "")
            q_text_clean = "".join(c for c in q_text_full[:60].lower() if c.isalnum())
            
            for msg in messages:
                # 1. Check if it's a direct text reply to our question
                ref = msg.get("referenced_message")
                ref_clean = ""
                if ref:
                    ref_clean = "".join(c for c in ref.get("content", "")[:60].lower() if c.isalnum())
                    
                if ref_clean and (q_text_clean in ref_clean or ref_clean in q_text_clean):
                    author = msg.get("author", "unknown")
                    reply_text = msg.get("content", "")
                    
                    q["status"] = "answered"
                    q["admin_reply"] = reply_text
                    q["admin_name"] = author
                    q["replied_at"] = msg.get("timestamp", "")
                    q["action_taken"] = "pending_review"
                    updates += 1
                    
                    print(f"[dispatch] 📥 Text reply found for [{q.get('id', 'q')}]!")
                    print(f"[dispatch]   From: {author}")
                    print(f"[dispatch]   Reply: {reply_text[:100]}...")
                    break # Move to next question
                    
                # 2. Check if our own message has emoji reactions
                m_clean = "".join(c for c in msg.get("content", "")[:60].lower() if c.isalnum())
                if m_clean and (q_text_clean in m_clean or m_clean in q_text_clean):
                    reactions = msg.get("reactions", [])
                    if reactions:
                        reaction_str = " ".join(reactions)
                        q["status"] = "answered"
                        q["admin_reply"] = f"[REACTION] {reaction_str}"
                        q["admin_name"] = "Admin (Reaction)"
                        q["replied_at"] = msg.get("timestamp", "")
                        q["action_taken"] = "pending_review"
                        updates += 1
                        
                        print(f"[dispatch] 📥 Emoji reaction found for [{q.get('id', 'q')}]!")
                        print(f"[dispatch]   Reaction: {reaction_str}")
                        break # Move to next question
        
        if updates:
            save_queue(queue)
            print(f"[dispatch] ✅ Updated {updates} questions with admin replies")
        else:
            print(f"[dispatch] No new replies found (checked {len(messages)} messages)")
        
        return updates
    
    except Exception as e:
        print(f"[dispatch] Reply harvest error: {e}")
        return 0

async def harvest_full_chat(page, since_date_str: str, until_date_str: str = None):
    """Fetch all messages from the channel within a date range (YYYY-MM-DD)."""
    until_str = until_date_str or datetime.now().strftime("%Y-%m-%d")
    print(f"\n[dispatch] 📥 Pulling all chat messages from {since_date_str} to {until_str}...")
    
    try:
        since_time = datetime.strptime(since_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        # For the JS untilTime, we want the end of the day
        until_time_str = f"{until_str} 23:59:59"
    except ValueError:
        print("[dispatch] Invalid date format. Use YYYY-MM-DD")
        return

    pull_js = """
    async (args) => {
        const { channelId, sinceDateIso, untilDateIso } = args;
        const sinceTime = new Date(sinceDateIso).getTime();
        const untilTime = untilDateIso ? new Date(untilDateIso).getTime() : Date.now();
        
        // Improved token extraction
        const token = (() => {
            try {
                // Method 1: iframe hack
                const iframe = document.createElement('iframe');
                iframe.style.display = 'none';
                document.body.appendChild(iframe);
                const t = iframe.contentWindow.localStorage.getItem('token');
                iframe.remove();
                if (t) return JSON.parse(t);
            } catch(e) {}
            
            try {
                // Method 2: webpack chunk (Discord Desktop/Web internals)
                return (window.webpackChunkdiscord_app.push([[''],{},e=>{m=[];for(let c in e.c)m.push(e.c[c])}]),m).find(m=>m?.exports?.default?.getToken).exports.default.getToken();
            } catch(e) {}
            
            return null;
        })();
        
        if (!token) return { ok: false, error: 'no_token_found' };
        
        const fetchData = (url) => {
            return new Promise((resolve, reject) => {
                const xhr = new XMLHttpRequest();
                xhr.open('GET', url);
                xhr.setRequestHeader('Authorization', token);
                xhr.setRequestHeader('Content-Type', 'application/json');
                xhr.onload = () => {
                    if (xhr.status >= 200 && xhr.status < 300) resolve(JSON.parse(xhr.responseText));
                    else reject({ status: xhr.status, text: xhr.responseText });
                };
                xhr.onerror = () => reject({ error: 'XHR_error' });
                xhr.send();
            });
        };
        
        let allMessages = [];
        let beforeId = null;
        let keepFetching = true;
        
        while (keepFetching) {
            let url = `https://discord.com/api/v9/channels/${channelId}/messages?limit=100`;
            if (beforeId) url += `&before=${beforeId}`;
            
            try {
                const msgs = await fetchData(url);
                if (!msgs || msgs.length === 0) break;
                
                for (const m of msgs) {
                    const msgTime = new Date(m.timestamp).getTime();
                    if (msgTime < sinceTime) {
                        keepFetching = false;
                        break;
                    }
                    if (msgTime <= untilTime) {
                        allMessages.push(m);
                    }
                }
                beforeId = msgs[msgs.length - 1].id;
                
                if (allMessages.length % 500 === 0 || allMessages.length < 500) {
                    console.log(`[progress] Fetched ${allMessages.length} messages total...`);
                }
                
                // Wait to avoid rate limits
                await new Promise(r => setTimeout(r, 800));
            } catch (e) {
                return { ok: false, error: 'fetch_failed', detail: e };
            }
        }
        
        // Reverse array so oldest messages are first
        allMessages.reverse();
        return { ok: true, messages: allMessages };
    }
    """
    
    try:
        result = await page.evaluate(pull_js, {
            "channelId": LEVEL3_QUESTION_ID, 
            "sinceDateIso": since_time.isoformat(),
            "untilDateIso": until_time_str
        })
        if not result.get("ok"):
            print(f"[dispatch] Chat pull failed: {result}")
            sys.exit(1)
            
        messages = result.get("messages", [])
        if not messages:
            print(f"[dispatch] No messages found between {since_date_str} and {until_str}")
            sys.exit(1)
            
        print(f"[dispatch] ✅ Successfully fetched {len(messages)} messages! (Range: {since_date_str} to {until_str})")
        
        out_dir = PROJECT_ROOT / "discord"
        out_dir.mkdir(exist_ok=True)
        # Use both dates in filename for clarity
        range_tag = f"{since_date_str}_to_{until_str}"
        out_file = out_dir / f"harvest_{range_tag}.json"
        
        out_file.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[dispatch] 💾 Saved chat to: {out_file.relative_to(PROJECT_ROOT)}")
        
    except Exception as e:
        print(f"[dispatch] Chat pull error: {e}")

async def trigger_rule_processor():
    """Run the rule processor immediately to update golden_rules.md with harvested answers."""
    print(f"\n[dispatch] ✨ Triggering atlas_discord_rule_processor.py to update rules...")
    try:
        subprocess.run([sys.executable, "atlas_discord_rule_processor.py"], check=False)
        print(f"[dispatch] ✨ Rule update complete!")
    except Exception as e:
        print(f"[dispatch] Failed to trigger rule processor: {e}")


async def run_dispatcher(args):
    """Main dispatcher loop."""
    queue = load_queue()
    pending = [q for q in queue if q.get("status") == "pending"]
    sent_today = count_sent_today(queue)
    
    print("=" * 60)
    print("[dispatch] Atlas Stealth Question Dispatcher v1.0")
    print(f"[dispatch] Mode: {'DRY RUN' if args.dry_run else 'PRODUCTION'}")
    print(f"[dispatch] Channel: #LEVEL3_QUESTION ({LEVEL3_QUESTION_ID})")
    print(f"[dispatch] Queue: {len(pending)} pending, {sent_today} sent today")
    print(f"[dispatch] Wait: {args.wait} min between questions")
    print(f"[dispatch] Max today: {args.max} (limit: {MAX_QUESTIONS_PER_DAY})")
    print("=" * 60)
    
    if args.harvest_only:
        print("[dispatch] HARVEST-ONLY mode — checking for replies once...")
        browser, page, pw = await connect_to_discord()
        if page:
            updates = await harvest_replies(page, queue)
            if updates > 0 and not args.dry_run:
                await trigger_rule_processor()
        await pw.stop()
        return
        
    if args.pull_chat_since:
        until_str = args.pull_chat_until or datetime.now().strftime("%Y-%m-%d")
        print(f"[dispatch] PULL-CHAT mode — fetching messages from {args.pull_chat_since} to {until_str}")
        browser, page, pw = await connect_to_discord()
        if page:
            await harvest_full_chat(page, args.pull_chat_since, args.pull_chat_until)
        await pw.stop()
        return
    
    if args.listen:
        print("[dispatch] LISTEN mode — continuously monitoring for admin replies in real-time...")
        browser, page, pw = await connect_to_discord()
        if not page:
            return
            
        print("[dispatch] Ear to the ground. Press Ctrl+C to stop.")
        try:
            while True:
                queue = load_queue()  # reload every loop in case queue changes
                updates = await harvest_replies(page, queue)
                if updates > 0 and not args.dry_run:
                    await trigger_rule_processor()
                # Fast polling for real-time feel
                await asyncio.sleep(5)
        except KeyboardInterrupt:
            print("\n[dispatch] Listen mode stopped.")
        finally:
            await pw.stop()
        return
    
    if not pending:
        print("[dispatch] No pending questions in queue.")
        print("[dispatch] Run: python atlas_question_generator.py first")
        return
    
    remaining_today = min(args.max, MAX_QUESTIONS_PER_DAY - sent_today)
    if remaining_today <= 0:
        print(f"[dispatch] Daily limit reached ({sent_today}/{MAX_QUESTIONS_PER_DAY})")
        return
    
    to_send = pending[:remaining_today]
    print(f"[dispatch] Will send {len(to_send)} questions this session")
    
    # Connect to Discord
    browser, page, pw = await connect_to_discord()
    if not page:
        await pw.stop()
        return
    
    # Send questions
    for i, question in enumerate(to_send):
        text = question.get("question_text") or question.get("question", "")
        
        print(f"\n{'─' * 50}")
        q_id = question.get("id", question.get("rule_topic", f"q{i+1}"))
        print(f"[dispatch] [{i+1}/{len(to_send)}] Sending: {q_id}")
        print(f"[dispatch] Text: {text[:80]}...")
        
        sent_time = await type_question_humanly(page, text, dry_run=args.dry_run)
        
        if not args.dry_run and sent_time:
            # Update queue
            question["status"] = "sent"
            question["sent_at"] = sent_time
            save_queue(queue)
            print(f"[dispatch] ✅ [{q_id}] sent and queue updated")
        
        # Wait before next question
        if i < len(to_send) - 1:
            jitter = random.randint(10, 60)
            wait_sec = (args.wait * 60) + jitter
            print(f"[dispatch] ⏳ Waiting {wait_sec // 60}m {wait_sec % 60}s before next...")
            
            # During wait, periodically check for replies
            elapsed = 0
            while elapsed < wait_sec:
                chunk = min(REPLY_CHECK_INTERVAL_SEC, wait_sec - elapsed)
                await asyncio.sleep(chunk)
                elapsed += chunk
                
                # Check for replies to previously sent questions
                if elapsed % REPLY_CHECK_INTERVAL_SEC == 0:
                    await harvest_replies(page, queue)
    
    # Final reply check
    print(f"\n{'─' * 50}")
    print("[dispatch] Final reply check...")
    await harvest_replies(page, queue)
    
    # Summary
    queue = load_queue()  # Reload for latest state
    sent = [q for q in queue if q.get("status") == "sent"]
    answered = [q for q in queue if q.get("status") == "answered"]
    pending_left = [q for q in queue if q.get("status") == "pending"]
    
    print(f"\n{'=' * 60}")
    print(f"[dispatch] SESSION COMPLETE")
    print(f"  📤 Sent: {len(to_send)}")
    print(f"  📥 Answered: {len(answered)}")
    print(f"  ⏳ Awaiting reply: {len(sent)}")
    print(f"  📋 Still pending: {len(pending_left)}")
    print(f"{'=' * 60}")
    
    await pw.stop()


def main():
    parser = argparse.ArgumentParser(description="Atlas Stealth Question Dispatcher")
    parser.add_argument("--dry-run", action="store_true",
                        help="Type questions but don't press Enter")
    parser.add_argument("--max", type=int, default=5,
                        help="Max questions to send this session (default: 5)")
    parser.add_argument("--wait", type=int, default=DEFAULT_WAIT_MINUTES,
                        help=f"Minutes between questions (default: {DEFAULT_WAIT_MINUTES})")
    parser.add_argument("--harvest-only", action="store_true",
                        help="Only check for replies, don't send questions")
    parser.add_argument("--pull-chat-since", type=str, metavar="YYYY-MM-DD",
                        help="Pull messages from this date (From)")
    parser.add_argument("--pull-chat-until", type=str, metavar="YYYY-MM-DD",
                        help="Pull messages until this date (To)")
    parser.add_argument("--listen", action="store_true",
                        help="Real-time listen mode: continuously poll for replies and Auto-Trigger rules update")
    args = parser.parse_args()
    
    # Note: Do NOT set WindowsSelectorEventLoopPolicy — it breaks Playwright subprocess creation.
    # Python 3.10+ on Windows defaults to ProactorEventLoopPolicy which works correctly.
    try:
        asyncio.run(run_dispatcher(args))
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    import sys
    main()
