"""Report review: every item of a call's Report, agreed, disagreed or fixed (owner, 23 Oct
2026). The items come from the Report's own structure, so a new section needs no code.
Fictional."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from ac_platform.conversation_intelligence import (
    brain4,
    brain4_shadow,
    gold_review_account,
    review_schema,
)
from ac_platform.conversation_intelligence.application import ConversationError
from ac_platform.conversation_intelligence.brain4_models import ConversationBrain4Review
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
from tests.database.test_gold_blind_review_postgresql import OBSERVED, brain4_answer

FIXED = "Fictional: the partner decides, not the caller."


def plan() -> Checkpoint:
    return Checkpoint.model_validate(
        {
            "name": "test-report",
            "since": datetime(2000, 1, 1, tzinfo=UTC),
            "mode": "report",
            "daily": 2,
            "total": 2,
            "assign_from_hour": 0,
            "minutes": None,
            "workspaces": "any",
            "at_least": {},
            "mix": {},
            "salespeople": {"at_least": 1, "at_most_each": 5},
        }
    )


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
        # The classic review, without Brain 4.0: production reads Brain 4.0 in its shadow.
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
        # He reviews the Report the seller sees: wait until Brain 4.0 has read the call.
        assert await assign_saved_reviews(db, ops, now, checkpoint=plan()) == 0
        read = brain4.parse(
            brain4_answer(evidence.transcript["segments"]), evidence.transcript["segments"]
        )
        db.add(
            ConversationBrain4Review(
                id=uuid4(),
                tenant_id=evidence.recording.tenant_id,
                recording_id=evidence.recording.id,
                run_id=case.report_run_id,
                report_draft_id=draft.id,
                source_sha256=evidence.recording.source_sha256,
                transcript_revision=evidence.transcript["revision"],
                version=brain4.VERSION,
                rubric_sha256=brain4.RUBRIC_SHA256,
                model_id=brain4_shadow.MODEL_ID,
                prompt_sha256="b" * 64,
                state="saved",
                payload=read,
                payload_sha256=brain4.payload_sha256(read),
                trigger="auto",
                created_by=brain4_shadow.CREATED_BY,
                created_at=now,
                finished_at=now,
            )
        )
        await db.flush()
        assert await assign_saved_reviews(db, ops, now, checkpoint=plan()) == 1
        assert await assign_saved_reviews(db, ops, now, checkpoint=plan()) == 0
        link = await db.scalar(select(GoldAssignment).where(GoldAssignment.review_id == review.id))
        assert link is not None
        assert (link.mode, link.checkpoint) == ("report", "test-report")
        assert link.items is not None and link.items >= len(brain4.DIMENSION_IDS)
        assert (await checkpoint_progress(db, ops, plan()))["chosen"] == 1
        return link.assignment_id, review.id


@pytest.fixture(scope="module")
def report_case(review_case: ReviewCase) -> tuple[ReviewCase, UUID, UUID]:
    assignment_id, review_id = run(prepare(review_case))
    return review_case, assignment_id, review_id


def test_every_report_item_is_agreed_disagreed_or_fixed(report_case: Any) -> None:
    case, assignment, review = report_case
    reviewer = case.reviewer_actor
    now = case.prepared.state.now

    async def exercise() -> None:
        async with case.sessions() as db, db.begin():
            svc = GoldReviews(_service(db, case))
            view = await svc.get(reviewer, assignment)
            assert view["mode"] == "report" and view["lines"] == []
            assert view["schema"]["registry"] == review_schema.registry()["version"]
            assert view["route"]["brain4"] == f"shadow:{brain4_shadow.MODEL_ID}"
            first = view["sections"][0]
            assert first["id"] == "brain4" and first["label"] == "AI coaching score"
            assert [i["id"] for i in first["items"]] == [
                f"brain4.{d}" for d in brain4.DIMENSION_IDS
            ]
            assert first["items"][0]["rating"] == 3 and first["items"][0]["text"] == OBSERVED
            items = [i for s in view["sections"] for i in s["items"]]
            # The 27 pointers and the person-entered outcome are not in the Report review.
            assert not any(i["id"].startswith(("pointers", "final_call_outcome")) for i in items)
            text = next(i for i in items if i["kind"] == "text")
            link = await db.get(GoldAssignment, assignment)
            assert link is not None and link.items == len(items)

            def save(target: str, **values: Any) -> GoldSave:
                return GoldSave(review_id=review, target=f"item:{target}", **values)

            for wrong in (
                GoldSave(review_id=review, target="pointer-1", verdict="agree"),
                save("brain4.D99", verdict="agree"),
                save(text["id"], verdict="fix", rating=2),  # a text item has no rating
            ):
                with pytest.raises(ConversationError):
                    await svc.save(reviewer, assignment, wrong, "wrong")
            agreed = await svc.save(
                reviewer, assignment, save("brain4.D01", verdict="agree", seconds=6), "d01"
            )
            assert agreed["value"]["module"] == "b4.shadow"
            assert agreed["value"]["ai"] == {"rating": 3}
            assert agreed["value"]["schema"]["digest"] == view["schema"]["digest"]
            fixed = await svc.save(
                reviewer,
                assignment,
                save("brain4.D02", verdict="fix", rating=4, opinion="He did confirm the need."),
                "d02",
            )
            assert fixed["value"]["rating"] == 4 and fixed["value"]["ai"] == {"rating": 3}
            words = await svc.save(
                reviewer, assignment, save(text["id"], verdict="fix", correction=FIXED), "text"
            )
            assert words["value"]["correction"] == FIXED
            assert words["value"]["module"] == "pr.classic" and "ai" not in words["value"]
            await svc.save(
                reviewer,
                assignment,
                save("brain4.D03", verdict="disagree", opinion="Tone needs the audio."),
                "d03",
            )
            assert await gold_assignment_state(db, assignment) == "in_progress"
            done = {"brain4.D01", "brain4.D02", "brain4.D03", text["id"]}
            rest = [i["id"] for i in items if i["id"] not in done]
            later = next(t for t in reversed(rest) if not t.startswith("brain4."))
            await svc.save(reviewer, assignment, save(later, skip="come_back"), "skip")
            for n, target in enumerate(t for t in rest if t != later):
                await svc.save(reviewer, assignment, save(target, verdict="agree"), f"a{n}")
            assert await gold_assignment_state(db, assignment) == "submitted"
            queue = await gold_review_account.queue(db, reviewer.person_id, now)
            mine = next(i for i in queue["items"] if i["assignment_id"] == str(assignment))
            assert (mine["mode"], mine["handled"], mine["total"], mine["state"]) == (
                "report",
                len(items),
                len(items),
                "done",
            )
            stats = await gold_review_account.metrics(
                db, case.operations_tenant_id, reviewer.person_id, now
            )
            assert stats["me"]["calls_done"] == 1
            assert stats["me"]["verdicts"]["fix"] == 2
            stored = (
                await db.scalars(select(GoldRow).where(GoldRow.assignment_id == assignment))
            ).all()
            # The AI's rating is kept for agreement, never its words.
            assert OBSERVED not in str([row.payload for row in stored])

    run(exercise())


def test_the_evaluation_agrees_per_section_and_engine_module(report_case: Any) -> None:
    case, _, _ = report_case

    async def exercise() -> None:
        async with case.sessions() as db, db.begin():
            result = await GoldReviews(_service(db, case)).evaluation(case.admin_actor)
        review = result["review"]
        assert review["calls"] == 1 and review["skipped"] == 1
        modules = {row["key"][0]: row for row in review["by_module"]}
        shadow = modules["b4.shadow"]
        assert (shadow["agree"], shadow["disagree"], shadow["fix"]) == (16, 1, 1)
        assert shadow["rating_moved"] == 1.0
        assert shadow["names"] == ["Brain 4.0 · separate read"]
        assert modules["pr.classic"]["fix"] == 1
        sections = {tuple(row["key"]) for row in review["by_section"]}
        assert ("brain4", "b4.shadow") in sections
        # Counts only: no note, correction or call words leave the evaluation.
        assert FIXED not in str(result) and OBSERVED not in str(result)
        assert "He did confirm" not in str(result)

    run(exercise())
