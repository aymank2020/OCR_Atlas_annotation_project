"""Compatibility shim for the extracted production monitor tool."""

from __future__ import annotations

from src.tools.production_monitor import (
    _detect_log_markers,
    _find_submit_lag_candidates,
    build_monitor_snapshot,
    maybe_send_alerts,
    render_alert_text,
    main,
)

__all__ = [
    "_detect_log_markers",
    "_find_submit_lag_candidates",
    "build_monitor_snapshot",
    "render_alert_text",
    "maybe_send_alerts",
    "main",
]

if __name__ == "__main__":
    main()
