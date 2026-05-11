import json
import os
import glob
import time
import argparse
from pathlib import Path
from google import genai
from google.genai import types

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ------------------------------------------------------------------------------
# 1. CONSTANTS & CONFIG
# ------------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
QUEUE_FILE = PROJECT_ROOT / "questions_queue.json"
RULES_FILE = PROJECT_ROOT / "prompts" / "golden_rules.md"

API_KEYS = [
    os.getenv("GEMINI_API_KEY_FALLBACK", ""),
    os.getenv("GEMINI_API_KEY_SECONDARY", ""),
    os.getenv("GEMINI_API_KEY", ""),
]
API_KEYS = [k for k in API_KEYS if k]  

_current_key_idx = 0
_client = None

def configure_next_key() -> bool:
    """Rotates to the next available API key."""
    global _current_key_idx, _client
    if _current_key_idx >= len(API_KEYS):
        return False
    
    key = API_KEYS[_current_key_idx]
    _client = genai.Client(api_key=key)
    _current_key_idx += 1
    return True

# Initialize first key
configure_next_key()

REVIEWER_SYSTEM_PROMPT = """You are a highly professional Senior Data Annotation Lead.
Your task is to review auto-generated video annotations to find boundary ambiguities, uncertain verb choices, or potential golden-rule violations.
You must formulate precise questions to ask the Administration Team on Discord to clarify these edge cases.

Format your output ONLY as a RAW JSON array of objects. No markdown formatting.
Each object must have:
- "rule_topic": A short 2-4 word theme (e.g., "Sewing Actions Boundaries")
- "question": Professional question directed to the admins referencing specific segment logic.
- "context": Brief explanation of why this is ambiguous based on the provided labels.

Example:
[
  {
    "rule_topic": "Tool interaction limits",
    "question": "If an actor is 'adjusting sew belt' right before 'pushing needle', should we combine this into the sewing action or keep it as a distinct adjustment segment?",
    "context": "Video sequence shows rapid transition between adjustment and sewing push/pull cycles."
  }
]"""

# ------------------------------------------------------------------------------
# 2. CORE LOGIC
# ------------------------------------------------------------------------------

def load_video_labels(limit=None):
    files = glob.glob(os.path.join(str(OUTPUTS_DIR), "labels_*.json"))
    files.sort(key=os.path.getmtime, reverse=True)
    if limit:
        files = files[:limit]
    
    videos_data = {}
    for f in files:
        vid_id = Path(f).stem.replace('labels_', '')
        try:
            with open(f, 'r', encoding='utf-8') as file:
                data = json.load(file)
                if 'segments' in data and len(data['segments']) > 0:
                    # simplify for prompt
                    simplified_segs = []
                    for s in data['segments']:
                        simplified_segs.append(f"[{s.get('start_sec', 0)} - {s.get('end_sec', 0)}] {s.get('label', '')}")
                    videos_data[vid_id] = "\n".join(simplified_segs)
        except Exception as e:
            print(f"[review] Error reading {f}: {e}")
            
    return videos_data

def read_golden_rules() -> str:
    if os.path.exists(RULES_FILE):
        with open(RULES_FILE, "r", encoding="utf-8") as f:
            return f.read()
    return ""

def load_queue() -> list:
    if os.path.exists(QUEUE_FILE):
        try:
            with open(QUEUE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_queue(q: list):
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(q, f, indent=4, ensure_ascii=False)

def generate_video_questions(vid_id: str, segments_text: str, rules_text: str, dry_run: bool = False) -> list:
    print(f"[review] Analyzing video {vid_id}...")
    
    user_prompt = f"""Review the following annotation sequence for Video {vid_id} against the Golden Rules.
Identify up to 2 specific areas of uncertainty (e.g., micro-actions, continuous vs discrete labeling) and ask precise questions.

=== VIDEO {vid_id} ANNOTATIONS ===
{segments_text}

=== ESTABLISHED RULES ===
{rules_text}

Return ONLY a valid JSON array!"""

    model_names = ["gemini-3.1-pro-preview", "gemini-2.5-flash", "gemini-2.0-flash"]
    
    for model_name in model_names:
        global _current_key_idx
        _current_key_idx = 0
        
        for key_attempt in range(len(API_KEYS)):
            if not configure_next_key():
                break
            
            try:
                response = _client.models.generate_content(
                    model=model_name,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=REVIEWER_SYSTEM_PROMPT,
                        temperature=0.7,
                    )
                )
                raw = response.text.strip()
                if raw.startswith("```"):
                    raw = raw.split("\n", 1)[1]
                    if raw.endswith("```"): raw = raw[:-3]
                    raw = raw.strip()
                if raw.startswith("json"): raw = raw[4:].strip()
                
                questions = json.loads(raw)
                print(f"[review] ✅ [{model_name}] generated {len(questions)} questions for {vid_id}")
                return questions
            
            except json.JSONDecodeError as e:
                print(f"[review] JSON Error: {e}")
                print(f"[review] Raw output: {raw[:500]}")
                return []
            except Exception as e:
                err_str = str(e)
                print(f"[review] Attempt Error ({model_name} / Key #{key_attempt}): {err_str[:200]}")
                if "429" in err_str or "quota" in err_str.lower() or "exhausted" in err_str.lower():
                    time.sleep(2)
                    continue
                elif "404" in err_str:
                    continue
                else:
                    return []
    
    print(f"[review] Failed to generate for {vid_id} after all retry attempts.")
    return []

def main():
    parser = argparse.ArgumentParser(description="Atlas Video Re-Reviewer")
    parser.add_argument("--limit", type=int, default=5, help="Max videos to review")
    parser.add_argument("--dry-run", action="store_true", help="Print without saving")
    args = parser.parse_args()
    
    print("=" * 60)
    print(f"[review] Atlas Video Re-Reviewer v1.0")
    print(f"[review] Mode: {'DRY RUN' if args.dry_run else 'PRODUCTION'}")
    print(f"[review] Limit: {args.limit} videos")
    print("=" * 60)
    
    rules = read_golden_rules()
    videos = load_video_labels(limit=args.limit)
    print(f"[review] Found {len(videos)} videos to review.")
    
    all_new_questions = []
    
    for vid_id, segs in videos.items():
        if len(segs.strip()) < 10:
            continue
            
        questions = generate_video_questions(vid_id, segs, rules, args.dry_run)
        
        for q in questions:
            q["source_type"] = "video_review"
            q["source_reference"] = vid_id
            q["status"] = "pending"
            q["timestamp"] = int(time.time())
            all_new_questions.append(q)
            
    if args.dry_run:
        print("\n" + "="*60)
        print(f"[review] DRY RUN - {len(all_new_questions)} questions generated but NOT saved.")
        for q in all_new_questions:
            print(f"- [Video {q['source_reference']}] {q['question']}")
        print("="*60)
    else:
        q_queue = load_queue()
        q_queue.extend(all_new_questions)
        save_queue(q_queue)
        print(f"\n[review] ✅ Appended {len(all_new_questions)} questions to queue.")

if __name__ == "__main__":
    main()
