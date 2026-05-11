"""
atlas_correction_chat.py
─────────────────────────
Human-in-the-Loop Correction Chat Interface for Atlas Pipeline.

When Gemini's output fails policy validation or confidence is low,
this script is invoked to let the QA team provide the correct answer,
which is then:
  1. Applied directly to the Atlas episode
  2. Saved to policy_lessons.jsonl for future RAG retrieval
  3. Used to generate a high-quality response for the blocked episode

Usage:
  python atlas_correction_chat.py \\
      --episode-id 68f15a779eff7d93259ab8cc \\
      --config sample_web_auto_solver_production.yaml
"""

import argparse
import json
import sys
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


LESSONS_DEFAULT_PATH = "outputs/knowledge/policy_lessons.jsonl"
OUTPUTS_DIR = Path("outputs")


def _load_json(path: str) -> Optional[Dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[correction] Warning: Failed to load {path}: {e}")
        return None


def _save_lesson(lesson: Dict[str, Any], lessons_path: str) -> None:
    Path(lessons_path).parent.mkdir(parents=True, exist_ok=True)
    with open(lessons_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(lesson, ensure_ascii=False) + "\n")
    print(f"[correction] ✔ Lesson saved to {lessons_path}")


def _display_episode_summary(episode_id: str, segments: List[Dict[str, Any]], errors: List[str]) -> None:
    print()
    print("=" * 60)
    print(f"  EPISODE: {episode_id}")
    print("=" * 60)

    if errors:
        print("\n  ❌ VALIDATION ERRORS:")
        for e in errors:
            print(f"     • {e}")

    print("\n  📋 CURRENT / PROPOSED SEGMENTS:")
    for seg in segments:
        idx   = seg.get("segment_index", seg.get("index", "?"))
        start = seg.get("start_sec", "?")
        end   = seg.get("end_sec", "?")
        label = seg.get("label", seg.get("current_label", "?"))
        print(f"     [{idx}] {start}s → {end}s  |  {label}")

    print()


def _prompt_user(prompt_text: str) -> str:
    sys.stdout.flush()
    try:
        return input(prompt_text).strip()
    except (EOFError, KeyboardInterrupt):
        print("\n[correction] Aborted by user.")
        sys.exit(0)


def run_correction_chat(
    episode_id: str,
    lessons_path: str = LESSONS_DEFAULT_PATH,
) -> Optional[Dict[str, Any]]:
    """
    Open interactive correction session for a failed episode.
    Returns the corrected payload (operations + segments) or None to skip.
    """
    # Detect outputs from the failed episode
    segments_file  = OUTPUTS_DIR / f"segments_{episode_id}.json"
    labels_file    = OUTPUTS_DIR / f"labels_{episode_id}.json"
    validation_file = OUTPUTS_DIR / f"validation_{episode_id}.json"

    # Load data
    segments_data = _load_json(str(segments_file)) or []
    if isinstance(segments_data, dict):
        segments_data = segments_data.get("segments", [])

    labels_data = _load_json(str(labels_file)) or {}
    validation_data = _load_json(str(validation_file)) or {}
    errors = validation_data.get("errors", [])

    # Display current state
    _display_episode_summary(episode_id, segments_data, errors)

    print("  📺 TO WATCH THE VIDEO:")
    print(f"     Look in outputs/video_{episode_id}.mp4")
    print()
    print("  HOW TO CORRECT:")
    print("  ─────────────────────────────────────────────────────────")
    print("  Option A: Paste the corrected JSON payload (then press ENTER twice)")
    print("  Option B: Type 'skip' to skip this episode")
    print("  Option C: Type 'accept' to accept Gemini's labels as-is")
    print()

    lines = []
    print("  > Paste your JSON (or command) below:")
    while True:
        try:
            line = input()
        except (EOFError, KeyboardInterrupt):
            break
        if len(lines) == 0:
            cmd = line.strip().lower()
            if cmd in ("skip", "accept"):
                if cmd == "skip":
                    print("[correction] Episode skipped.")
                    return None
                if cmd == "accept":
                    print("[correction] Accepted Gemini's labels as-is.")
                    return labels_data  # Return original labels
        lines.append(line)
        # Detect end of JSON (empty line after content)
        if len(lines) >= 2 and lines[-1] == "" and lines[-2] == "":
            break

    raw_text = "\n".join(lines).strip()
    if not raw_text:
        print("[correction] No input received. Episode skipped.")
        return None

    # Parse correction
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as e:
        print(f"[correction] ❌ Invalid JSON: {e}")
        print("[correction] Episode skipped. Please try again with valid JSON.")
        return None

    # Save this correction as a policy lesson for future RAG
    corrected_segments = payload.get("segments", [])
    if corrected_segments:
        # Create a summary of what was corrected
        old_labels = [str(s.get("label", s.get("current_label", ""))) for s in segments_data]
        new_labels = [str(s.get("label", "")) for s in corrected_segments]
        lesson = {
            "source": "human_correction",
            "category": "episode_correction",
            "episode_id": episode_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "question": f"How should segments {old_labels} be labeled?",
            "answer": f"Corrected labels: {new_labels}. Validation errors were: {errors}",
            "errors": errors,
            "original_segment_count": len(segments_data),
            "corrected_segment_count": len(corrected_segments),
            "payload": payload,
        }
        _save_lesson(lesson, lessons_path)

    print()
    print("[correction] ✅ Correction accepted and saved.")
    print(f"[correction] → {len(corrected_segments)} corrected segments will be applied.")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Atlas Human-in-the-Loop Correction Chat")
    parser.add_argument("--episode-id", required=True, help="Episode ID to correct")
    parser.add_argument("--lessons-path", default=LESSONS_DEFAULT_PATH,
                        help="Path to policy_lessons.jsonl")
    parser.add_argument("--config", default="", help="Config YAML path (unused, for compatibility)")
    args = parser.parse_args()

    result = run_correction_chat(
        episode_id=args.episode_id,
        lessons_path=args.lessons_path,
    )

    if result:
        # Save the approved payload so the main pipeline can pick it up
        output_path = OUTPUTS_DIR / f"correction_{args.episode_id}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"[correction] Correction payload saved: {output_path}")
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
