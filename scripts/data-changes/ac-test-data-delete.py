"""Exact owner-approved test-data erasure; dry-run unless --apply.

No raw SQL mutations. Submission acquisition usage and guest bindings are retained.
Storage erasure is irreversible even if the enclosing DB transaction rolls back;
retry the identical command after resolving a failure. Snapshot before applying.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.application.settings import get_settings
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import append_audit_event
from ac_platform.conversation_intelligence.acquisition_models import ConversationAcquisitionUsage
from ac_platform.conversation_intelligence.application import DELETE_JOB, ConversationApplication
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.models import (
    ConversationInferenceTask,
    ConversationRecording,
    ConversationReportDraft,
    ConversationRun,
)
from ac_platform.conversation_intelligence.processing_actor import ProcessingActor
from ac_platform.conversation_intelligence.source_objects import release_source_object
from ac_platform.conversation_intelligence.storage import (
    ObjectKey,
    ObjectKind,
    PrivateLocalRecordingStorage,
)
from ac_platform.conversation_intelligence.worker import _FencedExecutor
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.lead_desk import deletion
from ac_platform.lead_desk.models import Lead, LeadEvent
from ac_platform.outbox.models import Job
from ac_platform.outbox.repository import (
    RecoveryStateRepository,
    build_job_take_statement,
)

TENANT = UUID("02150758-5316-46bb-975b-4cd0f0041df2")
PREFIX = "f84c7afb"
WORK = "ac-test-delete-20261029"
APPROVER = "owner, orchestrator chat 29 Oct 2026"
DIGEST = "4daf10db94981810584a00f0bc2810be88c5bb3d53cbe65f432167065abbe291"
ACTION = "data_change.ac_test_data_deleted"
KINDS = ("recording", "report_draft", "submission", "test_lead")


def load_manifest(path: Path) -> dict[str, set[UUID]]:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != DIGEST:
        raise ValueError("refused_manifest")
    result: dict[str, set[UUID]] = {kind: set() for kind in KINDS}
    for line in raw.decode().splitlines():
        kind, identifier, person, _state, _date = line.split("|")
        if kind not in result or person != ("?" if kind == "test_lead" else PREFIX):
            raise ValueError("refused_manifest")
        result[kind].add(UUID(identifier))
    if [len(result[k]) for k in KINDS] != [69, 64, 115, 7]:
        raise ValueError("refused_manifest")
    return result


async def execute(sessions, wanted, *, apply=False, storage=None, tenant=TENANT, person=None):
    # Match worker lock order: storage fence, transaction, recovery fence, rows.
    if apply and storage is not None:
        async with _FencedExecutor(storage.root) as fenced:
            return await _execute(
                sessions,
                wanted,
                apply=apply,
                storage=storage,
                tenant=tenant,
                person=person,
                fenced=fenced,
            )
    return await _execute(
        sessions, wanted, apply=apply, storage=storage, tenant=tenant, person=person
    )


async def _execute(
    sessions, wanted, *, apply=False, storage=None, tenant=TENANT, person=None, fenced=None
):
    """Internal port accepts synthetic boundaries for PostgreSQL fixtures; CLI pins approval."""
    async with sessions() as db, db.begin():
        if apply:
            recovery = await RecoveryStateRepository(db).require_ready(lock=True, shared_lock=True)
        # Serialize this command, including replay, on its existing tenant row.
        from ac_platform.tenancy.models import Tenant

        await db.scalar(select(Tenant).where(Tenant.id == tenant).with_for_update())
        if person is None:
            people = list(await db.scalars(select(Person.id)))
            matches = [p for p in people if str(p).startswith(PREFIX)]
            if len(matches) != 1:
                raise ValueError("refused_person")
            person = matches[0]
        replay = await db.scalar(
            select(AuditEvent).where(
                AuditEvent.tenant_id == tenant,
                AuditEvent.action == ACTION,
                AuditEvent.resource_id == WORK,
            )
        )
        rows = {}
        models = dict(
            recording=ConversationRecording,
            report_draft=ConversationReportDraft,
            submission=ConversationAcquisitionUsage,
            test_lead=Lead,
        )
        for kind, model in models.items():
            column = model.submission_id if kind == "submission" else model.id
            found = list(
                await db.scalars(
                    select(model).where(column.in_(wanted[kind])).order_by(column).with_for_update()
                )
            )
            ids = {getattr(row, "submission_id" if kind == "submission" else "id") for row in found}
            if ids != wanted[kind] and not (kind == "test_lead" and replay):
                raise ValueError("refused_missing_ids")
            for row in found:
                owner = row.created_by_person_id if kind == "test_lead" else row.person_id
                if row.tenant_id != tenant:
                    raise ValueError("refused_tenant")
                if owner != person:
                    raise ValueError("refused_person")
            rows[kind] = found
        # Validate every dependent report/binding before the first storage side effect.
        related = list(
            await db.scalars(
                select(ConversationReportDraft)
                .where(ConversationReportDraft.recording_id.in_(wanted["recording"]))
                .with_for_update()
            )
        )
        if any(r.id not in wanted["report_draft"] for r in related):
            raise ValueError("refused_unlisted_report")
        if any(r.recording_id not in wanted["recording"] for r in rows["report_draft"]):
            raise ValueError("refused_unlisted_recording")
        links = list(
            await db.scalars(
                select(ConversationGuestSubmission)
                .where(
                    ConversationGuestSubmission.recording_id.in_(wanted["recording"])
                    | ConversationGuestSubmission.submission_id.in_(wanted["submission"])
                )
                .with_for_update()
            )
        )
        for link in links:
            if link.tenant_id != tenant or link.person_id != person:
                raise ValueError("refused_submission_owner")
            if (
                link.recording_id in wanted["recording"]
                and link.submission_id not in wanted["submission"]
            ):
                raise ValueError("refused_unlisted_submission")
        leads = rows["test_lead"]
        # The app removes lead history. Refuse any call event rather than erase it.
        if await db.scalar(
            select(LeadEvent.id)
            .where(LeadEvent.lead_id.in_(wanted["test_lead"]), LeadEvent.kind == "call")
            .limit(1)
        ):
            raise ValueError("refused_call_event")
        actors = {}
        for recording in rows["recording"]:
            if recording.state == "deleted":
                continue
            link = next((s for s in links if s.recording_id == recording.id), None)
            if link is not None:
                actors[recording.id] = ProcessingActor(person, tenant, link.processing_lease_id)
            else:
                session = await db.scalar(
                    select(IdentitySession)
                    .where(
                        IdentitySession.person_id == person,
                        IdentitySession.selected_tenant_id == tenant,
                    )
                    .order_by(IdentitySession.id)
                    .limit(1)
                )
                if session is None:
                    raise ValueError("refused_actor_binding")
                actors[recording.id] = ActorContext(person, session.id, tenant)
        before = {
            "recording": sum(r.state != "deleted" for r in rows["recording"]),
            "report_draft": sum(r.erased_at is None for r in rows["report_draft"]),
            "submission": len(rows["submission"]),
            "test_lead": len(leads),
        }
        result = {
            "before": before,
            "after": dict(before),
            "retained_submissions": len(rows["submission"]),
        }
        if not apply:
            return result
        if replay:
            if before["recording"] or before["report_draft"] or before["test_lead"]:
                raise ValueError("refused_replay_drift")
            return result
        if storage is None:
            raise ValueError("refused_storage")
        app = ConversationApplication(db)
        for recording in rows["recording"]:
            if recording.state == "deleted":
                continue
            await app._request_owned_deletion(
                actors[recording.id],
                recording,
                key=f"{WORK}:{recording.id}",
                now=datetime.now(UTC),
            )
            await db.flush()
            job = await db.scalar(
                select(Job)
                .where(
                    Job.dedupe_key == f"conversation:erase:{recording.id}:{recording.generation}",
                    Job.tenant_id == tenant,
                    Job.kind == DELETE_JOB,
                )
                .with_for_update()
            )
            if job is None:
                raise ValueError("refused_erasure_job")
            from uuid import uuid4

            token = uuid4()
            taken = await db.execute(
                build_job_take_statement(
                    job_id=job.id,
                    lease_token=token,
                    lease_for=timedelta(minutes=15),
                    recovery_generation=recovery.generation,
                    dialect="postgresql",
                    kinds=(DELETE_JOB,),
                )
            )
            if taken.rowcount != 1:
                raise ValueError("refused_erasure_lease")
            runs = list(
                await db.scalars(
                    select(ConversationRun).where(ConversationRun.recording_id == recording.id)
                )
            )
            tasks = list(
                await db.scalars(
                    select(ConversationInferenceTask).where(
                        ConversationInferenceTask.recording_id == recording.id
                    )
                )
            )
            expected = (
                ObjectKey(tenant, recording.id, recording.id, ObjectKind.SOURCE_AUDIO),
                *(ObjectKey(tenant, recording.id, r.id, ObjectKind.SIGNAL_FEATURES) for r in runs),
                *(
                    ObjectKey(tenant, recording.id, t.run_id, ObjectKind.PROVIDER_RESPONSE)
                    for t in tasks
                ),
            )
            receipt = await fenced.run(
                storage.delete_recording, tenant, recording.id, expected_keys=expected
            )
            if not receipt.local_inventory_empty:
                raise ValueError("refused_storage_inventory")
            await release_source_object(db, recording, storage, datetime.now(UTC))
            await app.finish_erasure(
                job_id=job.id, lease_token=token, recovery_generation=recovery.generation
            )
        if leads:
            await deletion.remove(db, tenant, [r.id for r in leads], datetime.now(UTC))
        await db.flush()
        if any(r.erased_at is None for r in rows["report_draft"]):
            raise ValueError("refused_report_not_erased")
        result["after"] = dict(
            recording=0, report_draft=0, submission=len(rows["submission"]), test_lead=0
        )
        await append_audit_event(
            db,
            tenant_id=tenant,
            actor_person_id=person,
            actor_type="operator",
            action=ACTION,
            resource_type="data_change",
            resource_id=WORK,
            request_id=WORK,
            reason=APPROVER,
            payload={"before": before, "after": result["after"]},
        )
        # Keep the storage fence through commit, as the app worker does.
        await db.commit()
        return result


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    wanted = load_manifest(args.ids)
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    try:
        storage = None
        if args.apply:
            if not settings.sales_xray_storage_root:
                raise ValueError("refused_storage_configuration")
            storage = PrivateLocalRecordingStorage(Path(settings.sales_xray_storage_root))
        result = await execute(
            async_sessionmaker(engine, expire_on_commit=False),
            wanted,
            apply=args.apply,
            storage=storage,
        )
        print(json.dumps(result, sort_keys=True))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        # DB/adapter exceptions may contain customer values; never echo them.
        print(json.dumps({"refused": 1}))
        raise SystemExit(1) from None
