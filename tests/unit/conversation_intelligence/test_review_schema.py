"""The Report review's items come from the Report's own structure (owner, 23 Oct 2026).

Fictional structures only."""

from datetime import UTC, datetime

from ac_platform.conversation_intelligence import review_schema
from ac_platform.conversation_intelligence.brain4_eval import ReviewItem, review_agreement

QUOTE = {
    "segment_id": "s3",
    "quote": "What happens to a lead after it comes in?",
    "start_ms": 14_000,
}


def structure(**extra: object) -> dict:
    return {
        "version": "report-structure/1",
        "review_status": "ai_draft_not_dipak_reviewed",
        "pointers": [{"id": "call_control", "label": "Call control"}],
        "final_call_outcome": {"status": "recorded", "outcome": "Won"},
        "overview": {
            "summary": "Fictional: you spoke about lead follow-up.",
            "biggest_strength": {
                "text": "You asked about the follow-up process.",
                "evidence": [QUOTE],
            },
            "biggest_improvement": None,
            "call_statistics": {"duration_ms": 600_000},
        },
        "brain4": {
            "status": "beta",
            "dimensions": [
                {
                    "id": "D01",
                    "number": 1,
                    "label": "Starting the Call",
                    "rating": 4,
                    "shown_rating": 4,
                    "observed": "You opened warmly.",
                    "coaching": "Ask what made them call.",
                    "evidence": [QUOTE],
                },
                {
                    "id": "D03",
                    "number": 3,
                    "label": "Tone, Pace & Pauses",
                    "rating": None,
                    "shown_rating": None,
                    "observed": "Needs audio.",
                    "coaching": None,
                    "evidence": [],
                },
            ],
        },
        "call_outcome_details": {
            "stages": ["Discovery", "Negotiation"],
            "reasons": ["The partner decides."],
            "objections": [{"text": "Too costly", "handled": False}],
            "next_steps": [
                {"text": "Call with both partners", "owner": "you", "when": "Friday 4 PM"}
            ],
            "notes": [],
            "suggested_action": "Send the plan before Friday.",
        },
        "prospect_signals": {
            "qualification": {
                "need": {"state": "confirmed", "note": "Leads go cold.", "evidence": []},
                "budget": {"state": "unknown", "note": None, "evidence": []},
            },
            "pains": [],
            "objections": [],
            "facts": [{"key": "team_size", "text": "Four people", "evidence": []}],
        },
        **extra,
    }


def test_items_follow_the_report_in_its_order() -> None:
    found = review_schema.items(structure())
    ids = [item["id"] for item in found]
    assert ids[:2] == ["brain4.D01", "brain4.D03"]
    assert "overview.summary" in ids and "overview.biggest_strength" in ids
    assert "overview.biggest_improvement" not in ids  # nothing to review
    assert "outcome.stages" in ids and "outcome.suggested_action" in ids
    assert "outcome.reasons.1" in ids and "outcome.objections.1" in ids
    assert "buyer.need" in ids and "buyer.budget" not in ids
    assert "buyer.facts.1" in ids
    # Person-entered outcome, the 27 pointers and bookkeeping are not reviewed.
    assert not any(i.startswith(("pointers", "final_call_outcome", "version")) for i in ids)


def test_a_rated_item_carries_rating_words_coaching_and_evidence() -> None:
    first, second = review_schema.items(structure())[:2]
    assert first["kind"] == "rating" and first["rating"] == 4 and first["number"] == 1
    assert first["text"] == "You opened warmly." and first["detail"] == "Ask what made them call."
    assert first["evidence"][0]["start_ms"] == 14_000
    assert second["kind"] == "rating" and second["rating"] is None  # "–" is still reviewed
    step = next(i for i in review_schema.items(structure()) if i["id"] == "outcome.next_steps.1")
    assert step["kind"] == "text" and "Friday 4 PM" in (step["detail"] or "")


def test_a_section_the_registry_does_not_know_is_still_reviewed() -> None:
    found = review_schema.items(structure(deal_risks={"summary": "Partner may say no."}))
    whole = next(i for i in found if i["section"] == "deal_risks")
    assert whole["id"] == "deal_risks.whole" and whole["text"] == "Partner may say no."
    sections = review_schema.sections(found)
    assert sections[0]["label"] == "AI coaching score"
    assert sections[-1]["label"] == "Deal risks"


def test_reviews_are_bound_to_the_schema_and_the_route() -> None:
    meta = review_schema.meta(structure())
    assert meta["structure"] == "report-structure/1"
    assert meta["registry"] == "review-schema/1" and len(meta["digest"]) == 16
    route = {
        "review": "automatic:one-pass-plan:gemini-3.8-flash",
        "brain4": "shadow:gemini-3.8-flash",
    }
    assert review_schema.route_module("brain4", route) == "b4.shadow"
    assert review_schema.route_module("outcome", route) == "c4.one-pass-v1"
    luna = {"review": "automatic:one-pass-plan:gpt-6-luna", "brain4": "review:gpt-6-luna"}
    assert review_schema.route_module("brain4", luna) == "c4.one-pass-v2"
    assert review_schema.route_module("buyer", luna) == "c4.one-pass-v1.luna-flex"
    classic = {"review": "automatic:pointer-review:gemini-3.8-flash", "brain4": None}
    assert review_schema.route_module("overview", classic) == "pr.classic"


def test_agreement_is_per_section_and_engine_module_with_their_names() -> None:
    at = datetime(2026, 10, 23, tzinfo=UTC)

    def item(call: str, verdict: str | None, **extra: object) -> ReviewItem:
        values: dict[str, object] = {
            "recording_id": call,
            "section": "brain4",
            "module": "b4.shadow",
            "created_at": at,
            "verdict": verdict,
            "skip": None,
            "ai_rating": 3,
            "rating": None,
        }
        values.update(extra)
        return ReviewItem(**values)  # type: ignore[arg-type]

    result = review_agreement(
        [
            item("a", "agree"),
            item("a", "fix", rating=5),
            item("b", "disagree"),
            item("b", None, skip="come_back"),
            item("b", "agree", section="deal_risks", module="pr.classic", ai_rating=None),
        ]
    )
    assert (result["items"], result["skipped"], result["calls"]) == (4, 1, 2)
    shadow = next(r for r in result["by_section"] if r["key"] == ["brain4", "b4.shadow"])
    assert shadow["names"] == ["AI coaching score", "Brain 4.0 · separate read"]
    assert (shadow["agree"], shadow["disagree"], shadow["fix"]) == (1, 1, 1)
    assert shadow["rating_moved"] == 2.0 and shadow["agree_rate"] == round(1 / 3, 4)
    risks = next(r for r in result["by_section"] if r["key"][0] == "deal_risks")
    assert risks["names"] == ["Deal risks", "Pointer review · classic"]
    unknown = review_agreement([item("a", "agree", module="x.new")])
    assert unknown["by_module"][0]["names"] == ["x.new"]
