"""Tenant-scoped read-only recording inventory for the AC admin surface.

The admin inventory joins existing canonical rows.  It does not create a
processing run, inspect source bytes, call a provider, or turn a quote into an
actual charge.  In particular, an actual cost is returned only when the
immutable reservation contains a settlement receipt.
"""

from __future__ import annotations

import base64
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import String, and_, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionUsage,
    ConversationVisitorClaim,
)
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
    ConversationDenied,
    ConversationError,
    utc,
)
from ac_platform.conversation_intelligence.entitlements import MinuteAccount, Quote
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationInferenceTask,
    ConversationMinuteAccount,
    ConversationProcessingPlan,
    ConversationQuote,
    ConversationRecording,
    ConversationReportDraft,
    ConversationRun,
)
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.conversation_intelligence.report_store import ConversationReports
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext

_MAX_LIMIT = 50
_MAX_SEARCH = 120
_CURSOR_SEPARATOR = "|"


def _cursor(created_at: datetime, recording_id: UUID) -> str:
    raw = f"{utc(created_at).isoformat()}{_CURSOR_SEPARATOR}{recording_id}"
    return base64.urlsafe_b64encode(raw.encode("ascii")).decode("ascii").rstrip("=")


def _decode_cursor(value: str | None) -> tuple[datetime, UUID] | None:
    if value is None:
        return None
    if not isinstance(value, str) or not 1 <= len(value) <= 256:
        raise ConversationError("The recordings cursor is invalid.")
    try:
        padded = value + "=" * (-len(value) % 4)
        raw = base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True).decode(
            "ascii"
        )
        timestamp, identifier = raw.rsplit(_CURSOR_SEPARATOR, 1)
        parsed_time = datetime.fromisoformat(timestamp)
        parsed_id = UUID(identifier)
    except (ValueError, UnicodeDecodeError, UnicodeEncodeError):
        raise ConversationError("The recordings cursor is invalid.") from None
    if parsed_time.tzinfo is None:
        parsed_time = parsed_time.replace(tzinfo=UTC)
    return utc(parsed_time), parsed_id


def _like(column: Any, value: str) -> Any:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return column.ilike(f"%{escaped}%", escape="\\")


def _latest(rows: Iterable[Any], key: Any) -> dict[UUID, Any]:
    result: dict[UUID, Any] = {}
    for row in rows:
        identifier = key(row)
        previous = result.get(identifier)
        if previous is None or (utc(row.created_at), row.id) > (
            utc(previous.created_at),
            previous.id,
        ):
            result[identifier] = row
    return result


