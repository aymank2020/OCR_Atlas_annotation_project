"""Compatibility shim for the extracted health snapshot tool."""

from __future__ import annotations

from src.tools.health_snapshot import (
    _account_batch_summary,
    _file_snapshot,
    _health_summary,
    _read_yaml_object,
    _safe_int,
    _service_state,
    build_health_snapshot,
    main,
)


__all__ = [
    "_safe_int",
    "_read_yaml_object",
    "_account_batch_summary",
    "_file_snapshot",
    "_service_state",
    "_health_summary",
    "build_health_snapshot",
    "main",
]


if __name__ == "__main__":
    main()
