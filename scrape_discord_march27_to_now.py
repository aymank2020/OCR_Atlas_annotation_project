"""
Targeted Discord scraper: March 27, 2026 to now
Connects to running Chrome via CDP, extracts auth token, fetches messages.
"""
import asyncio
import datetime
import json
import random
import re
import sys
import os
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("FATAL: pip install playwright && playwright install chromium")
    sys.exit(1)

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ─── Config ──────────────────────────────────────────────────────
CDP_URL = "http://127.0.0.1:9222"
GUILD_ID = "1448492968528052358"  # Atlas Label Community

# All important channels
CHANNELS = {
    "level-3-announcements": os.getenv("LEVEL3_ANNOUNCMENT", "1458584003605954717"),
    "level-3-questions":     os.getenv("LEVEL3_QUESTION", "1455689224593477674"),
    "atlas-announcements":   os.getenv("ATLAS_ANNOUNCMENT", "1453232420634624234"),
    "faqs":                  os.getenv("FAQS", "1480324076257149040"),
}

# March 27, 2026 start date
DATE_FILTER = datetime.datetime(2026, 3, 27, tzinfo=datetime.timezone.utc)

PROJECT_ROOT = Path(__file__).parent
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "discord_exports"

# Delays between batches (human-like)
MIN_DELAY = 2.0
MAX_DELAY = 3.5


# ─── Token extraction ────────────────────────────────────────────
async def get_discord_token(page) -> str:
    # Method 1: localStorage
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
            print("[scraper] Token found (localStorage)")
            return token
    except Exception as e:
        print(f"[scraper] localStorage failed: {str(e)[:60]}")

    # Method 2: script injection
    try:
        await page.evaluate("""
            () => {
                try {
                    const script = document.createElement('script');
                    script.textContent = `
                        try { window.__ATLAS_TOKEN = localStorage.getItem('token'); }
                        catch(e) { window.__ATLAS_TOKEN = null; }
                    `;
                    document.head.appendChild(script);
                    script.remove();
                } catch(e) {}
            }
        """)
        await asyncio.sleep(0.5)
        token = await page.evaluate("() => window.__ATLAS_TOKEN")
        if token:
            print("[scraper] Token found (script injection)")
            return token.strip('"')
    except Exception as e:
        print(f"[scraper] Script injection failed: {str(e)[:60]}")

    # Method 3: network interception
    print("[scraper] Using network interception...")
    captured = {"value": None}

    async def capture_auth(request):
        auth = request.headers.get("authorization", "")
        if auth and not auth.startswith("Bot ") and len(auth) > 20:
            captured["value"] = auth

    page.on("request", capture_auth)
    try:
        await page.reload(wait_until="domcontentloaded", timeout=20000)
        for _ in range(30):
            if captured["value"]:
                break
            await asyncio.sleep(0.5)
    except Exception as e:
        print(f"[scraper] Reload error: {str(e)[:60]}")
    finally:
        page.remove_listener("request", capture_auth)

    if captured["value"]:
        print("[scraper] Token found (network interception)")
        return captured["value"]

    return None


async def capture_real_headers(page) -> dict:
    return await page.evaluate(r"""
        () => {
            const h = {};
            h.userAgent = navigator.userAgent;
            try {
                const props = {
                    os: "Windows", browser: "Chrome", device: "",
                    system_locale: navigator.language || "en-US",
                    browser_user_agent: navigator.userAgent,
                    browser_version: navigator.userAgent.match(/Chrome\/([\d.]+)/)?.[1] || "",
                    os_version: navigator.userAgent.match(/Windows NT ([\d.]+)/)?.[1] || "10.0",
                    referrer: "", referring_domain: "",
                    referrer_current: "", referring_domain_current: "",
                    release_channel: "stable",
                    client_build_number: 0, client_event_source: null,
                };
                h.superProperties = btoa(JSON.stringify(props));
            } catch(e) { h.superProperties = ""; }
            h.locale = navigator.language || "en-US";
            return h;
        }
    """)


