"""Compatibility shim for the extracted episode history report tool."""

from __future__ import annotations

from src.tools.episode_history_report import (
    _extract_episode_id,
    _guess_account_from_path,
    _summarize_outputs_tree,
    build_episode_history_report,
    fetch_remote_summary,
    main,
)

__all__ = [
    "_extract_episode_id",
    "_guess_account_from_path",
    "_summarize_outputs_tree",
    "fetch_remote_summary",
    "build_episode_history_report",
    "main",
]


if __name__ == "__main__":
    main()
