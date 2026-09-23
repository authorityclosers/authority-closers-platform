"""Tenant-scoped read-only recording inventory for the AC admin surface.

The admin inventory joins existing canonical rows.  It does not create a
processing run, inspect source bytes, call a provider, or turn a quote into an
actual charge.  In particular, an actual cost is returned only when the
immutable reservation contains a settlement receipt.
"""

from __future__ import annotations

import base64
from collections.abc import Iterable, Mapping, Sequence
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
from ac_platform.conversation_intelligence.admin_pricing import estimate_provider_usage
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
    ConversationDenied,
    ConversationError,
    utc,
)
from ac_platform.conversation_intelligence.entitlements import BudgetAccount, MinuteAccount, Quote
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.models import (
    ConversationBudgetAccount,
    ConversationCheckpoint,
    ConversationCommand,
    ConversationInferenceTask,
    ConversationMinuteAccount,
    ConversationPlanStageAuthorization,
    ConversationProcessingPlan,
    ConversationQuote,
    ConversationRecording,
    ConversationReportDraft,
    ConversationRun,
)
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.conversation_intelligence.recovery_models import (
    ConversationRetainedC5Version,
)
from ac_platform.conversation_intelligence.report_store import ConversationReports
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.outbox.models import Job

_MAX_LIMIT = 50
_MAX_SEARCH = 120
_CURSOR_SEPARATOR = "|"
_PROVIDER_USAGE_KEYS = frozenset(
    {
        "promptTokenCount",
        "candidatesTokenCount",
        "thoughtsTokenCount",
        "cachedContentTokenCount",
        "totalTokenCount",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "input_tokens",
        "output_tokens",
    }
)


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


def _safe_provider_usage(value: Any) -> dict[str, int] | None:
    """Return only the bounded numeric usage counters from a provider receipt."""

    if not isinstance(value, Mapping):
        return None
    usage = {
        key: amount
        for key, amount in value.items()
        if key in _PROVIDER_USAGE_KEYS and type(amount) is int and 0 <= amount <= 1_000_000_000
    }
    return usage or None


def _provider_stage_view(
    task: ConversationInferenceTask,
    job: Job | None,
    *,
    duration_ms: int | None = None,
) -> dict[str, Any]:
    """Expose receipt metadata without treating usage as a provider invoice."""

    receipt = None if job is None else job.provider_receipt
    if not isinstance(receipt, Mapping):
        return {
            "stage": task.stage,
            "run_id": str(task.run_id),
            "state": task.state,
            "provider": None,
            "model": None,
            "request_id": None,
            "usage": None,
            "receipt_state": "not_recorded",
            "cost_state": "not_settled",
            "usage_estimate_paise": None,
            "usage_estimate_state": "usage_unavailable",
            "usage_estimate_basis": None,
            "pricing_snapshot": None,
        }

    provider = receipt.get("provider")
    model = receipt.get("model")
    request_id = receipt.get("provider_request_id")
    cost_state = receipt.get("cost_state")
    safe_provider = provider if isinstance(provider, str) and provider else None
    safe_model = model if isinstance(model, str) and model else None
    safe_usage = _safe_provider_usage(receipt.get("usage"))
    usage_estimate = estimate_provider_usage(
        safe_provider,
        safe_model,
        safe_usage,
        duration_ms=duration_ms if task.stage == "C2" else None,
    )
    return {
        "stage": task.stage,
        "run_id": str(task.run_id),
        "state": task.state,
        "provider": safe_provider,
        "model": safe_model,
        "request_id": request_id if isinstance(request_id, str) and request_id else None,
        "usage": _safe_provider_usage(receipt.get("usage")),
        "receipt_state": "recorded",
        "cost_state": (
            cost_state
            if isinstance(cost_state, str) and cost_state in {"reconciliation_required", "settled"}
            else "not_settled"
        ),
        "usage_estimate_paise": usage_estimate["paise"],
        "usage_estimate_state": usage_estimate["state"],
        "usage_estimate_basis": usage_estimate["basis"],
        "pricing_snapshot": usage_estimate["pricing_snapshot"],
    }


