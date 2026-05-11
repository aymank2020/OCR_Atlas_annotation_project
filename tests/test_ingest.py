"""Tests for atlas_knowledge_ingest.py — covers all 3 JSON formats."""
import json
import pytest
from pathlib import Path
from atlas_knowledge_ingest import KnowledgeIngestor
from src.policy import context_manager as policy_context

# ── Fixtures ────────────────────────────────────────────────────

@pytest.fixture
def mock_context_pack(tmp_path):
    p = tmp_path / "test_context_pack.txt"
    p.write_text("# Initial Knowledge\n[Dana] [ID: 100] Already here\n[SRC: 999] Existing rule\n", encoding="utf-8")
    return p


@pytest.fixture
def mock_policy_root(tmp_path):
    p = tmp_path / "policy"
    policy_context.ensure_policy_files(p)
    return p

@pytest.fixture
def sample_messages_json(tmp_path):
    p = tmp_path / "export.json"
    data = {"messages": [
        {"id": "100", "content": "Already here", "author": {"name": "Dana"}, "timestamp": "2024-01-01"},
        {"id": "200", "content": "New rule!", "author": {"name": "Ayman"}, "timestamp": "2024-01-02"},
        {"id": "200", "content": "Duplicate rule!", "author": {"name": "Ayman"}, "timestamp": "2024-01-02"},
        {"id": "300", "content": "  ", "author": {"name": "Empty"}, "timestamp": "2024-01-03"}
    ]}
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return p

@pytest.fixture
def sample_rules_json(tmp_path):
    p = tmp_path / "rules.json"
    data = {"rules": [
        {"source_message_id": "999", "rule": "Existing rule", "category": "Labeling", "extracted_at": "2026-03-25"},
        {"source_message_id": "1001", "rule": "استخدم loosen بدلاً من remove عند فك المسامير", "category": "Labeling", "extracted_at": "2026-03-25"},
        {"source_message_id": "1002", "rule": "استخدم dispense بدلاً من inject عند التفريغ", "category": "Labeling", "extracted_at": "2026-03-25"},
        {"source_message_id": "1003", "rule": "الشخص بيتكلم عن فلوس ونصب", "category": "Scam", "extracted_at": "2026-03-25"},
        {"source_message_id": "1004", "rule": "", "category": "Labeling", "extracted_at": "2026-03-25"},
    ]}
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return p

@pytest.fixture
def sample_discrub_json(tmp_path):
    p = tmp_path / "discrub.json"
    data = [
        {"id": "500", "content": "Discrub message", "author": {"username": "User1"}},
        {"id": "501", "content": "Another message", "author": {"name": "User2"}},
    ]
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return p


# ── Tests: DiscordChatExporter format ───────────────────────────

def test_messages_ingestion_deduplication(mock_context_pack, sample_messages_json, mock_policy_root):
    """Messages format: dedup by ID, skip empty, no re-add existing."""
    ingestor = KnowledgeIngestor(context_pack_path=mock_context_pack, policy_root=mock_policy_root)
    assert "100" in ingestor.existing_ids

    count = ingestor.ingest(sample_messages_json)

    content = mock_context_pack.read_text(encoding="utf-8")
    assert count == 1  # only ID 200 is new
    assert "[ID: 200] New rule!" in content
    assert content.count("[ID: 200]") == 1
    assert content.count("[ID: 100]") == 1  # not re-added
    assert "[ID: 300]" not in content  # empty content skipped


# ── Tests: Pre-purified Rules format ────────────────────────────

def test_rules_ingestion_dedup_and_filter(mock_context_pack, sample_rules_json, mock_policy_root):
    """Rules format: dedup by source_message_id, filter non-annotation categories."""
    ingestor = KnowledgeIngestor(context_pack_path=mock_context_pack, policy_root=mock_policy_root)
    assert "999" in ingestor.existing_ids  # already in context pack

    count = ingestor.ingest(sample_rules_json)

    content = mock_context_pack.read_text(encoding="utf-8")
    assert count == 2  # 1001 and 1002 are new valid rules
    assert "[SRC: 1001]" in content
    assert "[SRC: 1002]" in content
    assert "loosen" in content
    assert "dispense" in content
    # Filtered: category=Scam is not in ALLOWED_RULE_CATEGORIES
    assert "[SRC: 1003]" not in content
    # Filtered: empty rule text
    assert "[SRC: 1004]" not in content
    # Not re-added
    assert content.count("[SRC: 999]") == 1


