import os
import json
import time
import requests
import datetime
import re
from pathlib import Path
import re
from pathlib import Path
from dotenv import load_dotenv
import sys

# Try fetching Gemini Client (Universal approach)
try:
    from google import genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# ==============================================================================
# Atlas Stealth Scraper (Daemon Edition v3.0)
# ==============================================================================
# 0$ Cost: Uses Regex Logic instead of AI for parsing.
# Infinite Loop: Runs every 8 hours automatically.
# Incremental Fetch: Uses scraper_bookmarks.json to only download new messages.
# ==============================================================================

# Load environment variables
load_dotenv()
GUILD_ID = os.getenv("DISCORD_GUILD_ID", "1448492968528052358").strip().strip('"')

# Use Bot Token if available, otherwise User Token
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip().strip('"')
USER_TOKEN = os.getenv("DISCORD_USER_TOKEN", "").strip().strip('"')

# Try API Headers (Prefer User API with Stealth Headers, Fallback to Bot API)
if USER_TOKEN:
    AUTH_HEADER = USER_TOKEN
    print("[Daemon] Authenticating using User Token (Stealth Mode)...")
elif BOT_TOKEN:
    AUTH_HEADER = f"Bot {BOT_TOKEN}"
    print("[Daemon] Authenticating using official Bot Token...")
else:
    print("[Daemon] FATAL: Neither DISCORD_USER_TOKEN nor DISCORD_BOT_TOKEN found in .env")
    exit(1)

HEADERS = {
    'Authorization': AUTH_HEADER,
    'Accept': '*/*',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36'
}

CHANNELS = {
    "COMMAND_CHANNEL":     os.getenv("COMMAND_CHANNEL_ID", "1485540323584118877").strip().strip('"'),
    "LEVEL3_ANNOUNCEMENT": os.getenv("LEVEL3_ANNOUNCMENT", "1458584003605954717").strip().strip('"'),
    "LEVEL3_QUESTION":     os.getenv("LEVEL3_QUESTION", "1455689224593477674").strip().strip('"'),
    "ATLAS_ANNOUNCEMENT":  os.getenv("ATLAS_ANNOUNCMENT", "1453232420634624234").strip().strip('"'),
}

faq_id = os.getenv("FAQ_CHANNEL_ID", os.getenv("FAQS", os.getenv("FAQ", ""))).strip().strip('"')
if faq_id:
    CHANNELS["FAQ"] = faq_id

PROJECT_ROOT = Path(__file__).parent
OUTPUT_DIR = PROJECT_ROOT / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BOOKMARKS_FILE = OUTPUT_DIR / "scraper_bookmarks.json"

# --- Categorization Logic (0$ Cost AI) ---
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
DEPRECATED_KEYWORDS = ["easy room", "easy video", "easy category",
                       "verbs ending in", "use ing", "using ing",
                       "add ing", "with ing", "-ing form",
                       "present participle"]

def categorize_message(content: str, is_reply: bool = False) -> str:
    lower = content.lower()
    if len(lower) < 30: return "skip"
    if sum(1 for nk in NOISE_KEYWORDS if nk in lower) >= 2: return "skip"
    if sum(1 for dk in DEPRECATED_KEYWORDS if dk in lower) >= 1: return "skip"
    
    rule_hits = sum(1 for kw in RULE_KEYWORDS if kw in lower)
    qa_hits = sum(1 for kw in QA_KEYWORDS if kw in lower)
    important_hits = sum(1 for kw in IMPORTANT_KEYWORDS if kw in lower)
    
    if rule_hits >= 3: return "rule"
    if qa_hits >= 2 or (is_reply and "?" in content): return "qa"
    if important_hits >= 2: return "important"
    if rule_hits >= 1 and len(content) > 100: return "rule"
    if len(content) > 80: return "important"
    return "skip"

