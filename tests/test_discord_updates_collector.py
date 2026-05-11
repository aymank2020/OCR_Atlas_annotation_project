import tempfile
import unittest
from pathlib import Path

import discord_updates_collector as duc


class TestDiscordUpdatesCollector(unittest.TestCase):
    def test_parse_txt_infers_channel_from_filename(self) -> None:
        text = "[2026-03-06 10:00] Frans: New rule: split after two atomic actions."
        source = "C:/exports/level-3-announcements_20260306.txt"
        msgs = duc.parse_discord_txt_payload(text, source_file=source)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["channel_name"], "level-3-announcements")

    def test_message_relevance_uses_source_filename_fallback(self) -> None:
        cfg = duc.deep_merge(duc.DEFAULTS, {})
        msg = {
            "id": "m1",
            "timestamp": "2026-03-06T10:00:00Z",
            "author": "Frans",
            "channel_id": "",
            "channel_name": "",
            "content": "Guideline update: use at most two atomic actions.",
            "attachments": [],
            "source_file": "C:/exports/discord/level-3-announcements_updates.txt",
        }
        self.assertTrue(duc.message_is_relevant(msg, cfg))

    def test_parse_json_object_maybe_handles_fenced_json(self) -> None:
        text = """
```json
{"policy_updates":["Keep max two atomic actions per segment."]}
```
"""
        parsed = duc.parse_json_object_maybe(text)
        self.assertEqual(parsed.get("policy_updates"), ["Keep max two atomic actions per segment."])

    def test_upsert_managed_block_replaces_existing_content(self) -> None:
        base = (
            "header\n"
            "# BEGIN_DISCORD_LIVE_UPDATES\n"
            "old line\n"
            "# END_DISCORD_LIVE_UPDATES\n"
            "footer\n"
        )
        out = duc.upsert_managed_block(
            base,
            "# BEGIN_DISCORD_LIVE_UPDATES",
            "# END_DISCORD_LIVE_UPDATES",
            "new line",
        )
        self.assertIn("# BEGIN_DISCORD_LIVE_UPDATES\nnew line\n# END_DISCORD_LIVE_UPDATES\n", out)
        self.assertNotIn("old line", out)

    def test_apply_policy_sync_writes_override_and_main_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main_file = root / "data" / "gemini_policy_v1.txt"
            main_file.parent.mkdir(parents=True, exist_ok=True)
            main_file.write_text("base policy\n", encoding="utf-8")
            cfg = duc.deep_merge(
                duc.DEFAULTS,
                {
                    "discord_training": {
                        "policy_override_file": "data/gemini_policy_discord_live.txt",
                        "main_policy_file": "data/gemini_policy_v1.txt",
                        "sync_policy_into_main_file": True,
                    }
                },
            )
            result = duc.apply_policy_sync(
                cfg=cfg,
                root=root,
                policy_updates=["Never exceed two atomic actions per segment."],
                sources_count=4,
            )

            override = Path(result["override_file"])
            self.assertTrue(override.exists())
            self.assertIn("Never exceed two atomic actions per segment.", override.read_text(encoding="utf-8"))

            main_text = main_file.read_text(encoding="utf-8")
            self.assertIn("# BEGIN_DISCORD_LIVE_UPDATES", main_text)
            self.assertIn("# END_DISCORD_LIVE_UPDATES", main_text)


if __name__ == "__main__":
    unittest.main()
