"""
atlas_knowledge_ingest.py
-------------------------
Atlas Knowledge Ingestor — supports multiple JSON formats:
  1. DiscordChatExporter:  {"messages": [{"id": "...", "content": "..."}]}
  2. Pre-purified Rules:   {"rules": [{"rule": "...", "category": "...", "source_message_id": "..."}]}
  3. Discrub (list):       [{"id": "...", "content": "..."}]

Appends formatted knowledge to the Vertex Context Pack and optionally
triggers a project-wide Git + Vertex sync.

SPEC REF: FR-003 (spec-002), FR-007..FR-010 (spec-003)
"""

import os
import re
import json
import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Set, List, Dict, Any

from src.policy import context_manager as policy_context

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

CONTEXT_PACK_PATH = Path("prompts/atlas_vertex_context_pack.txt")

# Categories from rules JSON that are relevant to annotation work.
# Anything NOT in this set will be filtered out.
ALLOWED_RULE_CATEGORIES = {
    "Labeling", "labeling",
    "Merging", "merging",
    "Splitting", "splitting",
    "Timing", "timing",
    "Quality", "quality",
    "General", "general",
    "Segmentation", "segmentation",
    "Convention", "convention",
    "Best Practice", "best practice",
}


class KnowledgeIngestor:
    """Unified ingestor supporting multiple Discord/Rules JSON formats."""

    def __init__(self, context_pack_path: Path = CONTEXT_PACK_PATH, policy_root: Optional[Path] = None):
        self.context_pack_path = context_pack_path
        self.policy_root = policy_root or policy_context.POLICY_ROOT
        self.existing_ids: Set[str] = self._load_existing_ids()
        self._pending_policy_messages: List[Dict[str, Any]] = []
        self._pending_policy_rules: List[Dict[str, Any]] = []
        policy_context.ensure_policy_files(self.policy_root)

    def _load_existing_ids(self) -> Set[str]:
        """Extract existing Discord Message IDs from the context pack to prevent duplicates."""
        ids: Set[str] = set()
        if not self.context_pack_path.exists():
            return ids
        try:
            content = self.context_pack_path.read_text(encoding="utf-8")
            # Pattern to find [ID: 12345] or [SRC: 12345] in the file
            found = re.findall(r"\[(?:ID|SRC): (\d+)\]", content)
            ids.update(found)
        except Exception as e:
            logger.warning(f"Could not load existing IDs: {e}")
        return ids

    def _detect_format(self, data: Any) -> str:
        """Auto-detect JSON format: 'rules', 'messages', or 'discrub'."""
        if isinstance(data, list):
            return "discrub"
        if isinstance(data, dict):
            if "rules" in data:
                return "rules"
            if "messages" in data:
                return "messages"
        return "unknown"

    def ingest(self, json_path: Path, do_sync: bool = False,
               config_path: str = "sample_web_auto_solver_production.yaml") -> int:
        """
        Main entry point: auto-detect format and ingest accordingly.
        Returns the number of new entries ingested.
        """
        if not json_path.exists():
            logger.error(f"File not found: {json_path}")
            return 0

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"Failed to parse JSON from {json_path}: {e}")
            return 0

        fmt = self._detect_format(data)
        logger.info(f"📁 Detected format: '{fmt}' for {json_path.name}")

        self._pending_policy_messages = []
        self._pending_policy_rules = []
        if fmt == "rules":
            count = self._ingest_rules(data)
        elif fmt == "messages":
            count = self._ingest_messages(data.get("messages", []))
        elif fmt == "discrub":
            count = self._ingest_messages(data)
        else:
            logger.error(f"Unknown JSON format in {json_path}. Expected 'rules', 'messages', or list.")
            return 0

        self._sync_policy_candidates()

        if count > 0:
            logger.info(f"✅ Successfully ingested {count} new entries from {json_path.name}")
            if do_sync:
                self._trigger_sync(config_path)
        else:
            logger.info(f"No new knowledge found in {json_path.name} (all duplicates or filtered).")

        return count

    def _ingest_rules(self, data: Dict[str, Any]) -> int:
        """
        Ingest pre-purified rules JSON format:
        {"rules": [{"rule": "...", "category": "...", "source_message_id": "...", "extracted_at": "..."}]}
        
        Filters out non-annotation categories and deduplicates by source_message_id.
        """
        rules: List[Dict[str, Any]] = data.get("rules", [])
        new_entries: List[str] = []
        count = 0

        for rule_obj in rules:
            rule_text = str(rule_obj.get("rule", "")).strip()
            if not rule_text:
                continue

            category = str(rule_obj.get("category", "General")).strip()
            source_id = str(rule_obj.get("source_message_id", ""))
            extracted_at = str(rule_obj.get("extracted_at", ""))

            # --- Filter: skip non-annotation categories ---
            if category and category not in ALLOWED_RULE_CATEGORIES:
                logger.debug(f"Skipping rule (category={category}): {rule_text[:50]}...")
                continue

            # --- Deduplicate by source_message_id ---
            if source_id and source_id in self.existing_ids:
                continue

            # --- Format entry ---
            entry = (
                f"\n\n# === Golden Rule ({extracted_at}) [{category}] ===\n"
                f"[SRC: {source_id}] {rule_text}"
            )
            new_entries.append(entry)
            self._pending_policy_rules.append(rule_obj)
            if source_id:
                self.existing_ids.add(source_id)
            count += 1

        if new_entries:
            self._append_to_context_pack(new_entries)

        return count

    def _ingest_messages(self, messages: List[Dict[str, Any]]) -> int:
        """
        Ingest DiscordChatExporter or Discrub format messages.
        {"messages": [{"id": "...", "content": "...", "author": {...}, "timestamp": "..."}]}
        """
        new_entries: List[str] = []
        count = 0

        for msg in messages:
            msg_id = str(msg.get("id", ""))
            if msg_id and msg_id in self.existing_ids:
                continue

            content = str(msg.get("content", "")).strip()
            if not content:
                continue

            author = msg.get("author", {})
            if isinstance(author, dict):
                author_name = author.get("username") or author.get("name") or "unknown"
            else:
                author_name = "unknown"
            timestamp = str(msg.get("timestamp", ""))

            entry = f"\n\n# === Exported Entry ({timestamp}) ===\n[{author_name}] [ID: {msg_id}] {content}"
            new_entries.append(entry)
            self._pending_policy_messages.append(msg)
            if msg_id:
                self.existing_ids.add(msg_id)
            count += 1

        if new_entries:
            self._append_to_context_pack(new_entries)

        return count

    def _append_to_context_pack(self, entries: List[str]) -> None:
        """Append entries to the context pack file."""
        self.context_pack_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.context_pack_path, "a", encoding="utf-8") as f:
            f.write("".join(entries))

    def _sync_policy_candidates(self) -> None:
        report: Dict[str, Any] = {}
        if self._pending_policy_messages:
            report = policy_context.ingest_message_entries(
                self._pending_policy_messages,
                policy_root=self.policy_root,
            )
        if self._pending_policy_rules:
            report = policy_context.ingest_rule_entries(
                self._pending_policy_rules,
                policy_root=self.policy_root,
            )
        if report:
            self._refresh_policy_consumers()
            changed = report.get("changed_fields", [])
            if changed:
                logger.info(f"[policy] promoted {len(changed)} canonical rule updates.")

    @staticmethod
    def _refresh_policy_consumers() -> None:
        try:
            import prompts

            prompts.refresh_policy_assets()
        except Exception:
            pass
        try:
            import validator

            validator.refresh_policy_constraints()
        except Exception:
            pass
        try:
            import atlas_claude_smart_ai2 as claude_video

            claude_video.refresh_policy_constraints()
        except Exception:
            pass

    def _trigger_sync(self, config_path: str) -> None:
        """Trigger Git + Vertex sync after ingestion."""
        try:
            from src.sync.sync_utils import trigger_full_sync
            import asyncio
            prompt_id = "7380211766946430976"
            project = os.getenv("GOOGLE_CLOUD_PROJECT", "project-1e9e05a3-c200-4e5d-87f")
            logger.info("[ingest] Triggering sync after ingestion...")
            asyncio.run(trigger_full_sync(config_path, prompt_id, project))
            gemini_app_link = "https://gemini.google.com/app/b3006ba9f325b55c"
            logger.info(f"✨ Sync complete. MANUAL ACTION: Update your Gemini App: {gemini_app_link}")
        except Exception as e:
            logger.error(f"[ingest] Sync failed: {e}")


