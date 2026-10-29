"""Durable company-call recording intake. Provider I/O never holds a DB transaction.

Audit events are the work queue. A private per-call file lock serializes API processes;
failed work is retried by the next sweep, including terminal calls with late recordings.
No synthetic login, consent receipt, report or provider approval is manufactured here.
"""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import logging
import os
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid5

import anyio
from fastapi import FastAPI
from sqlalchemy import select, tuple_

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.call_ai import auto_consent
from ac_platform.conversation_intelligence.acquisition_processing import (
    AcquisitionProcessing,
    upload_policy,
)
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.processing_plan import (
    ConversationProcessingPlans,
    PlanAcceptance,
)
from ac_platform.conversation_intelligence.storage import CHUNK_BYTES
from ac_platform.conversation_intelligence.worker import _FencedExecutor
from ac_platform.http.sales_xray_profile import require_sales_xray_write_profile
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.lead_desk.models import Lead
from ac_platform.lead_desk.telephony import ledger, providers, service
from ac_platform.product_updates.models import Notification
from ac_platform.tenancy.models import Membership

LOG = logging.getLogger(__name__)
STATE = "company_call_pipeline"
STORED = "lead_desk.company_call.recording_stored.v1"
SUBMITTED = "lead_desk.company_call.submitted.v1"
STARTED = "lead_desk.company_call.analysis_started.v1"
READY = "lead_desk.company_call.report_ready.v1"
# Waiting provider recordings are bounded to the same seven-day inbox window as app uploads.
WINDOW = timedelta(days=7)


