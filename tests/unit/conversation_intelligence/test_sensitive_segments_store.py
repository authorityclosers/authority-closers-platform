"""Generation uses fictional C2 text; persisted facts contain references only."""

from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence.guest_models import ConversationProcessingPrincipal
from ac_platform.conversation_intelligence.sensitive_segment_models import (
    ConversationSensitiveSegmentMark,
)
from ac_platform.conversation_intelligence.sensitive_segments_store import (
    SensitiveSegmentInvalid,
    SensitiveSegmentRevisionUnknown,
    SensitiveSegmentsStore,
    withheld_plan_for,
)
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Membership
from tests.unit.conversation_intelligence.test_sensitive_segments_loader import add_c2
from tests.unit.conversation_intelligence.test_sensitive_segments_loader import state as state
from tests.unit.http.test_platform_sensitive_segments import OTHER_REVISION, REVISION
from tests.unit.http.test_platform_sensitive_segments import marks_state as marks_state
from tests.unit.http.test_workspaces import HttpDatabase
from tests.unit.http.test_workspaces import workspace_state as workspace_state


def principal(state):
    person_id = uuid4()
    with Session(state.engine) as db, db.begin():
        db.add(Person(id=person_id, email=f"processing-{person_id}@example.test"))
        db.flush()
        db.add(Membership(tenant_id=state.tenants["Alpha"], person_id=person_id, role="learner"))
        db.flush()
        db.add(
            ConversationProcessingPrincipal(
                id=uuid4(),
                tenant_id=state.tenants["Alpha"],
                person_id=person_id,
                operator_reference="AUT-916 fictional",
                created_at=datetime.now(UTC),
            )
        )
    return person_id


@pytest.mark.asyncio
async def test_generation_marks_and_audits_once_per_category_and_withholds(state):
    actor_id = principal(state)
    add_c2(
        state,
        state.recording,
        OTHER_REVISION,
        {
            "s3": "Fictional cash only off the books tax evasion example.",
        },
    )
    with Session(state.engine) as db, db.begin():
        database = cast(Any, HttpDatabase(db))
        store = SensitiveSegmentsStore(database)
        rows = await store.mark_generation(
            recording_id=state.recording,
            transcript_revision=OTHER_REVISION,
        )
        assert {r.category for r in rows} == {"SENSITIVE_FINANCIAL", "SENSITIVE_LEGAL"}
        assert all(r.source == "generation" and r.actor_person_id == actor_id for r in rows)
        assert all(r.reason_ref.startswith("sensitive_terms_v1:") for r in rows)
        assert (
            await store.mark_generation(
                recording_id=state.recording,
                transcript_revision=OTHER_REVISION,
                reason_prefix="AUT-524 census ",
            )
            == ()
        )
        audits = db.scalars(
            select(AuditEvent).where(AuditEvent.id.in_([r.audit_event_id for r in rows]))
        ).all()
        assert len(audits) == 2
        assert all(
            a.session_id is None and a.action == "conversation.sensitive_segment.mark"
            for a in audits
        )
        assert all(a.actor_person_id == actor_id for a in audits)
        plan = await withheld_plan_for(
            database, recording_id=state.recording, served_revisions=(OTHER_REVISION,)
        )
        assert plan.segment_ids == {"s3"}


@pytest.mark.asyncio
async def test_generation_no_hit_writes_nothing_and_unknown_revision_is_refused(state):
    with Session(state.engine) as db, db.begin():
        store = SensitiveSegmentsStore(cast(Any, HttpDatabase(db)))
        before = tuple(db.scalars(select(AuditEvent.id)))
        assert (
            await store.mark_generation(recording_id=state.recording, transcript_revision=REVISION)
            == ()
        )
        assert tuple(db.scalars(select(AuditEvent.id))) == before
        assert not db.scalars(select(ConversationSensitiveSegmentMark)).all()
        with pytest.raises(SensitiveSegmentRevisionUnknown):
            await store.mark_generation(recording_id=state.recording, transcript_revision="unknown")


@pytest.mark.asyncio
async def test_generation_respects_active_marks_and_operator_releases_by_revision(state):
    principal(state)
    add_c2(
        state, state.recording, OTHER_REVISION, {"s3": "Fictional cash only tax evasion example."}
    )
    with Session(state.engine) as db, db.begin():
        store = SensitiveSegmentsStore(cast(Any, HttpDatabase(db)))
        actor = ActorContext(state.person, state.session, state.tenants["Alpha"])
        (mark,) = await store.mark(
            actor,
            recording_id=state.recording,
            transcript_revision=OTHER_REVISION,
            segments=[("s3", "SENSITIVE_FINANCIAL")],
            reason_ref="AUT-916 fictional",
            idempotency_key="operator-mark",
        )
        rows = await store.mark_generation(
            recording_id=state.recording,
            transcript_revision=OTHER_REVISION,
        )
        assert [r.category for r in rows] == ["SENSITIVE_LEGAL"]
        for row in (mark, *rows):
            await store.release(
                actor, mark_id=row.id, reason_ref="AUT-916 release", idempotency_key=str(row.id)
            )
        assert (
            await store.mark_generation(
                recording_id=state.recording,
                transcript_revision=OTHER_REVISION,
            )
            == ()
        )
        assert (
            await withheld_plan_for(cast(Any, HttpDatabase(db)), recording_id=state.recording)
        ).empty


@pytest.mark.asyncio
async def test_generation_missing_principal_and_detector_failure_append_nothing(state, monkeypatch):
    add_c2(state, state.recording, OTHER_REVISION, {"s3": "Fictional cash only example."})
    with Session(state.engine) as db, db.begin():
        store = SensitiveSegmentsStore(cast(Any, HttpDatabase(db)))
        with pytest.raises(SensitiveSegmentInvalid, match="principal"):
            await store.mark_generation(
                recording_id=state.recording, transcript_revision=OTHER_REVISION
            )

        def broken(_segments):
            raise RuntimeError("fictional detector failure")

        monkeypatch.setattr(
            "ac_platform.conversation_intelligence.sensitive_segments_store.detect_sensitive_terms",
            broken,
        )
        with pytest.raises(RuntimeError):
            await store.mark_generation(
                recording_id=state.recording, transcript_revision=OTHER_REVISION
            )
        assert not db.scalars(select(ConversationSensitiveSegmentMark)).all()
