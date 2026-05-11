"""
Process Discord harvest: extract rules, announcements, Q&A from scraped messages.
Uses keyword detection + Gemini API to extract and synthesize policy updates.
"""
import json
import re
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

PROJECT_ROOT = Path(__file__).parent
HARVEST_FILE = PROJECT_ROOT / "outputs" / "discord_exports" / "harvest_2026-03-27_to_now_20260424_161951.json"

# Trusted authors (admins, QA leads, reviewers) - names from Discord
TRUSTED_AUTHORS = {
    "sentientcake", "sentientcake0", "atlascapture", "atlas",
    "ryanhanks", "alex", "jc_atlas", "atlasadmin", "atlasbot",
    "reviewer", "qa_lead", "trainer", "mod", "admin",
}

# Rule detection keywords
RULE_KEYWORDS = [
    "hold", "label", "segment", "annotation", "annotate", "labeling",
    "ego", "action", "coarse", "dense", "granularity", "must be labeled",
    "must label", "key rule", "effective immediately", "clarification",
    "merge", "split", "no action", "loosen", "remove", "place",
    "pick up", "timestamp", "overlap", "consecutive", "forbidden",
    "acceptable", "unacceptable", "correct", "incorrect",
    "policy", "rule update", "rule change", "new rule",
    "attention", "important", "reminder", "please note",
]

ANNOUNCEMENT_KEYWORDS = [
    "announcement", "update", "important", "reminder",
    "effective immediately", "please note", "attention",
    "changes to", "new rule", "policy", "mandatory",
    "everyone", "here", "notice", "updated", "revision",
]

NOISE_KEYWORDS = [
    "payment", "wallet", "crypto", "gift card", "boost",
    "nitro", "otp", "2fa", "ban", "suspended",
    "meme", "lol", "lmao", "haha", "xd",
]

DEPRECATED_KEYWORDS = [
    "easy room", "easy video", "easy category",
    "verbs ending in", "use ing", "using ing",
    "present participle",
]


def is_trusted(author: str) -> bool:
    lower = author.lower().strip()
    return any(t in lower for t in TRUSTED_AUTHORS)


def categorize(content: str, author: str, is_pinned: bool, channel: str) -> str:
    lower = content.lower()
    if len(lower) < 30:
        return "skip"

    # Skip noise
    if sum(1 for nk in NOISE_KEYWORDS if nk in lower) >= 2:
        return "skip"
    if sum(1 for dk in DEPRECATED_KEYWORDS if dk in lower) >= 1:
        return "skip"

    # Announcements channel messages are always important
    if "announcement" in channel.lower():
        if len(content) > 50:
            return "announcement"

    rule_hits = sum(1 for kw in RULE_KEYWORDS if kw in lower)
    ann_hits = sum(1 for kw in ANNOUNCEMENT_KEYWORDS if kw in lower)

    # Pinned messages are almost always important
    if is_pinned and len(content) > 50:
        return "rule" if rule_hits >= 2 else "announcement"

    # Trusted authors with rule keywords = definitely a rule
    trusted = is_trusted(author)
    if trusted and rule_hits >= 2:
        return "rule"
    if trusted and ann_hits >= 2:
        return "announcement"

    # High rule keyword density
    if rule_hits >= 4:
        return "rule"
    if ann_hits >= 3:
        return "announcement"

    # Moderate rule + long content from anyone
    if rule_hits >= 2 and len(content) > 200:
        return "rule"

    # Q&A detection
    if "?" in content and len(content) > 80:
        return "qa"

    if len(content) > 300 and (rule_hits >= 1 or ann_hits >= 1):
        return "important"

    return "skip"