def _safe_duration(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get("media_duration_ms")
    if type(value) is int and 0 < value <= 14_400_000:
        return value
    return None


def _owner_view(
    recording: ConversationRecording,
    guest: ConversationGuestSubmission | None,
    usage: ConversationAcquisitionUsage | None,
    claim: ConversationVisitorClaim | None,
    people: dict[UUID, Person],
) -> dict[str, Any]:
    if guest is None:
        person = people.get(recording.person_id)
        display = None if person is None else (person.display_name or person.first_name)
        email = None if person is None else person.email
        label = display or email or "Account owner"
        return {
            "kind": "learner",
            "label": label,
            "person_id": str(recording.person_id),
            "display_name": display,
            "email": email,
            "claimed": True,
        }

    if usage is None:
        return {
            "kind": "guest",
            "label": "Guest upload",
            "person_id": None,
            "display_name": None,
            "email": None,
            "claimed": False,
        }

    owner_id = usage.person_id or (claim.person_id if claim is not None else None)
    person = people.get(owner_id) if owner_id is not None else None
    display = None if person is None else (person.display_name or person.first_name)
    email = None if person is None else person.email
    return {
        "kind": "guest",
        "label": display or email or "Guest upload",
        "person_id": None if owner_id is None else str(owner_id),
        "display_name": display,
        "email": email,
        "claimed": owner_id is not None,
    }


def _status(
    recording: ConversationRecording,
    run: ConversationRun | None,
    plan: ConversationProcessingPlan | None,
    *,
    has_report: bool,
) -> str:
    if has_report:
        return "completed"
    if plan is not None and plan.state == "held":
        return "held"
    if run is not None:
        if run.state == "running":
            return "processing"
        return run.state
    if plan is not None:
        if plan.state == "active":
            return "processing"
        return plan.state
    return recording.state


def _cost_view(
    task: ConversationInferenceTask | None,
    quote_row: ConversationQuote | None,
    minute_row: ConversationMinuteAccount | None,
) -> dict[str, Any]:
    estimate: int | None = None
    quote: Quote | None = None
    if quote_row is not None:
        try:
            quote = Quote.from_dict(quote_row.quote)
        except (TypeError, ValueError, KeyError):
            quote = None
        if quote is not None:
            estimate = quote.max_cost_paise

    reservation = None
    if task is not None and minute_row is not None:
        try:
            account = MinuteAccount.from_dict(minute_row.snapshot)
            reservation = next(
                (item for item in account.reservations if item.reservation_id == str(task.run_id)),
                None,
            )
        except (TypeError, ValueError, KeyError):
            reservation = None

    actual: int | None = None
    reservation_paise: int | None = None
    state: str | None = None
    if reservation is not None:
        state = reservation.state
        # Keep the immutable reserved cap visible after settlement/release;
        # reservation_state tells the operator whether it is still held.
        reservation_paise = reservation.quote.max_cost_paise
        if reservation.settlement is not None:
            actual = reservation.settlement.actual_paise
    return {
        "currency": "INR",
        "reservation_paise": reservation_paise,
        "estimate_paise": estimate,
        "actual_paise": actual,
        "reservation_state": state,
        "actual_state": (
            "settled"
            if actual is not None
            else "reconciliation_required"
            if state == "reconciliation_required"
            else "not_settled"
        ),
    }


class AdminConversationRecordings:
    """Operations-tenant recording inventory with immutable read scope."""

    def __init__(self, application: ConversationApplication, operations_tenant_id: UUID) -> None:
        self.application = application
        self.database: AsyncSession = application.database
        self.operations_tenant_id = operations_tenant_id

    async def _admit(self, actor: ActorContext) -> None:
        if actor.tenant_id != self.operations_tenant_id:
            raise ConversationDenied("Conversation recordings require the AC operations tenant.")
        await ConversationProviderAdmin(self.application).admit(actor)

    async def list(
        self,
        actor: ActorContext,
        *,
        limit: int = 25,
        cursor: str | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        await self._admit(actor)
        if type(limit) is not int or not 1 <= limit <= _MAX_LIMIT:
            raise ConversationError("Use a recordings page size between 1 and 50.")
        if search is not None:
            if not isinstance(search, str) or len(search) > _MAX_SEARCH:
                raise ConversationError("The recordings search is too long.")
            search = search.strip()
        decoded = _decode_cursor(cursor)

        account_person = aliased(Person)
        guest_person = aliased(Person)
        claim_person = aliased(Person)
        guest = ConversationGuestSubmission
        usage = ConversationAcquisitionUsage
        claim = ConversationVisitorClaim
        query = (
            select(ConversationRecording)
            .select_from(ConversationRecording)
            .outerjoin(
                account_person,
                account_person.id == ConversationRecording.person_id,
            )
            .outerjoin(
                guest,
                and_(
                    guest.recording_id == ConversationRecording.id,
                    guest.tenant_id == self.operations_tenant_id,
                ),
            )
            .outerjoin(
                usage,
                and_(
                    usage.id == guest.usage_id,
                    usage.tenant_id == self.operations_tenant_id,
                ),
            )
            .outerjoin(
                claim,
                and_(
                    claim.visitor_id == usage.visitor_id,
                    claim.tenant_id == self.operations_tenant_id,
                ),
            )
            .outerjoin(guest_person, guest_person.id == usage.person_id)
            .outerjoin(claim_person, claim_person.id == claim.person_id)
            .where(
                ConversationRecording.tenant_id == self.operations_tenant_id,
                ConversationRecording.state != "deleted",
            )
            .distinct()
        )
        if decoded is not None:
            before_time, before_id = decoded
            query = query.where(
                or_(
                    ConversationRecording.created_at < before_time,
                    and_(
                        ConversationRecording.created_at == before_time,
                        ConversationRecording.id < before_id,
                    ),
                )
            )
        if search:
            search_columns = (
                cast(ConversationRecording.id, String),
                ConversationRecording.source_sha256,
                ConversationRecording.content_type,
                ConversationRecording.state,
                account_person.email,
                account_person.display_name,
                account_person.first_name,
                guest_person.email,
                guest_person.display_name,
                guest_person.first_name,
                claim_person.email,
                claim_person.display_name,
                claim_person.first_name,
            )
            query = query.where(or_(*(_like(column, search) for column in search_columns)))
        rows = (
            await self.database.scalars(
                query.order_by(
                    ConversationRecording.created_at.desc(), ConversationRecording.id.desc()
                ).limit(limit + 1)
            )
        ).all()
        page = rows[:limit]
        if not page:
            return {"items": [], "next_cursor": None}

        recording_ids = [row.id for row in page]
        guest_rows = (
            await self.database.scalars(
                select(ConversationGuestSubmission).where(
                    ConversationGuestSubmission.tenant_id == self.operations_tenant_id,
                    ConversationGuestSubmission.recording_id.in_(recording_ids),
                )
            )
        ).all()
        guests = {row.recording_id: row for row in guest_rows}
        usage_ids = [row.usage_id for row in guest_rows]
        usage_rows = (
            (
                await self.database.scalars(
                    select(ConversationAcquisitionUsage).where(
                        ConversationAcquisitionUsage.tenant_id == self.operations_tenant_id,
                        ConversationAcquisitionUsage.id.in_(usage_ids),
                    )
                )
            ).all()
            if usage_ids
            else []
        )
        usages = {row.id: row for row in usage_rows}
        visitor_ids = [row.visitor_id for row in usage_rows if row.visitor_id is not None]
        claim_rows = (
            (
                await self.database.scalars(
                    select(ConversationVisitorClaim).where(
                        ConversationVisitorClaim.tenant_id == self.operations_tenant_id,
                        ConversationVisitorClaim.visitor_id.in_(visitor_ids),
                    )
                )
            ).all()
            if visitor_ids
            else []
        )
        claims = {row.visitor_id: row for row in claim_rows}
        person_ids = {row.person_id for row in page}
        person_ids.update(row.person_id for row in usage_rows if row.person_id is not None)
        person_ids.update(row.person_id for row in claim_rows)
        person_rows = (
            (await self.database.scalars(select(Person).where(Person.id.in_(person_ids)))).all()
            if person_ids
            else []
        )
        people = {row.id: row for row in person_rows}

        runs = (
            await self.database.scalars(
                select(ConversationRun).where(
                    ConversationRun.tenant_id == self.operations_tenant_id,
                    ConversationRun.recording_id.in_(recording_ids),
                )
            )
        ).all()
        latest_runs = _latest(runs, lambda row: row.recording_id)
        plans = (
            await self.database.scalars(
                select(ConversationProcessingPlan).where(
                    ConversationProcessingPlan.tenant_id == self.operations_tenant_id,
                    ConversationProcessingPlan.recording_id.in_(recording_ids),
                    ConversationProcessingPlan.erased_at.is_(None),
                )
            )
        ).all()
        latest_plans = _latest(plans, lambda row: row.recording_id)
        tasks = (
            await self.database.scalars(
                select(ConversationInferenceTask).where(
                    ConversationInferenceTask.tenant_id == self.operations_tenant_id,
                    ConversationInferenceTask.recording_id.in_(recording_ids),
                    ConversationInferenceTask.erased_at.is_(None),
                )
            )
        ).all()
        latest_tasks = _latest(tasks, lambda row: row.recording_id)
        quote_ids = [row.quote_id for row in tasks]
        quote_rows = (
            (
                await self.database.scalars(
                    select(ConversationQuote).where(
                        ConversationQuote.tenant_id == self.operations_tenant_id,
                        ConversationQuote.id.in_(quote_ids),
                    )
                )
            ).all()
            if quote_ids
            else []
        )
        quotes = {row.id: row for row in quote_rows}
        minute_rows = (
            await self.database.scalars(
                select(ConversationMinuteAccount).where(
                    ConversationMinuteAccount.tenant_id == self.operations_tenant_id,
                    ConversationMinuteAccount.person_id.in_({row.person_id for row in page}),
                )
            )
        ).all()
        minutes = {row.person_id: row for row in minute_rows}
        checkpoints = (
            await self.database.scalars(
                select(ConversationCheckpoint).where(
                    ConversationCheckpoint.tenant_id == self.operations_tenant_id,
                    ConversationCheckpoint.recording_id.in_(recording_ids),
                    ConversationCheckpoint.stage == "C1",
                    ConversationCheckpoint.erased_at.is_(None),
                )
            )
        ).all()
        latest_checkpoints = _latest(checkpoints, lambda row: row.recording_id)
        drafts = (
            await self.database.scalars(
                select(ConversationReportDraft).where(
                    ConversationReportDraft.tenant_id == self.operations_tenant_id,
                    ConversationReportDraft.recording_id.in_(recording_ids),
                    ConversationReportDraft.erased_at.is_(None),
                )
            )
        ).all()
        latest_drafts = _latest(drafts, lambda row: row.recording_id)
        reports = ConversationReports(self.application)

        items: list[dict[str, Any]] = []
        for recording in page:
            guest_row = guests.get(recording.id)
            usage_row = usages.get(guest_row.usage_id) if guest_row is not None else None
            claim_row = (
                claims.get(usage_row.visitor_id)
                if usage_row is not None and usage_row.visitor_id is not None
                else None
            )
            run = latest_runs.get(recording.id)
            plan = latest_plans.get(recording.id)
            draft = latest_drafts.get(recording.id)
            has_report = False
            report_run_id: UUID | None = None
            report_id: UUID | None = None
            if draft is not None:
                try:
                    reports._validated(draft, recording)
                    await reports._canonical_draft(draft, recording)
                    has_report = True
                    report_run_id = draft.run_id
                    report_id = draft.id
                except (ConversationConflict, ConversationError, ValueError, TypeError, KeyError):
                    pass
            report_run = next(
                (candidate for candidate in runs if candidate.id == report_run_id),
                None,
            )
            review_eligible = bool(
                has_report
                and report_run is not None
                and report_run.state == "completed"
                and report_run.generation == recording.generation
                and recording.state == "ready"
            )
            checkpoint = latest_checkpoints.get(recording.id)
            duration_ms = _safe_duration(None if checkpoint is None else checkpoint.payload)
            duration_source = "native_measurement" if duration_ms is not None else None
            if duration_ms is None and usage_row is not None:
                duration_source = "acquisition_allowance"
            items.append(
                {
                    "id": str(recording.id),
                    "owner": _owner_view(recording, guest_row, usage_row, claim_row, people),
                    "uploaded_at": utc(recording.created_at).isoformat(),
                    "recording_state": recording.state,
                    "source": {
                        "bytes": recording.source_bytes,
                        "content_type": recording.content_type,
                        "sha256": recording.source_sha256,
                        "revision": recording.source_revision,
                    },
                    "duration": {
                        "milliseconds": duration_ms,
                        "seconds": (
                            round(duration_ms / 1000, 3)
                            if duration_ms is not None
                            else None
                            if usage_row is None
                            else usage_row.reserved_seconds
                        ),
                        "source": duration_source,
                    },
                    "status": _status(recording, run, plan, has_report=has_report),
                    "latest_run": (
                        None
                        if run is None
                        else {
                            "id": str(run.id),
                            "state": run.state,
                            "generation": run.generation,
                            "recipe_revision": run.recipe_revision,
                            "created_at": utc(run.created_at).isoformat(),
                            "completed_at": None
                            if run.completed_at is None
                            else utc(run.completed_at).isoformat(),
                        }
                    ),
                    "processing_plan": None
                    if plan is None
                    else {"id": str(plan.id), "state": plan.state},
                    "report": {
                        "available": has_report,
                        "id": None if report_id is None else str(report_id),
                        "run_id": None if report_run_id is None else str(report_run_id),
                        "review_eligible": review_eligible,
                        "invite_eligible": review_eligible,
                    },
                    "cost": _cost_view(
                        latest_tasks.get(recording.id),
                        quotes.get(latest_tasks[recording.id].quote_id)
                        if latest_tasks.get(recording.id) is not None
                        else None,
                        minutes.get(recording.person_id),
                    ),
                }
            )
        return {
            "items": items,
            "next_cursor": _cursor(page[-1].created_at, page[-1].id) if len(rows) > limit else None,
        }


__all__ = ["AdminConversationRecordings"]
