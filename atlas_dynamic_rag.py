"""
atlas_dynamic_rag.py
──────────────────────
A lightweight Retrieval-Augmented Generation (RAG) module.

Sources of knowledge:
  1. outputs/knowledge/policy_lessons.jsonl  — corrections from Discord/WhatsApp bots
  2. outputs/knowledge/golden_index.jsonl    — Drive golden dataset reference samples

Reads the original Atlas segments to understand the context of the current video,
then searches both sources to retrieve only the rules and examples relevant to this task.

This solves the "static prompt" issue which confuses the model with irrelevant rules.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List


LESSONS_PATH = "data/knowledge/policy_lessons.jsonl"
GOLDEN_INDEX_PATH = "data/knowledge/golden_index.jsonl"


def extract_keywords(text: str) -> set:
    """Extract lowercase alphabetic words from text, excluding stop words."""
    stop_words = {
        "the", "a", "an", "and", "or", "is", "are", "to", "from",
        "in", "on", "at", "of", "for", "that", "this", "with",
    }
    words = re.findall(r"[a-z]+", text.lower())
    return set(w for w in words if w not in stop_words and len(w) > 2)


def _load_jsonl(path: str) -> List[Dict[str, Any]]:
    """Load all lines from a JSONL file, skipping bad lines."""
    p = Path(path)
    if not p.exists():
        return []
    records = []
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                clean = line.strip()
                if not clean:
                    continue
                try:
                    records.append(json.loads(clean))
                except Exception:
                    continue
    except Exception as e:
        print(f"[RAG] Warning: Global failure reading {path}: {e}")
    return records


def _score_against_video(record_text: str, video_keywords: set) -> int:
    """Calculate how many keywords overlap between the record and the video."""
    record_keywords = extract_keywords(record_text)
    return len(video_keywords.intersection(record_keywords))


class AtlasContextHub:
    """
    Unified Memory & Context Hub (OpenViking Style).
    Unifies policy lessons, golden examples, and skills into a smart retrieval engine.
    """
    def __init__(self, lessons_path: str = LESSONS_PATH, golden_path: str = GOLDEN_INDEX_PATH):
        self.lessons_path = Path(lessons_path)
        self.golden_path = Path(golden_path)
        self.universal_categories = {"timestamp_policy", "hallucination", "quality_gate"}

    def _load_all(self, path: Path) -> List[Dict[str, Any]]:
        """Load JSONL robustly."""
        if not path.exists(): return []
        records = []
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    clean = line.strip()
                    if not clean: continue
                    try:
                        records.append(json.loads(clean))
                    except Exception:
                        continue
        except Exception as e:
            print(f"[Hub] Warning: Global failure reading {path.name}: {e}")
        return records

    def get_context(self, source_segments: List[Any], max_lessons=10, max_examples=2) -> str:
        # 1. Profile the current video (handle both dicts and plain strings)
        texts = []
        for s in source_segments:
            if isinstance(s, dict):
                texts.append(str(s.get("label", s.get("current_label", ""))))
            else:
                texts.append(str(s))
        
        segment_text = " ".join(texts)
        keywords = extract_keywords(segment_text)
        
        context_parts = []

        # 2. Retrieve Policy Lessons (The "Audit Brain")
        lessons = self._load_all(self.lessons_path)
        scored = []
        if lessons:
            for l in lessons:
                if l.get("category") in self.universal_categories:
                    scored.append((1000, l))
                else:
                    text = f"{l.get('question', '')} {l.get('answer', '')}"
                    scored.append((_score_against_video(text, keywords), l))

        if scored:
            scored.sort(key=lambda x: x[0], reverse=True)
        # Use simple slice and handle top items
        top_items = scored[:int(max_lessons)]
        top = [l for s, l in top_items if s > 0 or l.get("category") in self.universal_categories]
        if top:
            context_parts.append("=== POLICY AUDIT MEMORY (Corrections) ===")
            for l in top:
                q, a, src = str(l.get("question", "")), str(l.get("answer", "")), str(l.get("source", "qa"))
                if q: context_parts.append(f"Q: {q}")
                context_parts.append(f"A [{src}]: {a}\n")
            print(f"[Hub] Retrieved {len(top)} policy lessons.")

        # 3. Retrieve Golden Examples (The "Reference Skills")
        golden_data = self._load_all(self.golden_path)
        golden = [g for g in golden_data if g.get("has_labels")]
        if golden:
            scored_g = []
            for g in golden:
                s = _score_against_video(" ".join(g.get("keywords", [])), keywords)
                if g.get("labels", {}).get("human_corrected"): s += 5 # Quality boost
                scored_g.append((s, g))
            
            scored_g.sort(key=lambda x: x[0], reverse=True)
            top_g_items = scored_g[:int(max_examples)]
            top_g = [g for s, g in top_g_items if s > 0]
            if top_g:
                context_parts.append("=== REFERENCE SKILLS (Golden Examples) ===")
                for g in top_g:
                    context_parts.append(f"Example: {g.get('filename')}")
                    segments = g.get("labels", {}).get("segments", [])
                    for seg in segments[:5]:
                        context_parts.append(f"  [{seg.get('index', '?')}] {seg.get('start_sec')}s-{seg.get('end_sec')}s: {seg.get('label')}")
                    context_parts.append("")
                print(f"[Hub] Retrieved {len(top_g)} golden examples.")

        if not context_parts: return ""
        
        header = [
            "=== ATLAS UNIFIED CONTEXT HUB ===",
            "Context-aware memory unified from QA audits and golden dataset.",
            "Use these specific rules to override general model behavior.\n"
        ]
        return "\n".join(header + context_parts)

# Backward Compatibility wrapper
def retrieve_dynamic_context(*args, **kwargs) -> str:
    hub = AtlasContextHub()
    return hub.get_context(*args, **kwargs)
