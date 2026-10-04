"""Fictional organisation activity: role scope, privacy fences and fixed SQL cost."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionUsage as Usage,
)
from ac_platform.conversation_intelligence.canary_models import ConversationCanarySubmission
from ac_platform.conversation_intelligence.guest_models import (
    ConversationGuestSubmission,
    ConversationProcessingLease,
    ConversationProcessingPrincipal,
)
from ac_platform.conversation_intelligence.models import (
    ConversationPermission,
    ConversationProcessingPlan,
    ConversationRecording,
    ConversationReportDraft,
    ConversationRun,
)
from ac_platform.conversation_intelligence.submission_label_models import (
    ConversationSubmissionLabelRevision,
)
from ac_platform.identity.models import Person
from ac_platform.organisations import activity as activity_module
from ac_platform.outbox.models import Job
from ac_platform.tenancy.models import Membership
from tests.unit.http.test_organisation import call, state  # noqa: F401
from tests.unit.http.test_workspaces import OTHER_TOKEN, TOKEN, workspace_state  # noqa: F401


def seed_call(
    db: Session,
    tenant: UUID,
    owner: UUID,
    *,
    created_at: datetime,
    seconds: int = 90,
    recording_state: str = "ready",
    plan_state: str | None = None,
    report: bool = False,
    label: str | None = None,
) -> UUID:
    """Insert one direct account upload the way the acquisition services leave it."""
    principal = db.scalar(
        select(ConversationProcessingPrincipal).where(
            ConversationProcessingPrincipal.tenant_id == tenant
        )
    )
    if principal is None:
        processing = uuid4()
        db.add(Person(id=processing, display_name="Sales Xray processing", status="active"))
        db.flush()
        db.add(Membership(tenant_id=tenant, person_id=processing, role="processing"))
        db.flush()
        principal = ConversationProcessingPrincipal(
            id=uuid4(),
            tenant_id=tenant,
            person_id=processing,
            operator_reference="fictional",
            created_at=created_at,
        )
        db.add(principal)
        db.flush()
    submission, usage, lease, permission, recording = (uuid4() for _ in range(5))
    source = uuid4().hex * 2
    binding = dict(tenant_id=tenant, person_id=principal.person_id)
    db.add(
        Usage(
            id=usage,
            tenant_id=tenant,
            person_id=owner,
            submission_id=submission,
            source_sha256=source,
            duration_evidence_sha256="b" * 64,
            reserved_seconds=seconds,
            policy_revision="fictional",
            created_at=created_at,
        )
    )
    db.add(
        ConversationPermission(
            id=permission,
            **binding,
            source_sha256=source,
            provider="local",
            permission_reference="fictional",
            retention_reference="fictional",
            created_at=created_at,
            expires_at=created_at + timedelta(days=1),
            retention_until=created_at + timedelta(days=365),
        )
    )
    db.flush()
    db.add(
        ConversationProcessingLease(
            id=lease,
            principal_id=principal.id,
            **binding,
            usage_id=usage,
            created_at=created_at,
            expires_at=created_at + timedelta(hours=1),
        )
    )
    db.add(
        ConversationRecording(
            id=recording,
            **binding,
            permission_id=permission,
            request_key=str(submission),
            intent_sha256="1" * 64,
            source_sha256=source,
            source_bytes=1024,
            content_type="audio/mpeg",
            source_revision=1,
            generation=1,
            state=recording_state,
            created_at=created_at,
        )
    )
    db.flush()
    db.add(
        ConversationGuestSubmission(
            **binding,
            submission_id=submission,
            recording_id=recording,
            processing_lease_id=lease,
            usage_id=usage,
            source_sha256=source,
            created_at=created_at,
        )
    )
    db.flush()
    if plan_state is not None:
        db.add(
            ConversationProcessingPlan(
                id=uuid4(),
                **binding,
                recording_id=recording,
                processing_lease_id=lease,
                generation=1,
                plan_sha256="a" * 64,
                manifest={},
                state=plan_state,
                progress={},
                next_check_at=created_at,
                created_at=created_at,
                expires_at=created_at + timedelta(hours=1),
            )
        )
    if report:
        job, run = uuid4(), uuid4()
        db.add(Job(id=job, tenant_id=tenant, kind="fictional", dedupe_key=str(job), payload={}))
        db.flush()
        db.add(
            ConversationRun(
                id=run,
                **binding,
                recording_id=recording,
                request_key=str(run),
                intent_sha256="2" * 64,
                recipe_revision="fictional",
                generation=1,
                state="completed",
                job_id=job,
                created_at=created_at,
            )
        )
        db.flush()
        db.add(
            ConversationReportDraft(
                id=uuid4(),
                **binding,
                recording_id=recording,
                run_id=run,
                source_revision=1,
                source_sha256=source,
                report_sha256="3" * 64,
                transcript_sha256="4" * 64,
                profile_sha256="5" * 64,
                evidence_receipt_sha256="6" * 64,
                payload={},
                transcript={},
                evidence_receipt={},
                created_at=created_at,
            )
        )
    if label is not None:
        db.add(
            ConversationSubmissionLabelRevision(
                id=uuid4(),
                tenant_id=tenant,
                submission_id=submission,
                revision=1,
                display_name=label,
                actor_person_id=owner,
                created_at=created_at,
            )
        )
    db.flush()
    return submission


@pytest.fixture
def calls(state):  # noqa: F811
    now = datetime.now(UTC)
    with Session(state.engine) as db, db.begin():
        # The member also uploads in Personal; that call must stay private.
        db.add(Membership(tenant_id=state.tenants["Beta"], person_id=state.member, role="learner"))
        db.flush()
        state.calls = dict(
            reported=seed_call(
                db,
                state.tenant,
                state.member,
                created_at=now - timedelta(hours=3),
                report=True,
                label="Fictional discovery call",
            ),
            held=seed_call(
                db,
                state.tenant,
                state.other,
                created_at=now - timedelta(hours=2),
                seconds=30,
                plan_state="held",
            ),
            fresh=seed_call(db, state.tenant, state.member, created_at=now - timedelta(hours=1)),
            old=seed_call(db, state.tenant, state.member, created_at=now - timedelta(days=40)),
            deleted=seed_call(
                db, state.tenant, state.member, created_at=now, recording_state="deleted"
            ),
            personal=seed_call(db, state.tenants["Beta"], state.member, created_at=now),
        )
    return state


async def test_owner_and_admin_see_every_member_and_call(calls):
    for session in (TOKEN, OTHER_TOKEN):
        response = await call(calls, path="/activity", token=session)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "private, no-store"
        body = response.json()
        ids = calls.calls
        assert [row["id"] for row in body["calls"]] == [
            str(ids[name]) for name in ("fresh", "held", "reported")
        ]
        fresh, held, reported = body["calls"]
        assert reported == {
            "id": str(ids["reported"]),
            "owner_person_id": str(calls.member),
            "owner_name": "Fictional Rep",
            "label": "Fictional discovery call",
            "created_at": reported["created_at"],
            "duration_seconds": 90,
            "state": "report_ready",
            "has_report": True,
        }
        assert held["owner_person_id"] == str(calls.other) and held["state"] == "held"
        assert "@" in held["owner_name"] and "***" in held["owner_name"]
        assert (fresh["state"], fresh["has_report"], fresh["label"]) == ("ready", False, None)
        members = {row["person_id"]: row for row in body["members"]}
        # The processing principal's membership is not a person on the team.
        assert set(members) == {str(calls.person), str(calls.other), str(calls.member)}
        assert members[str(calls.person)] == {
            "person_id": str(calls.person),
            "calls": 0,
            "minutes": 0.0,
            "reports_ready": 0,
            "last_call_at": None,
        }
        rep = members[str(calls.member)]
        # Minutes and calls are the usage receipts, so a deleted call still counts.
        assert (rep["calls"], rep["minutes"], rep["reports_ready"]) == (3, 4.5, 1)
        assert rep["last_call_at"] is not None
        assert members[str(calls.other)]["minutes"] == 0.5
        reps = {row["person_id"]: row for row in body["per_rep"]}
        assert reps == {
            str(calls.member): dict(
                person_id=str(calls.member),
                name="Fictional Rep",
                calls=2,
                recorded_minutes=3.0,
                reports_ready=1,
            ),
            str(calls.other): dict(
                person_id=str(calls.other),
                name=held["owner_name"],
                calls=1,
                recorded_minutes=0.5,
                reports_ready=0,
            ),
        }
        assert sum(row["calls"] for row in body["per_day"]) == 3
        assert sum(row["reports_ready"] for row in body["per_day"]) == 1


async def test_member_sees_only_their_own_row_and_calls(calls):
    with Session(calls.engine) as db, db.begin():
        db.get(Membership, (calls.tenant, calls.other)).role = "member"
    body = (await call(calls, path="/activity", token=OTHER_TOKEN)).json()
    assert [row["person_id"] for row in body["members"]] == [str(calls.other)]
    assert [row["id"] for row in body["calls"]] == [str(calls.calls["held"])]
    assert body["per_rep"] == [
        dict(
            person_id=str(calls.other),
            name=body["calls"][0]["owner_name"],
            calls=1,
            recorded_minutes=0.5,
            reports_ready=0,
        )
    ]
    assert sum(row["calls"] for row in body["per_day"]) == 1


async def test_days_window_bounds_and_call_cap(calls, monkeypatch):
    wide = (await call(calls, path="/activity?days=90")).json()
    assert str(calls.calls["old"]) in [row["id"] for row in wide["calls"]]
    assert len(wide["calls"]) == 4
    for days in ("0", "91", "many"):
        assert (await call(calls, path=f"/activity?days={days}")).status_code == 422
    uncapped = (await call(calls, path="/activity")).json()
    monkeypatch.setattr(activity_module, "MAX_CALLS", 2)
    capped = (await call(calls, path="/activity")).json()
    assert [row["id"] for row in capped["calls"]] == [
        str(calls.calls[name]) for name in ("fresh", "held")
    ]
    assert {row["person_id"]: row["reports_ready"] for row in capped["members"]}[
        str(calls.member)
    ] == 1
    assert capped["per_day"] == uncapped["per_day"]
    assert capped["per_rep"] == uncapped["per_rep"]


async def test_empty_activity_has_empty_aggregates(state):  # noqa: F811
    body = (await call(state, path="/activity")).json()
    assert body["per_day"] == body["per_rep"] == body["calls"] == []
    assert len(body["members"]) == 3


async def test_utc_days_inclusive_cutoff_and_duration_rounding(state, monkeypatch):  # noqa: F811
    now = datetime.now(UTC).replace(microsecond=0)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(activity_module, "datetime", FixedDateTime)
    cutoff = now - timedelta(days=30)
    yesterday = now.replace(hour=0, minute=0, second=0) - timedelta(seconds=1)
    with Session(state.engine) as db, db.begin():
        seed_call(db, state.tenant, state.member, created_at=cutoff, seconds=60, report=True)
        seed_call(db, state.tenant, state.member, created_at=cutoff - timedelta(microseconds=1))
        seed_call(db, state.tenant, state.member, created_at=yesterday, seconds=2)
        seed_call(db, state.tenant, state.other, created_at=yesterday, seconds=2)
        seed_call(db, state.tenant, state.other, created_at=now, seconds=90, report=True)
    body = (await call(state, path="/activity")).json()
    assert body["per_day"] == [
        dict(date=cutoff.date().isoformat(), calls=1, recorded_minutes=1.0, reports_ready=1),
        dict(date=yesterday.date().isoformat(), calls=2, recorded_minutes=0.1, reports_ready=0),
        dict(date=now.date().isoformat(), calls=1, recorded_minutes=1.5, reports_ready=1),
    ]
    reps = {row["person_id"]: row for row in body["per_rep"]}
    assert (reps[str(state.member)]["calls"], reps[str(state.member)]["recorded_minutes"]) == (
        2,
        1.0,
    )
    assert (reps[str(state.other)]["calls"], reps[str(state.other)]["recorded_minutes"]) == (2, 1.5)
    narrow = (await call(state, path="/activity?days=1")).json()
    assert sum(row["calls"] for row in narrow["per_day"]) == 3


@pytest.mark.parametrize("fence", ["deleting", "revoked", "expired_retention", "canary"])
async def test_aggregates_keep_library_privacy_fences(calls, fence):
    with Session(calls.engine) as db, db.begin():
        recording = db.scalar(
            select(ConversationRecording).where(
                ConversationRecording.request_key == str(calls.calls["reported"])
            )
        )
        permission = db.get(ConversationPermission, recording.permission_id)
        if fence == "deleting":
            recording.state = fence
        elif fence == "revoked":
            permission.revoked_at = datetime.now(UTC)
        elif fence == "expired_retention":
            permission.retention_until = datetime.now(UTC) - timedelta(seconds=1)
        else:
            db.add(
                ConversationCanarySubmission(
                    tenant_id=calls.tenant,
                    submission_id=calls.calls["reported"],
                    environment="test",
                    fixture_sha256="a" * 64,
                    created_at=datetime.now(UTC),
                )
            )
    body = (await call(calls, path="/activity")).json()
    assert sum(row["calls"] for row in body["per_day"]) == 2
    assert sum(row["calls"] for row in body["per_rep"]) == 2
    assert sum(row["reports_ready"] for row in body["per_rep"]) == 0
    assert str(calls.calls["reported"]) not in {row["id"] for row in body["calls"]}


async def test_statement_count_does_not_grow_with_calls(calls):
    statements: list[str] = []

    def record(_connection, _cursor, statement, *_rest):
        statements.append(statement)

    event.listen(calls.engine, "before_cursor_execute", record)
    try:
        assert (await call(calls, path="/activity")).status_code == 200
        baseline = len(statements)
        with Session(calls.engine) as db, db.begin():
            for minute in range(1, 6):
                seed_call(
                    db,
                    calls.tenant,
                    calls.person,
                    created_at=datetime.now(UTC) - timedelta(minutes=minute),
                )
        statements.clear()
        response = await call(calls, path="/activity")
        assert len(response.json()["calls"]) == 8
        assert len(statements) == baseline
    finally:
        event.remove(calls.engine, "before_cursor_execute", record)
