"""Anonymous team suggestions never become individual diagnoses or scores."""

from uuid import UUID

from ac_platform.coaching.report_adapter import from_report
from ac_platform.coaching.team import summarize_team
from tests.unit.coaching.test_report_adapter import CALL, NOW, envelope


def test_team_counts_only_source_linked_suggestions_and_never_serializes_reps() -> None:
    data = envelope()
    call = from_report(data, submission_id=CALL, created_at=NOW, comparison_key="v1")
    rep = UUID(int=999)
    view = summarize_team(((rep, call), (rep, call)), person_id=UUID(int=1), tenant_id=UUID(int=2))
    assert view.analysed_calls == 1 and view.suggestions[0].suggestion_calls == 1
    assert view.rep_count == 1
    assert view.latest_call_at == NOW
    raw = view.model_dump_json()
    for private in (str(rep), str(CALL), "Handover takes time.", "Ask one impact question."):
        assert private not in raw
    assert view.named_rep_details is False and view.scope == "anonymous"


def test_partial_status_without_a_mission_is_not_a_team_mistake() -> None:
    data = envelope()
    data["report"]["content"].pop("overview")
    data["report"]["content"].pop("improvements")
    call = from_report(data, submission_id=CALL, created_at=NOW, comparison_key="v1")
    view = summarize_team(((UUID(int=9), call),), person_id=UUID(int=1), tenant_id=UUID(int=2))
    assert view.analysed_calls == 1 and view.suggestions == ()


def test_unclassified_legacy_suggestion_is_not_guessed_from_its_title_or_prose() -> None:
    data = envelope()
    data["report"]["content"]["dimensions"] = []
    data["report"]["content"]["improvements"][0]["title"] = "A private name and context"
    call = from_report(data, submission_id=CALL, created_at=NOW, comparison_key="v1")
    view = summarize_team(
        ((UUID(int=9), call),), person_id=UUID(int=1), tenant_id=UUID(int=2), history_limited=True
    )
    assert view.suggestions[0].skill_id == "report_next_step"
    assert view.suggestions[0].label == "Other suggestions"
    assert "private name" not in view.model_dump_json()
    assert "40" in view.limitations[-1]


def test_an_empty_team_has_no_latest_call_date() -> None:
    view = summarize_team((), person_id=UUID(int=1), tenant_id=UUID(int=2))
    assert view.analysed_calls == 0 and view.latest_call_at is None


def test_team_counts_buyer_objections_by_kind_and_handling_never_their_words() -> None:
    def call_with(objections: list[dict], submission: int):
        data = envelope()
        data["report"]["content"]["call_map"] = {"objections": objections}
        data["submission_id"] = str(UUID(int=submission))
        data["source_sha256"] = f"{submission:064x}"
        return from_report(
            data, submission_id=UUID(int=submission), created_at=NOW, comparison_key="v1"
        )

    price = {"id": "o1", "kind": "price_concern", "text": "Too costly for us", "evidence": []}
    first = call_with(
        [
            {**price, "handling": "answered"},
            {**price, "handling": "ignored"},
            {"kind": "stall", "handling": "question_back", "text": "Let me think"},
            # Withheld words, unknown kinds and handling never count.
            {"kind": "trust_concern", "handling": "deflected", "text": "[Withheld for privacy]"},
            {"kind": "made_up", "handling": "answered"},
            {"kind": "stall", "handling": "shrugged"},
        ],
        10,
    )
    second = call_with([{**price, "handling": "deflected"}], 11)
    older = from_report(envelope(), submission_id=CALL, created_at=NOW, comparison_key="v1")
    assert first and second and older and not older.has_call_map
    view = summarize_team(
        ((UUID(int=9), first), (UUID(int=8), second), (UUID(int=7), older)),
        person_id=UUID(int=1),
        tenant_id=UUID(int=2),
    )
    assert view.objection_calls == 2
    assert [(o.kind, o.calls, o.heard, o.handled) for o in view.objections] == [
        ("price_concern", 2, 3, 1),
        ("stall", 1, 1, 1),
    ]
    assert view.objections[0].label == "Price"
    raw = view.model_dump_json()
    assert "Too costly" not in raw and "Let me think" not in raw