class Pipeline:
    def __init__(
        self,
        *,
        sessions: Any,
        runtime: Any,
        preflight: Any,
        factory: Any,
        environment: str,
        allow_fictional_analysis: bool = False,
    ) -> None:
        self.sessions, self.runtime, self.preflight, self.factory = (
            sessions,
            runtime,
            preflight,
            factory,
        )
        self.environment = environment
        self._cursor: tuple[datetime, UUID] | None = None
        self.fake_callback: Callable[[UUID, UUID], Awaitable[bool]] | None = None
        # Test composition only. Hosted composition never enables external AI for fake audio.
        self.allow_fictional_analysis = allow_fictional_analysis and environment == "test"
        self.root = Path(runtime.storage.root) / "company-calls"
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)

    def path(self, tenant_id: UUID, call_id: UUID) -> Path:
        return self.root / str(tenant_id) / f"{call_id}.media"

    async def events(self, db: Any, call: ledger.CompanyCall) -> dict[str, dict[str, Any]]:
        rows = (
            await db.execute(
                select(AuditEvent.action, AuditEvent.payload)
                .where(
                    AuditEvent.tenant_id == call.tenant_id,
                    AuditEvent.resource_type == ledger.RESOURCE_TYPE,
                    AuditEvent.resource_id == str(call.id),
                )
                .order_by(AuditEvent.sequence_no)
            )
        ).all()
        return {action: payload for action, payload in rows if isinstance(payload, dict)}

    async def append(
        self, db: Any, call: ledger.CompanyCall, action: str, payload: dict[str, Any]
    ) -> None:
        await AuditRepository(db).append(
            tenant_id=call.tenant_id,
            actor_person_id=None,
            actor_type="system",
            action=action,
            resource_type=ledger.RESOURCE_TYPE,
            resource_id=str(call.id),
            payload=payload,
            now=datetime.now(UTC),
        )

    async def advance(self, provider: providers.Provider, tenant_id: UUID, call_id: UUID) -> None:
        """Resume one call. Another process handling it wins; the next sweep resumes it."""
        if provider.real and self.environment != "test":
            return  # Real audio intake awaits processor/consent/lifecycle activation.
        target = self.path(tenant_id, call_id)
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with target.with_suffix(".lock").open("a+b") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            try:
                await self._advance(provider, tenant_id, call_id, target)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    async def _advance(
        self, provider: providers.Provider, tenant_id: UUID, call_id: UUID, target: Path
    ) -> None:
        now = datetime.now(UTC)
        call = await service.refresh(self.sessions, provider, tenant_id, call_id, now=now)
        if call is None or call.provider != provider.name or not call.sid or not call.final:
            return
        async with self.sessions() as db, db.begin():
            events = await self.events(db, call)
        if READY in events:
            if self.environment in {"test", "local"}:
                return  # Tests exercise notification dispatch with an explicit fake sender.
            from ac_platform.lead_desk.telephony.notifications import dispatch

            await dispatch(self, call, UUID(events[READY]["submission_id"]))
            return
        if call.status != "completed" or call.lead_answered is not True:
            return
        if STORED not in events:
            # A provider may publish its recording after its terminal status callback.
            report = await provider.report(call.sid)
            if report.sid != call.sid or not report.recording_url:
                return
            recording = await provider.fetch_recording(report.recording_url)
            content = recording.content
            if not content or len(content) > providers.MAX_RECORDING:
                raise providers.TelephonyError("The recording is empty or too large.", status=422)
            digest = hashlib.sha256(content).hexdigest()
            partial = target.with_suffix(".part")
            try:
                async with await anyio.open_file(partial, "wb") as stream:
                    await stream.write(content)
                os.chmod(partial, 0o600)
                os.replace(partial, target)
            finally:
                with suppress(FileNotFoundError):
                    partial.unlink()
            async with self.sessions() as db, db.begin():
                await self.append(
                    db,
                    call,
                    STORED,
                    {
                        "sha256": digest,
                        "bytes": len(content),
                        "content_type": recording.content_type,
                        "provider": call.provider,
                        "sid": call.sid,
                        "fictional": not provider.real,
                        "lead_event_id": str(call.lead_event_id) if call.lead_event_id else None,
                    },
                )
                events = await self.events(db, call)
        if STARTED in events:
            async with self.sessions() as db, db.begin():
                from ac_platform.conversation_intelligence.models import ConversationProcessingPlan

                plan = await db.scalar(
                    select(ConversationProcessingPlan).where(
                        ConversationProcessingPlan.tenant_id == tenant_id,
                        ConversationProcessingPlan.id == UUID(events[STARTED]["plan_id"]),
                    )
                )
                if plan is not None and ConversationProcessingPlans.view(plan).get("report_ready"):
                    await self.notify(db, call, UUID(events[STARTED]["submission_id"]))
            return
        # The same validated file is handed to canonical intake, never a provider URL.
        stored = events[STORED]
        if not await anyio.to_thread.run_sync(target.is_file):
            return
        submission = uuid5(service.NAMESPACE, f"{tenant_id}:{call_id}:submission")
        terms = upload_policy(self.runtime.policy)["policy_sha256"]
        async with self.sessions() as db, db.begin():
            consent = await auto_consent.may_start(db, tenant_id, call.seller_person_id, terms)
            if consent is None:
                return  # Stored; the seller can use the normal recording + upload tap.
            # Reuse the real session that requested the call. Canonical admission checks
            # expiry/revocation and active membership; no fabricated background session.
            request = await db.scalar(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.resource_type == ledger.RESOURCE_TYPE,
                    AuditEvent.resource_id == str(call_id),
                    AuditEvent.action == ledger.REQUESTED,
                )
            )
            if request is None or request.session_id is None:
                return
            actor = ActorContext(
                person_id=call.seller_person_id, tenant_id=tenant_id, session_id=request.session_id
            )
            await require_sales_xray_write_profile(db, actor)
            await ConversationApplication(db).admit(actor)
        if not provider.real and not self.allow_fictional_analysis:
            return  # Never send generated silence to external AI from hosted dev.
        if SUBMITTED not in events:
            async with _FencedExecutor(self.runtime.storage.root) as fenced:
                # Native outputs must be isolated per attempt and disposed after preflight.
                import shutil

                with tempfile.TemporaryDirectory(dir=self.runtime.scratch.root) as folder:
                    scratch = Path(folder) / "source.media"
                    await fenced.run(shutil.copyfile, target, scratch)
                    measured = await fenced.run(
                        self.preflight.measure, scratch, submission, stored["sha256"]
                    )
                async with self.sessions() as db, db.begin():
                    consent = await auto_consent.may_start(
                        db, tenant_id, call.seller_person_id, terms
                    )
                    if consent is None:
                        return
                    ownership = GuestOwnership(self.factory(db, tenant_id))
                    processing = AcquisitionProcessing(ownership, self.runtime)
                    processing_actor, quote = await processing.prepare(
                        measured, actor=actor, policy_sha256=terms, standing_consent_id=consent
                    )
                    with target.open("rb") as source:
                        await processing.application.store_source(
                            processing_actor,
                            UUID(quote["recording_id"]),
                            chunks=iter(lambda: source.read(CHUNK_BYTES), b""),
                            storage=self.runtime.storage,
                        )
                    await processing.enqueue(processing_actor, quote)
                    await self.append(
                        db,
                        call,
                        SUBMITTED,
                        {"submission_id": str(submission), "recording_id": quote["recording_id"]},
                    )
                    # Supersede the lead event payload through the existing attach API,
                    # rather than mutate its audit-critical historical content.
                    from ac_platform.lead_desk.store import LeadDesk, Viewer

                    role = await db.scalar(
                        select(Membership.role).where(
                            Membership.tenant_id == tenant_id,
                            Membership.person_id == call.seller_person_id,
                            Membership.status == "active",
                            Membership.ended_at.is_(None),
                        )
                    )
                    desk = LeadDesk(
                        db,
                        Viewer(
                            person_id=actor.person_id,
                            tenant_id=tenant_id,
                            role=role or "member",
                            name="",
                            session_id=actor.session_id,
                        ),
                    )
                    await desk.attach_recording(
                        call.lead_id,
                        command_id=uuid5(service.NAMESPACE, f"{call.id}:attach"),
                        submission_id=submission,
                        call_event_id=call.lead_event_id,
                    )
        if self.runtime.authority is None:
            return
        async with self.sessions() as db, db.begin():
            ownership = GuestOwnership(self.factory(db, tenant_id))
            scope = await ownership.require_submission_owner(submission, actor=actor)
            processing_actor = await ownership.resolve_processing_actor(submission, actor=actor)
            plans = ConversationProcessingPlans(
                ConversationApplication(db), self.runtime.authority, self.runtime.storage
            )
            events = await self.events(db, call)
            if STARTED not in events:
                # Both upload and exact plan acceptance re-check current standing consent.
                consent = await auto_consent.may_start(db, tenant_id, actor.person_id, terms)
                if consent is None:
                    return
                key = f"company-call:{call.id}:plan"
                continuation = await ownership.ensure_processing_continuation(
                    submission, key=key, actor=actor
                )
                plan = await plans.quote(
                    processing_actor,
                    scope.recording_id,
                    key=key,
                    continuation_grant_id=continuation,
                )
                await plans.accept(
                    processing_actor,
                    scope.recording_id,
                    PlanAcceptance(
                        plan_id=UUID(plan["id"]),
                        plan_fingerprint=plan["plan_fingerprint"],
                        privacy_revision=plan["privacy_revision"],
                        accepted=True,
                    ),
                    key=key + ":accept",
                )
                await AuditRepository(db).append(
                    tenant_id=tenant_id,
                    actor_person_id=actor.person_id,
                    session_id=actor.session_id,
                    action="conversation.auto_analysis_started",
                    resource_type="conversation_submission",
                    resource_id=submission,
                    payload={"standing_consent_event_id": str(consent), "plan_id": plan["id"]},
                    now=datetime.now(UTC),
                )
                await self.append(
                    db,
                    call,
                    STARTED,
                    {
                        "submission_id": str(submission),
                        "plan_id": plan["id"],
                        "standing_consent_event_id": str(consent),
                    },
                )
            status = await plans.latest_submission_view(
                db,
                tenant_id=scope.tenant_id,
                person_id=scope.processing_person_id,
                recording_id=scope.recording_id,
                processing_lease_id=scope.processing_lease_id,
            )
            if status.get("report_ready"):
                await self.notify(db, call, submission)

    async def notify(self, db: Any, call: ledger.CompanyCall, submission: UUID) -> None:
        """Existing notifications API supplies the seller's badge and read receipt."""
        events = await self.events(db, call)
        if READY in events:
            return
        active = await db.scalar(
            select(Person.id)
            .join(
                Membership,
                Membership.person_id == Person.id,
            )
            .where(
                Person.id == call.seller_person_id,
                Person.status == "active",
                Membership.tenant_id == call.tenant_id,
                Membership.status == "active",
                Membership.ended_at.is_(None),
            )
        )
        if active is None:
            return
        lead = await db.scalar(
            select(Lead).where(Lead.tenant_id == call.tenant_id, Lead.id == call.lead_id)
        )
        name = lead.name if lead is not None else "your lead"
        db.add(
            Notification(
                person_id=call.seller_person_id,
                tenant_id=call.tenant_id,
                kind="report_ready",
                dedupe_key=f"company-call:{call.id}:ready",
                title=f"Your call with {name} is analysed"[:200],
                body="Open the report and coaching.",
                href=f"/analysis/calls/{submission}",
                urgent=False,
                created_at=datetime.now(UTC),
            )
        )
        await self.append(
            db,
            call,
            READY,
            {
                "submission_id": str(submission),
                "ready_at_epoch": int(datetime.now(UTC).timestamp()),
            },
        )

    async def resume(self, provider: providers.Provider, tenant_id: UUID, call_id: UUID) -> None:
        try:
            await self.advance(provider, tenant_id, call_id)
        except (ConversationError, providers.TelephonyError):
            LOG.info("Company call awaits intake or analysis prerequisites: %s", call_id)
        except Exception:  # noqa: BLE001 - isolate a failed call; retry next pass
            LOG.warning("Company call intake failed; will retry")

    async def tick(self, provider: providers.Provider) -> None:
        query = select(
            AuditEvent.tenant_id, AuditEvent.resource_id, AuditEvent.occurred_at, AuditEvent.id
        ).where(
            AuditEvent.resource_type == ledger.RESOURCE_TYPE,
            AuditEvent.action == ledger.REQUESTED,
            AuditEvent.occurred_at >= datetime.now(UTC) - WINDOW,
        )
        if self._cursor is not None:
            query = query.where(tuple_(AuditEvent.occurred_at, AuditEvent.id) > self._cursor)
        async with self.sessions() as db:
            rows = (
                await db.execute(query.order_by(AuditEvent.occurred_at, AuditEvent.id).limit(200))
            ).all()
        self._cursor = (rows[-1].occurred_at, rows[-1].id) if len(rows) == 200 else None
        for tenant, resource, _, _ in rows:
            call_id = UUID(resource)
            # Simulated providers post the same signed webhook without leaving this API.
            if (
                provider.name == "fake"
                and self.fake_callback is not None
                and await self.fake_callback(tenant, call_id)
            ):
                continue
            await self.resume(provider, tenant, call_id)


