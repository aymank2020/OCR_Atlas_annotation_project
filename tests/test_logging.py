"""Tests for atlas/shared/logging.py — Structured logging module."""
import json
import logging
import pytest
from atlas.shared.logging import (
    get_logger, JSONFormatter, HumanFormatter, generate_transaction_id, log_spec
)


def test_json_formatter_output():
    """JSONFormatter produces valid JSON with required fields."""
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="hello world", args=(), exc_info=None
    )
    output = formatter.format(record)
    parsed = json.loads(output)
    assert parsed["level"] == "INFO"
    assert parsed["message"] == "hello world"
    assert "timestamp" in parsed


def test_json_formatter_with_extra_fields():
    """JSONFormatter includes spec_ref and transaction_id when present."""
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="processing", args=(), exc_info=None
    )
    record.spec_ref = "FR-001"
    record.transaction_id = "abc123"
    output = formatter.format(record)
    parsed = json.loads(output)
    assert parsed["spec_ref"] == "FR-001"
    assert parsed["transaction_id"] == "abc123"


def test_human_formatter_output():
    """HumanFormatter produces readable output."""
    formatter = HumanFormatter()
    record = logging.LogRecord(
        name="test", level=logging.WARNING, pathname="", lineno=0,
        msg="warning msg", args=(), exc_info=None
    )
    output = formatter.format(record)
    assert "WARNING" in output
    assert "warning msg" in output


def test_generate_transaction_id():
    """Transaction IDs are unique 12-char hex strings."""
    id1 = generate_transaction_id()
    id2 = generate_transaction_id()
    assert len(id1) == 12
    assert id1 != id2


def test_get_logger_creates_handler():
    """get_logger creates a logger with a handler."""
    logger = get_logger("test_unique_logger_name")
    assert len(logger.handlers) >= 1
    assert logger.level == logging.INFO


def test_log_spec_decorator():
    """@log_spec decorator runs the function and tags logs."""
    results = []

    @log_spec("FR-005")
    def my_func(x):
        results.append(x)
        return x * 2

    assert my_func(5) == 10
    assert results == [5]


def test_log_spec_decorator_on_exception():
    """@log_spec re-raises exceptions."""
    @log_spec("FR-006")
    def failing_func():
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        failing_func()
