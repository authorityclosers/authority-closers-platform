"""Brain 4.0 gold-set evaluation over saved gold rows of a fictional call."""

import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from ac_platform.conversation_intelligence import brain4
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.gold_review_contracts import GoldSave
from ac_platform.conversation_intelligence.gold_review_job import assign_saved_reviews
from ac_platform.conversation_intelligence.gold_review_models import GoldAssignment
from ac_platform.conversation_intelligence.gold_reviews import GoldReviews
from ac_platform.conversation_intelligence.models import ConversationReportDraft
from ac_platform.conversation_intelligence.pointer_review import POINTER_IDS
from ac_platform.conversation_intelligence.pointer_review_models import ConversationPointerReview
from tests.database.test_conversation_reviews_postgresql import ReviewCase, _service, run
from tests.database.test_conversation_reviews_postgresql import (
    postgres_harness as postgres_harness,
)
from tests.database.test_conversation_reviews_postgresql import (
    review_case as review_case,
)

NOTE = "Fictional note that must never leave the gold rows."


def brain4_block(next_steps: int) -> dict:
    return {
        "version": brain4.VERSION,
        "status": "beta",
        "dimensions": [
            {
                "id": dimension,
                "rating": next_steps if dimension == "D18" else 4,
                "applicability": "applicable",
            }
            for dimension in brain4.DIMENSION_IDS
        ],
    }


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
            "brain4": brain4_block(2),
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
            prompt_sha256="b" * 64,
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
        await assign_saved_reviews(db, case.operations_tenant_id, case.prepared.state.now)
        assignment = await db.scalar(
            select(GoldAssignment).where(GoldAssignment.review_id == review.id)
        )
        return assignment.assignment_id, review.id


@pytest.fixture(scope="module")
def brain4_case(review_case):
    assignment_id, review_id = run(prepare(review_case))
    return review_case, assignment_id, review_id


def test_evaluation_reads_current_gold_lines_and_brain4_runs(brain4_case) -> None:
    case, assignment, review = brain4_case

    async def exercise():
        async with case.sessions() as db, db.begin():
            gold = GoldReviews(_service(db, case))
            saves = [
                GoldSave(review_id=review, target="active_listening", verdict="agree"),
                GoldSave(
                    review_id=review,
                    target="next_steps",
                    verdict="disagree",
                    score=45,
                    reasons=["too_generous"],
                    opinion=NOTE,
                ),
                GoldSave(review_id=review, target="tone_energy", skip="audio_unclear"),
            ]
            first = None
            for number, intent in enumerate(saves):
                saved = await gold.save(case.reviewer_actor, assignment, intent, f"save-{number}")
                first = first or saved
            # A later answer on the same line supersedes the first; only it counts.
            await gold.save(
                case.reviewer_actor,
                assignment,
                saves[0].model_copy(
                    update={
                        "verdict": "partly",
                        "reasons": ["too_harsh"],
                        "supersedes_id": UUID(first["id"]),
                    }
                ),
                "save-again",
            )
            await db.flush()
        async with case.sessions() as db, db.begin():
            result = await GoldReviews(_service(db, case)).evaluation(case.admin_actor)
        assert result["gold"]["lines"] == 3
        assert result["gold"]["calls"] == 1
        assert result["gold"]["calls_with_brain4"] == 1
        acceptance = result["classic_acceptance"]
        assert (acceptance["agree"], acceptance["partly"], acceptance["disagree"]) == (0, 1, 1)
        assert acceptance["skipped"] == 1
        assert acceptance["reasons"] == {"too_harsh": 1, "too_generous": 1}
        dims = {item["id"]: item for item in result["dimensions"]}
        # The reviewer said next steps deserved 45: Brain 4.0's 2 lands on that band,
        # today's 80 does not.
        assert dims["D18"]["brain4"]["exact"] == 1.0
        assert dims["D18"]["classic"]["exact"] == 0.0
        # Active listening now only says "too harsh": Brain 4.0's 4 is today's band.
        assert dims["D04"]["brain4"]["directions"] == 1
        assert dims["D04"]["brain4"]["direction_right"] == 0.0
        assert dims["D18"]["readiness"]["state"] == "needs_data"
        assert NOTE not in json.dumps(result)

    run(exercise())


def test_gold_evaluation_route_is_admin_only(brain4_case) -> None:
    import httpx

    from tests.database.reviewer_http_support import account_token, app_for, settings_for

    case, _, _ = brain4_case

    async def exercise():
        settings = settings_for(case)
        transport = httpx.ASGITransport(app=app_for(case, settings))
        async with httpx.AsyncClient(transport=transport, base_url="https://admin.test") as anyone:
            denied = await anyone.get("/v1/admin/conversation/gold-evaluation")
            assert denied.status_code in (401, 403)
        token = await account_token(case, settings, case.admin_actor.person_id)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://admin.test",
            cookies={settings.session_cookie_name: token},
        ) as admin:
            answer = await admin.get("/v1/admin/conversation/gold-evaluation")
            assert answer.status_code == 200, answer.text
            body = answer.json()
            assert body["version"] == "brain4-eval/1"
            assert len(body["dimensions"]) == 18
            assert NOTE not in answer.text

    run(exercise())


def test_gold_calls_get_a_shadow_read_that_the_evaluation_counts(brain4_case) -> None:
    from datetime import UTC, datetime

    from ac_platform.conversation_intelligence import brain4_eval, brain4_shadow
    from ac_platform.conversation_intelligence.brain4_models import ConversationBrain4Review

    case, _, review = brain4_case

    async def exercise():
        now = datetime.now(UTC)
        async with case.sessions() as db:
            pointer = await db.get(ConversationPointerReview, review)
            found = await db.run_sync(
                lambda sync: brain4_shadow.gold_reports(sync.connection(), now, 10)
            )
        assert [item["draft_id"] for item in found] == [pointer.report_draft_id]
        block = brain4_block(3)
        async with case.sessions() as db, db.begin():
            db.add(
                ConversationBrain4Review(
                    id=uuid4(),
                    tenant_id=pointer.tenant_id,
                    recording_id=pointer.recording_id,
                    run_id=pointer.run_id,
                    report_draft_id=pointer.report_draft_id,
                    source_sha256=pointer.source_sha256,
                    transcript_revision=pointer.transcript_revision,
                    version=brain4.VERSION,
                    rubric_sha256=brain4.RUBRIC_SHA256,
                    model_id="fictional-offline",
                    prompt_sha256="d" * 64,
                    state="saved",
                    payload=block,
                    payload_sha256=brain4.payload_sha256(block),
                    trigger="auto",
                    created_by="fictional-test",
                    created_at=now,
                    finished_at=now,
                )
            )
        async with case.sessions() as db:
            data = await brain4_eval.load(db)
            again = await db.run_sync(
                lambda sync: brain4_shadow.gold_reports(sync.connection(), now, 10)
            )
        # The review's own block first, then the shadow read: two runs of one call.
        assert [run["dimensions"][-1]["rating"] for run in data.brain4[str(review)]] == [2, 3]
        assert again == []

    run(exercise())
