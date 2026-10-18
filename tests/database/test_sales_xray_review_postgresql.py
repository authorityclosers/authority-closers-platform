"""Phone gold review (19 Oct): account sessions of standing reviewers, fictional data."""

from uuid import UUID

import pytest
from pydantic import ValidationError

from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationDenied,
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.gold_review_account import (
    AccountGoldReviewService,
    account_actor,
    badge,
    metrics,
    queue,
)
from ac_platform.conversation_intelligence.gold_review_contracts import GoldSave
from ac_platform.conversation_intelligence.gold_review_models import GoldRow
from ac_platform.conversation_intelligence.gold_reviews import GoldReviews
from ac_platform.kernel.authz import ActorContext
from tests.database.test_conversation_reviews_postgresql import ReviewCase, run
from tests.database.test_conversation_reviews_postgresql import (
    postgres_harness as postgres_harness,
)
from tests.database.test_conversation_reviews_postgresql import (
    review_case as review_case,
)
from tests.database.test_gold_reviews_postgresql import prepare


def _account(db, case: ReviewCase) -> AccountGoldReviewService:
    return AccountGoldReviewService(
        ConversationApplication(db, clock=lambda: case.prepared.state.now),
        operations_tenant_id=case.operations_tenant_id,
    )


@pytest.fixture(scope="module")
def phone_case(review_case):
    assignment_id, review_id = run(prepare(review_case))
    return review_case, assignment_id, review_id


def test_contract_keeps_skips_and_reasons_honest() -> None:
    review = UUID(int=1)
    with pytest.raises(ValidationError):
        GoldSave(review_id=review, target="pointer-1", skip="not_sure", verdict="agree")
    with pytest.raises(ValidationError):
        GoldSave(review_id=review, target="pointer-1")
    with pytest.raises(ValidationError):
        GoldSave(review_id=review, target="pointer-1", verdict="disagree", reasons=["misheard"] * 2)
    note_free = GoldSave(review_id=review, target="pointer-1", verdict="agree")
    assert note_free.opinion == "" and note_free.reasons == []


def test_reviewer_account_reviews_saves_and_sees_metrics(phone_case) -> None:
    case, assignment, review = phone_case
    reviewer = account_actor(
        ActorContext(case.reviewer_actor.person_id, case.reviewer_actor.session_id, uuid_or(case))
    )
    now = case.prepared.state.now

    async def exercise():
        async with case.sessions() as db, db.begin():
            listed = await queue(db, reviewer.person_id, now)
            assert [i["assignment_id"] for i in listed["items"]] == [str(assignment)]
            assert listed["items"][0]["state"] == "new" and listed["lines_left"] == 29
            assert (await badge(db, case.operations_tenant_id, reviewer.person_id, now))[
                "waiting"
            ] == 1
            gold = GoldReviews(_account(db, case))
            view = await gold.get(reviewer, assignment)
            assert len(view["lines"]) == 29 and view["context"]["recorded_at"]
            first = await gold.save(
                reviewer,
                assignment,
                GoldSave(
                    review_id=review,
                    target="pointer-1",
                    verdict="disagree",
                    status="average",
                    reasons=["too_generous", "wrong_evidence"],
                    seconds=21,
                ),
                "phone-1",
            )
            skipped = await gold.save(
                reviewer,
                assignment,
                GoldSave(review_id=review, target="pointer-2", skip="audio_unclear", seconds=5),
                "phone-2",
            )
            await gold.save(
                reviewer,
                assignment,
                GoldSave(review_id=review, target="pointer-3", score=60, seconds=12),
                "phone-3",
            )
            row = await db.get(GoldRow, UUID(first["id"]))
            # The AI value judged is captured server-side; the AI review is unchanged.
            assert row.payload["ai"] == {"status": "good", "score": 72}
            assert row.payload["reasons"] == ["too_generous", "wrong_evidence"]
            assert (await db.get(GoldRow, UUID(skipped["id"]))).payload["skip"] == "audio_unclear"
            listed = await queue(db, reviewer.person_id, now)
            assert listed["items"][0]["state"] == "in_progress"
            assert listed["items"][0]["handled"] == 3 and listed["lines_left"] == 26
            figures = await metrics(db, case.operations_tenant_id, reviewer.person_id, now)
            assert figures["scope"] in {"reviewer", "owner"}
            assert figures["me"]["labels"] == 2 and figures["me"]["skipped"] == 1
            assert figures["me"]["median_seconds"] == 12.0
            one = next(p for p in figures["pointers"] if p["target"] == "pointer-1")
            assert one["disagree"] == 1 and one["wrong_rate"] == 1.0
            assert one["status_changed"] == 1 and one["top_reasons"][0] == "too_generous"
            three = next(p for p in figures["pointers"] if p["target"] == "pointer-3")
            assert three["mean_score_gap"] == 12.0
            assert figures["wrong_most"][0] == "pointer-1"
            assert figures["team"]["labels"] >= 2

    run(exercise())


def uuid_or(case: ReviewCase):
    """A real account session carries a workspace; review drops it (account_actor)."""
    return case.prepared.state.tenant_id


def test_only_standing_reviewers_and_owners_get_in(phone_case) -> None:
    case, assignment, review = phone_case
    now = case.prepared.state.now

    async def exercise():
        for actor in (case.source_actor, case.foreign_actor, case.other_reviewer_actor):
            async with case.sessions() as db, db.begin():
                assert not (await badge(db, case.operations_tenant_id, actor.person_id, now))[
                    "reviewer"
                ]
                with pytest.raises(ConversationDenied):
                    await queue(db, actor.person_id, now)
                gold = GoldReviews(_account(db, case))
                with pytest.raises((ConversationDenied, ConversationNotFound)):
                    await gold.get(account_actor(actor), assignment)
                with pytest.raises((ConversationDenied, ConversationNotFound)):
                    await gold.save(
                        account_actor(actor),
                        assignment,
                        GoldSave(review_id=review, target="pointer-9", verdict="agree"),
                        "intruder",
                    )
        async with case.sessions() as db, db.begin():
            # A workspace-scoped actor is never admitted: the gold path drops the workspace.
            scoped = ActorContext(
                case.reviewer_actor.person_id, case.reviewer_actor.session_id, uuid_or(case)
            )
            with pytest.raises((ConversationDenied, ConversationNotFound)):
                await GoldReviews(_account(db, case)).get(scoped, assignment)
        async with case.sessions() as db, db.begin():
            # The operations owner/admin reads the figures, with each reviewer's counts.
            figures = await metrics(db, case.operations_tenant_id, case.admin_actor.person_id, now)
            assert figures["scope"] == "owner" and figures["me"] is None
            assert "reviewers" in figures

    run(exercise())
