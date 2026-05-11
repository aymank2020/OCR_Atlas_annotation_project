"""
Atlas AI Question Generator — Zero-Trust Annotation Pipeline
=============================================================
Reads golden_rules.md + discord_rules.md and uses Gemini to convert
ambiguous/unclear rules into professional questions for Discord admins.

Usage:
  python atlas_question_generator.py --dry-run          # Preview questions only
  python atlas_question_generator.py --limit 5          # Generate max 5 questions
  python atlas_question_generator.py                    # Generate all + write queue
  python atlas_question_generator.py --from-rules       # From golden_rules.md only
  python atlas_question_generator.py --from-discord      # From discord_rules.md only
"""

import argparse
import json
import os
import sys
import time
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

try:
    from google import genai
    from google.genai import types
except ImportError:
    print("[qgen] FATAL: pip install google-genai")
    sys.exit(1)

# ── Config ──────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent
GOLDEN_RULES = PROJECT_ROOT / "prompts" / "golden_rules.md"
DISCORD_RULES = PROJECT_ROOT / "outputs" / "discord_rules.md"
QUEUE_FILE = PROJECT_ROOT / "questions_queue.json"

# Try multiple API keys (free tier quota rotates)
API_KEYS = [
    os.getenv("GEMINI_API_KEY_FALLBACK", ""),
    os.getenv("GEMINI_API_KEY_SECONDARY", ""),
    os.getenv("GEMINI_API_KEY", ""),
]
API_KEYS = [k for k in API_KEYS if k]  # Remove empty

_current_key_idx = 0
_client = None

def configure_next_key():
    """Try the next available API key."""
    global _current_key_idx, _client
    if _current_key_idx >= len(API_KEYS):
        print("[qgen] ERROR: All API keys exhausted!")
        return False
    key = API_KEYS[_current_key_idx]
    _client = genai.Client(api_key=key)
    print(f"[qgen] Using API key #{_current_key_idx + 1} (...{key[-6:]})")
    _current_key_idx += 1
    return True

configure_next_key()

# ── System Prompt for Question Generation ───────────────────────────
QUESTION_SYSTEM_PROMPT = """You are a QA Data Engineer working on video annotation (labeling).
Your job is to read annotation rules and generate professional clarification questions.

CONTEXT:
- You work on "Atlas", an egocentric video annotation project
- Videos show humans doing tasks (cooking, cleaning, repair, gym, sewing, etc.)
- You label segments with action verbs + objects (e.g., "pick up spoon", "place box on table")
- Questions go to Discord admins (sentientcake, jujumu007, shangccic, Clemmie)

RULES FOR GENERATING QUESTIONS:
1. Each question MUST look like it comes from a professional human annotator
2. Use format: "Hey team, if [scenario], should I [option A] or [option B]? Thanks!"
3. Questions should resolve REAL ambiguity in the rules
4. Focus on edge cases, contradictions, or unclear boundaries
5. DO NOT ask about things that are already clearly defined
6. Keep questions SHORT (1-3 sentences max)
7. Use concrete examples from video labeling scenarios
8. NEVER mention AI, automation, scripts, or bots

CATEGORIES OF GOOD QUESTIONS:
- When two rules seem to contradict (e.g., "hold" rule vs "no action" rule)
- When a rule has edge cases not covered (e.g., what if object is half-visible?)
- When verb choice is ambiguous (e.g., "move" vs "pick up + place")
- When segment boundaries are unclear
- When dense vs coarse choice is a judgment call

OUTPUT FORMAT:
Return a JSON array. Each item has:
{
  "question_text": "The actual question to post on Discord",
  "rule_ref": "Which rule this relates to (e.g., 'Section 5.2 - Verb Definitions')",
  "ambiguity_type": "contradiction|edge_case|verb_choice|boundary|judgment",
  "priority": "high|medium|low"
}

Generate ONLY questions that would genuinely help improve annotation quality.
Aim for 5-15 high-quality questions per batch."""


