"""Company insight from the analysis: wordings by calls, skill scores weakest first."""

from uuid import uuid4

from ac_platform.conversation_intelligence.analysis_insights import _top, skill_scores


def test_wordings_rank_by_how_many_calls_said_them() -> None:
    one, two, three = uuid4(), uuid4(), uuid4()
    rows = [
        (one, "Price is too high."),
        (one, "price is too  high"),  # same call, same wording: counted once
        (two, "Price is too high"),
        (three, "Need to ask my partner"),
        (three, "  "),  # empty wordings are skipped
    ]
    assert _top(rows) == [
        {"text": "Price is too high.", "calls": 2},
        {"text": "Need to ask my partner", "calls": 1},
    ]


def test_skill_scores_average_each_skill_and_count_needs_work() -> None:
    payloads = [
        {
            "pointers": [
                {"label": "Agenda", "status": "needs_improvement", "score": 40},
                {"label": "Listening", "status": "good", "score": 80},
            ]
        },
        {
            "pointers": [
                {"label": "Agenda", "status": "good", "score": 70},
                {"label": "Listening", "status": "good", "score": 90},
                {"label": "Broken", "status": "good", "score": True},
                "not a pointer",
            ]
        },
        None,
    ]
    assert skill_scores(payloads) == [
        {"label": "Agenda", "calls": 2, "average": 55, "needs_work_share": 0.5},
        {"label": "Listening", "calls": 2, "average": 85, "needs_work_share": 0.0},
    ]
