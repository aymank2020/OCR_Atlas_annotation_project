"""
Atlas Verb Glossary Builder — Comprehensive Action Verb Dictionary
==================================================================
Builds a complete glossary of English action verbs organized by domain
(cooking, cleaning, repair, gym, sewing, etc.) + general English verbs.

This replaces the need to download external PDFs by generating a comprehensive
verb database directly using AI + curated domain knowledge.

Usage:
  python atlas_verb_glossary_builder.py                  # Build full glossary
  python atlas_verb_glossary_builder.py --domain cooking # Single domain
  python atlas_verb_glossary_builder.py --add-general    # Add general English verbs
  python atlas_verb_glossary_builder.py --merge           # Merge with existing tech_glossary.json

Output: prompts/tech_glossary.json
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
    import google.generativeai as genai
except ImportError:
    print("[glossary] FATAL: pip install google-generativeai")
    sys.exit(1)

# ── Config ──────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent
GLOSSARY_FILE = PROJECT_ROOT / "prompts" / "tech_glossary.json"

API_KEY = os.getenv("GEMINI_API_KEY", "")
if not API_KEY:
    API_KEY = os.getenv("GEMINI_API_KEY_FALLBACK", "")
genai.configure(api_key=API_KEY)

# ── All Atlas Video Domains ─────────────────────────────────────────
DOMAINS = {
    "cooking": {
        "name": "Cooking & Kitchen",
        "description": "Food preparation, cooking, baking, kitchen cleaning",
        "example_videos": "Chopping vegetables, stirring soup, frying eggs, washing dishes"
    },
    "cleaning": {
        "name": "House Cleaning",
        "description": "Mopping, sweeping, vacuuming, wiping surfaces, laundry",
        "example_videos": "Mopping floor, folding clothes, scrubbing sink, sorting laundry"
    },
    "repair": {
        "name": "Device & Electronics Repair",
        "description": "Phone repair, computer repair, appliance repair, soldering",
        "example_videos": "Unscrewing phone, disconnecting battery, soldering component"
    },
    "gym": {
        "name": "Gym & Fitness",
        "description": "Weight training, cardio, stretching, equipment use",
        "example_videos": "Lifting dumbbell, adjusting machine, stretching, running on treadmill"
    },
    "sewing": {
        "name": "Sewing & Textile Work",
        "description": "Hand sewing, machine sewing, cutting fabric, measuring",
        "example_videos": "Threading needle, cutting fabric, pinning pattern, sewing seam"
    },
    "automotive": {
        "name": "Automotive & Mechanical",
        "description": "Car repair, oil change, tire work, engine maintenance",
        "example_videos": "Loosening bolt, draining oil, jacking car, replacing filter"
    },
    "woodworking": {
        "name": "Woodworking & Carpentry",
        "description": "Sawing, sanding, drilling, measuring, assembling furniture",
        "example_videos": "Sawing board, sanding surface, drilling hole, measuring length"
    },
    "gardening": {
        "name": "Gardening & Yard Work",
        "description": "Planting, watering, pruning, mowing, raking",
        "example_videos": "Digging soil, planting seedling, watering plants, raking leaves"
    },
    "crafts": {
        "name": "Arts & Crafts",
        "description": "Painting, drawing, sculpting, paper craft, jewelry making",
        "example_videos": "Cutting paper, gluing pieces, painting canvas, shaping clay"
    },
    "personal_care": {
        "name": "Personal Care & Grooming",
        "description": "Hair care, makeup, nail care, shaving",
        "example_videos": "Brushing hair, applying cream, trimming nails, shaving"
    },
    "pet_care": {
        "name": "Pet Care",
        "description": "Feeding, grooming, walking, bathing pets",
        "example_videos": "Pouring food, brushing fur, attaching leash, bathing dog"
    },
    "office": {
        "name": "Office & Desk Work",
        "description": "Filing, organizing, typing, stapling, packaging",
        "example_videos": "Stapling papers, opening envelope, typing on keyboard, packaging box"
    },
    "medical": {
        "name": "Medical & First Aid",
        "description": "Bandaging, taking temperature, applying medication",
        "example_videos": "Wrapping bandage, applying ointment, measuring blood pressure"
    }
}

# ── Curated Base Verb Set (Atlas-specific) ──────────────────────────
ATLAS_BASE_VERBS = [
    # Core verbs from golden_rules.md
    "pick up", "place", "move", "adjust", "hold", "grab",
    "loosen", "remove", "attach", "detach", "insert", "pull",
    "push", "press", "twist", "turn", "flip", "rotate",
    "open", "close", "fold", "unfold", "wrap", "unwrap",
    "pour", "fill", "empty", "squeeze", "stretch", "bend",
    "cut", "slice", "chop", "tear", "break", "snap",
    "wipe", "scrub", "rinse", "wash", "dry", "spray",
    "stir", "mix", "shake", "whisk", "knead", "roll",
    "peel", "grate", "mash", "spread", "dip", "drizzle",
    "screw", "unscrew", "drill", "hammer", "nail", "glue",
    "tape", "staple", "clip", "pin", "tie", "untie",
    "zip", "unzip", "button", "unbutton", "lace", "unlace",
    "plug", "unplug", "connect", "disconnect", "switch", "toggle",
    "measure", "mark", "draw", "trace", "write", "erase",
    "sand", "file", "polish", "buff", "sharpen", "grind",
    "lift", "lower", "raise", "drop", "toss", "catch",
    "carry", "drag", "slide", "stack", "arrange", "organize",
    "sort", "separate", "combine", "assemble", "disassemble",
    "sew", "stitch", "thread", "weave", "knit", "crochet",
    "iron", "steam", "hang", "drape", "smooth", "flatten",
    "sweep", "mop", "vacuum", "dust", "polish", "wax",
    "pump", "inflate", "deflate", "tighten", "lock", "unlock",
    "pry", "lever", "wedge", "clamp", "crimp", "solder",
    "weld", "paint", "coat", "apply", "smear", "dab",
]


DOMAIN_PROMPT = """You are a lexicography expert specializing in English ACTION VERBS.