def test_rules_golden_rule_format(mock_context_pack, sample_rules_json, mock_policy_root):
    """Rules are formatted as '# === Golden Rule (...) [Category] ==='."""
    ingestor = KnowledgeIngestor(context_pack_path=mock_context_pack, policy_root=mock_policy_root)
    ingestor.ingest(sample_rules_json)
    content = mock_context_pack.read_text(encoding="utf-8")
    assert "# === Golden Rule" in content
    assert "[Labeling]" in content


# ── Tests: Discrub format ───────────────────────────────────────

def test_discrub_ingestion(mock_context_pack, sample_discrub_json, mock_policy_root):
    """Discrub (list) format: auto-detected and ingested."""
    ingestor = KnowledgeIngestor(context_pack_path=mock_context_pack, policy_root=mock_policy_root)
    count = ingestor.ingest(sample_discrub_json)
    content = mock_context_pack.read_text(encoding="utf-8")
    assert count == 2
    assert "[ID: 500]" in content
    assert "[ID: 501]" in content


# ── Tests: Format detection ─────────────────────────────────────

def test_format_detection():
    ingestor = KnowledgeIngestor.__new__(KnowledgeIngestor)
    assert ingestor._detect_format({"messages": []}) == "messages"
    assert ingestor._detect_format({"rules": []}) == "rules"
    assert ingestor._detect_format([{"id": "1"}]) == "discrub"
    assert ingestor._detect_format({"unknown_key": 1}) == "unknown"


# ── Tests: ID extraction regex ──────────────────────────────────

def test_load_ids_regex_both_formats(tmp_path):
    """ID extraction finds both [ID: x] and [SRC: x] formats."""
    p = tmp_path / "ids.txt"
    p.write_text("[Author] [ID: 555] some rule\n[SRC: 888] golden rule\n[ID: 666]\nNo ID here\n[Other] [ID: 777] more", encoding="utf-8")
    ingestor = KnowledgeIngestor(context_pack_path=p)
    assert "555" in ingestor.existing_ids
    assert "666" in ingestor.existing_ids
    assert "777" in ingestor.existing_ids
    assert "888" in ingestor.existing_ids
    assert len(ingestor.existing_ids) == 4


# ── Tests: Edge cases ───────────────────────────────────────────

def test_missing_file(tmp_path):
    """Non-existent file returns 0."""
    cp = tmp_path / "cp.txt"
    cp.write_text("", encoding="utf-8")
    ingestor = KnowledgeIngestor(context_pack_path=cp, policy_root=tmp_path / "policy")
    count = ingestor.ingest(tmp_path / "nonexistent.json")
    assert count == 0


def test_trusted_discord_update_promotes_max_segment_policy(mock_context_pack, mock_policy_root, tmp_path):
    export_path = tmp_path / "trusted_update.json"
    export_path.write_text(
        json.dumps(
            {
                "messages": [
                    {
                        "id": "1487171215255670966",
                        "content": "The max segment duration is now: 10 seconds, with 2-5 seconds being the sweet spot",
                        "author": {"username": "sentientcake"},
                        "timestamp": "2026-03-27T19:27:28.022000+00:00",
                        "channel": "#LEVEL3_ANNOUNCEMENT",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    ingestor = KnowledgeIngestor(context_pack_path=mock_context_pack, policy_root=mock_policy_root)
    count = ingestor.ingest(export_path)

    policy = policy_context.load_current_policy(mock_policy_root / "current_policy.json")
    staged = (mock_policy_root / "staged_rules.jsonl").read_text(encoding="utf-8")
    assert count == 1
    assert policy_context.get_policy(
        "engine_limits.max_segment_seconds",
        policy=policy,
    ) == 10.0
    assert '"status": "promoted"' in staged
