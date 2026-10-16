"""AUT-2010: a saved AI pointer review reaches the Report only through the
authorized account read, and the current privacy marks apply after it.

Fictional transcript and review; the readers are the existing service doubles.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ac_platform.conversation_intelligence import report_structure_service as service
from ac_platform.conversation_intelligence.application import ConversationDenied
from ac_platform.conversation_intelligence.pointer_review import parse_review
from ac_platform.conversation_intelligence.sensitive_segments import (
    EMPTY_PLAN,
    WITHHELD_MARKER,
    grams,
    withheld_plan,
)
from tests.unit.conversation_intelligence import test_report_structure_service as base
from tests.unit.conversation_intelligence.test_pointer_review import SEGMENTS, answer

PIVOT = "They said our leads are poor quality, so you pivoted."


@pytest.fixture
def overlay(monkeypatch):
    envelope, _, submission_id, actor, transcript, *_ = base.setup.__wrapped__(monkeypatch)
    review = parse_review(
        answer(call_opening_first_impression={"evidence": ["s2"], "what_happened": PIVOT}),
        SEGMENTS,
    )
    latest = AsyncMock(return_value=review)
    plan = AsyncMock(return_value=EMPTY_PLAN)
    monkeypatch.setattr(service, "latest_review", latest)
    monkeypatch.setattr(service, "withheld_plan_for", plan)
    ownership = SimpleNamespace(database=object())
    return envelope, ownership, submission_id, actor, latest, plan, transcript


async def read(overlay, *, actor=...):
    envelope, ownership, submission_id, default_actor, *_ = overlay
    return await service.enrich_report_structure(
        envelope,
        ownership,
        submission_id,
        actor=default_actor if actor is ... else actor,
        shared_identity_locks=True,
    )


def first_pointer(result):
    return result["report"]["content"]["structure"]["pointers"][0]


async def test_permitted_account_read_overlays_the_ai_draft_after_current_marks(overlay):
    envelope, ownership, *_, latest, plan, _ = overlay
    result = await read(overlay)
    structure = result["report"]["content"]["structure"]
    assert structure["overview"]["score_status"] == "ai_draft"
    assert structure["review_status"] == "ai_draft_not_dipak_reviewed"
    assert len(structure["pointers"]) == 27
    assert first_pointer(result)["what_happened"] == PIVOT
    assert first_pointer(result)["evidence"][0]["segment_id"] == "s2"
    latest.assert_awaited_once_with(ownership.database, envelope)
    assert plan.await_args.kwargs["served_revisions"] == (envelope["transcript_revision"],)
    assert str(plan.await_args.kwargs["recording_id"]) == str(envelope["recording_id"])
    # The person's own outcome record keeps precedence over the AI draft.
    assert structure["final_call_outcome"]["outcome"] == "Won"


@pytest.mark.parametrize("who", ["guest", "no_actor"])
async def test_guest_or_anonymous_reads_never_load_a_review(overlay, who):
    envelope, *_, latest, plan, _ = overlay
    if who == "guest":
        envelope["report"]["access"] = "guest_preview"
    result = await read(overlay, actor=None if who == "no_actor" else ...)
    assert result is envelope
    latest.assert_not_awaited()
    plan.assert_not_awaited()


async def test_denied_read_loads_no_review_content(overlay):
    *_, latest, plan, transcript = overlay
    transcript.side_effect = ConversationDenied("Call access revoked")
    with pytest.raises(ConversationDenied):
        await read(overlay)
    latest.assert_not_awaited()
    plan.assert_not_awaited()


async def test_a_mark_made_after_the_review_hides_its_quote_and_narrative(overlay):
    *_, plan, _ = overlay
    plan.return_value = withheld_plan(
        [(s["id"], s["text"]) for s in SEGMENTS], {"s2"}, grams(SEGMENTS[1]["text"])
    )
    result = await read(overlay)
    pointer = first_pointer(result)
    assert pointer["evidence"][0]["quote"] == WITHHELD_MARKER
    assert pointer["what_happened"] == WITHHELD_MARKER
    assert "poor quality" not in json.dumps(result["report"]["content"]["structure"]["pointers"])
    assert result["report"]["content"]["structure"]["final_call_outcome"]["outcome"] == "Won"


async def test_a_mark_on_another_revision_hides_the_same_words_by_content(overlay):
    *_, plan, _ = overlay
    # Changed segment ids: the mark is on another revision ("x9"), only its words match.
    plan.return_value = withheld_plan(
        [(s["id"], s["text"]) for s in SEGMENTS], set(), grams(SEGMENTS[1]["text"])
    )
    result = await read(overlay)
    assert first_pointer(result)["evidence"][0]["quote"] == WITHHELD_MARKER
    assert first_pointer(result)["what_happened"] == WITHHELD_MARKER


async def test_without_a_saved_review_the_report_stays_unscored(overlay):
    *_, latest, plan, _ = overlay
    latest.return_value = None
    result = await read(overlay)
    structure = result["report"]["content"]["structure"]
    assert structure["overview"].get("score_status") != "ai_draft"
    assert "review_status" not in structure
    plan.assert_not_awaited()