Generate a comprehensive list of action verbs for the domain: {domain_name}
Description: {domain_desc}
Example video scenarios: {domain_examples}

RULES:
1. Only include PHYSICAL ACTION verbs (hands/body doing something)
2. Use IMPERATIVE form (e.g., "pick up", "place", "turn")
3. Include both common and specialized verbs
4. Include two-word verbs (phrasal verbs) like "pick up", "put down"  
5. DO NOT include mental verbs (think, decide, inspect, check)
6. DO NOT include movement verbs (walk, run, navigate)
7. Group verbs by sub-category within the domain

For each verb, provide:
- The verb (imperative form)
- A brief definition specific to this domain
- Common objects it pairs with in this domain

OUTPUT FORMAT: Return ONLY a valid JSON object:
{{
  "domain": "{domain_key}",
  "domain_name": "{domain_name}",
  "verb_count": <number>,
  "categories": [
    {{
      "category": "Cutting & Slicing",
      "verbs": [
        {{
          "verb": "chop",
          "definition": "Cut food into small pieces with a knife",
          "common_objects": ["onion", "garlic", "vegetables", "herbs"]
        }}
      ]
    }}
  ]
}}

Generate at least 30 verbs per domain. Be thorough!"""


GENERAL_VERBS_PROMPT = """You are a lexicography expert. Generate a comprehensive list of 
ALL common English physical action verbs that could appear in egocentric (first-person) 
video annotations. These are verbs describing what a person's HANDS and BODY do.

CATEGORIES to cover:
1. Hand manipulation (grip, pinch, squeeze, twist, etc.)
2. Force application (push, pull, press, yank, etc.)
3. Placement & movement (place, position, slide, drag, etc.)
4. Connection & fastening (attach, clip, plug, tape, etc.)
5. Separation & removal (detach, peel, strip, unplug, etc.)
6. Transformation (fold, bend, crush, flatten, etc.)
7. Cleaning & maintenance (wipe, scrub, polish, sweep, etc.)
8. Tool use (hammer, drill, saw, file, etc.)
9. Container operations (pour, fill, empty, load, etc.)
10. Surface interaction (touch, tap, stroke, rub, etc.)