def clean_content(content: str) -> str:
    text = re.sub(r"<@[!&]?\d+>", "", content)
    text = re.sub(r"@(?:everyone|here)", "", text)
    text = re.sub(r"<:\w+:\d+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_date(ts: str) -> str:
    try:
        return ts[:10]
    except Exception:
        return "unknown"


def main():
    print(f"[process] Loading harvest from {HARVEST_FILE.name}...")
    data = json.loads(HARVEST_FILE.read_text(encoding="utf-8"))

    messages_by_channel = data.get("messages_by_channel", {})

    rules = []
    announcements = []
    qa_pairs = []
    important = []
    stats = {"total": 0, "rules": 0, "announcements": 0, "qa": 0, "important": 0, "skipped": 0}

    for ch_name, messages in messages_by_channel.items():
        print(f"\n[process] Channel: #{ch_name} ({len(messages)} messages)")
        ch_rules = ch_ann = ch_qa = ch_imp = ch_skip = 0

        for msg in messages:
            stats["total"] += 1
            content = msg.get("content", "")
            author = msg.get("author", "Unknown")
            pinned = msg.get("pinned", False)
            ts = msg.get("timestamp", "")

            cat = categorize(content, author, pinned, ch_name)

            entry = {
                "id": msg.get("id"),
                "author": author,
                "timestamp": ts,
                "date": extract_date(ts),
                "content": content,
                "clean_content": clean_content(content),
                "channel": ch_name,
                "pinned": pinned,
                "is_reply": msg.get("is_reply", False),
                "reply_to": msg.get("reply_to_content", ""),
                "reply_author": msg.get("reply_to_author", ""),
                "attachments": msg.get("attachments", []),
            }

            if cat == "rule":
                rules.append(entry)
                ch_rules += 1
                stats["rules"] += 1
            elif cat == "announcement":
                announcements.append(entry)
                ch_ann += 1
                stats["announcements"] += 1
            elif cat == "qa":
                qa_pairs.append(entry)
                ch_qa += 1
                stats["qa"] += 1
            elif cat == "important":
                important.append(entry)
                ch_imp += 1
                stats["important"] += 1
            else:
                ch_skip += 1
                stats["skipped"] += 1

        print(f"  Rules: {ch_rules}, Announcements: {ch_ann}, Q&A: {ch_qa}, Important: {ch_imp}, Skipped: {ch_skip}")

    # Sort by date
    rules.sort(key=lambda x: x["timestamp"])
    announcements.sort(key=lambda x: x["timestamp"])

    print(f"\n{'=' * 60}")
    print(f"[process] EXTRACTION COMPLETE")
    print(f"  Total messages: {stats['total']}")
    print(f"  Rules: {stats['rules']}")
    print(f"  Announcements: {stats['announcements']}")
    print(f"  Q&A: {stats['qa']}")
    print(f"  Important: {stats['important']}")
    print(f"  Skipped: {stats['skipped']}")

    # Save extracted data
    out_dir = PROJECT_ROOT / "outputs" / "discord_processed"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Save rules
    rules_file = out_dir / "extracted_rules.json"
    rules_file.write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  Rules saved: {rules_file} ({len(rules)} entries)")

    # Save announcements
    ann_file = out_dir / "extracted_announcements.json"
    ann_file.write_text(json.dumps(announcements, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  Announcements saved: {ann_file} ({len(announcements)} entries)")

    # Save Q&A (just count, too many to process all)
    qa_file = out_dir / "extracted_qa.json"
    qa_file.write_text(json.dumps(qa_pairs[:5000], ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  Q&A saved: {qa_file} ({min(len(qa_pairs), 5000)} entries)")

    # Save important
    imp_file = out_dir / "extracted_important.json"
    imp_file.write_text(json.dumps(important[:5000], ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  Important saved: {imp_file} ({min(len(important), 5000)} entries)")

    # Generate markdown summaries
    # Rules markdown
    rules_md = out_dir / "discord_rules_march27_to_now.md"
    with open(rules_md, "w", encoding="utf-8") as f:
        f.write(f"# Discord Rules Extracted (March 27 - April 24, 2026)\n\n")
        f.write(f"Total: {len(rules)} rule-related messages\n\n")

        # Group by date
        by_date = {}
        for r in rules:
            d = r["date"]
            by_date.setdefault(d, []).append(r)

        for date in sorted(by_date.keys()):
            f.write(f"\n## {date}\n\n")
            for r in by_date[date]:
                trusted_tag = " [TRUSTED]" if is_trusted(r["author"]) else ""
                pinned_tag = " [PINNED]" if r["pinned"] else ""
                f.write(f"### {r['author']}{trusted_tag}{pinned_tag} in #{r['channel']}\n")
                f.write(f"{r['clean_content'][:1000]}\n\n")
                if r["attachments"]:
                    for att in r["attachments"]:
                        f.write(f"- Attachment: {att.get('filename', 'unknown')}\n")
                f.write("---\n\n")

    print(f"\n  Rules markdown: {rules_md}")

    # Announcements markdown
    ann_md = out_dir / "discord_announcements_march27_to_now.md"
    with open(ann_md, "w", encoding="utf-8") as f:
        f.write(f"# Discord Announcements (March 27 - April 24, 2026)\n\n")
        f.write(f"Total: {len(announcements)} announcement messages\n\n")
        for a in announcements:
            trusted_tag = " [TRUSTED]" if is_trusted(a["author"]) else ""
            f.write(f"### {a['date']} - {a['author']}{trusted_tag} in #{a['channel']}\n")
            f.write(f"{a['clean_content'][:2000]}\n\n---\n\n")

    print(f"  Announcements markdown: {ann_md}")

    # Print the most important rules (from trusted sources)
    trusted_rules = [r for r in rules if is_trusted(r["author"])]
    print(f"\n{'=' * 60}")
    print(f"[process] TRUSTED AUTHOR RULES: {len(trusted_rules)}")
    print(f"{'=' * 60}")
    for r in trusted_rules[:30]:
        print(f"\n--- {r['date']} | {r['author']} | #{r['channel']} ---")
        print(r["clean_content"][:500])

    # Print all announcements
    print(f"\n{'=' * 60}")
    print(f"[process] ALL ANNOUNCEMENTS: {len(announcements)}")
    print(f"{'=' * 60}")
    for a in announcements:
        print(f"\n--- {a['date']} | {a['author']} | #{a['channel']} ---")
        print(a["clean_content"][:800])


if __name__ == "__main__":
    main()
