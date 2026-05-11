from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv

from src.sync.sync_utils import trigger_full_sync

try:
    import discord  # type: ignore
    _DISCORD_READY = hasattr(discord, "Client") and hasattr(discord, "Intents")
except Exception:
    discord = None  # type: ignore
    _DISCORD_READY = False


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

DEFAULT_OUT_DIR = Path("data/discord_autofetch")
DEFAULT_OUT_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_OUTPUTS_DIR = Path("outputs")
DEFAULT_OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _short_text(value: Any, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


def build_discord_runtime_snapshot(
    *,
    outputs_dir: Path,
    command_channel_id: int,
    target_channel_ids: List[int],
    ready_at: str = "",
    last_event: str = "",
    last_command: str = "",
    last_sync_at: str = "",
    last_history_export_at: str = "",
    last_error: str = "",
    buffer_count: int = 0,
) -> Dict[str, Any]:
    rule_sync_report = _load_json(outputs_dir / "discord_rule_sync_report.json", {}) or {}
    feedback_summary = _load_json(outputs_dir / "training_feedback" / "live" / "last_run_summary.json", {}) or {}
    review_index = _load_json(outputs_dir / "episodes_review_index.json", {}) or {}
    feedback_index_path = Path(str(feedback_summary.get("training_dir", "")).strip()) / "INDEX.json"
    feedback_index = _load_json(feedback_index_path, {}) if str(feedback_summary.get("training_dir", "")).strip() else {}
    return {
        "generated_at": _iso_now(),
        "command_channel_id": int(command_channel_id or 0),
        "target_channel_ids": [int(item) for item in target_channel_ids if int(item or 0)],
        "ready_at": str(ready_at or ""),
        "last_event": str(last_event or ""),
        "last_command": _short_text(last_command),
        "last_sync_at": str(last_sync_at or ""),
        "last_history_export_at": str(last_history_export_at or ""),
        "last_error": _short_text(last_error),
        "buffer_count": int(buffer_count or 0),
        "rule_sync": {
            "generated_at": str(rule_sync_report.get("generated_at_utc", "")),
            "message_count": int(rule_sync_report.get("message_count", 0) or 0),
            "channel_count": int(rule_sync_report.get("channel_count", 0) or 0),
            "candidate_count": int((rule_sync_report.get("policy_report", {}) or {}).get("candidate_count", 0) or 0),
            "promoted_count": len((rule_sync_report.get("policy_report", {}) or {}).get("promoted_rule_ids", []) or []),
        },
        "feedback": {
            "status": str(feedback_summary.get("status", feedback_index.get("gemini_status", "unknown"))),
            "generated_at": str(feedback_summary.get("generated_at", feedback_index.get("generated_at", ""))),
            "episodes_collected": int(feedback_index.get("episodes_collected", 0) or 0),
            "feedback_entries_found": int(feedback_index.get("feedback_entries_found", 0) or 0),
            "training_dir": str(feedback_summary.get("training_dir", "")),
            "error": _short_text(feedback_summary.get("error", "")),
        },
        "review_index": {
            "generated_at": str(review_index.get("generated_at", "")),
            "total": int(review_index.get("total", 0) or 0),
            "status_counts": dict(review_index.get("status_counts", {})) if isinstance(review_index, dict) else {},
        },
    }


def format_discord_status_message(snapshot: Dict[str, Any]) -> str:
    rule_sync = snapshot.get("rule_sync", {}) if isinstance(snapshot.get("rule_sync"), dict) else {}
    feedback = snapshot.get("feedback", {}) if isinstance(snapshot.get("feedback"), dict) else {}
    review_index = snapshot.get("review_index", {}) if isinstance(snapshot.get("review_index"), dict) else {}
    status_counts = review_index.get("status_counts", {}) if isinstance(review_index.get("status_counts"), dict) else {}
    status_bits = ", ".join(f"{key}={value}" for key, value in sorted(status_counts.items())) or "none"
    lines = [
        "Atlas Discord status",
        f"- generated_at: {snapshot.get('generated_at', '') or 'unknown'}",
        f"- last_event: {snapshot.get('last_event', '') or 'unknown'}",
        f"- command_channel_id: {snapshot.get('command_channel_id', 0)}",
        f"- target_channel_ids: {', '.join(str(item) for item in snapshot.get('target_channel_ids', [])) or 'none'}",
        f"- ready_at: {snapshot.get('ready_at', '') or 'unknown'}",
        f"- last_history_export_at: {snapshot.get('last_history_export_at', '') or 'unknown'}",
        f"- last_sync_at: {snapshot.get('last_sync_at', '') or 'unknown'}",
        f"- buffer_count: {snapshot.get('buffer_count', 0)}",
        f"- last_command: {snapshot.get('last_command', '') or 'none'}",
        f"- rule_sync: messages={rule_sync.get('message_count', 0)} channels={rule_sync.get('channel_count', 0)} promoted={rule_sync.get('promoted_count', 0)} generated_at={rule_sync.get('generated_at', '') or 'unknown'}",
        f"- feedback: status={feedback.get('status', 'unknown')} episodes={feedback.get('episodes_collected', 0)} entries={feedback.get('feedback_entries_found', 0)} generated_at={feedback.get('generated_at', '') or 'unknown'}",
        f"- review_index: total={review_index.get('total', 0)} statuses={status_bits}",
    ]
    if snapshot.get("last_error"):
        lines.append(f"- last_error: {snapshot['last_error']}")
    return "\n".join(lines)


class AtlasKnowledgeBot(discord.Client if _DISCORD_READY else object):
    def __init__(
        self,
        target_channel_ids: List[int],
        target_guild_id: int | None = None,
        gcs_bucket: str | None = None,
        gcs_prefix: str = "discord_knowledge",
        config_path: str = "sample_web_auto_solver_production.yaml",
        command_channel_id: int | None = None,
    ):
        if not _DISCORD_READY:
            raise RuntimeError("discord.py is not available in this environment.")
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(intents=intents)

        self.target_channel_ids = target_channel_ids
        self.target_guild_id = target_guild_id
        self.gcs_bucket = gcs_bucket
        self.gcs_prefix = gcs_prefix
        self.config_path = config_path
        self.vertex_prompt_id = "7380211766946430976"
        self.vertex_project = "project-1e9e05a3-c200-4e5d-87f"
        self.command_channel_id = command_channel_id or int(os.getenv("COMMAND_CHANNEL_ID", "0"))

        self.knowledge_buffer: List[Dict[str, Any]] = []
        self.flush_interval_sec = 3600
        self.buffer_threshold = 10
        self.last_flush_time = time.time()

        self.outputs_dir = DEFAULT_OUTPUTS_DIR
        self.status_path = self.outputs_dir / "discord_bot_status.json"
        self.ready_at = ""
        self.last_command_text = ""
        self.last_history_export_at = ""
        self.last_sync_at = ""
        self.last_error = ""

    def _status_snapshot(self, last_event: str = "") -> Dict[str, Any]:
        return build_discord_runtime_snapshot(
            outputs_dir=self.outputs_dir,
            command_channel_id=self.command_channel_id,
            target_channel_ids=self.target_channel_ids,
            ready_at=self.ready_at,
            last_event=last_event,
            last_command=self.last_command_text,
            last_sync_at=self.last_sync_at,
            last_history_export_at=self.last_history_export_at,
            last_error=self.last_error,
            buffer_count=len(self.knowledge_buffer),
        )

    def _write_status(self, last_event: str) -> None:
        try:
            self.status_path.parent.mkdir(parents=True, exist_ok=True)
            self.status_path.write_text(
                json.dumps(self._status_snapshot(last_event=last_event), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning(f"Failed to write Discord status file: {exc}")

    async def on_ready(self):
        logger.info(f"Logged on as {self.user}!")
        logger.info(f"Command Channel ID: {self.command_channel_id}")
        logger.info(f"Bot Guilds: {[g.name for g in self.guilds]}")
        self.ready_at = _iso_now()
        self.last_error = ""
        self._write_status("ready")
        await self._start_background_tasks()

    async def _start_background_tasks(self):
        asyncio.create_task(self._background_flush())
        asyncio.create_task(self._periodic_history_export())

    async def on_message(self, message: discord.Message):
        if message.author == self.user:
            return
        if message.channel.id == self.command_channel_id:
            self.last_command_text = message.content.strip()
            await self._handle_command(message)
            return
        if message.channel.id in self.target_channel_ids:
            await self._buffer_message(message)

    async def _handle_command(self, message: discord.Message):
        content = message.content.strip()
        lowered = content.lower()

        if lowered in {"status", "status!"}:
            self.last_error = ""
            self._write_status("status_requested")
            await message.channel.send(f"```text\n{format_discord_status_message(self._status_snapshot(last_event='status_requested'))}\n```")
            return

        if lowered.startswith("rule:") or lowered.startswith("correction:"):
            logger.info(f"[command] Received manual knowledge from {message.author}: {content}")
            success = self._append_to_context_pack(content, message.author.name, "CommandCenter")
            if success:
                await message.add_reaction("✅")
                await trigger_full_sync(self.config_path, self.vertex_prompt_id, self.vertex_project)
                self.last_sync_at = _iso_now()
                self.last_error = ""
                self._write_status("manual_rule_sync_ok")
                gemini_app_link = "https://gemini.google.com/app/b3006ba9f325b55c"
                await message.channel.send(
                    "Knowledge synced and pushed to repository/Vertex AI.\n"
                    f"Reminder: update Gemini App manually if needed: {gemini_app_link}"
                )
            else:
                self.last_error = "Failed to append manual rule to context pack."
                self._write_status("manual_rule_sync_error")
                await message.add_reaction("❌")
            return

        if lowered == "sync!":
            logger.info(f"[command] Manual sync triggered by {message.author}")
            await message.add_reaction("🔄")
            await trigger_full_sync(self.config_path, self.vertex_prompt_id, self.vertex_project)
            self.last_sync_at = _iso_now()
            self.last_error = ""
            self._write_status("manual_sync_ok")
            gemini_app_link = "https://gemini.google.com/app/b3006ba9f325b55c"
            await message.channel.send(
                "Project-wide synchronization complete.\n"
                f"Reminder: update Gemini App manually: {gemini_app_link}"
            )

    def _append_to_context_pack(self, content: str, author: str, source: str):
        context_pack_path = Path("prompts/atlas_vertex_context_pack.txt")
        try:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            entry = f"\n\n# === Manual Entry ({ts}) ===\n[{author} in {source}] {content}\n"
            with open(context_pack_path, "a", encoding="utf-8") as f:
                f.write(entry)
            logger.info(f"Appended manual entry to {context_pack_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to append to context pack: {e}")
            return False

    async def _buffer_message(self, message: discord.Message):
        data = {
            "id": message.id,
            "content": message.content,
            "author": {"id": message.author.id, "name": message.author.name},
            "channel": {"id": message.channel.id, "name": message.channel.name},
            "timestamp": message.created_at.isoformat(),
        }
        self.knowledge_buffer.append(data)
        self._write_status("buffered_message")
        if len(self.knowledge_buffer) >= self.buffer_threshold:
            await self._flush_buffer()

    async def _periodic_history_export(self):
        history_path = Path("data/discord_history_export.txt")
        history_path.parent.mkdir(parents=True, exist_ok=True)

        while True:
            try:
                channel_id = self.command_channel_id or (self.target_channel_ids[0] if self.target_channel_ids else None)
                if not channel_id:
                    await asyncio.sleep(300)
                    continue

                channel = self.get_channel(channel_id)
                if not channel:
                    try:
                        channel = await self.fetch_channel(channel_id)
                    except Exception:
                        channel = None

                if channel and isinstance(channel, discord.TextChannel):
                    logger.info(f"[export] Dumping history for #{channel.name}...")
                    lines = [f"=== Atlas Discord Export: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ==="]
                    lines.append("Master Gemini App: https://gemini.google.com/app/b3006ba9f325b55c\n")

                    async for msg in channel.history(limit=100):
                        ts = msg.created_at.strftime("%Y-%m-%d %H:%M")
                        lines.append(f"[{ts}] {msg.author.name}: {msg.content}")

                    with open(history_path, "w", encoding="utf-8") as f:
                        f.write("\n".join(lines))
                    self.last_history_export_at = _iso_now()
                    self.last_error = ""
                    self._write_status("history_export_ok")
                else:
                    logger.warning(f"[export] Channel {channel_id} inaccessible.")
            except Exception as e:
                logger.error(f"[export] Error: {e}")
                self.last_error = _short_text(str(e))
                self._write_status("history_export_error")

            await asyncio.sleep(300)

    async def _background_flush(self):
        while True:
            await asyncio.sleep(60)
            if self.knowledge_buffer and (time.time() - self.last_flush_time) > self.flush_interval_sec:
                await self._flush_buffer()

    async def _flush_buffer(self):
        if not self.knowledge_buffer:
            return
        self.knowledge_buffer.clear()
        self.last_flush_time = time.time()
        self._write_status("buffer_flushed")


def main():
    parser = argparse.ArgumentParser(description="Atlas Knowledge Discord Bot (Private Commander Mode)")
    parser.add_argument("--token", help="Discord Bot Token")
    parser.add_argument("--channel", type=int, help="Target channel ID for passive listening")
    parser.add_argument("--command-channel", type=int, help="Dedicated Command Channel ID")
    parser.add_argument("--guild", type=int, help="Target Guild ID")
    parser.add_argument("--config", default="sample_web_auto_solver_production.yaml", help="Path to production config")

    args = parser.parse_args()
    token = args.token or os.getenv("DISCORD_BOT_TOKEN")
    guild_id = args.guild or int(os.getenv("DISCORD_GUILD_ID", os.getenv("DISCORD_SERVER_ID", "0")))
    if not token:
        logger.error("No token provided.")
        return

    target_channels = [args.channel] if args.channel else []

    bot = AtlasKnowledgeBot(
        target_channel_ids=target_channels,
        target_guild_id=guild_id,
        config_path=args.config,
        command_channel_id=args.command_channel,
    )
    bot.run(token)


if __name__ == "__main__":
    main()
