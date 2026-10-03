"""Withheld-plan loader, checkpoint guard and D7 refusal over SQLite (fictional text only)."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
)
from ac_platform.conversation_intelligence.models import ConversationCheckpoint
from ac_platform.conversation_intelligence.processing_plan import refuse_marked_rerun
from ac_platform.conversation_intelligence.sensitive_segment_models import (
    ConversationSensitiveSegmentMark,
)
from ac_platform.conversation_intelligence.sensitive_segments import (
    WITHHELD_MARKER,
    grams,
    shared_grams,
)
from ac_platform.conversation_intelligence.sensitive_segments_store import (
    marks_in_force,
    withheld_plan_for,
)
from tests.unit.http import test_platform_sensitive_segments as t1
from tests.unit.http.test_platform_sensitive_segments import (
    OTHER_REVISION,
    REVISION,
    seed_recording,
)
from tests.unit.http.test_platform_sensitive_segments import (
    marks_state as marks_state,
)
from tests.unit.http.test_workspaces import HttpDatabase
from tests.unit.http.test_workspaces import workspace_state as workspace_state

S3 = "The purple otter paid the lighthouse invoice on Tuesday evening"
S4 = "She said the lighthouse invoice on Tuesday was late"
S9 = "Our kettle whistles whenever the moon rises over the shed"
TEXTS = {"s1": "Thanks for joining the fictional demo today.", "s3": S3, "s4": S4, "s9": S9}


def _transcript(revision: str, texts: dict[str, str] = TEXTS) -> dict[str, Any]:
    return {
        "source_sha256": "0" * 64,
        "revision": revision,
        "timebase_id": "fictional-timebase",
        "segments": [
            {
                "id": sid,
                "speaker_id": "A",
                "start_ms": i * 1000,
                "end_ms": i * 1000 + 900,
                "text": t,
            }
            for i, (sid, t) in enumerate(texts.items())
        ],
    }


@pytest.fixture
def state(marks_state, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(t1, "_transcript", _transcript)
    marks_state.recording = seed_recording(marks_state, revision=REVISION)
    return marks_state


def _db(state) -> Any:
    return cast(Any, HttpDatabase(Session(state.engine)))


def insert_mark(
    state, recording_id: UUID, segment_id: str, *, revision: str = REVISION, release_of=None
) -> UUID:
    now = datetime.now(UTC)
    with Session(state.engine) as db, db.begin():
        tenant = state.tenants["Alpha"]
        prior = db.scalars(select(AuditEvent).where(AuditEvent.tenant_id == tenant)).all()
        audit = AuditEvent(
            id=uuid4(),
            tenant_id=tenant,
            sequence_no=len(prior) + 1,
            actor_person_id=state.person,
            actor_type="person",
            action="conversation.sensitive_segment.mark",
            resource_type="conversation_sensitive_segment_mark",
            payload={},
            reason="AUT-521 fixture",
            previous_hash="0" * 64,
            event_hash=sha256(str(len(prior)).encode()).hexdigest(),
        )
        db.add(audit)
        db.flush()
        row = ConversationSensitiveSegmentMark(
            id=uuid4(),
            tenant_id=tenant,
            recording_id=recording_id,
            transcript_revision=revision,
            segment_id=segment_id,
            category="SENSITIVE_FINANCIAL",
            action="release" if release_of else "mark",
            supersedes_mark_id=release_of,
            source="operator",
            actor_person_id=state.person,
            reason_ref="AUT-521 fixture",
            audit_event_id=audit.id,
            created_at=now,
        )
        db.add(row)
        db.flush()
        return cast(UUID, row.id)


def add_c2(state, recording_id: UUID, revision: str, texts: dict[str, str]) -> None:
    with Session(state.engine) as db, db.begin():
        db.add(
            ConversationCheckpoint(
                id=uuid4(),
                tenant_id=state.tenants["Alpha"],
                person_id=state.person,
                recording_id=recording_id,
                cache_key=sha256(f"{recording_id}:{revision}".encode()).hexdigest(),
                manifest_sha256="4" * 64,
                payload_sha256="5" * 64,
                stage="C2",
                payload=_transcript(revision, texts),
                created_at=datetime.now(UTC),
            )
        )


@pytest.mark.asyncio
async def test_plan_expands_to_neighbours_and_never_holds_text(state) -> None:
    assert (await withheld_plan_for(_db(state), recording_id=state.recording)).empty
    mark = insert_mark(state, state.recording, "s3")
    plan = await withheld_plan_for(
        _db(state), recording_id=state.recording, served_revisions=(REVISION,)
    )
    assert plan.segment_ids == {"s3", "s4"} and plan.grams == grams(S3)
    assert S3 not in repr(plan)  # IDs and normalised grams only, never the sentence
    assert await marks_in_force(_db(state), recording_id=state.recording)
    with pytest.raises(ConversationConflict) as refused:
        await refuse_marked_rerun(_db(state), state.recording)
    assert "purple" not in str(refused.value) and refused.value.status == 409

    insert_mark(state, state.recording, "s3", release_of=mark)
    assert (await withheld_plan_for(_db(state), recording_id=state.recording)).empty
    assert not await marks_in_force(_db(state), recording_id=state.recording)
    await refuse_marked_rerun(_db(state), state.recording)


@pytest.mark.asyncio
async def test_duplicate_recording_and_other_revision(state) -> None:
    insert_mark(state, state.recording, "s3")
    duplicate = seed_recording(state, revision=REVISION)
    plan = await withheld_plan_for(_db(state), recording_id=duplicate, served_revisions=(REVISION,))
    assert plan.segment_ids == {"s3", "s4"} and plan.grams == grams(S3)

    renamed = {"t1": "Unrelated fictional opening line.", "t3": S3, "t9": S9}
    add_c2(state, state.recording, OTHER_REVISION, renamed)
    other = await withheld_plan_for(
        _db(state), recording_id=state.recording, served_revisions=(OTHER_REVISION,)
    )
    assert other.segment_ids == {"t3"} and other.grams == grams(S3)  # grams only, by overlap


@pytest.mark.asyncio
async def test_checkpoints_are_withheld_and_unmarked_reads_are_identical(state) -> None:
    app = ConversationApplication(_db(state))
    before = await app.render_checkpoints(
        state.recording, tenant_id=state.tenants["Alpha"], person_id=state.person
    )
    assert shared_grams(before, grams(S3)) == len(grams(S3))
    again = await app.render_checkpoints(
        state.recording, tenant_id=state.tenants["Alpha"], person_id=state.person
    )
    assert again == before

    insert_mark(state, state.recording, "s3")
    guarded = await app.render_checkpoints(
        state.recording, tenant_id=state.tenants["Alpha"], person_id=state.person
    )
    texts = [segment["text"] for segment in guarded[0]["payload"]["segments"]]
    assert texts == [TEXTS["s1"], WITHHELD_MARKER, WITHHELD_MARKER, S9]
    assert [c["id"] for c in guarded] == [c["id"] for c in before]
    assert shared_grams(guarded, grams(S3)) == 0
