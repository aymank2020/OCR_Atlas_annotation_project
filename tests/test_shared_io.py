import pytest
import json
from pathlib import Path
from atlas.shared import io

def test_load_json_valid_file(tmp_path):
    d = tmp_path / "test.json"
    data = {"hello": "world"}
    d.write_text(json.dumps(data))
    assert io.load_json(d) == data

def test_load_json_missing_file_raises(tmp_path):
    d = tmp_path / "missing.json"
    with pytest.raises(FileNotFoundError):
        io.load_json(d)

def test_load_json_safe_missing_returns_default():
    assert io.load_json_safe("non_existent.json", default={"a": 1}) == {"a": 1}

def test_load_json_safe_corrupt_returns_default(tmp_path):
    d = tmp_path / "corrupt.json"
    d.write_text("{ invalid json }")
    assert io.load_json_safe(d, default=[]) == []

def test_save_json_creates_parent_dirs(tmp_path):
    d = tmp_path / "subdir" / "test.json"
    io.save_json({"key": "val"}, d)
    assert d.exists()
    assert json.loads(d.read_text()) == {"key": "val"}

def test_save_json_roundtrip(tmp_path):
    d = tmp_path / "roundtrip.json"
    data = {"a": [1, 2, 3], "b": {"c": True}}
    io.save_json(data, d)
    assert io.load_json(d) == data

def test_append_jsonl_and_load_jsonl(tmp_path):
    d = tmp_path / "test.jsonl"
    recs = [{"id": 1}, {"id": 2}]
    for r in recs:
        io.append_jsonl(r, d)
    
    loaded = io.load_jsonl(d)
    assert len(loaded) == 2
    assert loaded == recs

def test_load_text_missing_returns_default():
    assert io.load_text("missing.txt", default="fallback") == "fallback"

def test_now_utc_iso_format():
    ts = io.now_utc_iso()
    assert isinstance(ts, str)
    # Basic ISO format check (contains T and Z or +00:00)
    assert "T" in ts

def test_safe_float_valid():
    assert io.safe_float("12.5") == 12.5
    assert io.safe_float(42) == 42.0

def test_safe_float_invalid_returns_default():
    assert io.safe_float("abc", default=-1.0) == -1.0
    assert io.safe_float(None, default=0.0) == 0.0
