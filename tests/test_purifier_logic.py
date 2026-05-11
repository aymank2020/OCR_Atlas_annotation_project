import os
from types import SimpleNamespace

import pytest

from src.purify import knowledge_builder
from src.purify.knowledge_builder import load_processed_files, save_processed_files


def test_load_save_processed_files(tmp_path):
    state_file = tmp_path / "processed.json"
    processed = {"file1.json", "file2.json"}

    save_processed_files(state_file, processed)
    assert state_file.exists()

    loaded = load_processed_files(state_file)
    assert loaded == processed


def test_json_format_detection():
    discrub_data = [{"id": "1", "content": "hello"}]
    exporter_data = {"messages": [{"id": "2", "content": "world"}]}

    def get_messages(data):
        if isinstance(data, list):
            return data
        return data.get("messages", [])

    assert len(get_messages(discrub_data)) == 1
    assert get_messages(discrub_data)[0]["content"] == "hello"
    assert len(get_messages(exporter_data)) == 1
    assert get_messages(exporter_data)[0]["content"] == "world"


def test_author_parsing():
    message = {"author": {"username": "atlas_bot", "name": "Atlas"}, "content": "test"}

    def get_author_name(entry):
        author = entry.get("author", {})
        return author.get("username") or author.get("name") or "User"

    assert get_author_name(message) == "atlas_bot"


def test_purify_messages_from_text_raises_clear_error_when_genai_missing(monkeypatch):
    monkeypatch.setattr(knowledge_builder, "genai", None)
    monkeypatch.setattr(knowledge_builder, "types", None)

    with pytest.raises(RuntimeError, match="google-genai module not found"):
        knowledge_builder.purify_messages_from_text("hello", "gemini-1.5-flash", "prompt")


def test_purify_messages_from_text_uses_google_genai_client(monkeypatch):
    captured = {}

    class DummyResponse:
        text = "RULE 1"

    class DummyModels:
        def generate_content(self, **kwargs):
            captured.update(kwargs)
            return DummyResponse()

    class DummyClient:
        def __init__(self, api_key):
            captured["api_key"] = api_key
            self.models = DummyModels()

    class DummyConfig:
        def __init__(self, **kwargs):
            self.system_instruction = kwargs.get("system_instruction")
            self.temperature = kwargs.get("temperature")

    monkeypatch.setattr(knowledge_builder, "genai", SimpleNamespace(Client=DummyClient))
    monkeypatch.setattr(knowledge_builder, "types", SimpleNamespace(GenerateContentConfig=DummyConfig))
    monkeypatch.setenv("GEMINI_API_KEY", "primary-key")
    monkeypatch.delenv("GEMINI_API_KEY_FALLBACK", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY_SECONDARY", raising=False)

    result = knowledge_builder.purify_messages_from_text(
        "hello from discord",
        "gemini-2.5-flash",
        "prompt date [CURRENT_DATE]",
    )

    assert result == "RULE 1"
    assert captured["api_key"] == "primary-key"
    assert captured["model"] == "gemini-2.5-flash"
    assert "Extract Golden Rules from the following chat log" in captured["contents"]
    assert "[CURRENT_DATE]" not in captured["config"].system_instruction
    assert captured["config"].temperature == 0.1