def attach(
    application: FastAPI,
    pipeline: Pipeline,
    provider: Callable[[], providers.Provider | None],
    *,
    base_url: str | None = None,
) -> None:
    setattr(application.state, STATE, pipeline)
    if base_url:

        async def callback(tenant: UUID, call_id: UUID) -> bool:
            return await post_fake_callback(application, base_url, tenant, call_id)

        pipeline.fake_callback = callback
    if pipeline.environment in {"local", "test"}:
        return
    inner = application.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[Any]:
        async with inner(app) as state:
            stop = asyncio.Event()

            async def run() -> None:
                while not stop.is_set():
                    found = provider()
                    if found is not None:
                        try:
                            await pipeline.tick(found)
                        except Exception:  # noqa: BLE001 - a transient DB failure must not stop the queue
                            LOG.warning("Company-call sweep failed; will retry")
                    with suppress(TimeoutError):
                        await asyncio.wait_for(stop.wait(), timeout=15)

            task = asyncio.create_task(run(), name="company-call-intake")
            try:
                yield state
            finally:
                stop.set()
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    application.router.lifespan_context = lifespan


async def post_fake_callback(app: FastAPI, base_url: str, tenant: UUID, call_id: UUID) -> bool:
    """Local ASGI delivery: no external network and no HTTP-client URL logging."""
    from ac_platform.lead_desk.telephony.http import sign

    secret = (os.environ.get("AC_TELEPHONY_WEBHOOK_SECRET") or "").strip()
    if not secret:
        return False
    parsed = urlparse(base_url)
    if not parsed.hostname:
        return False
    mac = sign(secret, tenant, call_id)
    path = f"/v1/lead-desk/meta/webhook/telephony/fake/{tenant}/{call_id}/{mac}"
    body_sent = False
    status = 0

    async def receive() -> dict[str, Any]:
        nonlocal body_sent
        if body_sent:
            return {"type": "http.disconnect"}
        body_sent = True
        return {"type": "http.request", "body": b"{}", "more_body": False}

    async def send(message: Any) -> None:
        nonlocal status
        if message["type"] == "http.response.start":
            status = message["status"]

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": parsed.scheme,
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"host", parsed.netloc.encode()),
                (b"content-type", b"application/json"),
                (b"content-length", b"2"),
            ],
            "server": (parsed.hostname, parsed.port or 443),
            "client": ("127.0.0.1", 0),
        },
        receive,
        send,
    )
    return status == 200
