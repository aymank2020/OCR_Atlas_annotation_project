"""
atlas_knowledge_collector.py
─────────────────────────────
Collects policy knowledge from Discord exports and WhatsApp chat exports,
then feeds it into the 3 evaluation methods (API/Chat/Vertex) as enriched context.

Also downloads Discord video attachments as reference material.

Supported input formats:
  Discord: JSON export from DiscordChatExporter
  WhatsApp: .txt export from WhatsApp "Export Chat" feature

Output:
  outputs/knowledge/policy_lessons.jsonl     → structured Q&A pairs
  outputs/knowledge/knowledge_summary.txt    → combined context text for Gemini
  prompts/atlas_vertex_context_pack.txt      → auto-updated (merged with existing)

Usage:
  python atlas_knowledge_collector.py --discord-json discord_export.json
  python atlas_knowledge_collector.py --whatsapp-txt whatsapp_chat.txt
  python atlas_knowledge_collector.py --discord-json d.json --whatsapp-txt w.txt --update-context
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import urllib.request
import logging
from urllib.parse import urlparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from google.cloud import storage as gcs_storage
    HAS_GCS = True
except ImportError:
    HAS_GCS = False

# Configure Logger
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("knowledge_collector")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

LESSON_CATEGORY_KEYWORDS = {
    "verb_policy": ["verb", "action", "starts with", "imperative", "pick up", "place", "move"],
    "no_action_policy": ["no action", "inactivity", "when to use no action"],
    "hallucination": ["hallucination", "invented", "made up", "not in video", "fabricated"],
    "timestamp_policy": ["timestamp", "overlap", "gap", "gapless", "start", "end", "duration"],
    "numeral_policy": ["numeral", "number", "digit", "write two not 2"],
    "intent_policy": ["intent", "prepare to", "try to", "about to"],
    "object_policy": ["object", "tool", "device", "missing object", "place without"],
    "quality_gate": ["submit", "safe", "quality gate", "score", "threshold", "approve", "reject"],
    "general": [],
}

def _classify_lesson(text: str) -> str:
    low = text.lower()
    for category, keywords in LESSON_CATEGORY_KEYWORDS.items():
        if category == "general":
            continue
        if any(kw in low for kw in keywords):
            return category
    return "general"


# ---------------------------------------------------------------------------
# Discord parser
# ---------------------------------------------------------------------------

def parse_discord_export(json_path: Path) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Parse a Discord JSON export (DiscordChatExporter format).
    Returns (lessons, video_urls).
    """
    if not json_path.exists():
        return [], []

    try:
        data = json.loads(json_path.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:
        logger.error(f"Failed to parse Discord export {json_path}: {e}")
        return [], []

    messages = []
    if isinstance(data, dict):
        if "messages" in data:
            messages = data.get("messages", [])
        else:
            # Assuming channel map format from stealth scraper
            for ch_name, ch_msgs in data.items():
                if isinstance(ch_msgs, list):
                    messages.extend(ch_msgs)
    elif isinstance(data, list):
        messages = data

    lessons: List[Dict[str, Any]] = []
    video_urls: List[str] = []

    # Collect consecutive messages to find Q&A pairs
    prev_msg: Optional[Dict[str, Any]] = None

    for msg in messages:
        if not isinstance(msg, dict):
            continue

        content = str(msg.get("content", "") or "").strip()
        author_raw = msg.get("author", {})
        if isinstance(author_raw, dict):
            author = str(author_raw.get("name", "") or "").strip()
        else:
            author = str(author_raw or "").strip()
        timestamp = str(msg.get("timestamp", "") or "").strip()

        # Collect video attachments
        attachments = msg.get("attachments", []) or []
        for att in attachments:
            if not isinstance(att, dict):
                continue
            url = str(att.get("url", "") or "").strip()
            fname = str(att.get("filename", "") or "").strip().lower()
            if url and any(fname.endswith(ext) for ext in (".mp4", ".mov", ".webm", ".mkv")):
                video_urls.append(url)

        # Detect policy instructions / Q&A
        is_instruction = (
            len(content) > 30 and (
                any(kw in content.lower() for kw in [
                    "should", "must", "always", "never", "rule", "policy",
                    "correct", "wrong", "instead", "example", "note:",
                    "important", "remember", "تذكر", "يجب", "لازم", "مش",
                    "صح", "غلط", "مثال", "ملاحظة",
                ])
            )
        )

        if is_instruction and content:
            # Check if previous message was a question (Q&A pair)
            context = ""
            if prev_msg is not None:
                prev_content = str(prev_msg.get("content", "") or "").strip()
                if "?" in prev_content or "؟" in prev_content:
                    context = prev_content

            lesson = {
                "source": "discord",
                "author": author,
                "timestamp": timestamp,
                "category": _classify_lesson(content),
                "question": context,
                "answer": content,
                "raw": content,
            }
            lessons.append(lesson)

        prev_msg = msg

    return lessons, video_urls


# ---------------------------------------------------------------------------
# WhatsApp parser
# ---------------------------------------------------------------------------

def parse_whatsapp_export(txt_path: Path) -> List[Dict[str, Any]]:
    """
    Parse WhatsApp .txt export.
    Format: [DD/MM/YYYY, HH:MM:SS] Author: message
    or:     [DD/MM/YY, HH:MM] - Author: message
    """
    if not txt_path.exists():
        return []

    content = txt_path.read_text(encoding="utf-8", errors="replace")
    lessons: List[Dict[str, Any]] = []

    # Match both formats
    pattern = re.compile(
        r"(?:\[(\d{1,2}/\d{1,2}/\d{2,4}),\s*(\d{1,2}:\d{2}(?::\d{2})?)\]\s*"
        r"|(\d{1,2}/\d{1,2}/\d{2,4}),\s*(\d{1,2}:\d{2})\s*-\s*)"
        r"([^:]+):\s*(.+)"
    )

    prev_lesson: Optional[Dict[str, Any]] = None

    for match in pattern.finditer(content):
        date = match.group(1) or match.group(3) or ""
        time_s = match.group(2) or match.group(4) or ""
        author = str(match.group(5) or "").strip()
        message = str(match.group(6) or "").strip()

        # Skip system messages and media placeholders
        if message in ("<Media omitted>", "image omitted", "video omitted", "audio omitted"):
            continue
        if len(message) < 15:
            continue

        is_instruction = any(kw in message.lower() for kw in [
            "should", "must", "always", "never", "rule", "policy", "correct",
            "wrong", "instead", "example", "note", "important",
            "يجب", "لازم", "مش", "صح", "غلط", "مثال", "ملاحظة", "تذكر",
        ])

        if is_instruction:
            context = ""
            if prev_lesson is not None:
                prev_msg = str(prev_lesson.get("raw", "") or "").strip()
                if "?" in prev_msg or "؟" in prev_msg:
                    context = prev_msg

            lesson = {
                "source": "whatsapp",
                "author": author,
                "timestamp": f"{date} {time_s}".strip(),
                "category": _classify_lesson(message),
                "question": context,
                "answer": message,
                "raw": message,
            }
            lessons.append(lesson)
            prev_lesson = lesson
        else:
            prev_lesson = {"raw": message, "source": "whatsapp"}

    return lessons


def _is_safe_url(url: str) -> bool:
    """Basic check for Discord attachment URLs."""
    try:
        parsed = urlparse(url)
        return parsed.scheme == "https" and "discord" in parsed.netloc
    except Exception as e:
        logger.debug(f"URL safety check failed for {url[:50]}: {e}")
        return False


# ---------------------------------------------------------------------------
# Video downloader
# ---------------------------------------------------------------------------

def download_discord_videos(
    video_urls: List[str],
    out_dir: Path,
    max_videos: int = 20,
) -> List[Path]:
    """Download Discord video attachments as reference material."""
    out_dir.mkdir(parents=True, exist_ok=True)
    downloaded: List[Path] = []

    for i, url in enumerate(video_urls[:max_videos]):
        if not _is_safe_url(url):
            print(f"[knowledge] skipping unsafe url: {url[:80]}")
            continue
        filename = re.sub(r"[^\w\-.]", "_", url.split("/")[-1].split("?")[0])
        if not filename.endswith(".mp4"):
            filename = f"discord_ref_{i:03d}.mp4"
        out_path = out_dir / filename

        if out_path.exists():
            downloaded.append(out_path)
            continue

        try:
            print(f"[knowledge] downloading video {i+1}/{min(len(video_urls), max_videos)}: {filename}")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                out_path.write_bytes(resp.read())
            downloaded.append(out_path)
            print(f"[knowledge] saved: {out_path}")
        except Exception as exc:
            print(f"[knowledge] warn: download failed for {url[:80]}: {exc}")

    return downloaded


# ---------------------------------------------------------------------------
# Context builder — feeds lessons to evaluation methods
# ---------------------------------------------------------------------------

def build_knowledge_context(
    lessons: List[Dict[str, Any]],
    *,
    max_lessons_per_category: int = 15,
    max_total_chars: int = 24000,
) -> str:
    """
    Build a structured context text from collected lessons.
    Groups by category and formats as clear policy Q&A blocks.
    This text is appended to the Vertex context pack.
    """
    by_category: Dict[str, List[Dict[str, Any]]] = {}
    for lesson in lessons:
        cat = str(lesson.get("category", "general") or "general")
        by_category.setdefault(cat, []).append(lesson)

    parts = [
        "=== COLLECTED POLICY KNOWLEDGE (from team Discord/WhatsApp) ===",
        f"Total lessons: {len(lessons)}",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
        "",
    ]

    cat_order = [
        "verb_policy", "no_action_policy", "timestamp_policy", "numeral_policy",
        "intent_policy", "object_policy", "hallucination", "quality_gate", "general",
    ]

    for cat in cat_order:
        cat_lessons = by_category.get(cat, [])
        if not cat_lessons:
            continue
        parts.append(f"--- {cat.upper().replace('_', ' ')} ---")
        for lesson in cat_lessons[:max_lessons_per_category]:
            q = str(lesson.get("question", "") or "").strip()
            a = str(lesson.get("answer", "") or "").strip()
            src = str(lesson.get("source", "") or "")
            if q:
                parts.append(f"Q: {q}")
            parts.append(f"A [{src}]: {a}")
            parts.append("")

    result = "\n".join(parts)
    if len(result) > max_total_chars:
        result = result[:max_total_chars] + "\n...[truncated]"
    return result


def update_vertex_context_pack(
    knowledge_context: str,
    context_pack_path: Path,
    *,
    max_total_chars: int = 48000,
) -> None:
    """Merge new knowledge into the existing context pack file."""
    existing = ""
    if context_pack_path.exists():
        existing = context_pack_path.read_text(encoding="utf-8", errors="replace")

    # Remove old knowledge block if present
    marker = "=== COLLECTED POLICY KNOWLEDGE"
    if marker in existing:
        existing = existing[:existing.index(marker)].rstrip()

    merged = existing + "\n\n" + knowledge_context if existing else knowledge_context
    if len(merged) > max_total_chars:
        merged = merged[:max_total_chars]

    context_pack_path.parent.mkdir(parents=True, exist_ok=True)
    context_pack_path.write_text(merged, encoding="utf-8")
    print(f"[knowledge] context pack updated: {context_pack_path} ({len(merged)} chars)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def collect_and_enrich(
    *,
    discord_json_paths: List[Path],
    whatsapp_txt_paths: List[Path],
    outputs_dir: Path,
    update_context: bool = True,
    download_videos: bool = True,
    max_videos: int = 20,
    context_pack_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Full collection and enrichment pipeline."""
    all_lessons: List[Dict[str, Any]] = []
    all_video_urls: List[str] = []

    for p in discord_json_paths:
        print(f"[knowledge] parsing discord: {p}")
        lessons, video_urls = parse_discord_export(p)
        all_lessons.extend(lessons)
        all_video_urls.extend(video_urls)
        print(f"[knowledge] discord: {len(lessons)} lessons, {len(video_urls)} videos found")

    for p in whatsapp_txt_paths:
        print(f"[knowledge] parsing whatsapp: {p}")
        lessons = parse_whatsapp_export(p)
        all_lessons.extend(lessons)
        print(f"[knowledge] whatsapp: {len(lessons)} lessons found")

    # Deduplicate by answer text
    seen_answers: set = set()
    unique_lessons: List[Dict[str, Any]] = []
    for lesson in all_lessons:
        key = str(lesson.get("answer", "") or "")[:120]
        if key not in seen_answers:
            seen_answers.add(key)
            unique_lessons.append(lesson)

    print(f"[knowledge] total unique lessons: {len(unique_lessons)}")

    # Save lessons
    knowledge_dir = outputs_dir / "knowledge"
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    lessons_path = knowledge_dir / "policy_lessons.jsonl"
    with lessons_path.open("w", encoding="utf-8") as f:
        for lesson in unique_lessons:
            f.write(json.dumps(lesson, ensure_ascii=False) + "\n")

    # Build context text
    knowledge_context = build_knowledge_context(unique_lessons)
    summary_path = knowledge_dir / "knowledge_summary.txt"
    summary_path.write_text(knowledge_context, encoding="utf-8")
    print(f"[knowledge] summary saved: {summary_path}")

    # Update Vertex context pack
    if update_context:
        pack_path = context_pack_path or Path("prompts/atlas_vertex_context_pack.txt")
        update_vertex_context_pack(knowledge_context, pack_path)

    # Download videos
    downloaded_videos: List[Path] = []
    if download_videos and all_video_urls:
        video_ref_dir = knowledge_dir / "reference_videos"
        downloaded_videos = download_discord_videos(
            all_video_urls, video_ref_dir, max_videos=max_videos
        )
        print(f"[knowledge] downloaded {len(downloaded_videos)} reference videos")

    return {
        "lessons_total": len(unique_lessons),
        "lessons_by_category": {
            cat: sum(1 for l in unique_lessons if l.get("category") == cat)
            for cat in LESSON_CATEGORY_KEYWORDS
        },
        "videos_found": len(all_video_urls),
        "videos_downloaded": len(downloaded_videos),
        "lessons_path": str(lessons_path),
        "summary_path": str(summary_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect policy knowledge from Discord/WhatsApp")
    parser.add_argument("--discord-json", nargs="+", default=[], help="Discord JSON export file(s)")
    parser.add_argument("--whatsapp-txt", nargs="+", default=[], help="WhatsApp .txt export file(s)")
    parser.add_argument("--outputs-dir", default="outputs")
    parser.add_argument("--context-pack", default="prompts/atlas_vertex_context_pack.txt")
    parser.add_argument("--update-context", action="store_true", default=True)
    parser.add_argument("--no-update-context", dest="update_context", action="store_false")
    parser.add_argument("--download-videos", action="store_true", default=True)
    parser.add_argument("--no-download-videos", dest="download_videos", action="store_false")
    parser.add_argument("--max-videos", type=int, default=20)
    parser.add_argument("--gcs-bucket", type=str, default="", help="GCS bucket containing bot exports")
    parser.add_argument("--gcs-prefix", type=str, default="discord_knowledge", help="GCS folder prefix for bot exports")
    args = parser.parse_args()

    discord_paths = [Path(p) for p in args.discord_json if p]
    
    # Auto-fetch from GCS if configured
    if args.gcs_bucket and HAS_GCS:
        print(f"[knowledge] fetching bot exports from gs://{args.gcs_bucket}/{args.gcs_prefix} ...")
        try:
            client = gcs_storage.Client()
            bucket = client.bucket(args.gcs_bucket)
            blobs = list(bucket.list_blobs(prefix=args.gcs_prefix))
            if blobs:
                gcs_dl_dir = Path("data/discord_autofetch_gcs")
                gcs_dl_dir.mkdir(parents=True, exist_ok=True)
                for blob in blobs:
                    if not blob.name.endswith(".json"):
                        continue
                    fname = blob.name.split("/")[-1]
                    local_p = gcs_dl_dir / fname
                    if not local_p.exists():
                        blob.download_to_filename(str(local_p))
                        print(f"  -> downloaded {fname}")
                    discord_paths.append(local_p)
        except Exception as e:
            print(f"[knowledge] GCS fetch failed: {e}")

    whatsapp_paths = [Path(p) for p in args.whatsapp_txt if p]

    if not discord_paths and not whatsapp_paths and not args.gcs_bucket:
        parser.error("Provide at least --discord-json, --whatsapp-txt, or --gcs-bucket")

    stats = collect_and_enrich(
        discord_json_paths=discord_paths,
        whatsapp_txt_paths=whatsapp_paths,
        outputs_dir=Path(args.outputs_dir),
        update_context=args.update_context,
        download_videos=args.download_videos,
        max_videos=args.max_videos,
        context_pack_path=Path(args.context_pack),
    )

    print("\n[knowledge] Collection complete:")
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
