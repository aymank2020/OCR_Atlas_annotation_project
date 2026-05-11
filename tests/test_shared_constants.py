from atlas.shared import constants
from src.policy import context_manager as policy_context

def test_no_action_label_is_string():
    assert isinstance(constants.NO_ACTION_LABEL, str)
    assert constants.NO_ACTION_LABEL == "No Action"

def test_max_segment_seconds_positive():
    assert constants.MAX_SEGMENT_SECONDS > 0
    assert constants.MAX_SEGMENT_SECONDS == int(
        policy_context.get_policy("engine_limits.max_segment_seconds", 10)
    )

def test_forbidden_verbs_non_empty():
    assert isinstance(constants.FORBIDDEN_VERBS, list)
    assert len(constants.FORBIDDEN_VERBS) > 0
    assert "inspect" in constants.FORBIDDEN_VERBS

def test_disallowed_tool_terms_non_empty():
    assert isinstance(constants.DISALLOWED_TOOL_TERMS, tuple)
    assert len(constants.DISALLOWED_TOOL_TERMS) > 0
    assert "mechanical arm" in constants.DISALLOWED_TOOL_TERMS