def _iso_or_none(value: Any) -> str | None:
    return None if value is None else utc(value).isoformat()


def _runtime_binding_state(
    recording: ConversationRecording,
    guest: ConversationGuestSubmission | None,
    usage: ConversationAcquisitionUsage | None,
) -> str:
    """Classify the saved-source join without guessing at missing rows."""

    if guest is None or usage is None:
        return "absent"
    checks = (
        getattr(guest, "recording_id", None) == recording.id,
        getattr(guest, "usage_id", None) == usage.id,
        getattr(guest, "submission_id", None) == getattr(usage, "submission_id", None),
        getattr(guest, "source_sha256", None) == recording.source_sha256,
        getattr(usage, "source_sha256", None) == recording.source_sha256,
    )
    return "verified" if all(checks) else "inconsistent"


def _receipt_validation_state(job: Job | None) -> str:
    receipt = None if job is None else job.provider_receipt
    if not isinstance(receipt, Mapping):
        return "not_checked"
    value = receipt.get("validation_state")
    return value if value in {"not_checked", "validated", "invalid"} else "not_checked"


def _runtime_trace(
    recording: ConversationRecording,
    guest: ConversationGuestSubmission | None,
    usage: ConversationAcquisitionUsage | None,
    *,
    plans: Iterable[ConversationProcessingPlan],
    plan_quote_ids: Mapping[UUID, set[UUID]],
    commands: Mapping[UUID, ConversationCommand],
    tasks: Iterable[ConversationInferenceTask],
    jobs: Mapping[UUID, Job],
    c6_checkpoint: ConversationCheckpoint | None,
    has_report: bool,
    recovered_report: bool,
    report_id: UUID | None,
    report_run_id: UUID | None,
) -> dict[str, Any]:
    """Expose read-only evidence for the boundary where a report can stop.

    This deliberately reports unknown/incomplete joins instead of deriving a
    provider state from a plan label or a missing receipt.
    """

    binding_state = _runtime_binding_state(recording, guest, usage)
    plan_rows = sorted(plans, key=lambda row: (utc(row.created_at), row.id))
    plan_views: list[dict[str, Any]] = []
    quote_to_plan: dict[UUID, UUID] = {}
    for plan in plan_rows:
        acceptance_id = getattr(plan, "acceptance_command_id", None)
        command = commands.get(acceptance_id) if acceptance_id is not None else None
        accepted = (
            command is not None
            and command.action == "processing_plan_accepted"
            and command.result_id == plan.id
        )
        plan_views.append(
            {
                "id": str(plan.id),
                "state": plan.state,
                "acceptance_command_id": None if acceptance_id is None else str(acceptance_id),
                "accepted_at": (
                    _iso_or_none(command.created_at) if accepted and command is not None else None
                ),
            }
        )
        for quote_id in plan_quote_ids.get(plan.id, set()):
            quote_to_plan.setdefault(quote_id, plan.id)

    task_views: list[dict[str, Any]] = []
    relationships_complete = True
    for task in sorted(tasks, key=lambda row: (utc(row.created_at), row.run_id)):
        plan_id = quote_to_plan.get(task.quote_id)
        job = jobs.get(task.job_id) if getattr(task, "job_id", None) is not None else None
        if plan_id is None or (getattr(task, "job_id", None) is not None and job is None):
            relationships_complete = False
        task_views.append(
            {
                "run_id": str(task.run_id),
                "job_id": None if getattr(task, "job_id", None) is None else str(task.job_id),
                "plan_id": None if plan_id is None else str(plan_id),
                "stage": task.stage,
                "state": task.state,
                "job_status": None if job is None else getattr(job, "status", None),
                "dispatch_started_at": _iso_or_none(
                    None if job is None else getattr(job, "dispatch_started_at", None)
                ),
                "receipt_validation_state": _receipt_validation_state(job),
            }
        )

    if recovered_report:
        publication_kind = "recovered_draft"
        publication_validation = "not_checked"
    elif has_report:
        publication_kind = "canonical_draft"
        publication_validation = "validated"
    else:
        publication_kind = "none"
        publication_validation = "not_checked"
    submission_id = None if usage is None else getattr(usage, "submission_id", None)
    return {
        "submission_id": None if submission_id is None else str(submission_id),
        "binding_state": binding_state,
        "source_revision": getattr(recording, "source_revision", None),
        "generation": getattr(recording, "generation", None),
        "scope_complete": binding_state == "verified" and relationships_complete,
        "plans": plan_views,
        "tasks": task_views,
        "publication": {
            "kind": publication_kind,
            "report_id": None if report_id is None else str(report_id),
            "run_id": None if report_run_id is None else str(report_run_id),
            "c6_checkpoint_id": None if c6_checkpoint is None else str(c6_checkpoint.id),
            "validation_state": publication_validation,
        },
    }


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
    recovered_report: bool = False,
    report_run_id: UUID | None = None,
    provider_run_ids: frozenset[UUID] = frozenset(),
) -> str:
    if plan is not None and plan.state == "held":
        return "held"
    if plan is not None and plan.state == "active":
        return "processing"
    if plan is not None and plan.state == "cancelled":
        return "cancelled"
    # A native C1 run can be newer than a verified report without invalidating
    # that report. Provider runs, and an explicitly newer plan, do supersede it.
    if (
        has_report
        and not recovered_report
        and (run is None or run.id == report_run_id or run.id not in provider_run_ids)
    ):
        return "completed"
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
    *,
    plan_tasks: Iterable[ConversationInferenceTask] | None = None,
    plan_quote_ids: Iterable[UUID] | None = None,
    quote_rows: Mapping[UUID, ConversationQuote] | None = None,
    budget_rows: Mapping[UUID, ConversationBudgetAccount] | None = None,
    provider_stages: Iterable[Mapping[str, Any]] | None = None,
    scope: str = "recording_total",
) -> dict[str, Any]:
    tasks = list(plan_tasks) if plan_tasks is not None else ([] if task is None else [task])
    quote_by_id = dict(quote_rows or {})
    if task is not None and quote_row is not None:
        quote_by_id.setdefault(task.quote_id, quote_row)

    estimate_quote_ids = (
        set(plan_quote_ids) if plan_quote_ids is not None else {item.quote_id for item in tasks}
    )
    estimates: list[int] = []
    for quote_id in estimate_quote_ids:
        row = quote_by_id.get(quote_id)
        if row is None:
            continue
        try:
            quote = Quote.from_dict(row.quote)
        except (TypeError, ValueError, KeyError):
            continue
        estimates.append(quote.max_cost_paise)

    reservations: dict[str, Any] = {}
    for budget_row in (budget_rows or {}).values():
        try:
            budget_account = BudgetAccount.from_dict(budget_row.snapshot)
        except (TypeError, ValueError, KeyError):
            continue
        reservations.update({item.reservation_id: item for item in budget_account.reservations})
    if minute_row is not None:
        try:
            minute_account = MinuteAccount.from_dict(minute_row.snapshot)
            for reservation in minute_account.reservations:
                reservations.setdefault(reservation.reservation_id, reservation)
        except (TypeError, ValueError, KeyError):
            pass

    task_reservations = [reservations.get(str(item.run_id)) for item in tasks]
    complete_reservations = bool(tasks) and all(item is not None for item in task_reservations)
    reservation_values = [item for item in task_reservations if item is not None]
    reservation_paise = (
        sum(item.quote.max_cost_paise for item in reservation_values)
        if complete_reservations
        else None
    )
    settlement_values = [item.settlement for item in reservation_values]
    actual = (
        sum(item.actual_paise for item in settlement_values if item is not None)
        if complete_reservations and all(item is not None for item in settlement_values)
        else None
    )
    states = {item.state for item in reservation_values}
    if not complete_reservations:
        state: str | None = None
    elif len(states) == 1:
        state = next(iter(states))
    elif "reconciliation_required" in states:
        state = "reconciliation_required"
    elif states & {"in_flight", "uncertain"}:
        state = "uncertain" if "uncertain" in states else "in_flight"
    elif "reserved" in states:
        state = "reserved"
    elif "settled" in states:
        state = "settled"
    elif "released" in states:
        state = "released"
    else:
        state = next(iter(states))
    provider_stage_values = list(provider_stages or ())
    available_stage_values = [
        stage["usage_estimate_paise"]
        for stage in provider_stage_values
        if stage.get("usage_estimate_state") == "available"
        and type(stage.get("usage_estimate_paise")) is int
    ]
    estimate_states = {stage.get("usage_estimate_state") for stage in provider_stage_values}
    if provider_stage_values and len(available_stage_values) == len(provider_stage_values):
        usage_estimate_state = "available"
        usage_estimate_paise = sum(available_stage_values)
    elif available_stage_values:
        usage_estimate_state = "partial"
        usage_estimate_paise = sum(available_stage_values)
    elif "rate_unavailable" in estimate_states:
        usage_estimate_state = "rate_unavailable"
        usage_estimate_paise = None
    elif provider_stage_values:
        usage_estimate_state = "usage_unavailable"
        usage_estimate_paise = None
    else:
        usage_estimate_state = "not_applicable"
        usage_estimate_paise = None
    snapshots = [
        stage["pricing_snapshot"]
        for stage in provider_stage_values
        if isinstance(stage.get("pricing_snapshot"), Mapping)
    ]
    snapshot_dates = {snapshot.get("source_date") for snapshot in snapshots}
    snapshot_fx = {snapshot.get("usd_to_inr") for snapshot in snapshots}
    usage_snapshot = (
        snapshots[0]
        if available_stage_values
        and snapshots
        and len(snapshot_dates) == 1
        and len(snapshot_fx) == 1
        else None
    )
    return {
        "currency": "INR",
        "scope": scope,
        "reservation_paise": reservation_paise,
        "estimate_paise": sum(estimates) if estimates else None,
        "actual_paise": actual,
        "reservation_state": state,
        "actual_state": (
            "settled"
            if actual is not None
            else "reconciliation_required"
            if state == "reconciliation_required"
            else "not_settled"
        ),
        # The canonical receipt stores usage counters but not the rate.  The
        # immutable release snapshot supplies a planning rate when units match;
        # keep that estimate separate from quote ceiling and settlement.
        "usage_estimate_paise": usage_estimate_paise,
        "usage_estimate_state": usage_estimate_state,
        "usage_estimate_basis": (
            "provider_usage_x_approved_planning_rates" if available_stage_values else None
        ),
        "usage_estimate_currency": (
            usage_snapshot.get("currency") if usage_snapshot is not None else None
        ),
        "usage_estimate_fx_usd_to_inr": (
            usage_snapshot.get("usd_to_inr") if usage_snapshot is not None else None
        ),
        "usage_estimate_source_date": (
            usage_snapshot.get("source_date") if usage_snapshot is not None else None
        ),
        "usage_estimate_is_billing_rate": False if available_stage_values else None,
    }


