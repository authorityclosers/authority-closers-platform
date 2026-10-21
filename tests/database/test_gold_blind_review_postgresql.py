"""Gold checkpoints and the blind Brain 4.0 review (orchestrator, 21 Oct 2026). Fictional."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from ac_platform.conversation_intelligence import brain4, gold_review_account
from ac_platform.conversation_intelligence.application import (
    ConversationConflict,
    ConversationError,
)
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.gold_checkpoint import Checkpoint
from ac_platform.conversation_intelligence.gold_review_contracts import GoldSave
from ac_platform.conversation_intelligence.gold_review_job import (
    assign_saved_reviews,
    checkpoint_progress,
)
from ac_platform.conversation_intelligence.gold_review_models import GoldAssignment, GoldRow
from ac_platform.conversation_intelligence.gold_reviews import (
    GoldReviews,
    gold_assignment_state,
)
from ac_platform.conversation_intelligence.models import ConversationReportDraft
from ac_platform.conversation_intelligence.pointer_review_models import ConversationPointerReview
from tests.database.test_conversation_reviews_postgresql import ReviewCase, _service, run
from tests.database.test_conversation_reviews_postgresql import (
    postgres_harness as postgres_harness,
)
from tests.database.test_conversation_reviews_postgresql import (
    review_case as review_case,
)

OBSERVED = "Fictional: you asked what happens to a lead after it comes in."


def plan(**changes: Any) -> Checkpoint:
    data: dict[str, Any] = {
        "name": "test-blind",
        "since": datetime(2000, 1, 1, tzinfo=UTC),
        "mode": "brain4_blind",
        "daily": 2,
        "total": 2,
        "assign_from_hour": 0,
        "minutes": None,
        "workspaces": "any",
        "at_least": {"price": 1},
        "mix": {},
        "salespeople": {"at_least": 1, "at_most_each": 5},
    }
    data.update(changes)
    return Checkpoint.model_validate(data)


def brain4_answer(segments: list[dict[str, Any]]) -> dict[str, Any]:
    first = [str(segments[0]["id"])]
    return {
        "call_type": "inbound",
        "dimensions": [
            {
                "id": d,
                "applicability": "applicable",
                "rating": 3,
                "confidence": "medium",
                "evidence": first,
                "observed": OBSERVED,
                "coaching": "On your next relevant call, ask who else decides.",
                "ethics_gate": "PASS" if d == "D07" else None,
            }
            for d in brain4.DIMENSION_IDS
        ],
    }


async def prepare(case: ReviewCase) -> tuple[UUID, UUID]:
    now = case.prepared.state.now
    async with case.sessions() as db, db.begin():
        service = _service(db, case)
        draft = await db.scalar(
            select(ConversationReportDraft).where(
                ConversationReportDraft.run_id == case.report_run_id
            )
        )
        assert draft is not None
        evidence = await service._evidence(case.report_run_id, now)
        payload = {
            "version": "pointer-review/1",
            "pointers": [
                {
                    "id": f"pointer-{i}",
                    "number": i,
                    "label": f"Skill {i}",
                    "status": "good",
                    "score": 72,
                    "what_happened": "The seller asked about timing.",
                    "evidence": [],
                    "how_to_improve": [],
                }
                for i in range(1, 28)
            ],
            "outcome": {"stages": ["Discovery", "Negotiation"], "objections": []},
            # The call's Brain 4.0 read, saved with the review (beta).
            "brain4": brain4.parse(
                brain4_answer(evidence.transcript["segments"]), evidence.transcript["segments"]
            ),
        }
        review = ConversationPointerReview(
            id=uuid4(),
            tenant_id=evidence.recording.tenant_id,
            recording_id=evidence.recording.id,
            run_id=case.report_run_id,
            report_draft_id=draft.id,
            source_sha256=evidence.recording.source_sha256,
            transcript_revision=evidence.transcript["revision"],
            version="pointer-review/1",
            model_id="fictional-offline",
            prompt_sha256="a" * 64,
            payload=payload,
            payload_sha256=content_hash(payload),
            created_by="fictional-test",
            created_at=now,
        )
        db.add(review)
        await db.flush()
        await GoldReviews(service).designate(
            case.admin_actor,
            "reviewer-" + case.reviewer_actor.person_id.hex + "@example.test",
            True,
        )
        ops = case.operations_tenant_id
        # Waits: not our company's workspace, not 10-30 minutes, before the morning hour,
        # a call that cannot meet a count every place needs.
        assert await assign_saved_reviews(db, ops, now, checkpoint=plan(workspaces="company")) == 0
        assert await assign_saved_reviews(db, ops, now, checkpoint=plan(minutes=(10, 30))) == 0
        hour = now.astimezone(ZoneInfo("Asia/Kolkata")).hour
        if hour < 23:
            early = plan(assign_from_hour=hour + 1)
            assert await assign_saved_reviews(db, ops, now, checkpoint=early) == 0
        tight = plan(total=1, daily=1, at_least={"objection": 1})
        assert await assign_saved_reviews(db, ops, now, checkpoint=tight) == 0
        # Chosen once, then nothing more (the reviewer already has the call).
        assert await assign_saved_reviews(db, ops, now, checkpoint=plan()) == 1
        assert await assign_saved_reviews(db, ops, now, checkpoint=plan()) == 0
        link = await db.scalar(select(GoldAssignment).where(GoldAssignment.review_id == review.id))
        assert link is not None
        assert (link.mode, link.checkpoint) == ("brain4_blind", "test-blind")
        progress = await checkpoint_progress(db, ops, plan())
        assert progress["chosen"] == 1
        assert progress["at_least"]["price"] == {"want": 1, "have": 1}
        return link.assignment_id, review.id


@pytest.fixture(scope="module")
def blind_case(review_case: ReviewCase) -> tuple[ReviewCase, UUID, UUID]:
    assignment_id, review_id = run(prepare(review_case))
    return review_case, assignment_id, review_id


def test_blind_review_shows_brain4_only_after_all_18_ratings(blind_case: Any) -> None:
    case, assignment, review = blind_case
    reviewer = case.reviewer_actor
    dims = list(brain4.DIMENSION_IDS)

    async def exercise() -> None:
        async with case.sessions() as db, db.begin():
            svc = GoldReviews(_service(db, case))
            view = await svc.get(reviewer, assignment)
            assert view["mode"] == "brain4_blind" and view["lines"] == []
            assert [d["id"] for d in view["dimensions"]] == dims
            assert view["brain4"] is None and view["revealed"] is False
            assert view["context"]["summary"] is None and view["context"]["verdict"] is None
            assert OBSERVED not in str(view)
            with pytest.raises(ConversationError):
                await svc.save(
                    reviewer,
                    assignment,
                    GoldSave(review_id=review, target="pointer-1", verdict="agree"),
                    "classic-line",
                )
            early = GoldSave(
                review_id=review,
                target="moment:01",
                opinion="Gave the price before asking about the team.",
                moment={"at_ms": 61_000, "kind": "criticism", "dimension": "D15"},
            )
            caught_early = GoldSave(
                review_id=review,
                target="moment:01",
                opinion="Gave the price before asking about the team.",
                moment={"at_ms": 61_000, "kind": "criticism", "dimension": "D15", "caught": "yes"},
            )
            with pytest.raises(ConversationError):
                await svc.save(reviewer, assignment, caught_early, "caught-too-early")
            first_moment = await svc.save(reviewer, assignment, early, "moment-1")
            assert first_moment["value"]["blind"] is True
            for n, d in enumerate(dims[:-1]):
                intent = (
                    GoldSave(review_id=review, target=f"brain4:{d}", skip="not_applicable")
                    if d == "D08"
                    else GoldSave(review_id=review, target=f"brain4:{d}", rating=1 + n % 5)
                )
                await svc.save(reviewer, assignment, intent, f"rate-{d}")
            view = await svc.get(reviewer, assignment)
            assert view["brain4"] is None and OBSERVED not in str(view)
            assert await gold_assignment_state(db, assignment) == "in_progress"
            await svc.save(
                reviewer,
                assignment,
                GoldSave(review_id=review, target="brain4:D18", rating=2, seconds=40),
                "rate-D18",
            )
        async with case.sessions() as db, db.begin():
            svc = GoldReviews(_service(db, case))
            view = await svc.get(reviewer, assignment)
            assert view["revealed"] is True and view["brain4"]["status"] == "read"
            assert view["brain4"]["label"] == "beta"
            shown = {d["id"]: d for d in view["brain4"]["dimensions"]}
            assert shown["D16"]["rating"] == 3 and shown["D16"]["observed"] == OBSERVED
            assert shown["D16"]["evidence"][0]["quote"]
            assert await gold_assignment_state(db, assignment) == "submitted"
            heads = {row["target"]: row for row in view["saved"]}
            with pytest.raises(ConversationConflict):
                await svc.save(
                    reviewer,
                    assignment,
                    GoldSave(
                        review_id=review,
                        target="brain4:D18",
                        rating=4,
                        supersedes_id=UUID(heads["brain4:D18"]["id"]),
                    ),
                    "change-after-reveal",
                )
            marked = await svc.save(
                reviewer,
                assignment,
                GoldSave(
                    review_id=review,
                    target="moment:01",
                    opinion="Gave the price before asking about the team.",
                    moment={
                        "at_ms": 61_000,
                        "kind": "criticism",
                        "dimension": "D15",
                        "caught": "partly",
                    },
                    supersedes_id=UUID(heads["moment:01"]["id"]),
                ),
                "moment-1-marked",
            )
            assert marked["value"]["blind"] is True  # written before the reveal, unchanged
            after = await svc.save(
                reviewer,
                assignment,
                GoldSave(
                    review_id=review,
                    target="moment:02",
                    opinion="Agreed a clear time for the next call.",
                    moment={"at_ms": 400_000, "kind": "praise", "caught": "yes"},
                ),
                "moment-2",
            )
            assert after["value"]["blind"] is False
            queue = await gold_review_account.queue(db, reviewer.person_id, case.prepared.state.now)
            item = next(i for i in queue["items"] if i["assignment_id"] == str(assignment))
            assert (item["mode"], item["handled"], item["total"], item["state"]) == (
                "brain4_blind",
                18,
                18,
                "done",
            )
            stored = (
                await db.scalars(select(GoldRow).where(GoldRow.assignment_id == assignment))
            ).all()
            assert all("ai" not in (row.payload or {}) for row in stored)

    run(exercise())


def test_the_evaluation_compares_blind_ratings_and_counts_moments(blind_case: Any) -> None:
    case, _, _ = blind_case

    async def exercise() -> None:
        async with case.sessions() as db, db.begin():
            result = await GoldReviews(_service(db, case)).evaluation(case.admin_actor)
        blind = result["blind"]
        assert (blind["ratings"], blind["calls"], blind["calls_with_brain4"]) == (18, 1, 1)
        dims = {d["id"]: d for d in blind["dimensions"]}
        assert dims["D18"]["brain4"]["rated"] == 1 and dims["D18"]["brain4"]["lean"] == 1.0
        assert dims["D08"]["brain4"]["judgeable_agree"] == 0.0
        assert dims["D03"]["readiness"]["state"] == "undecidable"
        moments = blind["moments"]
        assert (moments["criticisms"], moments["praise"], moments["marked"]) == (1, 1, 1)
        assert moments["caught"] == {"yes": 0, "partly": 1, "no": 0}
        assert OBSERVED not in str(result) and "Gave the price" not in str(result)

    run(exercise())