# --- Legacy compatibility wrapper ---
def ingest_json(json_path, context_pack=None, do_sync=False, config_path="sample_web_auto_solver_production.yaml"):
    """Legacy wrapper for backward compatibility with old callers."""
    cp = Path(context_pack) if context_pack else CONTEXT_PACK_PATH
    ingestor = KnowledgeIngestor(context_pack_path=cp)
    return ingestor.ingest(Path(json_path), do_sync=do_sync, config_path=config_path)


def main():
    parser = argparse.ArgumentParser(
        description="Atlas Knowledge Ingestor — supports DiscordChatExporter, Discrub, and pre-purified Rules JSON"
    )
    parser.add_argument("--file", required=True, help="Path to the JSON file (any supported format)")
    parser.add_argument("--context-pack", default=str(CONTEXT_PACK_PATH), help="Path to the context pack file")
    parser.add_argument("--sync", action="store_true", help="Trigger project-wide sync after ingestion")
    parser.add_argument("--config", default="sample_web_auto_solver_production.yaml", help="Path to config for sync")

    args = parser.parse_args()

    ingestor = KnowledgeIngestor(context_pack_path=Path(args.context_pack))
    count = ingestor.ingest(Path(args.file), do_sync=args.sync, config_path=args.config)
    logger.info(f"📊 Total new entries: {count}")


if __name__ == "__main__":
    main()