def load_rules(source: str = "both") -> str:
    """Load rule files as text for Gemini to analyze."""
    parts = []
    
    if source in ("both", "golden") and GOLDEN_RULES.exists():
        text = GOLDEN_RULES.read_text(encoding="utf-8")
        parts.append(f"=== GOLDEN RULES (Official) ===\n{text}\n")
        print(f"[qgen] Loaded golden_rules.md ({len(text)} chars)")
    
    if source in ("both", "discord") and DISCORD_RULES.exists():
        text = DISCORD_RULES.read_text(encoding="utf-8")
        # Truncate if too long (keep most recent 500 lines)
        lines = text.split("\n")
        if len(lines) > 500:
            text = "\n".join(lines[:500])
            print(f"[qgen] Truncated discord_rules.md to 500 lines (was {len(lines)})")
        parts.append(f"=== DISCORD COMMUNITY RULES ===\n{text}\n")
        print(f"[qgen] Loaded discord_rules.md ({len(text)} chars)")
    
    if not parts:
        print("[qgen] ERROR: No rule files found!")
        sys.exit(1)
    
    return "\n\n".join(parts)


def load_existing_queue() -> list:
    """Load existing questions to avoid duplicates."""
    if QUEUE_FILE.exists():
        try:
            return json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def generate_questions(rules_text: str, limit: int = 15, wait_for_quota: bool = False) -> list:
    """Use Gemini to generate professional questions from rules."""
    print(f"[qgen] Generating questions (limit={limit})...")
    
    user_prompt = f"""Analyze these annotation rules and generate {limit} professional 
clarification questions that a human annotator would ask their admin team on Discord.

Focus on:
1. Rules that seem contradictory or have edge cases
2. Recent updates that might conflict with older rules
3. Scenarios where verb/object choice is ambiguous
4. Segment boundary gray areas

{rules_text}

Return ONLY a valid JSON array. No markdown formatting, no code blocks."""

    # Try different model variants (each has its own quota)
    model_names = ["gemini-3.1-pro-preview", "gemini-2.5-flash", "gemini-2.0-flash"]
    
    for model_name in model_names:
        # Reset key index for each model
        global _current_key_idx
        _current_key_idx = 0
        
        for key_attempt in range(len(API_KEYS)):
            if not configure_next_key():
                break
            
            print(f"[qgen] Trying model={model_name}, key #{_current_key_idx}...")
            
            try:
                response = _client.models.generate_content(
                    model=model_name,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=QUESTION_SYSTEM_PROMPT,
                        temperature=0.7,
                    )
                )
                raw = response.text.strip()
                
                # Clean JSON markers if present
                if raw.startswith("```"):
                    raw = raw.split("\n", 1)[1]
                    if raw.endswith("```"):
                        raw = raw[:-3]
                    raw = raw.strip()
                if raw.startswith("json"):
                    raw = raw[4:].strip()
                
                questions = json.loads(raw)
                print(f"[qgen] ✅ Gemini ({model_name}) generated {len(questions)} questions!")
                return questions
            
            except json.JSONDecodeError as e:
                print(f"[qgen] ERROR parsing Gemini response: {e}")
                print(f"[qgen] Raw (first 300 chars): {raw[:300]}")
                return []
            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "quota" in err_str.lower() or "exhausted" in err_str.lower():
                    print(f"[qgen] Rate limited. Trying next key...")
                    time.sleep(2)
                    continue
                elif "400" in err_str and "API Key" in err_str:
                    print(f"[qgen] Invalid key, skipping...")
                    continue
                else:
                    print(f"[qgen] ERROR: {e}")
                    return []
        
        print(f"[qgen] All keys exhausted for {model_name}, trying next model...")
    
    # If wait_for_quota, do a final retry after waiting
    if wait_for_quota:
        print(f"[qgen] All models/keys exhausted. Waiting 60s for quota reset...")
        time.sleep(60)
        _current_key_idx = 0
        configure_next_key()
        try:
            response = _client.models.generate_content(
                model="gemini-3.1-pro-preview",
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=QUESTION_SYSTEM_PROMPT,
                )
            )
            raw = response.text.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1]
                if raw.endswith("```"): raw = raw[:-3]
                raw = raw.strip()
            if raw.startswith("json"): raw = raw[4:].strip()
            questions = json.loads(raw)
            print(f"[qgen] ✅ Retry succeeded! {len(questions)} questions")
            return questions
        except Exception as e:
            print(f"[qgen] Final retry also failed: {e}")
    
    print("[qgen] All API keys and models exhausted.")
    return []


