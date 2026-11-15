"""The server starts the analysis of a call its seller's standing consent covers, as soon as
the call's audio check (C1) is done (orchestrator, 14 Nov 2026: reports waited for the
phone's background worker to come back, quote and accept the plan, which took 70-270 s or
more on Android 16 and MIUI, while C2, C4 and C5 take 40-90 s).

A call uploaded marked "standing" (``conversation.auto_upload_accepted``, which names the
consent and the session that uploaded it) has its plan quoted and accepted here, exactly
as the phone's own quote and accept would do it:

- the same checks: the standing consent read again now (on, for the upload terms in force,
  the seller's AI level not Off: ``auto_consent.may_start``), the uploading session's
  admission (expiry, revocation, active membership), the seller's write profile, the
  provider budget in the quote, and every hold the plan applies when it advances (AI
  level, short call, no conversation). The seller's minutes were taken at upload, as
  before;
- the same receipts: the acceptance is the plan's own, and
  ``conversation.auto_analysis_started`` names the consent it relied on (and
  ``started_by: server``);
- the phone's own start later is a no-op: its read sees the active plan
  (``automatic_progression``), its quote returns that plan, and accepting it again reuses
  the one acceptance and records no second start.

A call that can't start here (consent off, a refusal from the plan) is marked once
(``conversation.auto_analysis_waiting``) and keeps its tap. Nothing is made up: the actor is
the session that uploaded the call; an upload recorded without its session (before this
change) is left to the phone. Content-free: ids and codes only.

A call an organisation's API key uploaded for a seller (``conversation.api_upload_accepted``,
API gap 2, 15 Nov 2026) starts here the same way, as that seller through the key
(``key_upload.KeyUploadActor``): the key, its maker and the seller are admitted again, and
instead of the seller's standing consent the workspace's API-upload terms must still be on
for the upload terms in force, with the seller's AI level not Off (``key_upload.may_upload``).
Its start names that acceptance and the key; no session is borrowed.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, cast
from uuid import UUID

from fastapi import FastAPI
from sqlalchemy import String, and_, or_, select, text

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.call_ai import auto_consent
from ac_platform.conversation_intelligence import key_upload
from ac_platform.conversation_intelligence.acquisition_processing import upload_policy
from ac_platform.conversation_intelligence.application import (
    LOCAL_JOB,
    ConversationApplication,
    ConversationConflict,
    ConversationError,
)
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.models import (
    ConversationProcessingPlan,
    ConversationRecording,
    ConversationRun,
)
from ac_platform.conversation_intelligence.processing_plan import (
    ConversationProcessingPlans,
    PlanAcceptance,
)
from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.errors import DomainError
from ac_platform.outbox.models import Job

LOG = logging.getLogger(__name__)
STATE: Final = "auto_start"
UPLOADED: Final = "conversation.auto_upload_accepted"
STARTED: Final = "conversation.auto_analysis_started"
WAITING: Final = "conversation.auto_analysis_waiting"
# Only calls whose audio check finished this recently start here (as the one-pass reads:
# nothing old starts and charges by itself); an older one keeps its tap.
FRESH: Final = timedelta(hours=2)
INTERVAL_SECONDS: Final = 3.0
BATCH: Final = 20
_LANGUAGES: Final = frozenset({"en", "hi-Deva+en", "mr-Deva+en"})


@dataclass(frozen=True)
class Candidate:
    tenant_id: UUID
    person_id: UUID
    session_id: UUID | None
    recording_id: UUID
    submission_id: UUID
    # An API upload (key_upload): the key and its maker; the session is then None.
    key_id: UUID | None = None
    maker_person_id: UUID | None = None
    report_language: str | None = None


def _lock_key(recording_id: UUID) -> int:
    return int.from_bytes(recording_id.bytes[:8], "big", signed=True)


class AutoStart:
    def __init__(
        self, *, sessions: Any, runtime: Any, factory: Any, environment: str | None = None
    ) -> None:
        self.sessions, self.runtime, self.factory = sessions, runtime, factory
        # Where API uploads may be switched on (key_upload.OPEN_ENVIRONMENTS); without it
        # none starts here.
        self.environment = environment

    async def candidates(self, now: datetime) -> list[Candidate]:
        """Calls whose audio check finished in the last ``FRESH``, with no plan yet, uploaded
        under a standing consent by a recorded session (or by an organisation's key), and not
        already marked waiting. Only such calls are fetched: calls waiting for their seller's
        tap never fill the batch and hide one that can start here."""
        found: list[Candidate] = []
        recording = ConversationRun.recording_id.cast(String)

        def marked(action: str) -> Any:
            return (
                select(AuditEvent.id)
                .where(
                    AuditEvent.tenant_id == ConversationRun.tenant_id,
                    AuditEvent.resource_type == "conversation_recording",
                    AuditEvent.resource_id == recording,
                    AuditEvent.action == action,
                    *(
                        (
                            AuditEvent.actor_person_id.is_not(None),
                            AuditEvent.session_id.is_not(None),
                        )
                        if action == UPLOADED
                        else ()
                    ),
                )
                .exists()
            )

        keyed = (
            select(ConversationGuestSubmission.submission_id)
            .join(
                AuditEvent,
                and_(
                    AuditEvent.tenant_id == ConversationGuestSubmission.tenant_id,
                    AuditEvent.resource_type == key_upload.UPLOAD_RESOURCE,
                    AuditEvent.resource_id
                    == ConversationGuestSubmission.submission_id.cast(String),
                    AuditEvent.action == key_upload.UPLOADED,
                ),
            )
            .where(
                ConversationGuestSubmission.tenant_id == ConversationRun.tenant_id,
                ConversationGuestSubmission.recording_id == ConversationRun.recording_id,
            )
            .exists()
        )
        async with self.sessions() as db:
            runs = (
                await db.execute(
                    select(ConversationRun.tenant_id, ConversationRun.recording_id)
                    .join(Job, Job.id == ConversationRun.job_id)
                    .join(
                        ConversationRecording,
                        ConversationRecording.id == ConversationRun.recording_id,
                    )
                    .where(
                        Job.kind == LOCAL_JOB,
                        ConversationRun.state == "completed",
                        ConversationRun.completed_at >= now - FRESH,
                        ConversationRun.generation == ConversationRecording.generation,
                        ConversationRecording.deleted_at.is_(None),
                        ~select(ConversationProcessingPlan.id)
                        .where(
                            ConversationProcessingPlan.recording_id == ConversationRun.recording_id
                        )
                        .exists(),
                        or_(marked(UPLOADED), keyed),
                        ~marked(WAITING),
                    )
                    .order_by(ConversationRun.completed_at)
                    .limit(BATCH)
                )
            ).all()
            for tenant_id, recording_id in runs:
                events = (
                    await db.scalars(
                        select(AuditEvent)
                        .where(
                            AuditEvent.tenant_id == tenant_id,
                            AuditEvent.resource_type == "conversation_recording",
                            AuditEvent.resource_id == str(recording_id),
                            AuditEvent.action.in_((UPLOADED, WAITING)),
                        )
                        .order_by(AuditEvent.sequence_no)
                    )
                ).all()
                if any(event.action == WAITING for event in events):
                    continue
                upload = next((event for event in events if event.action == UPLOADED), None)
                if upload is None:
                    by_key = await self._api_upload(db, tenant_id, recording_id)
                    if by_key is not None:
                        found.append(by_key)
                    continue
                if (
                    upload is None
                    or upload.actor_person_id is None
                    or upload.session_id is None
                    or not isinstance(upload.payload, dict)
                ):
                    continue
                try:
                    submission_id = UUID(str(upload.payload["submission_id"]))
                except (KeyError, ValueError):
                    continue
                found.append(
                    Candidate(
                        tenant_id=tenant_id,
                        person_id=upload.actor_person_id,
                        session_id=upload.session_id,
                        recording_id=recording_id,
                        submission_id=submission_id,
                    )
                )
        return found

    @staticmethod
    async def _api_upload(db: Any, tenant_id: UUID, recording_id: UUID) -> Candidate | None:
        """The call's API upload, when an organisation's key sent it."""
        submission_id = await db.scalar(
            select(ConversationGuestSubmission.submission_id).where(
                ConversationGuestSubmission.tenant_id == tenant_id,
                ConversationGuestSubmission.recording_id == recording_id,
            )
        )
        if submission_id is None:
            return None
        event = await db.scalar(
            select(AuditEvent)
            .where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.resource_type == key_upload.UPLOAD_RESOURCE,
                AuditEvent.resource_id == str(submission_id),
                AuditEvent.action == key_upload.UPLOADED,
            )
            .limit(1)
        )
        payload = event.payload if event is not None and isinstance(event.payload, dict) else {}
        try:
            seller = UUID(str(payload["seller_person_id"]))
            key_id = UUID(str(payload["key_id"]))
            maker = UUID(str(payload["maker_person_id"]))
        except (KeyError, ValueError):
            return None
        language = payload.get("report_language")
        return Candidate(
            tenant_id=tenant_id,
            person_id=seller,
            session_id=None,
            recording_id=recording_id,
            submission_id=submission_id,
            key_id=key_id,
            maker_person_id=maker,
            report_language=language if language in _LANGUAGES else None,
        )

    async def _wait(self, item: Candidate, reason: str) -> None:
        async with self.sessions() as db, db.begin():
            await AuditRepository(db).append(
                tenant_id=item.tenant_id,
                actor_person_id=item.person_id,
                session_id=item.session_id,
                action=WAITING,
                resource_type="conversation_recording",
                resource_id=item.recording_id,
                payload={"submission_id": str(item.submission_id), "reason": reason},
            )

    async def start(self, item: Candidate) -> str:
        """Start one call: ``started``, ``waiting:<reason>``, or ``skipped:<why>`` (another
        process has it, or a plan exists already)."""
        authority = self.runtime.authority
        if authority is None:
            return "skipped:no_authority"
        refusal: str | None = None
        async with self.sessions() as db, db.begin():
            # One process per call; the plan's own keys make a repeat a replay anyway.
            locked = await db.scalar(
                text("SELECT pg_try_advisory_xact_lock(:key)"),
                {"key": _lock_key(item.recording_id)},
            )
            if not locked:
                return "skipped:busy"
            planned = await db.scalar(
                select(ConversationProcessingPlan.id)
                .where(ConversationProcessingPlan.recording_id == item.recording_id)
                .limit(1)
            )
            if planned is not None:
                return "skipped:planned"
            terms = upload_policy(self.runtime.policy)["policy_sha256"]
            actor: ActorContext
            relied_on: dict[str, str]
            if item.key_id is not None and item.maker_person_id is not None:
                accepted, why = (
                    (None, key_upload.CLOSED)
                    if self.environment is None
                    else await key_upload.may_upload(
                        db, item.tenant_id, item.person_id, terms, self.environment
                    )
                )
                consent = accepted
                if accepted is None:
                    refusal = "terms" if why == key_upload.CLOSED else "ai_off"
                actor = key_upload.key_actor(
                    seller=item.person_id,
                    tenant_id=item.tenant_id,
                    key_id=item.key_id,
                    maker=item.maker_person_id,
                )
                relied_on = {
                    "api_upload_terms_event_id": str(accepted),
                    "key_id": str(item.key_id),
                }
            else:
                consent = await auto_consent.may_start(db, item.tenant_id, item.person_id, terms)
                if consent is None:
                    refusal = "consent"
                assert item.session_id is not None
                actor = ActorContext(
                    person_id=item.person_id, tenant_id=item.tenant_id, session_id=item.session_id
                )
                relied_on = {"standing_consent_event_id": str(consent)}
            if consent is not None:
                try:
                    async with db.begin_nested():
                        plan = await self._accept(db, item, actor, authority)
                except (ConversationError, DomainError) as error:
                    refusal = type(error).__name__
                else:
                    await AuditRepository(db).append(
                        tenant_id=item.tenant_id,
                        actor_person_id=item.person_id,
                        actor_type="person" if item.key_id is None else "api_key",
                        session_id=item.session_id,
                        action=STARTED,
                        resource_type="conversation_submission",
                        resource_id=item.submission_id,
                        payload={
                            **relied_on,
                            "plan_id": str(plan["id"]),
                            "started_by": "server",
                        },
                    )
                    return "started"
        await self._wait(item, refusal or "refused")
        return f"waiting:{refusal}"

    async def _accept(
        self, db: Any, item: Candidate, actor: ActorContext, authority: Any
    ) -> dict[str, Any]:
        from ac_platform.http.sales_xray_profile import require_sales_xray_write_profile

        await require_sales_xray_write_profile(db, actor)
        await ConversationApplication(db).admit(actor)
        ownership = GuestOwnership(self.factory(db, item.tenant_id))
        scope = await ownership.require_submission_owner(item.submission_id, actor=actor)
        if scope.recording_id != item.recording_id:
            raise ConversationConflict("This call's recording changed.")
        key = f"auto-start:{item.submission_id}:plan"
        continuation = await ownership.ensure_processing_continuation(
            item.submission_id, key=key, actor=actor
        )
        processing = await ownership.resolve_processing_actor(item.submission_id, actor=actor)
        plans = ConversationProcessingPlans(
            ConversationApplication(db), authority, self.runtime.storage
        )
        plan = await plans.quote(
            processing,
            item.recording_id,
            key=key,
            continuation_grant_id=continuation,
            report_language=cast(Any, item.report_language),
        )
        return await plans.accept(
            processing,
            item.recording_id,
            PlanAcceptance(
                plan_id=UUID(plan["id"]),
                plan_fingerprint=plan["plan_fingerprint"],
                privacy_revision=plan["privacy_revision"],
                accepted=True,
            ),
            key=key + ":accept",
        )

    async def tick(self, now: datetime | None = None) -> list[str]:
        outcomes = []
        for item in await self.candidates(now or datetime.now(UTC)):
            try:
                outcomes.append(await self.start(item))
            except Exception:  # noqa: BLE001 - one call never stops the others; next tick retries
                LOG.warning("Automatic start failed for one call; will retry")
                outcomes.append("error")
        return outcomes


def attach(application: FastAPI, auto: AutoStart, *, environment: str) -> None:
    """Keep the starter on the app; hosted environments run it every few seconds."""
    setattr(application.state, STATE, auto)
    if environment in {"local", "test"}:
        return
    inner: Callable[[FastAPI], Any] = application.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[Any]:
        async with inner(app) as state:
            stop = asyncio.Event()

            async def run() -> None:
                while not stop.is_set():
                    try:
                        await auto.tick()
                    except Exception:  # noqa: BLE001 - a transient DB failure must not stop it
                        LOG.warning("Automatic start sweep failed; will retry")
                    with suppress(TimeoutError):
                        await asyncio.wait_for(stop.wait(), timeout=INTERVAL_SECONDS)

            task = asyncio.create_task(run(), name="standing-consent-auto-start")
            try:
                yield state
            finally:
                stop.set()
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    application.router.lifespan_context = lifespan


__all__ = ["STARTED", "STATE", "UPLOADED", "WAITING", "AutoStart", "Candidate", "attach"]
