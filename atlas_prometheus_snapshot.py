"""Compatibility shim for Prometheus health snapshot export."""

from __future__ import annotations

from src.tools.prometheus_snapshot import main, render_prometheus_metrics, write_prometheus_metrics

__all__ = ["render_prometheus_metrics", "write_prometheus_metrics", "main"]


if __name__ == "__main__":
    main()
