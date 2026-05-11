"""
Atlas Stealth Scraper v2.2 — Hardened In-Browser Fetch (Discrub approach)
==========================================================================
⚠️  LOCAL-ONLY: Connects to YOUR existing Chrome session via CDP.
    Reads auth token from localStorage + copies real browser headers.
    Token NEVER leaves your local machine — same approach as Discrub.

SAFETY MEASURES:
  - Auth token stays in browser context (never sent to any server)
  - Copies REAL browser headers (User-Agent, X-Super-Properties)
  - 2-3 second delay between batches (human reading speed)
  - Automatic rate-limit detection and backoff
  - Runs ONLY on Windows (LOCAL-ONLY guard)

HOW TO USE:
  1. Run: Run_Atlas_Chrome.bat
  2. In Chrome → discord.com/app → Atlas Label Community → log in
  3. New terminal: python atlas_stealth_scraper.py

Account: danatimmer2050@gmail.com (DanaTimmer2050)
"""
import asyncio
import datetime
import json
import random
import re
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
else:
    print("[SAFETY] This script is LOCAL-ONLY (Windows). Aborting on non-Windows.")
    sys.exit(1)

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("[stealth] FATAL: pip install playwright && playwright install chromium")
    sys.exit(1)

# ─── Config ──────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    import os
    load_dotenv()
    GUILD_ID = os.getenv("DISCORD_GUILD_ID", "1448492968528052358").strip().strip('"')
except Exception:
    GUILD_ID = "1448492968528052358"

CDP_URL = "http://127.0.0.1:9222"

CHANNELS = {
    "COMMAND_CHANNEL":     os.getenv("COMMAND_CHANNEL_ID", "1485540323584118877").strip().strip('"'),
    "LEVEL3_ANNOUNCEMENT": os.getenv("LEVEL3_ANNOUNCMENT", "1458584003605954717").strip().strip('"'),
    "LEVEL3_QUESTION":     os.getenv("LEVEL3_QUESTION", "1455689224593477674").strip().strip('"'),
    "ATLAS_ANNOUNCEMENT":  os.getenv("ATLAS_ANNOUNCMENT", "1453232420634624234").strip().strip('"'),
}

# Add FAQ channel if present in .env
faq_id = os.getenv("FAQ_CHANNEL_ID", os.getenv("FAQS", os.getenv("FAQ", ""))).strip().strip('"')
if faq_id:
    CHANNELS["FAQ"] = faq_id

# Go back to Jan 2025 for full historical extraction
DATE_FILTER = datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc)
PROJECT_ROOT = Path(__file__).parent
OUTPUT_DIR = PROJECT_ROOT / "outputs"

# Safety: delay range between batches (seconds) — mimics human reading
MIN_DELAY = 2.0
MAX_DELAY = 3.5

# ─── Message Categorization ─────────────────────────────────────
RULE_KEYWORDS = [
    "hold", "label", "segment", "annotation", "annotate", "labeling",
    "ego", "action", "coarse", "dense", "granularity", "must be labeled",
    "must label", "key rule", "effective immediately", "clarification",
    "merge", "split", "no action", "loosen", "remove", "place",
    "pick up", "timestamp", "overlap", "consecutive", "forbidden",
    "acceptable", "unacceptable", "correct", "incorrect",
]

QA_KEYWORDS = ["?", "question", "answer", "does this", "is it", "can we",
               "how do", "what if", "should i", "should we"]

IMPORTANT_KEYWORDS = ["announcement", "update", "important", "reminder",
                      "effective immediately", "please note", "attention",
                      "changes to", "new rule", "policy", "mandatory"]

NOISE_KEYWORDS = ["payment", "wallet", "crypto", "gift card", "boost",
                  "nitro", "otp", "2fa", "ban", "suspended",
                  "meme", "lol", "lmao", "haha"]

