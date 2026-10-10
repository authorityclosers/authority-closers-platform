"""Attempt lineage is bounded and source/input/effect evidence cannot drift."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence.application import ConversationConflict
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.models import ConversationInferenceTask
from ac_platform.conversation_intelligence.safe_stage_retry import (
    predecessor_id,
    require_retry_predecessor,
)
from tests.database.test_conversation_postgresql import run


def fixture():
    recording = SimpleNamespace(tenant_id=uuid4(), person_id=uuid4(), id=uuid4(), generation=1)
    tasks, jobs = {}, {}

    def add(previous=None, *, stage="C2", config=None):
        run_id, job_id = uuid4(), uuid4()
        intent = {
            "checkpoint": {
                "binding": {},
                "stage": stage,
                "revision": "fictional",
                "config": config or {},
                "parents": [],
                "replicate": "" if previous is None else f"retry:{previous.run_id}",
            }
        }
        task = SimpleNamespace(
            run_id=run_id,
            job_id=job_id,
            tenant_id=recording.tenant_id,
            person_id=recording.person_id,
            recording_id=recording.id,
            generation=1,
            erased_at=None,
            state="failed",
            checkpoint_id=None,
            intent=intent,
            intent_sha256=content_hash(intent),
            stage=stage,
        )
        job = SimpleNamespace(
            tenant_id=recording.tenant_id,
            status="dead_letter",
            lease_token=None,
            leased_until=None,
            external_side_effect=True,
            kind="conversation.infer_provider.v1",
            payload={"run_id": str(run_id)},
            provider_receipt=None,
            dispatch_started_at=None,
        )
        tasks[run_id], jobs[job_id] = task, job
        return task

    db = AsyncMock()
    db.get.side_effect = lambda model, identifier: (
        tasks if model is ConversationInferenceTask else jobs
    ).get(identifier)
    return recording, db, add, jobs


def test_three_attempts_are_the_technical_ceiling_and_cycles_are_rejected():
    recording, db, add, jobs = fixture()
    first = add()
    second = add(first)
    third = add(second)
    assert (
        run(require_retry_predecessor(db, recording, second.run_id, now=datetime.now(UTC)))
        is second
    )
    with pytest.raises(ConversationConflict, match="retry limit"):
        run(require_retry_predecessor(db, recording, third.run_id, now=datetime.now(UTC)))
    first.intent["checkpoint"]["replicate"] = f"retry:{first.run_id}"
    first.intent_sha256 = content_hash(first.intent)
    with pytest.raises(ConversationConflict, match="retry limit"):
        run(require_retry_predecessor(db, recording, first.run_id, now=datetime.now(UTC)))


@pytest.mark.parametrize(
    "field,value",
    [
        ("state", "running"),
        ("generation", 2),
        ("intent_sha256", "f" * 64),
        ("checkpoint_id", uuid4()),
        ("person_id", uuid4()),
    ],
)
def test_retries_require_terminal_exact_owned_intent(field, value):
    recording, db, add, jobs = fixture()
    task = add()
    setattr(task, field, value)
    with pytest.raises(ConversationConflict, match="safely retryable"):
        run(require_retry_predecessor(db, recording, task.run_id, now=datetime.now(UTC)))


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "leased"),
        ("lease_token", uuid4()),
        ("provider_receipt", {"fixture": True}),
        ("kind", "other.worker.v1"),
    ],
)
def test_retries_require_reconciled_job_without_a_returned_receipt(field, value):
    recording, db, add, jobs = fixture()
    task = add()
    setattr(jobs[task.job_id], field, value)
    with pytest.raises(ConversationConflict, match="reconciliation"):
        run(require_retry_predecessor(db, recording, task.run_id, now=datetime.now(UTC)))


@pytest.mark.parametrize("change", ["stage", "input"])
def test_retry_lineage_cannot_change_stage_or_input(change):
    recording, db, add, jobs = fixture()
    first = add()
    second = add(first, stage="C4" if change == "stage" else "C2", config={"different": change})
    with pytest.raises(ConversationConflict, match="original stage input"):
        run(require_retry_predecessor(db, recording, second.run_id, now=datetime.now(UTC)))


@pytest.mark.parametrize("replicate", ["unapproved", "retry:invalid", 123])
def test_unapproved_replicates_do_not_create_retry_authority(replicate):
    with pytest.raises(ConversationConflict):
        predecessor_id({"replicate": replicate})