async def fetch_channel_messages(page, channel_id, after_date, auth_token, real_headers):
    discord_epoch = 1420070400000
    after_snowflake = str(
        (int(after_date.timestamp() * 1000) - discord_epoch) << 22
    )
    delay_min_ms = int(MIN_DELAY * 1000)
    delay_max_ms = int(MAX_DELAY * 1000)

    result = await page.evaluate("""
        async ({ channelId, afterSnowflake, authToken, realHeaders, delayMinMs, delayMaxMs }) => {
            const allMsgs = [];
            let beforeId = null;
            let batchCount = 0;
            let reachedDateLimit = false;
            const humanDelay = () => new Promise(r =>
                setTimeout(r, delayMinMs + Math.random() * (delayMaxMs - delayMinMs))
            );

            while (batchCount < 9999 && !reachedDateLimit) {
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
                        allMsgs.push({
                            id: msg.id,
                            author: msg.author?.username || 'Unknown',
                            author_id: msg.author?.id || '',
                            timestamp: msg.timestamp,
                            edited_timestamp: msg.edited_timestamp || null,
                            content: msg.content || '',
                            attachments: (msg.attachments || []).map(a => ({
                                filename: a.filename, url: a.url,
                                content_type: a.content_type || '',
                            })),
                            embeds: (msg.embeds || []).map(e => ({
                                title: e.title || '', description: e.description || '',
                                url: e.url || '',
                            })),
                            is_reply: !!msg.referenced_message,
                            reply_to_content: msg.referenced_message?.content?.slice(0, 500) || '',
                            reply_to_author: msg.referenced_message?.author?.username || '',
                            pinned: msg.pinned || false,
                            type: msg.type,
                        });
                    }

                    beforeId = data[data.length - 1].id;
                    batchCount++;
                    if (batchCount % 5 === 0) {
                        console.log(`[fetch] ch=${channelId} batch=${batchCount} msgs=${allMsgs.length}`);
                    }
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
        "authToken": auth_token,
        "realHeaders": real_headers,
        "delayMinMs": delay_min_ms,
        "delayMaxMs": delay_max_ms,
    })
    return result


# ─── Main ─────────────────────────────────────────────────────────
async def main():
    print("=" * 60)
    print("[SCRAPER] Discord March 27 -> Now")
    print(f"[SCRAPER] CDP: {CDP_URL}")
    print(f"[SCRAPER] Channels: {list(CHANNELS.keys())}")
    print(f"[SCRAPER] Date filter: >= {DATE_FILTER.date()}")
    print("=" * 60)

    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(CDP_URL)
            print("[scraper] Connected to Chrome!")
        except Exception as e:
            print(f"[scraper] Cannot connect: {e}")
            return

        contexts = browser.contexts
        if not contexts:
            print("[scraper] No browser contexts")
            return

        context = contexts[0]
        discord_page = None
        for pg in context.pages:
            if "discord.com" in pg.url:
                discord_page = pg
                break

        if not discord_page:
            print("[scraper] No Discord tab found")
            return

        print(f"[scraper] Discord tab: {discord_page.url}")

        # Get auth token
        print("[scraper] Reading auth token...")
        auth_token = await get_discord_token(discord_page)
        if not auth_token:
            print("[scraper] FAILED to get token! Refresh Discord and retry.")
            return
        print(f"[scraper] Token: {len(auth_token)} chars")

        # Get real headers
        real_headers = await capture_real_headers(discord_page)
        print(f"[scraper] Headers captured")

        # Verify auth
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
                        return { ok: true, user: data.username };
                    }
                    return { ok: false, status: r.status };
                } catch(e) { return { ok: false, error: e.message }; }
            }
        """, {"token": auth_token, "headers": real_headers})

        if auth_check.get("ok"):
            print(f"[scraper] Authenticated as: {auth_check['user']}")
        else:
            print(f"[scraper] Auth check: {auth_check}")
            print("[scraper] Continuing anyway...")

        # Listen for fetch progress logs
        discord_page.on("console", lambda msg: print(f"  {msg.text}") if "[fetch]" in msg.text else None)

        # Fetch each channel
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        all_data = {}
        total = 0

        for ch_name, ch_id in CHANNELS.items():
            print(f"\n{'─' * 50}")
            print(f"[scraper] Fetching #{ch_name} ({ch_id})")

            result = await fetch_channel_messages(
                discord_page, ch_id, DATE_FILTER, auth_token, real_headers
            )

            if result.get("error"):
                print(f"[scraper] Error: {result['error']}")

            messages = result.get("msgs", [])
            total += len(messages)
            print(f"[scraper] #{ch_name}: {len(messages)} messages")

            all_data[ch_name] = messages

            # Inter-channel delay
            await asyncio.sleep(random.uniform(3, 5))

        # Save combined output
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_file = OUTPUT_DIR / f"harvest_2026-03-27_to_now_{ts}.json"
        export = {
            "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "guild_id": GUILD_ID,
            "start_date": "2026-03-27",
            "end_date": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"),
            "channel_count": len(CHANNELS),
            "message_count": total,
            "channels": {name: len(msgs) for name, msgs in all_data.items()},
            "messages_by_channel": all_data,
        }
        out_file.write_text(json.dumps(export, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n{'=' * 60}")
        print(f"[SCRAPER] COMPLETE: {total} messages")
        for name, msgs in all_data.items():
            print(f"  #{name}: {len(msgs)}")
        print(f"\nSaved: {out_file}")
        print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())