def clean_content(content: str) -> str:
    text = re.sub(r"<@[!&]?\d+>", "", content)
    text = re.sub(r"@(?:everyone|here)", "", text)
    text = re.sub(r"<:\w+:\d+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

# --- AI Intelligence Logic (Gemini Flash + Pro) ---

def process_with_ai(raw_messages):
    """
    Stage 2 & 3:
    Flash Cleans the raw messages.
    Pro Merges them into the dynamic rules file.
    """
    if not HAS_GENAI:
        print("[AI] Skipping Stage 2/3: google-genai library not installed.")
        return
        
    keys_pool = []
    pool_raw = os.getenv("GEMINI_API_KEYS_POOL", "")
    if pool_raw:
        keys_pool.extend([k.strip() for k in pool_raw.split(",") if k.strip() and k.strip() not in keys_pool])
    for env_k in ["GEMINI_API_KEY2", "GEMINI_API_KEY", "GEMINI_API_KEY_FALLBACK", "GOOGLE_API_KEY"]:
        v = os.getenv(env_k, "").strip().strip('"')
        if v and v not in keys_pool:
            keys_pool.append(v)
            
    if not keys_pool:
        print("[AI] Skipping Stage 2/3: No Gemini API keys found.")
        return

    # Prepare text for Flash
    raw_text = ""
    for m in raw_messages:
        raw_text += f"- [{m.get('author')}]: {m.get('content')}\n"
        
    if not raw_text.strip():
        return

    def _run_with_key_rotation(model_name, prompt_contents, task_name):
        for idx, api_key in enumerate(keys_pool):
            try:
                print(f"[AI] ({task_name}) Using Key {idx+1}/{len(keys_pool)}...")
                client = genai.Client(api_key=api_key)
                resp = client.models.generate_content(
                    model=model_name,
                    contents=prompt_contents
                )
                return resp.text
            except Exception as e:
                err_str = str(e).lower()
                if "429" in err_str or "quota" in err_str or "exhausted" in err_str:
                    print(f"   [!] Key {idx+1} exhausted (429). Switching...")
                    time.sleep(2)  # Short pause before next key
                    continue
                else:
                    print(f"   [!] Fatal AI error during {task_name}: {e}")
                    raise e
        raise RuntimeError(f"All {len(keys_pool)} keys exhausted or failed for {task_name}.")

    try:
        print(f"[AI] Stage 2: Cleaning {len(raw_messages)} messages with Gemini Flash...")
        flash_prompt = f"""You are an Expert Rule Extractor for the Atlas Annotation project.
Read these raw Discord chat messages and extract ONLY the technical annotation rules, policy changes, or official clarifications.
Ignore casual chat, greetings, status updates, or payment talk.

Return a clean, bulleted list of the rules in English. If a rule contradicts an older one, identify it.

Raw Messages:
{raw_text}
"""
        clean_rules = _run_with_key_rotation("gemini-2.0-flash", flash_prompt, "Stage 2 (Flash)")
        
        print("[AI] Stage 3: Merging rules into Master Updates with Gemini 3.1 Pro...")
        updates_file = PROJECT_ROOT / "prompts" / "atlas_discord_updates.md"
        current_updates = ""
        if updates_file.exists():
            current_updates = updates_file.read_text(encoding="utf-8")
            
        pro_prompt = f"""You are the Master Rule Integrator for Atlas.
I will give you CLEAN NEW RULES from Discord and the CURRENT UP-TO-DATE rules file.
Your job is to MERGE the new rules into the current file.

RULES FOR MERGING:
1. Deduplicate: If a rule already exists, don't add it.
2. Update: If a new rule overrides an old one, update the instruction.
3. Quality: Keep the tone strict, imperative, and technical (e.g., "Label 'hold' in every segment").
4. Chronology: Newest updates should be at the bottom under their respective date headers.

CURRENT RULES:
{current_updates}

NEW CLEANED RULES:
{clean_rules}

Return the FULL updated content for atlas_discord_updates.md. Include the '# 🧠 Dynamic Discord Rules' header if missing.
"""
        updated_content = _run_with_key_rotation("gemini-3.1-pro-preview", pro_prompt, "Stage 3 (Pro)")
        
        updates_file.parent.mkdir(parents=True, exist_ok=True)
        updates_file.write_text(updated_content, encoding="utf-8")
        print(f"[AI] Successfully updated {updates_file.name}")
        
    except Exception as e:
        print(f"[AI] Error in Stage 2/3: {e}")

# --- Bookmarks Management ---
def load_bookmarks():
    if BOOKMARKS_FILE.exists():
        try:
            with open(BOOKMARKS_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {}

def save_bookmarks(bookmarks):
    with open(BOOKMARKS_FILE, "w") as f:
        json.dump(bookmarks, f, indent=4)

# --- Appending to Markdown Files ---
def append_markdown(filename, md_text):
    filepath = OUTPUT_DIR / filename
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(md_text + "\n")

# --- Fetching Logic (Incremental) ---
def fetch_incremental(channel_id, after_id=None):
    messages = []
    
    # If no bookmark, start from Jan 1 2025 (Snowflake: 1324151700683079680)
    if not after_id:
        after_id = "1324151700683079680"
        
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages?limit=100&after={after_id}"
        
    try:
        response = requests.get(url, headers=HEADERS)
        if response.status_code == 401 or response.status_code == 403:
            print(f"   [!] Permission Error {response.status_code}. (Is your bot in the server?)")
            return []
        if response.status_code == 429:
            retry_after = response.json().get("retry_after", 5)
            print(f"   [!] Rate limit! Sleeping for {retry_after}s")
            time.sleep(retry_after)
            return fetch_incremental(channel_id, after_id)
            
        if response.status_code == 200:
            msgs = response.json()
            # Discord 'after' returns older first. 
            # We want to process them chronologically.
            msgs.reverse() 
            messages.extend(msgs)
            
            # If we got exactly 100, there might be more...
            while len(msgs) == 100:
                last_id = msgs[-1]["id"]
                next_url = f"https://discord.com/api/v10/channels/{channel_id}/messages?limit=100&after={last_id}"
                time.sleep(1.5) # Soft delay
                resp = requests.get(next_url, headers=HEADERS)
                if resp.status_code == 200:
                    msgs = resp.json()
                    msgs.reverse()
                    messages.extend(msgs)
                else:
                    break
                    
    except Exception as e:
        print(f"   [!] HTTP Error: {e}")
        
    return messages

# --- Main Daemon Loop ---
def scraper_daemon(interval_hours=8):
    print("=====================================================")
    print("🦇 Atlas Discord Scraper Daemon Activated 🦇")
    print(f"   Loop Interval: Every {interval_hours} hours")
    print("   Cost: 0.00$ (Regex Categorization)")
    print("=====================================================")
    
    interval_seconds = interval_hours * 3600
    
    while True:
        now = datetime.datetime.now()
        print(f"\n[{now.strftime('%Y-%m-%d %H:%M:%S')}] Starting Scan Cycle...")
        
        bookmarks = load_bookmarks()
        total_extracted = 0
        
        for ch_name, ch_id in CHANNELS.items():
            if not ch_id: continue
            
            last_id = bookmarks.get(ch_id, None)
            print(f"   Scanning #{ch_name} (After ID: {last_id if last_id else 'Beginning of time'})")
            
            new_msgs = fetch_incremental(ch_id, after_id=last_id)
            if not new_msgs:
                print("      No new messages.")
                continue
                
            print(f"      Got {len(new_msgs)} new messages. Processing...")
            
            highest_id = last_id
            
            for msg in new_msgs:
                msg_id = msg.get("id")
                content = msg.get("content", "")
                author = msg.get("author", {}).get("username", "Unknown")
                ts = msg.get("timestamp", "")[:19]
                
                # Metadata
                is_reply = msg.get("referenced_message") is not None
                
                # Update highest ID for bookmark
                if not highest_id or int(msg_id) > int(highest_id):
                    highest_id = msg_id
                    
                # Categorize
                category = categorize_message(content, is_reply)
                if category == "skip": continue
                
                clean_txt = clean_content(content)
                total_extracted += 1
                
                # Write to respective files
                if category == "rule":
                    block = f"### Rule from {author} ({ts})\n<!-- msg_id: {msg_id} -->\n{clean_txt}\n---"
                    append_markdown("discord_rules.md", block)
                elif category == "qa":
                    reply_text = msg.get("referenced_message", {}).get("content", "") if is_reply else ""
                    if reply_text:
                        block = f"**Q:** {clean_content(reply_text)}\n**A ({author}, {ts}):** {clean_txt}\n"
                    else:
                        block = f"**{author} ({ts}):** {clean_txt}\n"
                    append_markdown("discord_qa.md", block)
                elif category == "important":
                    block = f"### {author} ({ts})\n{clean_txt}\n---"
                    append_markdown("discord_important.md", block)
            
            # Final AI Processing Stage (Only if we got new rules or important insights)
            if total_extracted > 0:
                process_with_ai(new_msgs)
                
            # Save Bookmark
            if highest_id:
                bookmarks[ch_id] = highest_id
                save_bookmarks(bookmarks)
                
            time.sleep(2) # Delay between channels
            
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Cycle Complete. Extracted {total_extracted} useful insights.")
        print(f"⏳ Sleeping for {interval_hours} hour. Press Ctrl+C to abort.\n")
        
        # Sleep for the designated interval
        time.sleep(interval_seconds)

if __name__ == "__main__":
    # Ensure prompts dir exists
    (PROJECT_ROOT / "prompts").mkdir(parents=True, exist_ok=True)
    scraper_daemon(interval_hours=1)
