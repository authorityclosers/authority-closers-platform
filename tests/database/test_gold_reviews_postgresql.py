"""Fictional full saved-call journey, append/supersede, isolation and erasure."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

from ac_platform.conversation_intelligence.application import (
    ConversationConflict,
    ConversationDenied,
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.gold_review_contracts import GoldSave
from ac_platform.conversation_intelligence.gold_review_job import assign_saved_reviews
from ac_platform.conversation_intelligence.gold_review_models import GoldAssignment, GoldRow
from ac_platform.conversation_intelligence.gold_reviews import GoldReviews
from ac_platform.conversation_intelligence.models import (
    ConversationRecording,
    ConversationReportDraft,
)
from ac_platform.conversation_intelligence.pointer_review_models import ConversationPointerReview
from ac_platform.tenancy.models import Membership
from tests.database.test_conversation_reviews_postgresql import (
    ReviewCase,
    _service,
    run,
)
from tests.database.test_conversation_reviews_postgresql import (
    postgres_harness as postgres_harness,
)
from tests.database.test_conversation_reviews_postgresql import (
    review_case as review_case,
)


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
                    "id": f"pointer-{i}",
                    "number": i,
                    "label": f"Skill {i}",
                    "status": "good",
                    "score": 72,
                    "what_happened": "The seller asked about timing.",
                    "evidence": [],
                    "how_to_improve": ["Ask who decides."],
                }
                for i in range(1, 28)
            ],
            "outcome": {"notes": ["The buyer will ask a colleague."]},
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
            created_at=case.prepared.state.now,
        )
        db.add(review)
        await db.flush()
        await GoldReviews(service).designate(
            case.admin_actor,
            "reviewer-" + case.reviewer_actor.person_id.hex + "@example.test",
            True,
        )
        assert (
            await assign_saved_reviews(db, case.operations_tenant_id, case.prepared.state.now) == 1
        )
        assert (
            await assign_saved_reviews(db, case.operations_tenant_id, case.prepared.state.now) == 0
        )
        assignment = await db.scalar(
            select(GoldAssignment).where(GoldAssignment.review_id == review.id)
        )
        return assignment.assignment_id, review.id


@pytest.fixture(scope="module")
def gold_case(review_case):
    assignment_id, review_id = run(prepare(review_case))
    return review_case, assignment_id, review_id


def test_reviewer_saves_exact_ai_as_immediate_append_only_gold(gold_case) -> None:
    case, assignment, review = gold_case

    async def exercise():
        async with case.sessions() as db, db.begin():
            # No learner membership is needed for this independent session.
            member = await db.get(
                Membership, (case.prepared.state.tenant_id, case.reviewer_actor.person_id)
            )
            member.status = "inactive"
            member.ended_at = case.prepared.state.now
            svc = GoldReviews(_service(db, case))
            view = await svc.get(case.reviewer_actor, assignment)
            assert (
                len(view["lines"]) == 29 and view["review_status"] == "ai_draft_not_dipak_reviewed"
            )
            intent = GoldSave(
                review_id=review,
                target="pointer-1",
                verdict="partly",
                opinion="Ask who makes the decision.",
            )
            first = await svc.save(case.reviewer_actor, assignment, intent, "first-save")
            assert await svc.save(case.reviewer_actor, assignment, intent, "first-save") == first
            changed = intent.model_copy(
                update={
                    "opinion": "Wait for the buyer to finish.",
                    "supersedes_id": UUID(first["id"]),
                }
            )
            second = await svc.save(case.reviewer_actor, assignment, changed, "second-save")
            assert second["supersedes_id"] == first["id"]
            assert (await db.get(GoldRow, UUID(first["id"]))).payload["opinion"] == intent.opinion
            assert len((await svc.rows(case.admin_actor))["items"]) == 2
            with pytest.raises(ConversationConflict):
                await svc.save(case.reviewer_actor, assignment, intent, "stale-tab")
            with pytest.raises(ConversationConflict):
                await svc.save(case.reviewer_actor, assignment, changed, "first-save")
            for target in ("final_call_outcome", "coaching"):
                await svc.save(
                    case.reviewer_actor,
                    assignment,
                    intent.model_copy(update={"target": target}),
                    target,
                )
            await db.flush()
        async with case.sessions() as db, db.begin():
            view = await GoldReviews(_service(db, case)).get(case.reviewer_actor, assignment)
            assert len(view["saved"]) == 3 and view["history_count"] == 4
            assert all(r["review_id"] == str(review) for r in view["saved"])

    run(exercise())


def test_reviewer_and_account_sessions_cannot_cross_assignments(gold_case) -> None:
    case, assignment, review = gold_case

    async def exercise():
        for actor in (
            case.source_actor,
            case.admin_actor,
            case.foreign_actor,
            case.other_reviewer_actor,
        ):
            async with case.sessions() as db, db.begin():
                svc = GoldReviews(_service(db, case))
                with pytest.raises((ConversationDenied, ConversationNotFound)):
                    await svc.get(actor, assignment)
                with pytest.raises((ConversationDenied, ConversationNotFound)):
                    await svc.save(
                        actor,
                        assignment,
                        GoldSave(
                            review_id=review, target="pointer-1", score=50, opinion="Fictional."
                        ),
                        "no",
                    )
        async with case.sessions() as db, db.begin():
            svc = GoldReviews(_service(db, case))
            with pytest.raises(ConversationConflict):
                await svc.save(
                    case.reviewer_actor,
                    assignment,
                    GoldSave(review_id=uuid4(), target="pointer-1", score=50, opinion="Fictional."),
                    "wrong-version",
                )

    run(exercise())


def test_history_refuses_rewrite_and_delete(gold_case) -> None:
    case, _, _ = gold_case

    async def exercise():
        for sql in (
            "UPDATE conversation_gold_rows SET payload = '{}'::json",
            "DELETE FROM conversation_gold_rows",
        ):
            with pytest.raises(DBAPIError):
                async with case.sessions() as db, db.begin():
                    await db.execute(text(sql))

    run(exercise())


def test_removing_standing_reviewer_revokes_the_assignments(gold_case) -> None:
    case, assignment, _ = gold_case

    async def exercise():
        async with case.sessions() as db, db.begin():
            svc = GoldReviews(_service(db, case))
            await svc.designate(
                case.admin_actor,
                "reviewer-" + case.reviewer_actor.person_id.hex + "@example.test",
                False,
            )
            with pytest.raises(ConversationDenied):
                await svc.get(case.reviewer_actor, assignment)
            await db.rollback()  # Keep the independent fixture's grant for erasure proof.

    run(exercise())


def test_reader_excludes_sandbox_and_serializes_duplicate_workers(gold_case) -> None:
    import asyncio

    from ac_platform.conversation_intelligence.synthetic_import_models import (
        ConversationSandboxOrganisation,
    )
    from ac_platform.tenancy.models import Organisation

    case, _, _ = gold_case

    async def exercise():
        async with case.sessions() as db, db.begin():
            svc = GoldReviews(_service(db, case))
            email = "reviewer-" + case.other_reviewer_actor.person_id.hex + "@example.test"
            await svc.designate(case.admin_actor, email, True)
        async with case.sessions() as db, db.begin():
            tenant = case.prepared.state.tenant_id
            if await db.get(Organisation, tenant) is None:
                db.add(
                    Organisation(
                        tenant_id=tenant,
                        creation_command_id=uuid4(),
                        domain_verification_token="fictional-" + "x" * 44,
                    )
                )
                await db.flush()
            db.add(
                ConversationSandboxOrganisation(
                    tenant_id=tenant,
                    approved_by_person_id=case.admin_actor.person_id,
                    approval_reference="fictional-sandbox",
                    created_at=case.prepared.state.now,
                )
            )
            await db.flush()
            assert (
                await assign_saved_reviews(db, case.operations_tenant_id, case.prepared.state.now)
                == 0
            )
            await db.rollback()

        async def worker():
            async with case.sessions() as db, db.begin():
                return await assign_saved_reviews(
                    db, case.operations_tenant_id, case.prepared.state.now
                )

        assert sum(await asyncio.gather(worker(), worker())) == 1
        async with case.sessions() as db:
            assert await db.scalar(select(func.count()).select_from(GoldAssignment)) == 2

    run(exercise())


def test_gold_http_mailbox_login_and_same_origin_save(gold_case) -> None:
    from urllib.parse import parse_qs, urlsplit

    import httpx

    from ac_platform.http.reviewer_auth import reviewer_cookie_name
    from tests.database.reviewer_http_support import (
        account_token,
        app_for,
        deliver,
        mail_worker,
        settings_for,
    )

    case, assignment, review = gold_case

    async def exercise():
        settings = settings_for(case)
        app = app_for(case, settings)
        worker, provider = mail_worker(case, settings)
        email = "reviewer-" + case.reviewer_actor.person_id.hex + "@example.test"
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://admin.test",
            headers={"origin": "https://admin.test"},
        ) as client:
            requested = await client.post("/v1/reviewer/auth/request", json={"email": email})
            assert requested.status_code == 202
            mail = await deliver(worker, provider, "reviewer-sign-in", email)
            token = parse_qs(urlsplit(str(mail.variables["action_link"])).fragment)["token"][0]
            verified = await client.post("/v1/reviewer/auth/verify", json={"token": token})
            assert verified.status_code == 200, verified.text
            assert reviewer_cookie_name(settings) in client.cookies
            assert (await client.get("/v1/me")).status_code == 401
            path = f"/v1/reviewer/review-assignments/{assignment}/gold"
            loaded = await client.get(path)
            assert loaded.status_code == 200, loaded.text
            assert len(loaded.json()["lines"]) == 29
            body = {
                "review_id": str(review),
                "target": "pointer-2",
                "verdict": "agree",
                "opinion": "The buyer understood the purpose.",
            }
            denied = await client.post(
                path,
                json=body,
                headers={"Origin": "https://learner.test", "Idempotency-Key": "bad-origin"},
            )
            assert denied.status_code == 403
            saved = await client.post(
                path, json=body, headers={"Idempotency-Key": "http-gold-save"}
            )
            assert saved.status_code == 201, saved.text
            assert saved.json()["review_id"] == str(review)
            assert (await client.get("/v1/admin/conversation/gold-rows")).status_code in (401, 403)
        token = await account_token(case, settings, case.admin_actor.person_id)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://admin.test",
            cookies={settings.session_cookie_name: token},
        ) as admin:
            assert (await admin.get("/v1/admin/conversation/gold-reviewers")).status_code == 200
            assert (await admin.get("/v1/admin/conversation/gold-rows")).status_code == 200
            assert (await admin.get(path)).status_code == 401

    run(exercise())


def test_owner_data_change_is_dry_run_idempotent_and_adds_no_learner_access(gold_case) -> None:
    import importlib.util
    from pathlib import Path

    from ac_platform.conversation_intelligence.gold_review_models import GoldReviewer
    from ac_platform.identity.models import Person

    case, _, _ = gold_case
    source = Path(__file__).resolve().parents[2] / "scripts/data-changes/designate-gold-reviewer.py"
    spec = importlib.util.spec_from_file_location("gold_change_test", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.REVIEWER = "fictional-gold-reviewer@example.test"
    module.APPROVER = "admin@authorityclosers.com"

    async def exercise():
        async with case.sessions() as db, db.begin():
            before = await db.scalar(select(func.count()).select_from(Membership))
            dry = await module.change(
                db, operations_tenant_id=case.operations_tenant_id, apply=False, create_person=True
            )
            assert not dry["before"]["person_exists"] and not dry["applied"]
            assert await db.scalar(select(Person).where(Person.email == module.REVIEWER)) is None
            applied = await module.change(
                db, operations_tenant_id=case.operations_tenant_id, apply=True, create_person=True
            )
            assert applied["applied"]
            person = await db.get(Person, UUID(applied["after"]["person_id"]))
            assert person.email_verified_at is None
            again = await module.change(
                db, operations_tenant_id=case.operations_tenant_id, apply=True, create_person=True
            )
            assert again["before"]["gold_reviewer"]
            assert again["after"]["person_id"] == str(person.id)
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(GoldReviewer)
                    .where(GoldReviewer.person_id == person.id)
                )
                == 1
            )
            assert await db.scalar(select(func.count()).select_from(Membership)) == before
            await db.rollback()

    run(exercise())


def test_canonical_pointer_erasure_removes_every_gold_save(gold_case) -> None:
    case, assignment, review = gold_case

    async def exercise():
        async with case.sessions() as db, db.begin():
            await db.execute(
                update(ConversationRecording)
                .where(ConversationRecording.id == case.prepared.recording_id)
                .values(state="deleting")
            )
            await db.execute(
                update(ConversationPointerReview)
                .where(ConversationPointerReview.id == review)
                .values(payload=None, erased_at=case.prepared.state.now)
            )
        async with case.sessions() as db, db.begin():
            rows = (await db.scalars(select(GoldRow))).all()
            assert len(rows) >= 4 and all(
                r.payload is None and r.erased_at is not None for r in rows
            )
            assert await db.scalar(select(func.count()).select_from(GoldRow)) == len(rows)
            with pytest.raises(ConversationConflict):
                await GoldReviews(_service(db, case)).get(case.reviewer_actor, assignment)

    run(exercise())