RULES:
- Only PHYSICAL verbs (no mental, emotional, or movement verbs)
- Imperative form
- Include phrasal verbs (pick up, put down, take off, etc.)
- Minimum 100 verbs total

OUTPUT FORMAT: Return ONLY a valid JSON object:
{
  "domain": "general",
  "domain_name": "General English Action Verbs",
  "verb_count": <number>,
  "categories": [
    {
      "category": "Hand Manipulation",
      "verbs": [
        {
          "verb": "grip",
          "definition": "Hold something firmly with the hand",
          "common_objects": ["handle", "tool", "object"]
        }
      ]
    }
  ]
}"""


def generate_domain_verbs(domain_key: str, domain_info: dict) -> dict:
    """Generate verb glossary for a specific domain using Gemini."""
    print(f"[glossary] Generating verbs for: {domain_info['name']}...")
    
    model = genai.GenerativeModel("gemini-2.0-flash")
    
    prompt = DOMAIN_PROMPT.format(
        domain_name=domain_info["name"],
        domain_desc=domain_info["description"],
        domain_examples=domain_info["example_videos"],
        domain_key=domain_key
    )
    
    try:
        response = model.generate_content(prompt)
        raw = response.text.strip()
        
        # Clean JSON
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()
        
        result = json.loads(raw)
        verb_count = sum(
            len(cat.get("verbs", []))
            for cat in result.get("categories", [])
        )
        print(f"[glossary]   ✅ {verb_count} verbs generated")
        return result
    
    except json.JSONDecodeError as e:
        print(f"[glossary]   ERROR parsing JSON: {e}")
        return None
    except Exception as e:
        print(f"[glossary]   ERROR: {e}")
        if "429" in str(e):
            print(f"[glossary]   Rate limited — waiting 60s...")
            time.sleep(60)
        return None


def generate_general_verbs() -> dict:
    """Generate comprehensive general English action verb list."""
    print("[glossary] Generating general English action verbs...")
    
    model = genai.GenerativeModel("gemini-2.0-flash")
    
    try:
        response = model.generate_content(GENERAL_VERBS_PROMPT)
        raw = response.text.strip()
        
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()
        
        result = json.loads(raw)
        verb_count = sum(
            len(cat.get("verbs", []))
            for cat in result.get("categories", [])
        )
        print(f"[glossary]   ✅ {verb_count} general verbs generated")
        return result
    
    except Exception as e:
        print(f"[glossary]   ERROR: {e}")
        return None


def merge_into_glossary(glossary: dict, domain_data: dict):
    """Merge domain verb data into the master glossary."""
    if not domain_data:
        return
    
    domain_key = domain_data.get("domain", "unknown")
    
    # Add to domains section
    if "domains" not in glossary:
        glossary["domains"] = {}
    
    glossary["domains"][domain_key] = {
        "name": domain_data.get("domain_name", ""),
        "categories": domain_data.get("categories", []),
        "verb_count": domain_data.get("verb_count", 0)
    }
    
    # Flatten all verbs into master list
    if "all_verbs" not in glossary:
        glossary["all_verbs"] = set()
    else:
        glossary["all_verbs"] = set(glossary["all_verbs"])
    
    for cat in domain_data.get("categories", []):
        for v in cat.get("verbs", []):
            glossary["all_verbs"].add(v.get("verb", "").lower())
    
    # Convert set to sorted list for JSON serialization
    glossary["all_verbs"] = sorted(list(glossary["all_verbs"]))


def add_atlas_base_verbs(glossary: dict):
    """Add the curated Atlas base verbs."""
    if "all_verbs" not in glossary:
        glossary["all_verbs"] = []
    
    existing = set(glossary["all_verbs"])
    for v in ATLAS_BASE_VERBS:
        existing.add(v.lower())
    
    glossary["all_verbs"] = sorted(list(existing))
    
    # Also add as a special domain
    if "domains" not in glossary:
        glossary["domains"] = {}
    
    glossary["domains"]["atlas_core"] = {
        "name": "Atlas Core Verbs (from Golden Rules)",
        "categories": [
            {
                "category": "Official Atlas Verbs",
                "verbs": [
                    {"verb": v, "definition": "Atlas core verb", "common_objects": []}
                    for v in sorted(ATLAS_BASE_VERBS)
                ]
            }
        ],
        "verb_count": len(ATLAS_BASE_VERBS)
    }


def main():
    parser = argparse.ArgumentParser(description="Atlas Verb Glossary Builder")
    parser.add_argument("--domain", type=str, default=None,
                        help="Generate for specific domain only")
    parser.add_argument("--add-general", action="store_true",
                        help="Add general English action verbs")
    parser.add_argument("--list-domains", action="store_true",
                        help="List available domains")
    parser.add_argument("--merge", action="store_true",
                        help="Merge with existing tech_glossary.json")
    args = parser.parse_args()
    
    if args.list_domains:
        print("Available domains:")
        for key, info in DOMAINS.items():
            print(f"  {key:15s} — {info['name']}")
        return
    
    print("=" * 60)
    print("[glossary] Atlas Verb Glossary Builder v1.0")
    print(f"[glossary] Output: {GLOSSARY_FILE}")
    print("=" * 60)
    
    # Load existing glossary if merging
    glossary = {}
    if args.merge and GLOSSARY_FILE.exists():
        try:
            glossary = json.loads(GLOSSARY_FILE.read_text(encoding="utf-8"))
            print(f"[glossary] Loaded existing glossary ({len(glossary.get('all_verbs', []))} verbs)")
        except Exception:
            pass
    
    # Add Atlas base verbs
    add_atlas_base_verbs(glossary)
    print(f"[glossary] Added {len(ATLAS_BASE_VERBS)} Atlas core verbs")
    
    # Generate domain-specific verbs
    domains_to_process = {}
    if args.domain:
        if args.domain in DOMAINS:
            domains_to_process = {args.domain: DOMAINS[args.domain]}
        else:
            print(f"[glossary] Unknown domain: {args.domain}")
            print(f"[glossary] Use --list-domains to see available domains")
            return
    else:
        domains_to_process = DOMAINS
    
    for i, (key, info) in enumerate(domains_to_process.items()):
        result = generate_domain_verbs(key, info)
        if result:
            merge_into_glossary(glossary, result)
        
        # Rate limit between API calls
        if i < len(domains_to_process) - 1:
            delay = 5
            print(f"[glossary] Waiting {delay}s (rate limit)...")
            time.sleep(delay)
    
    # Generate general English verbs
    if args.add_general or not args.domain:
        general = generate_general_verbs()
        if general:
            merge_into_glossary(glossary, general)
    
    # Add metadata
    glossary["_metadata"] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "atlas_verb_glossary_builder.py v1.0",
        "total_verbs": len(glossary.get("all_verbs", [])),
        "domains_count": len(glossary.get("domains", {})),
        "priority": 2,
        "note": "Priority 2 = below Discord Golden Rules, above domain-specific rules"
    }
    
    # Save
    GLOSSARY_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    # Convert set to list if needed
    if isinstance(glossary.get("all_verbs"), set):
        glossary["all_verbs"] = sorted(list(glossary["all_verbs"]))
    
    GLOSSARY_FILE.write_text(
        json.dumps(glossary, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    
    total = len(glossary.get("all_verbs", []))
    domains = len(glossary.get("domains", {}))
    
    print(f"\n{'=' * 60}")
    print(f"[glossary] ✅ GLOSSARY SAVED: {GLOSSARY_FILE}")
    print(f"  Total unique verbs: {total}")
    print(f"  Domains covered: {domains}")
    for key, domain in glossary.get("domains", {}).items():
        vc = domain.get("verb_count", len(domain.get("categories", [{}])[0].get("verbs", [])))
        print(f"    • {key}: {domain.get('name', '')} ({vc} verbs)")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
