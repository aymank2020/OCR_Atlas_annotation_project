"""
Atlas Mistake Extractor — Self-Improving AI Engine

Reads QA correction files (qa_approved_golden_*.json vs ai_corrected_labels_*.json)
and extracts mistakes into prompts/negative_examples.json for future prompt injection.

Usage:
    python atlas_mistake_extractor.py --qa-dir outputs/local_trial
    python atlas_mistake_extractor.py --qa-file outputs/local_trial/qa_approved_golden_69058134.json
"""
import json
import re
import sys
from pathlib import Path
from typing import List, Dict, Any

NEGATIVE_EXAMPLES_PATH = Path(__file__).parent / "prompts" / "negative_examples.json"

# Rule detection patterns
HOLD_INTENT_PATTERN = re.compile(
    r"\bhold\b.+\b(to\s+(check|see|verify|inspect|examine|test|ensure|confirm|observe|look|monitor|view))\b",
    re.IGNORECASE,
)
INTENT_VERBS = {"examine", "inspect", "observe", "look at", "check", "verify", "test", "monitor"}


def load_negative_examples() -> List[Dict[str, Any]]:
    """Load existing negative examples."""
    if NEGATIVE_EXAMPLES_PATH.exists():
        return json.loads(NEGATIVE_EXAMPLES_PATH.read_text(encoding="utf-8"))
    return []


def save_negative_examples(examples: List[Dict[str, Any]]) -> None:
    """Save negative examples back to file."""
    NEGATIVE_EXAMPLES_PATH.write_text(
        json.dumps(examples, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[extractor] Saved {len(examples)} negative examples to {NEGATIVE_EXAMPLES_PATH}")


def detect_rule_violation(ai_label: str, qa_label: str) -> str:
    """Detect which rule was violated based on label differences."""
    if HOLD_INTENT_PATTERN.search(ai_label):
        return "RULE-HOLD"
    if ai_label.lower().startswith("hold") and qa_label.lower().startswith("hold"):
        if len(ai_label) > len(qa_label) + 5:
            return "RULE-HOLD"
    for verb in INTENT_VERBS:
        if verb in ai_label.lower() and verb not in qa_label.lower():
            return "RULE-NOINTENT"
    return "RULE-UNKNOWN"


def extract_from_qa_file(qa_path: Path) -> List[Dict[str, Any]]:
    """Extract mistakes by comparing QA-approved labels against AI-corrected labels."""
    qa_data = json.loads(qa_path.read_text(encoding="utf-8"))
    episode_id = qa_data.get("episode_id", "unknown")
    qa_segments = {s["index"]: s for s in qa_data.get("segments", [])}

    # Find matching AI file
    ai_path = qa_path.parent / qa_path.name.replace("qa_approved_golden_", "ai_corrected_labels_")
    if not ai_path.exists():
        print(f"[extractor] WARNING: No AI file found for {qa_path.name}")
        return []

    ai_data = json.loads(ai_path.read_text(encoding="utf-8"))
    ai_segments = {s["index"]: s for s in ai_data.get("ai_corrected_segments", [])}

    mistakes = []

    # Check segment count difference (merge happened)
    if len(ai_segments) != len(qa_segments):
        mistakes.append({
            "episode_id": episode_id,
            "date": qa_data.get("approved_at", "")[:10],
            "rule_violated": "RULE-MERGE",
            "ai_label": f"AI had {len(ai_segments)} segments",
            "corrected_label": f"QA approved {len(qa_segments)} segments (after merging)",
            "explanation": "QA merged consecutive segments with identical actions under 60s cap.",
            "segment_index": "multiple",
            "severity": "HIGH",
        })

    # Check individual label differences
    for idx, qa_seg in qa_segments.items():
        ai_seg = ai_segments.get(idx)
        if not ai_seg:
            continue
        if qa_seg["label"] != ai_seg["label"]:
            rule = detect_rule_violation(ai_seg["label"], qa_seg["label"])
            mistakes.append({
                "episode_id": episode_id,
                "date": qa_data.get("approved_at", "")[:10],
                "rule_violated": rule,
                "ai_label": ai_seg["label"],
                "corrected_label": qa_seg["label"],
                "explanation": f"AI label differed from QA-approved label at segment {idx}.",
                "segment_index": idx,
                "severity": "HIGH" if rule in ("RULE-HOLD", "RULE-MERGE") else "MEDIUM",
            })

    return mistakes


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Extract AI mistakes for self-improving pipeline")
    parser.add_argument("--qa-dir", help="Directory containing qa_approved_golden_*.json files")
    parser.add_argument("--qa-file", help="Single QA-approved file to process")
    args = parser.parse_args()

    existing = load_negative_examples()
    existing_keys = {(e["episode_id"], str(e.get("segment_index", ""))) for e in existing}
    new_mistakes = []

    if args.qa_file:
        files = [Path(args.qa_file)]
    elif args.qa_dir:
        files = list(Path(args.qa_dir).glob("qa_approved_golden_*.json"))
    else:
        print("[extractor] ERROR: Specify --qa-dir or --qa-file")
        sys.exit(1)

    for f in files:
        print(f"[extractor] Processing {f.name}...")
        mistakes = extract_from_qa_file(f)
        for m in mistakes:
            key = (m["episode_id"], str(m.get("segment_index", "")))
            if key not in existing_keys:
                new_mistakes.append(m)
                existing_keys.add(key)

    if new_mistakes:
        existing.extend(new_mistakes)
        save_negative_examples(existing)
        print(f"[extractor] Added {len(new_mistakes)} new mistakes")
    else:
        print("[extractor] No new mistakes found")


if __name__ == "__main__":
    main()
