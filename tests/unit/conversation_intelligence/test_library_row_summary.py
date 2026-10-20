"""A Calls list row's Report facts and their withholding (owner, 20 Oct 2026).

The list shows each call's outcome, assessment and counts without reading its
whole Report. The fields follow the Calls page's own order of preference, and
any call or transcript with a sensitive-segment mark passes the Report's own
withholding first.
"""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

from ac_platform.conversation_intelligence import acquisition_library as library
from ac_platform.conversation_intelligence.sensitive_segments import (
    WITHHELD_MARKER,
    grams,
    withheld_plan,
)

ASSESSMENT = "The rep asked about the budget early and the buyer agreed to a second call."


def _payload(revision="rev-1", **overrides):
    payload = {
        "transcript_revision": revision,
        "verdict": "Verdict text.",
        "strengths": [{"title": "Rapport"}, {"title": "Pace"}],
        "missed_opportunities": [{"title": "Timeline"}],
        "improvements": [{"title": "Ask for the decision maker"}],
        "overview": {
            "outcome": {"kind": "follow_up", "text": "They agreed to meet again."},
            "final_assessment": {
                "repeat": "Keep the open questions.",
                "fix_first": "Confirm the budget owner.",
                "next_focus": "Book the demo on the call.",
                "assessment": ASSESSMENT,
            },
            "next_call_focus": {"behavior": "Summarise before the close."},
        },
    }
    payload.update(overrides)
    return payload


def test_row_summary_reads_the_overview_first():
    assert library.library_row_summary(_payload()) == {
        "outcome": "follow_up",
        "assessment": ASSESSMENT,
        "fix_first": "Confirm the budget owner.",
        "next_focus": "Book the demo on the call.",
        "strengths": 2,
        "missed": 1,
    }


def test_row_summary_falls_back_like_the_calls_page():
    older = _payload()
    del older["overview"]
    assert library.library_row_summary(older) == {
        "outcome": None,
        "assessment": "Verdict text.",
        "fix_first": None,
        "next_focus": "Ask for the decision maker",
        "strengths": 2,
        "missed": 1,
    }
    odd = _payload(
        overview={
            "outcome": {"kind": "sideways", "text": " The call ended. "},
            "final_assessment": {"assessment": "   "},
            "next_call_focus": {"behavior": "Summarise before the close."},
        },
        strengths="not a list",
    )
    summary = library.library_row_summary(odd)
    assert summary is not None
    assert summary["outcome"] is None
    assert summary["assessment"] == "The call ended."
    assert summary["next_focus"] == "Summarise before the close."
    assert summary["strengths"] is None
    assert library.library_row_summary(None) is None
    assert library.library_row_summary(["not", "a", "report"]) is None


class _Database:
    """Answers the three summary statements in order: retained, drafts, marks."""

    def __init__(self, *results):
        self.results = list(results)

    async def execute(self, statement):
        return self.results.pop(0)


def test_row_summaries_use_the_report_source_and_withhold_marked_calls(monkeypatch):
    tenant, person = uuid4(), uuid4()
    retained, drafted, unfinished, unread = uuid4(), uuid4(), uuid4(), uuid4()

    def row(recording_id, has_report=True):
        return SimpleNamespace(
            recording_id=recording_id,
            has_report=has_report,
            recording_tenant_id=tenant,
            recording_person_id=person,
            generation=1,
        )

    database = _Database(
        # The retained Report of the current generation wins over any draft.
        [(retained, tenant, person, 1, _payload("rev-1"))],
        [
            (drafted, tenant, person, _payload("rev-2"), 1, "completed"),
            (drafted, tenant, person, _payload("rev-old"), 1, "completed"),
            # The Report read answers 409 for a draft whose run has not completed.
            (unfinished, tenant, person, _payload("rev-3"), 1, "running"),
        ],
        # A mark on the retained Report's transcript revision (from another call).
        [(uuid4(), "rev-1")],
    )
    plans = []

    async def plan_for(database, *, recording_id, served_revisions):
        plans.append((recording_id, served_revisions))
        return withheld_plan([("seg-1", ASSESSMENT)], {"seg-1"}, grams(ASSESSMENT))

    monkeypatch.setattr(library, "withheld_plan_for", plan_for)
    summaries = asyncio.run(
        library._row_summaries(
            database,
            [row(retained), row(drafted), row(unfinished), row(unread, has_report=False)],
        )
    )
    assert set(summaries) == {retained, drafted}
    assert summaries[retained]["assessment"] == WITHHELD_MARKER
    assert summaries[retained]["strengths"] == 2
    assert summaries[drafted]["assessment"] == ASSESSMENT
    assert plans == [(retained, ("rev-1",))]