def deduplicate(new_questions: list, existing_queue: list) -> list:
    """Remove questions that are too similar to existing ones."""
    existing_texts = {q.get("question_text", "").lower()[:60] for q in existing_queue}
    
    unique = []
    for q in new_questions:
        short = q.get("question_text", "").lower()[:60]
        if short not in existing_texts:
            unique.append(q)
            existing_texts.add(short)
    
    removed = len(new_questions) - len(unique)
    if removed:
        print(f"[qgen] Deduplicated: removed {removed} similar questions")
    return unique


def build_queue_entries(questions: list, existing_queue: list) -> list:
    """Convert raw Gemini output to queue format with IDs."""
    max_id = 0
    for q in existing_queue:
        qid = q.get("id", "q0")
        try:
            num = int(qid.replace("q", ""))
            max_id = max(max_id, num)
        except ValueError:
            pass
    
    entries = []
    for i, q in enumerate(questions, start=max_id + 1):
        entries.append({
            "id": f"q{i}",
            "question_text": q.get("question_text", ""),
            "rule_ref": q.get("rule_ref", "unknown"),
            "ambiguity_type": q.get("ambiguity_type", "unknown"),
            "priority": q.get("priority", "medium"),
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "sent_at": None,
            "message_id": None,
            "admin_reply": None,
            "admin_name": None,
            "replied_at": None,
            "action_taken": None
        })
    
    return entries


def main():
    parser = argparse.ArgumentParser(description="Atlas AI Question Generator")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview questions without writing to queue")
    parser.add_argument("--limit", type=int, default=10,
                        help="Max questions to generate (default: 10)")
    parser.add_argument("--from-rules", action="store_true",
                        help="Generate from golden_rules.md only")
    parser.add_argument("--from-discord", action="store_true",
                        help="Generate from discord_rules.md only")
    parser.add_argument("--wait-for-quota", action="store_true",
                        help="Wait 60s and retry if all keys are rate-limited")
    args = parser.parse_args()
    
    print("=" * 60)
    print("[qgen] Atlas AI Question Generator v1.0")
    print(f"[qgen] Mode: {'DRY RUN' if args.dry_run else 'PRODUCTION'}")
    print(f"[qgen] Limit: {args.limit} questions")
    print("=" * 60)
    
    # Determine source
    source = "both"
    if args.from_rules:
        source = "golden"
    elif args.from_discord:
        source = "discord"
    
    # Load rules
    rules_text = load_rules(source)
    
    # Load existing queue
    existing = load_existing_queue()
    pending = [q for q in existing if q.get("status") == "pending"]
    print(f"[qgen] Existing queue: {len(existing)} total, {len(pending)} pending")
    
    # Generate questions
    raw_questions = generate_questions(rules_text, args.limit, args.wait_for_quota)
    if not raw_questions:
        print("[qgen] No questions generated. Exiting.")
        return
    
    # Deduplicate
    unique_questions = deduplicate(raw_questions, existing)
    if not unique_questions:
        print("[qgen] All questions already exist in queue. Exiting.")
        return
    
    # Build queue entries
    new_entries = build_queue_entries(unique_questions, existing)
    
    # Display questions
    print(f"\n{'=' * 60}")
    print(f"[qgen] Generated {len(new_entries)} new questions:")
    print(f"{'=' * 60}")
    for entry in new_entries:
        priority_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(
            entry["priority"], "⚪")
        print(f"\n  {priority_icon} [{entry['id']}] ({entry['ambiguity_type']})")
        print(f"  📎 Rule: {entry['rule_ref']}")
        print(f"  💬 {entry['question_text']}")
    
    if args.dry_run:
        print(f"\n{'=' * 60}")
        print(f"[qgen] DRY RUN — {len(new_entries)} questions generated but NOT saved.")
        print(f"[qgen] Run without --dry-run to save to {QUEUE_FILE.name}")
        print(f"{'=' * 60}")
        return
    
    # Save to queue
    full_queue = existing + new_entries
    QUEUE_FILE.write_text(
        json.dumps(full_queue, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    
    print(f"\n{'=' * 60}")
    print(f"[qgen] ✅ Saved {len(new_entries)} new questions to {QUEUE_FILE.name}")
    print(f"[qgen] Total queue: {len(full_queue)} ({len(pending) + len(new_entries)} pending)")
    print(f"[qgen] Next step: python atlas_question_dispatcher.py")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
