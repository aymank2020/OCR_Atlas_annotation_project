from __future__ import annotations

import subprocess
from pathlib import Path


def _tracked_files(*patterns: str) -> list[Path]:
    files = subprocess.check_output(["git", "ls-files", *patterns], text=True).splitlines()
    return [Path(item) for item in files if item]


def test_shell_and_systemd_assets_use_lf_line_endings():
    tracked = _tracked_files("*.sh", "*.service")
    assert tracked, "Expected tracked deployment assets."

    bad = [str(path) for path in tracked if b"\r\n" in path.read_bytes()]
    assert not bad, f"Expected LF-only deployment assets, found CRLF in: {bad}"


def test_service_shell_scripts_strip_bom_when_loading_dotenv():
    tracked = _tracked_files("*.sh")
    target_names = {
        "run_solver_hetzner.sh",
        "run_feedback_collector_once.sh",
        "run_discord_bot_service.sh",
        "run_episode_review_refresh.sh",
    }
    targets = [path for path in tracked if path.name in target_names]
    assert len(targets) == len(target_names), "Expected tracked service shell scripts."

    missing = [str(path) for path in targets if 'encoding="utf-8-sig"' not in path.read_text(encoding="utf-8")]
    assert not missing, f"Expected BOM-safe dotenv loading in: {missing}"