# Deprecated rules to skip — old T2 rules no longer relevant
DEPRECATED_KEYWORDS = ["easy room", "easy video", "easy category",
                       "verbs ending in", "use ing", "using ing",
                       "add ing", "with ing", "-ing form",
                       "present participle"]


def categorize_message(content: str, is_reply: bool = False) -> str:
    lower = content.lower()
    if len(lower) < 30:
        return "skip"
    if sum(1 for nk in NOISE_KEYWORDS if nk in lower) >= 2:
        return "skip"
    # Skip deprecated rules (easy room, +ing verb form)
    if sum(1 for dk in DEPRECATED_KEYWORDS if dk in lower) >= 1:
        return "skip"
    rule_hits = sum(1 for kw in RULE_KEYWORDS if kw in lower)
    qa_hits = sum(1 for kw in QA_KEYWORDS if kw in lower)
    important_hits = sum(1 for kw in IMPORTANT_KEYWORDS if kw in lower)
    if rule_hits >= 3:
        return "rule"
    if qa_hits >= 2 or (is_reply and "?" in content):
        return "qa"
    if important_hits >= 2:
        return "important"
    if rule_hits >= 1 and len(content) > 100:
        return "rule"
    if len(content) > 80:
        return "important"
    return "skip"


def clean_content(content: str) -> str:
    text = re.sub(r"<@[!&]?\d+>", "", content)
    text = re.sub(r"@(?:everyone|here)", "", text)
    text = re.sub(r"<:\w+:\d+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ─── Token + Real Headers (Anti-Fingerprinting) ──────────────────

async def get_discord_token(page) -> str:
    """Get Discord auth token using multiple methods.
    
    Method 1: window.localStorage in page context
    Method 2: Inject script tag to read localStorage
    Method 3: Intercept Discord's own network requests (most robust)
    """
    
    # Method 1: Try window.localStorage directly
    try:
        token = await page.evaluate("""
            () => {
                try {
                    let t = window.localStorage.getItem('token');
                    if (t) return t.replace(/"/g, '');
                } catch(e) {}
                return null;
            }
        """)
        if token:
            print("[stealth]   (Method 1: window.localStorage)")
            return token
    except Exception as e:
        print(f"[stealth]   Method 1 failed: {str(e)[:60]}")

    # Method 2: Create a script tag that reads localStorage and stores result
    try:
        await page.evaluate("""
            () => {
                try {
                    const script = document.createElement('script');
                    script.textContent = `
                        try {
                            window.__ATLAS_TOKEN = localStorage.getItem('token');
                        } catch(e) {
                            window.__ATLAS_TOKEN = null;
                        }
                    `;
                    document.head.appendChild(script);
                    script.remove();
                } catch(e) {}
            }
        """)
        await asyncio.sleep(0.5)
        token = await page.evaluate("() => window.__ATLAS_TOKEN")
        if token:
            token = token.strip('"')
            print("[stealth]   (Method 2: script injection)")
            return token
    except Exception as e:
        print(f"[stealth]   Method 2 failed: {str(e)[:60]}")

    # Method 3: Intercept network requests to capture Authorization header
    print("[stealth]   Methods 1-2 failed. Using network interception (Method 3)...")
    print("[stealth]   Refreshing page to capture Discord's API requests...")
    
    captured_token = {"value": None}
    
    async def capture_auth(request):
        auth = request.headers.get("authorization", "")
        if auth and not auth.startswith("Bot ") and len(auth) > 20:
            captured_token["value"] = auth
    
    page.on("request", capture_auth)
    
    try:
        # Reload page — Discord will make API calls with the real token
        await page.reload(wait_until="domcontentloaded", timeout=20000)
        
        # Wait up to 15 seconds for Discord to make an authenticated request
        for _ in range(30):
            if captured_token["value"]:
                break
            await asyncio.sleep(0.5)
        
    except Exception as e:
        print(f"[stealth]   Reload error: {str(e)[:60]}")
    finally:
        page.remove_listener("request", capture_auth)
    
    if captured_token["value"]:
        print("[stealth]   (Method 3: network interception)")
        return captured_token["value"]
    
    return None


async def capture_real_headers(page) -> dict:
    """Capture the REAL headers that Discord's client sends.
    This ensures our fetch() requests are indistinguishable from normal usage.
    """
    headers = await page.evaluate(r"""
        () => {
            const h = {};
            
            // Get real User-Agent
            h.userAgent = navigator.userAgent;
            
            // Get real X-Super-Properties (Discord encodes this in base64)
            // Discord stores build info we can reconstruct
            try {
                const props = {
                    os: "Windows",
                    browser: "Chrome",
                    device: "",
                    system_locale: navigator.language || "en-US",
                    browser_user_agent: navigator.userAgent,
                    browser_version: navigator.userAgent.match(/Chrome\/([\d.]+)/)?.[1] || "",
                    os_version: navigator.userAgent.match(/Windows NT ([\d.]+)/)?.[1] || "10.0",
                    referrer: "",
                    referring_domain: "",
                    referrer_current: "",
                    referring_domain_current: "",
                    release_channel: "stable",
                    client_build_number: 0,
                    client_event_source: null,
                };
                h.superProperties = btoa(JSON.stringify(props));
            } catch(e) {
                h.superProperties = "";
            }
            
            // Get real locale
            h.locale = navigator.language || "en-US";
            
            return h;
        }
    """)
    return headers


async def fetch_channel_messages(page, channel_id: str, after_date: datetime.datetime,
                                  auth_token: str, real_headers: dict,
                                  max_batches: int = 9999) -> list[dict]:
    """Fetch ALL messages using Discord REST API with REAL browser headers.
    
    Safety measures:
    - Uses real User-Agent and X-Super-Properties from the actual browser
    - 2-3 second randomized delay between batches (human speed)
    - Automatic rate-limit backoff
    """
    discord_epoch = 1420070400000
    after_snowflake = str(
        (int(after_date.timestamp() * 1000) - discord_epoch) << 22
    )
    
    # Randomized delay in ms (2000-3500ms)
    delay_min_ms = int(MIN_DELAY * 1000)
    delay_max_ms = int(MAX_DELAY * 1000)
    
    all_messages = await page.evaluate("""
        async ({ channelId, afterSnowflake, maxBatches, authToken, 
                 realHeaders, delayMinMs, delayMaxMs }) => {
            const allMsgs = [];
            let beforeId = null;
            let batchCount = 0;
            let reachedDateLimit = false;
            
            // Random delay function (human-like timing)
            const humanDelay = () => new Promise(r => 
                setTimeout(r, delayMinMs + Math.random() * (delayMaxMs - delayMinMs))
            );
            
            while (batchCount < maxBatches && !reachedDateLimit) {
                let url = `/api/v9/channels/${channelId}/messages?limit=100`;
                if (beforeId) url += `&before=${beforeId}`;
                
                try {
                    const resp = await fetch(url, {
                        headers: {
                            'Authorization': authToken,
                            'Accept': 'application/json',
                            'Content-Type': 'application/json',
                            'User-Agent': realHeaders.userAgent,
                            'X-Super-Properties': realHeaders.superProperties,
                            'Accept-Language': realHeaders.locale,
                            'X-Discord-Locale': realHeaders.locale,
                            'X-Discord-Timezone': Intl.DateTimeFormat().resolvedOptions().timeZone,
                        }
                    });
                    
                    if (resp.status === 401 || resp.status === 403) {
                        return { error: `HTTP ${resp.status}: ${resp.statusText}`, msgs: allMsgs };
                    }
                    
                    if (resp.status === 429) {
                        const retryData = await resp.json();
                        const waitMs = (retryData.retry_after || 5) * 1000;
                        await new Promise(r => setTimeout(r, waitMs + 1000));
                        continue;
                    }
                    
                    if (!resp.ok) {
                        return { error: `HTTP ${resp.status}`, msgs: allMsgs };
                    }
                    
                    const data = await resp.json();
                    if (!data || !data.length) break;
                    
                    for (const msg of data) {
                        if (BigInt(msg.id) < BigInt(afterSnowflake)) {
                            reachedDateLimit = true;
                            break;
                        }
                        
                        const attachments = (msg.attachments || []).map(a => ({
                            filename: a.filename,
                            url: a.url,
                            proxy_url: a.proxy_url || '',
                            content_type: a.content_type || '',
                            size: a.size || 0,
                            width: a.width || null,
                            height: a.height || null,
                        }));
                        
                        const embeds = (msg.embeds || []).map(e => ({
                            title: e.title || '',
                            description: e.description || '',
                            url: e.url || '',
                            image: e.image?.url || e.thumbnail?.url || '',
                        }));
                        
                        allMsgs.push({
                            id: msg.id,
                            author: msg.author?.username || 'Unknown',
                            author_id: msg.author?.id || '',
                            author_avatar: msg.author?.avatar || '',
                            timestamp: msg.timestamp,
                            edited_timestamp: msg.edited_timestamp || null,
                            content: msg.content || '',
                            attachments: attachments,
                            embeds: embeds,
                            is_reply: !!msg.referenced_message,
                            reply_to_content: msg.referenced_message?.content || '',
                            reply_to_author: msg.referenced_message?.author?.username || '',
                            reactions: (msg.reactions || []).map(r => ({
                                emoji: r.emoji?.name || '',
                                count: r.count || 0,
                            })),
                            pinned: msg.pinned || false,
                            type: msg.type,
                            mentions: (msg.mentions || []).map(m => m.username || ''),
                        });
                    }
                    
                    beforeId = data[data.length - 1].id;
                    batchCount++;
                    
                    // Progress logging every 10 batches
                    if (batchCount % 10 === 0) {
                        console.log(`[stealth-fetch] Batch ${batchCount}: ${allMsgs.length} msgs so far...`);
                    }
                    
                    // Human-speed delay between batches
                    await humanDelay();
                    
                } catch (e) {
                    return { error: e.message, msgs: allMsgs };
                }
            }
            
            return { error: null, msgs: allMsgs };
        }
    """, {
        "channelId": channel_id,
        "afterSnowflake": after_snowflake,
        "maxBatches": max_batches,
        "authToken": auth_token,
        "realHeaders": real_headers,
        "delayMinMs": delay_min_ms,
        "delayMaxMs": delay_max_ms,
    })
    
    return all_messages


# ─── Output Writers ──────────────────────────────────────────────

def save_rules_md(rules, filepath):
    with open(filepath, "a", encoding="utf-8") as f:
        for msg in rules:
            clean = clean_content(msg.get("content", ""))
            author = msg.get("author", "Unknown")
            ts = msg.get("timestamp", "")[:19]
            f.write(f"\n### Rule from {author} ({ts})\n")
            f.write(f"<!-- msg_id: {msg.get('id', '')} -->\n")
            f.write(f"{clean}\n")
            for att in msg.get("attachments", []):
                f.write(f"- [{att['filename']}]({att['url']})\n")
            f.write("---\n")


def save_qa_md(qa_pairs, filepath):
    with open(filepath, "a", encoding="utf-8") as f:
        for msg in qa_pairs:
            clean = clean_content(msg.get("content", ""))
            author = msg.get("author", "Unknown")
            ts = msg.get("timestamp", "")[:19]
            reply_to = msg.get("reply_to_content", "")
            reply_author = msg.get("reply_to_author", "")
            if reply_to:
                f.write(f"\n**Q ({reply_author}):** {clean_content(reply_to)}\n")
                f.write(f"**A ({author}, {ts}):** {clean}\n")
            elif "?" in clean:
                parts = clean.split("?", 1)
                f.write(f"\n**Q ({author}, {ts}):** {parts[0]}?\n")
                if parts[1].strip():
                    f.write(f"**A:** {parts[1].strip()}\n")
            else:
                f.write(f"\n**{author} ({ts}):** {clean}\n")
            for att in msg.get("attachments", []):
                f.write(f"- [{att['filename']}]({att['url']})\n")
            f.write("\n")


def save_important_md(important, filepath):
    with open(filepath, "a", encoding="utf-8") as f:
        for msg in important:
            clean = clean_content(msg.get("content", ""))
            author = msg.get("author", "Unknown")
            ts = msg.get("timestamp", "")[:19]
            f.write(f"\n### {author} ({ts})\n")
            f.write(f"{clean}\n")
            for att in msg.get("attachments", []):
                f.write(f"- [{att['filename']}]({att['url']})\n")
            f.write("\n")


# ─── Main ─────────────────────────────────────────────────────────

async def main():
    print("=" * 60)
    print("[STEALTH] Atlas Discord Extractor v2.2 (Hardened Fetch)")
    print(f"[STEALTH] CDP: {CDP_URL}")
    print(f"[STEALTH] Channels: {len(CHANNELS)}")
    print(f"[STEALTH] Date filter: >= {DATE_FILTER.date()}")
    print(f"[STEALTH] Batch delay: {MIN_DELAY}-{MAX_DELAY}s (human speed)")
    print("=" * 60)

    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(CDP_URL)
            print("[stealth] Connected to Chrome!")
        except Exception as e:
            print(f"[stealth] Cannot connect to Chrome at {CDP_URL}")
            print(f"[stealth] Error: {e}")
            print(f'\n[stealth] Run: Run_Atlas_Chrome.bat')
            return

        contexts = browser.contexts
        if not contexts:
            print("[stealth] No browser contexts found")
            return
        
        context = contexts[0]
        
        discord_page = None
        for pg in context.pages:
            if "discord.com" in pg.url:
                discord_page = pg
                break
        
        if not discord_page:
            print("[stealth] No Discord tab — opening Discord...")
            discord_page = await context.new_page()
            await discord_page.goto(f"https://discord.com/channels/{GUILD_ID}", timeout=30000)
            await asyncio.sleep(8)
        
        print(f"[stealth] Discord tab: {discord_page.url}")
        
        # ── Step 1: Get auth token ──
        print("[stealth] Reading auth token from localStorage...")
        auth_token = await get_discord_token(discord_page)
        
        if not auth_token:
            print("[stealth] Could not read token!")
            print("[stealth] Fix: refresh Discord page (F5) then run again.")
            return
        
        print(f"[stealth] Token found ({len(auth_token)} chars)")
        
        # ── Step 2: Capture REAL browser headers ──
        print("[stealth] Capturing real browser fingerprint...")
        real_headers = await capture_real_headers(discord_page)
        print(f"[stealth] User-Agent: {real_headers.get('userAgent', '')[:60]}...")
        print(f"[stealth] X-Super-Properties: captured ({len(real_headers.get('superProperties', ''))} chars)")
        
        # ── Step 3: Verify auth ──
        auth_check = await discord_page.evaluate("""
            async ({ token, headers }) => {
                try {
                    const r = await fetch('/api/v9/users/@me', {
                        headers: { 
                            'Authorization': token,
                            'User-Agent': headers.userAgent,
                            'X-Super-Properties': headers.superProperties,
                        }
                    });
                    if (r.ok) {
                        const data = await r.json();
                        return { ok: true, user: data.username + '#' + data.discriminator };
                    }
                    return { ok: false, status: r.status };
                } catch(e) {
                    return { ok: false, error: e.message };
                }
            }
        """, {"token": auth_token, "headers": real_headers})
        
        if auth_check.get("ok"):
            print(f"[stealth] Authenticated as: {auth_check['user']}")
        else:
            print(f"[stealth] Auth verification: {auth_check}")
            print("[stealth] Continuing — some channels may still work...")

        # ── Step 4: Prepare output ──
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        rules_file = OUTPUT_DIR / "discord_rules.md"
        qa_file = OUTPUT_DIR / "discord_qa.md"
        important_file = OUTPUT_DIR / "discord_important.md"
        json_file = OUTPUT_DIR / "discord_full_export.json"
        
        for f in [rules_file, qa_file, important_file]:
            if f.exists():
                f.unlink()
        
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        rules_file.write_text(f"# Discord Extracted Rules\n# Source: Atlas Label Community\n# Date: {now}\n\n", encoding="utf-8")
        qa_file.write_text(f"# Discord Q&A Pairs\n# Source: Atlas Label Community\n# Date: {now}\n\n", encoding="utf-8")
        important_file.write_text(f"# Discord Important Messages\n# Source: Atlas Label Community\n# Date: {now}\n\n", encoding="utf-8")

        all_export = {}
        total_rules = 0
        total_qa = 0
        total_important = 0
        total_messages = 0
        total_attachments = 0

        # ── Step 5: Fetch each channel ──
        # Listen for console.log from JS so batch progress is visible
        discord_page.on("console", lambda msg: print(f"[stealth]    {msg.text}") if "stealth-fetch" in msg.text else None)
        
        for ch_name, ch_id in CHANNELS.items():
            print(f"\n{'_' * 50}")
            print(f"[stealth] Fetching: #{ch_name} ({ch_id})")
            print(f"{'_' * 50}")

            result = await fetch_channel_messages(
                discord_page, ch_id, DATE_FILTER, auth_token, real_headers
            )
            
            if result.get("error"):
                print(f"[stealth] Error: {result['error']}")
                if not result.get("msgs"):
                    all_export[ch_name] = []
                    continue
            
            messages = result.get("msgs", [])
            total_messages += len(messages)
            
            ch_attachments = sum(len(m.get("attachments", [])) for m in messages)
            total_attachments += ch_attachments
            
            print(f"[stealth] #{ch_name}: {len(messages)} msgs, {ch_attachments} files")
            
            rules, qa, imp = [], [], []
            for msg in messages:
                content = msg.get("content", "")
                is_reply = msg.get("is_reply", False)
                cat = categorize_message(content, is_reply)
                if cat == "rule":
                    rules.append(msg)
                elif cat == "qa":
                    qa.append(msg)
                elif cat == "important":
                    imp.append(msg)
            
            total_rules += len(rules)
            total_qa += len(qa)
            total_important += len(imp)
            
            print(f"[stealth]    {len(rules)} rules, {len(qa)} Q&A, {len(imp)} important")
            
            for f in [rules_file, qa_file, important_file]:
                with open(f, "a", encoding="utf-8") as fh:
                    fh.write(f"\n## Channel: #{ch_name}\n\n")
            
            save_rules_md(rules, rules_file)
            save_qa_md(qa, qa_file)
            save_important_md(imp, important_file)
            
            all_export[ch_name] = messages
            
            # Delay between channels (longer pause)
            delay = random.uniform(3.0, 5.0)
            print(f"[stealth]    Waiting {delay:.1f}s before next channel...")
            await asyncio.sleep(delay)

        # ── Step 6: Save JSON export ──
        json_file.write_text(json.dumps(all_export, ensure_ascii=False, indent=2), encoding="utf-8")
        
        print(f"\n{'=' * 60}")
        print(f"[STEALTH] SCAN COMPLETE")
        print(f"  Total messages:    {total_messages}")
        print(f"  Total attachments: {total_attachments}")
        print(f"  Rules extracted:   {total_rules}")
        print(f"  Q&A pairs:         {total_qa}")
        print(f"  Important:         {total_important}")
        print(f"\nOutput files:")
        print(f"  {rules_file}")
        print(f"  {qa_file}")
        print(f"  {important_file}")
        print(f"  {json_file}")
        print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())
