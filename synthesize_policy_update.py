"""
Synthesize Discord rules into policy update using Gemini API.
Reads extracted rules and announcements, produces updated policy text.
"""
import json
import sys
import os
from pathlib import Path
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import google.generativeai as genai

PROJECT_ROOT = Path(__file__).parent

# Load Gemini API key
api_key = os.getenv("GEMINI_API_KEY_FREE_OPS", "")
if not api_key:
    keys = os.getenv("GEMINI_API_KEYS_FREE_POOL", "")
    api_key = keys.split(",")[0].strip() if keys else ""

genai.configure(api_key=api_key)


def load_announcements():
    f = PROJECT_ROOT / "outputs" / "discord_processed" / "extracted_announcements.json"
    return json.loads(f.read_text(encoding="utf-8"))


def load_rules():
    f = PROJECT_ROOT / "outputs" / "discord_processed" / "extracted_rules.json"
    return json.loads(f.read_text(encoding="utf-8"))


def load_current_policy():
    f = PROJECT_ROOT / "data" / "gemini_policy_v1.txt"
    if f.exists():
        return f.read_text(encoding="utf-8")
    return ""


def load_golden_rules():
    f = PROJECT_ROOT / "prompts" / "golden_rules.md"
    if f.exists():
        return f.read_text(encoding="utf-8")
    return ""


def build_admin_digest(rules, announcements):
    """Build a focused digest of admin/trusted messages for Gemini."""
    ADMIN_USERS = {'sentientcake', 'jujumu007', 'juphams', 'sharingcaring', 'leoni_3105',
                   'kurosakikazui', 'mark.atlas', 'shangccic', 'parshxn', 'n810tester',
                   '_josephgreenwood', 'austin._._0', 'm.xssx'}

    digest = []

    # All announcements
    for a in announcements:
        digest.append({
            "date": a["date"],
            "author": a["author"],
            "channel": a["channel"],
            "type": "announcement",
            "content": a["clean_content"][:1500]
        })

    # Admin rules only
    for r in rules:
        if r["author"].lower() in {u.lower() for u in ADMIN_USERS}:
            digest.append({
                "date": r["date"],
                "author": r["author"],
                "channel": r["channel"],
                "type": "admin_rule",
                "content": r["clean_content"][:800]
            })

    digest.sort(key=lambda x: x["date"])
    return digest


def synthesize_with_gemini(digest, current_policy, golden_rules):
    """Use Gemini to synthesize all Discord messages into policy updates."""

    # Build the digest text
    digest_text = ""
    for d in digest:
        digest_text += f"\n[{d['date']}] ({d['type']}) {d['author']} in #{d['channel']}:\n{d['content']}\n---\n"

    # Truncate if too long
    if len(digest_text) > 200000:
        digest_text = digest_text[:200000] + "\n\n[TRUNCATED - showing first 200K chars]"

    prompt = f"""You are an expert Atlas Capture QA policy analyst. Your task is to analyze Discord messages from March 27 to April 24, 2026 and extract ALL new labeling rules, clarifications, and policy changes.

## Current Policy (for reference - DO NOT repeat unchanged rules):
{current_policy[:5000]}

## Current Golden Rules (for reference):
{golden_rules[:8000]}

## Discord Messages (March 27 - April 24, 2026):
{digest_text}

## Your Task:
1. Identify ALL new rules, clarifications, or policy changes that are NOT already in the current policy
2. Focus on LABELING rules only (ignore payment, admin, hiring discussions)
3. Prioritize rules from ADMIN/MOD sources (sentientcake, jujumu007, m.xssx, austin._._0, _josephgreenwood, sharingcaring, kurosakikazui)
4. For each rule/clarification, note the date, source, and exact wording

Output a structured JSON with this format:
{{
    "new_rules": [
        {{
            "rule_id": "DISCORD-2026-03-27-001",
            "date": "2026-03-27",
            "source": "sentientcake",
            "channel": "level-3-announcements",
            "title": "Short title",
            "description": "Full rule description",
            "impact": "high/medium/low",
            "category": "segmentation/labeling/hold/merge/split/verb/format/other"
        }}
    ],
    "clarifications": [
        {{
            "date": "2026-03-27",
            "source": "admin_name",
            "topic": "topic",
            "clarification": "exact clarification text",
            "existing_rule_affected": "which current rule this clarifies"
        }}
    ],
    "summary": "Brief overall summary of what changed since March 27"
}}

Be thorough. Extract EVERY unique labeling rule or clarification from admin sources.
Return ONLY valid JSON, no markdown formatting."""

    model = genai.GenerativeModel("gemini-2.0-flash")
    response = model.generate_content(
        prompt,
        generation_config=genai.GenerationConfig(
            temperature=0.1,
            max_output_tokens=8192,
        )
    )

    return response.text


def main():
    print("[synth] Loading data...")
    announcements = load_announcements()
    rules = load_rules()
    current_policy = load_current_policy()
    golden_rules = load_golden_rules()

    print(f"[synth] Announcements: {len(announcements)}")
    print(f"[synth] Rules: {len(rules)}")

    # Build admin digest
    digest = build_admin_digest(rules, announcements)
    print(f"[synth] Admin/announcement digest: {len(digest)} entries")

    # Synthesize with Gemini
    print("[synth] Calling Gemini for synthesis...")
    result = synthesize_with_gemini(digest, current_policy, golden_rules)

    # Clean up response (remove markdown code fences if present)
    result = result.strip()
    if result.startswith("```json"):
        result = result[7:]
    if result.startswith("```"):
        result = result[3:]
    if result.endswith("```"):
        result = result[:-3]
    result = result.strip()

    # Save raw response
    out_dir = PROJECT_ROOT / "outputs" / "discord_processed"
    raw_file = out_dir / "gemini_synthesis_raw.json"
    raw_file.write_text(result, encoding="utf-8")
    print(f"[synth] Raw synthesis saved: {raw_file}")

    # Parse and display
    try:
        synthesis = json.loads(result)

        print(f"\n{'=' * 60}")
        print(f"[synth] SYNTHESIS RESULTS")
        print(f"{'=' * 60}")

        new_rules = synthesis.get("new_rules", [])
        clarifications = synthesis.get("clarifications", [])
        summary = synthesis.get("summary", "")

        print(f"\nSummary: {summary}")
        print(f"\nNew Rules: {len(new_rules)}")
        for r in new_rules:
            print(f"  [{r.get('impact','?')}] {r.get('rule_id','')}: {r.get('title','')}")
            print(f"       {r.get('description','')[:200]}")

        print(f"\nClarifications: {len(clarifications)}")
        for c in clarifications:
            print(f"  [{c.get('date','')}] {c.get('topic','')}: {c.get('clarification','')[:200]}")

        # Save structured output
        structured_file = out_dir / "policy_synthesis.json"
        structured_file.write_text(json.dumps(synthesis, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nStructured synthesis: {structured_file}")

    except json.JSONDecodeError as e:
        print(f"[synth] WARNING: Could not parse Gemini response as JSON: {e}")
        print(f"[synth] Raw response saved to {raw_file}")
        print(result[:2000])


if __name__ == "__main__":
    main()
