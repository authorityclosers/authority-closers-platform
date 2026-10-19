"""Coaching as stable points: the one mapping from a saved report's overview."""

from ac_platform.conversation_intelligence.coaching_points import coaching_points

REPORT = {
    "improvements": [{"title": "Name the next step"}, {"title": "Price earlier"}],
    "overview": {
        "next_call_focus": {
            "improvement_index": 0,
            "behavior": "Ask for the date",
            "target": "Every call",
        },
        "diagnosis": {"text": "The rep waits for the buyer to lead."},
        "improvement_details": [
            {"finding_index": 1, "replacement_behavior": "Say the price in minute five."},
            {"finding_index": 0, "replacement_behavior": "  "},
            {"finding_index": 9, "replacement_behavior": "Propose Tuesday at 10."},
        ],
        "practice": {
            "instructions": "Role-play the close",
            "success_condition": "Three dates asked",
        },
    },
}


def test_points_have_stable_keys_titles_and_text() -> None:
    assert coaching_points(REPORT) == [
        {
            "key": "focus",
            "kind": "focus",
            "title": "What to work on now",
            "text": "Ask for the date · Target: Every call",
        },
        {
            "key": "diagnosis",
            "kind": "diagnosis",
            "title": "Why this keeps happening",
            "text": "The rep waits for the buyer to lead.",
        },
        {
            "key": "better:0",
            "kind": "better",
            "title": "Price earlier",
            "text": "Say the price in minute five.",
        },
        # An empty detail is skipped but keeps the index of the ones after it.
        {
            "key": "better:2",
            "kind": "better",
            "title": "What better looks like",
            "text": "Propose Tuesday at 10.",
        },
        {
            "key": "practice",
            "kind": "practice",
            "title": "Practice",
            "text": "Role-play the close · Done when: Three dates asked",
        },
    ]


def test_reports_without_coaching_have_no_points() -> None:
    assert coaching_points(None) == []
    assert coaching_points({"improvements": []}) == []
    assert coaching_points({"overview": {"next_call_focus": None, "diagnosis": None}}) == []
