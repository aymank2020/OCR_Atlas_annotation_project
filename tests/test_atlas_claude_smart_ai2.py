import unittest

import atlas_claude_smart_ai2 as mod
from src.policy import context_manager as policy_context


class TestAtlasClaudeSmartAI2(unittest.TestCase):
    def test_autofix_enforces_gripper_policy_and_word_limit(self):
        label = (
            "use mechanical arm to pick up 3 paper clips and place paper clips "
            "in tray while checking alignment and continuing movement carefully"
        )
        fixed, issues = mod.autofix_label(label)

        self.assertNotIn("mechanical arm", fixed)
        self.assertNotRegex(fixed, r"\b\d+\b")
        self.assertIn("three", fixed)
        self.assertLessEqual(len(fixed.split()), mod.MAX_LABEL_WORDS)
        self.assertGreaterEqual(len(issues), 1)

    def test_normalize_segments_splits_long_segments_and_fills_gap(self):
        raw = [
            {
                "start": 0,
                "end": 130,
                "label": "pick up box, place box on table",
                "type": "coarse",
                "confidence": "high",
            },
            {
                "start": 140,
                "end": 150,
                "label": "move item to shelf",
                "type": "coarse",
                "confidence": "high",
            },
        ]
        out = mod.normalize_segments(raw, duration=160)

        self.assertTrue(out, "Expected normalized segments")
        self.assertTrue(any(s["label"] == "No Action" for s in out), "Expected No Action gap segment")
        self.assertTrue(all((s["end"] - s["start"]) <= mod.MAX_SEGMENT_SECONDS + 1e-6 for s in out))

    def test_normalize_segments_outputs_monotonic_non_overlapping_timeline(self):
        raw = [
            {"start": 8.0, "end": 12.0, "label": "pick up item"},
            {"start": 2.0, "end": 6.0, "label": "grab item"},
            {"start": 5.0, "end": 9.5, "label": "place item on table"},
        ]
        out = mod.normalize_segments(raw, duration=15.0)

        self.assertTrue(out)
        for i in range(1, len(out)):
            prev = out[i - 1]
            cur = out[i]
            self.assertGreaterEqual(cur["start"], prev["end"] - 1e-6)

    def test_postprocess_includes_policy_metadata(self):
        raw = {
            "episode_description": "demo",
            "segments": [{"start": 0.0, "end": 2.0, "label": "pick up item"}],
        }
        out = mod.postprocess_result(raw, duration=3.0)

        self.assertEqual(
            out["policy_version"],
            policy_context.load_current_policy()["policy_version"],
        )
        self.assertIn("quality_report", out)

    def test_autofix_label_rewrites_reach_by_default(self):
        """autofix_label should always rewrite 'reach' to 'pick up'."""
        fixed, _issues = mod.autofix_label("reach for connector")
        self.assertNotIn("reach", fixed)
        self.assertIn("pick up", fixed)

    def test_normalize_segments_rewrites_reach_in_segments(self):
        """normalize_segments should rewrite 'reach' labels since autofix always replaces reach."""
        raw = [{"start": 9.8, "end": 10.0, "label": "reach for connector", "type": "coarse"}]
        out = mod.normalize_segments(raw, duration=10.0)
        self.assertTrue(out)
        # autofix_label always converts "reach" -> "pick up", so the last segment should have "pick up"
        self.assertIn("pick up", out[-1]["label"])


if __name__ == "__main__":
    unittest.main()