class AdminConversationRecordings:
    """Operations-tenant recording inventory with immutable read scope."""

    def __init__(
        self,
        application: ConversationApplication,
        operations_tenant_id: UUID,
        *,
        recording_tenant_ids: Sequence[UUID] | None = None,
        recovery_enabled: bool = False,
    ) -> None:
        self.application = application
        self.database: AsyncSession = application.database
        self.operations_tenant_id = operations_tenant_id
        self.recovery_enabled = recovery_enabled
        candidates = (operations_tenant_id, *(recording_tenant_ids or ()))
        if any(type(identifier) is not UUID for identifier in candidates):
            raise ValueError("recording tenant scope must contain UUIDs")
        self.recording_tenant_ids = tuple(dict.fromkeys(candidates))

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
                    guest.tenant_id == ConversationRecording.tenant_id,
                ),
            )
            .outerjoin(
                usage,
                and_(
                    usage.id == guest.usage_id,
                    usage.tenant_id == guest.tenant_id,
                ),
            )
            .outerjoin(
                claim,
                and_(
                    claim.visitor_id == usage.visitor_id,
                    claim.tenant_id == usage.tenant_id,
                ),
            )
            .outerjoin(guest_person, guest_person.id == usage.person_id)
            .outerjoin(claim_person, claim_person.id == claim.person_id)
            .where(
                ConversationRecording.tenant_id.in_(self.recording_tenant_ids),
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
                    ConversationGuestSubmission.tenant_id.in_(self.recording_tenant_ids),
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
                        ConversationAcquisitionUsage.tenant_id.in_(self.recording_tenant_ids),
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
                        ConversationVisitorClaim.tenant_id.in_(self.recording_tenant_ids),
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
                    ConversationRun.tenant_id.in_(self.recording_tenant_ids),
                    ConversationRun.recording_id.in_(recording_ids),
                )
            )
        ).all()
        latest_runs = _latest(runs, lambda row: row.recording_id)
        plans = (
            await self.database.scalars(
                select(ConversationProcessingPlan).where(
                    ConversationProcessingPlan.tenant_id.in_(self.recording_tenant_ids),
                    ConversationProcessingPlan.recording_id.in_(recording_ids),
                    ConversationProcessingPlan.erased_at.is_(None),
                )
            )
        ).all()
        latest_plans = _latest(plans, lambda row: row.recording_id)
        tasks = (
            await self.database.scalars(
                select(ConversationInferenceTask).where(
                    ConversationInferenceTask.tenant_id.in_(self.recording_tenant_ids),
                    ConversationInferenceTask.recording_id.in_(recording_ids),
                    ConversationInferenceTask.erased_at.is_(None),
                )
            )
        ).all()
        task_job_ids = {task.job_id for task in tasks if getattr(task, "job_id", None) is not None}
        jobs = (
            (
                await self.database.scalars(
                    select(Job).where(
                        Job.id.in_(task_job_ids),
                        Job.tenant_id.in_(self.recording_tenant_ids),
                    )
                )
            ).all()
            if task_job_ids
            else []
        )
        jobs_by_id = {job.id: job for job in jobs}
        # Keep every non-erased plan in the bounded page so an old task can be
        # tied to the exact plan that authorized it.  The display/cost view
        # still uses latest_plans below.
        plan_ids = {row.id for row in plans}
        plan_stage_rows = (
            (
                await self.database.scalars(
                    select(ConversationPlanStageAuthorization).where(
                        ConversationPlanStageAuthorization.tenant_id.in_(self.recording_tenant_ids),
                        ConversationPlanStageAuthorization.plan_id.in_(plan_ids),
                    )
                )
            ).all()
            if plan_ids
            else []
        )
        plan_quote_ids: dict[UUID, set[UUID]] = {}
        for stage_row in plan_stage_rows:
            plan_quote_ids.setdefault(stage_row.plan_id, set()).add(stage_row.quote_id)
        acceptance_command_ids = {
            row.acceptance_command_id
            for row in plans
            if getattr(row, "acceptance_command_id", None) is not None
        }
        command_rows = (
            (
                await self.database.scalars(
                    select(ConversationCommand).where(
                        ConversationCommand.tenant_id.in_(self.recording_tenant_ids),
                        ConversationCommand.id.in_(acceptance_command_ids),
                    )
                )
            ).all()
            if acceptance_command_ids
            else []
        )
        commands = {row.id: row for row in command_rows}
        quote_ids = [row.quote_id for row in tasks]
        for stage_quote_ids in plan_quote_ids.values():
            quote_ids.extend(stage_quote_ids)
        quote_ids = list(set(quote_ids))
        quote_rows = (
            (
                await self.database.scalars(
                    select(ConversationQuote).where(
                        ConversationQuote.tenant_id.in_(self.recording_tenant_ids),
                        ConversationQuote.id.in_(quote_ids),
                    )
                )
            ).all()
            if quote_ids
            else []
        )
        quotes = {row.id: row for row in quote_rows}
        budget_scope_ids = {
            row.budget_scope_id for row in quote_rows if row.budget_scope_id is not None
        }
        budget_rows = (
            (
                await self.database.scalars(
                    select(ConversationBudgetAccount).where(
                        ConversationBudgetAccount.scope_id.in_(budget_scope_ids)
                    )
                )
            ).all()
            if budget_scope_ids
            else []
        )
        budgets = {row.scope_id: row for row in budget_rows}
        minute_rows = (
            await self.database.scalars(
                select(ConversationMinuteAccount).where(
                    ConversationMinuteAccount.tenant_id.in_(self.recording_tenant_ids),
                    ConversationMinuteAccount.person_id.in_({row.person_id for row in page}),
                )
            )
        ).all()
        minutes = {(row.tenant_id, row.person_id): row for row in minute_rows}
        checkpoints = (
            await self.database.scalars(
                select(ConversationCheckpoint).where(
                    ConversationCheckpoint.tenant_id.in_(self.recording_tenant_ids),
                    ConversationCheckpoint.recording_id.in_(recording_ids),
                    ConversationCheckpoint.stage.in_(("C1", "C6")),
                    ConversationCheckpoint.erased_at.is_(None),
                )
            )
        ).all()
        latest_checkpoints = _latest(
            (row for row in checkpoints if row.stage == "C1"), lambda row: row.recording_id
        )
        latest_c6_checkpoints = _latest(
            (row for row in checkpoints if row.stage == "C6"), lambda row: row.recording_id
        )
        drafts = (
            await self.database.scalars(
                select(ConversationReportDraft).where(
                    ConversationReportDraft.tenant_id.in_(self.recording_tenant_ids),
                    ConversationReportDraft.recording_id.in_(recording_ids),
                    ConversationReportDraft.erased_at.is_(None),
                )
            )
        ).all()
        latest_drafts = _latest(drafts, lambda row: row.recording_id)
        if self.recovery_enabled:
            recoveries = (
                await self.database.scalars(
                    select(ConversationRetainedC5Version).where(
                        ConversationRetainedC5Version.tenant_id.in_(self.recording_tenant_ids),
                        ConversationRetainedC5Version.recording_id.in_(recording_ids),
                        ConversationRetainedC5Version.erased_at.is_(None),
                        ConversationRetainedC5Version.payload.is_not(None),
                    )
                )
            ).all()
            latest_recoveries = _latest(recoveries, lambda row: row.recording_id)
        else:
            latest_recoveries = {}
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
            recovered = latest_recoveries.get(recording.id)
            if recovered is not None and recovered.generation != recording.generation:
                recovered = None
            has_report = False
            recovered_report = False
            report_run_id: UUID | None = None
            report_id: UUID | None = None
            if recovered is not None:
                # A retained recovery version is the read authority for this
                # report, while the failed provider run remains the status and
                # cost authority in the inventory.
                has_report = True
                recovered_report = True
                report_run_id = recovered.run_id
                report_id = recovered.id
            elif draft is not None:
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
            provider_run_ids = frozenset(
                candidate.run_id for candidate in tasks if hasattr(candidate, "run_id")
            )
            current_plan_quote_ids = (
                plan_quote_ids.get(plan.id, set()) if plan is not None else None
            )
            recording_tasks = [
                candidate for candidate in tasks if candidate.recording_id == recording.id
            ]
            current_plan_tasks = (
                [candidate for candidate in tasks if candidate.quote_id in current_plan_quote_ids]
                if current_plan_quote_ids is not None
                else recording_tasks
            )
            plan_is_complete = (
                plan is not None
                and current_plan_quote_ids is not None
                and all(
                    candidate.quote_id in current_plan_quote_ids for candidate in recording_tasks
                )
            )
            cost_tasks = current_plan_tasks if plan_is_complete else recording_tasks
            cost_quote_ids = (
                current_plan_quote_ids
                if plan_is_complete
                else {candidate.quote_id for candidate in recording_tasks}
            )
            checkpoint = latest_checkpoints.get(recording.id)
            c6_checkpoint = latest_c6_checkpoints.get(recording.id)
            duration_ms = _safe_duration(None if checkpoint is None else checkpoint.payload)
            duration_source = "native_measurement" if duration_ms is not None else None
            if duration_ms is None and usage_row is not None:
                duration_source = "acquisition_allowance"
            provider_stages = [
                _provider_stage_view(
                    candidate,
                    jobs_by_id.get(job_id)
                    if isinstance(job_id := getattr(candidate, "job_id", None), UUID)
                    else None,
                    duration_ms=duration_ms,
                )
                for candidate in sorted(
                    cost_tasks,
                    key=lambda candidate: (utc(candidate.created_at), candidate.run_id),
                )
            ]
            review_eligible = bool(
                has_report
                and report_run is not None
                and report_run.state == "completed"
                and report_run.generation == recording.generation
                and recording.state == "ready"
            )
            items.append(
                {
                    "id": str(recording.id),
                    # Acquisition owns a distinct submission namespace. Keep
                    # the join visible to Admin so operators never have to
                    # probe recording/run UUIDs against owner-facing routes.
                    "submission_id": (None if usage_row is None else str(usage_row.submission_id)),
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
                    "status": _status(
                        recording,
                        run,
                        plan,
                        has_report=has_report,
                        recovered_report=recovered_report,
                        report_run_id=report_run_id,
                        provider_run_ids=provider_run_ids,
                    ),
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
                            "provider_stages": provider_stages,
                        }
                    ),
                    "processing_plan": None
                    if plan is None
                    else {"id": str(plan.id), "state": plan.state},
                    "runtime_trace": _runtime_trace(
                        recording,
                        guest_row,
                        usage_row,
                        plans=(
                            candidate
                            for candidate in plans
                            if candidate.recording_id == recording.id
                        ),
                        plan_quote_ids={
                            candidate.id: plan_quote_ids.get(candidate.id, set())
                            for candidate in plans
                            if candidate.recording_id == recording.id
                        },
                        commands=commands,
                        tasks=recording_tasks,
                        jobs=jobs_by_id,
                        c6_checkpoint=c6_checkpoint,
                        has_report=has_report,
                        recovered_report=recovered_report,
                        report_id=report_id,
                        report_run_id=report_run_id,
                    ),
                    "report": {
                        "available": has_report,
                        "id": None if report_id is None else str(report_id),
                        "run_id": None if report_run_id is None else str(report_run_id),
                        "review_eligible": review_eligible,
                        "invite_eligible": review_eligible,
                        "recovery": (
                            None
                            if recovered is None
                            else {
                                "validation_state": recovered.validation_state,
                                "provider_calls": 0,
                                "review_origin": recovered.review_origin,
                            }
                        ),
                    },
                    "cost": _cost_view(
                        cost_tasks[-1] if cost_tasks else None,
                        quotes.get(cost_tasks[-1].quote_id) if cost_tasks else None,
                        minutes.get((recording.tenant_id, recording.person_id)),
                        plan_tasks=cost_tasks,
                        plan_quote_ids=cost_quote_ids,
                        quote_rows=quotes,
                        budget_rows=budgets,
                        provider_stages=provider_stages,
                        scope="current_plan" if plan_is_complete else "recording_total",
                    ),
                }
            )
        return {
            "items": items,
            "next_cursor": _cursor(page[-1].created_at, page[-1].id) if len(rows) > limit else None,
        }


__all__ = ["AdminConversationRecordings"]
