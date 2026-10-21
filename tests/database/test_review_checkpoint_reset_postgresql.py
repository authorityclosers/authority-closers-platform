"""scripts/data-changes/review-checkpoint-reset-20261021.py on PostgreSQL: listed open gold
assignments are revoked through Admin's own revoke, audited with the owner's approval, dry run
by default, idempotent; the Pulse part only builds its statements here. Fictional fixture."""

import importlib.util
import json
import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence.application import ConversationDenied
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.gold_checkpoint import EVERY_CALL
from ac_platform.conversation_intelligence.gold_review_job import assign_saved_reviews
from ac_platform.conversation_intelligence.gold_review_models import GoldAssignment, GoldReviewer
from ac_platform.conversation_intelligence.gold_reviews import GoldReviews
from ac_platform.conversation_intelligence.models import (
    ConversationReportDraft,
    ConversationReviewRevocation,
)
from ac_platform.conversation_intelligence.pointer_review import POINTER_IDS
from ac_platform.conversation_intelligence.pointer_review_models import ConversationPointerReview
from tests.database.test_conversation_reviews_postgresql import ReviewCase, _service, run
from tests.database.test_conversation_reviews_postgresql import (
    postgres_harness as postgres_harness,
)
from tests.database.test_conversation_reviews_postgresql import (
    review_case as review_case,
)

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "review_checkpoint_reset", ROOT / "scripts/data-changes/review-checkpoint-reset-20261021.py"
)
assert _spec is not None and _spec.loader is not None
script = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = script  # its dataclasses look themselves up here
_spec.loader.exec_module(script)


async def prepare(case: ReviewCase):
    async with case.sessions() as db, db.begin():
        service = _service(db, case)
        draft = await db.scalar(
            select(ConversationReportDraft).where(
                ConversationReportDraft.run_id == case.report_run_id
            )
        )
        evidence = await service._evidence(case.report_run_id, case.prepared.state.now)
        payload = {
            "version": "pointer-review/1",
            "pointers": [
                {
                    "id": pointer,
                    "number": number,
                    "label": f"Skill {number}",
                    "status": "good",
                    "score": 80,
                    "what_happened": "The seller asked about timing.",
                    "evidence": [],
                    "how_to_improve": [],
                }
                for number, pointer in enumerate(POINTER_IDS, 1)
            ],
            "outcome": {"notes": []},
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
            prompt_sha256="e" * 64,
            payload=payload,
            payload_sha256=content_hash(payload),
            created_by="fictional-test",
            created_at=case.prepared.state.now,
        )
        db.add(review)
        await db.flush()
        await GoldReviews(service).designate(
            case.admin_actor,
            "reviewer-" + case.reviewer_actor.person_id.hex + "@example.test",
            True,
        )
        await assign_saved_reviews(
            db, case.operations_tenant_id, case.prepared.state.now, checkpoint=EVERY_CALL
        )
        assignment = await db.scalar(
            select(GoldAssignment).where(GoldAssignment.review_id == review.id)
        )
        return assignment.assignment_id


@pytest.fixture(scope="module")
def reset_case(review_case):
    return review_case, run(prepare(review_case))


def test_listed_open_assignments_close_through_admins_revoke_with_the_approval(
    reset_case,
) -> None:
    case, assignment = reset_case
    unknown = str(uuid4())

    async def exercise():
        async def do(apply: bool):
            command = script.Command(
                environment="test", issue="AUT-test", apply=apply, ids=(str(assignment), unknown)
            )
            async with case.sessions() as db:
                transaction = await db.begin()
                try:
                    result = await script.close(
                        db,
                        command,
                        operations_tenant_id=case.operations_tenant_id,
                        actor=case.admin_actor,
                    )
                except BaseException:
                    await transaction.rollback()
                    raise
                if apply and result["status"] == "applied":
                    await transaction.commit()
                else:
                    await transaction.rollback()
                return result

        dry = await do(False)
        assert dry["status"] == "dry_run" and dry["closed"] == 1
        assert dry["before"] == {"not_gold": 1, "open": 1}
        assert dry["after"] == {"not_gold": 1, "revoked": 1}
        async with case.sessions() as db:
            assert await db.get(ConversationReviewRevocation, assignment) is None
        applied = await do(True)
        assert applied["status"] == "applied" and applied["closed"] == 1
        assert (await do(True))["status"] == "no_op"
        async with case.sessions() as db:
            assert await db.get(ConversationReviewRevocation, assignment) is not None
            # The designation stays: new calls are still assigned to the reviewer.
            reviewer = await db.get(GoldReviewer, case.reviewer_actor.person_id)
            assert reviewer is not None and reviewer.revoked_at is None
            events = (
                await db.scalars(select(AuditEvent).where(AuditEvent.action == script.ACTION))
            ).all()
            with pytest.raises(ConversationDenied):
                await GoldReviews(_service(db, case)).get(case.reviewer_actor, assignment)
        assert len(events) == 1
        payload = events[0].payload
        assert payload["closed"] == [str(assignment)]
        assert payload["skipped"] == {unknown: "not_gold"}
        assert payload["reason"] == "checkpoint 2026-10-21 reset"
        assert payload["approval"]["approval"] == script.APPROVAL
        assert payload["approval"]["issue"] == "AUT-test"

    run(exercise())


def test_the_listed_ids_and_the_pulse_statements() -> None:
    production = script.ASSIGNMENTS["production"]
    development = script.ASSIGNMENTS["development"]
    assert len(production) == len(set(production)) == 61
    assert len(development) == len(set(development)) == 35
    assert not set(production) & set(development)
    assert all(str(UUID(identifier)) == identifier for identifier in production + development)
    assert script.assignment_ids("development-live") == development
    marks = script.markers(production[:2])
    assert marks[0] == f"https://admin.authorityclosers.com/reviewer/review/{production[0]}"
    json.dumps(marks)
    dry, real = script.pulse_sql(False), script.pulse_sql(True)
    assert dry.rstrip().endswith("rollback;") and real.rstrip().endswith("commit;")
    assert "pulse.task_move(t.id, 'cancelled', :'note')" in real
    assert "t.parent_id is not null" in real  # subtasks only; the parent task stays
    with pytest.raises(script.Refused, match="production_only"):
        script.run_pulse(script.Command(environment="development", issue="AUT-test"))


def test_the_cli_refuses_production_without_its_flag_and_an_issue() -> None:
    assert script.main(["--environment", "production", "--issue", "AUT-1", "pulse"]) == 2
    assert script.main(["--environment", "development", "--issue", " ", "pulse"]) == 2
    with pytest.raises(SystemExit):
        script.main(["--environment", "development", "--issue", "AUT-1", "bogus"])
