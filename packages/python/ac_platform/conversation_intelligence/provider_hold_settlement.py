"""Settle provider budget holds left uncertain after a successful, receipted call.

Every hosted provider stage (C2 transcription, C4 facts, C5 coaching) ends with
its budget reservation in the ``uncertain`` state, referenced
``provider-cost-reconciliation:<run id>`` by ``inference_worker``. The step that
turns the provider's usage into a settled cost was never built. Each hold keeps
the full quoted maximum (about Rs 21) while the call really cost about Rs 1-5,
so budget caps fill with spend that never happened and analyses get refused.

Owner decision, 17 Oct 2026 ("fix this"): settle them at list price from the
provider's own usage counters on the job's final receipt, using the planning
rates in ``admin_pricing``. The settlement receipt says so
(``list-price-estimate:<pricing ref>:job:<job id>``), so a later invoice
reconciliation can supersede it. A hold is settled only when its single task's
job succeeded with a validated receipt for the same provider and model, and the
estimate fits within the quoted maximum. Customer minutes are untouched: the
settled seconds equal the quoted entitlement. Everything else stays on hold.

Owner approval, 19 Oct 2026 ("Yes: settle AI budget holds automatically at list
price when a validated provider receipt lands"): ``settle_on_receipt`` applies
the same rules inside the worker's receipt transaction, so a hold settles the
moment its receipt is saved, once, with an audit event naming the approval.
Holds whose provider outcome is unknown, and older holds these rules can't
price, stay open for an invoice check.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.admin_pricing import estimate_provider_usage
from ac_platform.conversation_intelligence.entitlements import (
    BudgetAccount,
    MinuteAccount,
    Reservation,
    SettlementReceipt,
    settle,
)
from ac_platform.conversation_intelligence.models import (
    ConversationBudgetAccount,
    ConversationCheckpoint,
    ConversationInferenceTask,
    ConversationMinuteAccount,
)
from ac_platform.outbox.models import Job

ACTION = "conversation.provider_holds_settled"
AUTO_ACTION = "conversation.provider_hold_settled"
APPROVAL = (
    "owner 19 Oct 2026: settle AI budget holds automatically at list price "
    "when a validated provider receipt lands"
)
UNCERTAIN_PREFIX = "provider-cost-reconciliation:"
RECEIPT_PREFIX = "list-price-estimate"
_RECEIPT_SCHEMA = "ac.sales-xray.provider-receipt/1"


@dataclass(frozen=True)
class _Planned:
    reservation_id: str
    tenant_id: UUID
    person_id: UUID
    receipt: SettlementReceipt
    held_paise: int


async def _duration_ms(db: AsyncSession, task: ConversationInferenceTask) -> int | None:
    value = (task.intent or {}).get("duration_ms")
    if type(value) is int and value > 0:
        return value
    if task.checkpoint_id is None:
        return None
    checkpoint = await db.get(ConversationCheckpoint, task.checkpoint_id)
    payload = checkpoint.payload if checkpoint is not None else None
    value = payload.get("duration_ms") if isinstance(payload, dict) else None
    return value if type(value) is int and value > 0 else None


def list_price_receipt(
    reservation: Reservation,
    receipt: Any,
    *,
    job_id: UUID,
    job_succeeded: bool,
    tenant_id: UUID,
    duration_ms: int | None,
) -> tuple[SettlementReceipt | None, str]:
    """The list-price settlement for one open hold, or why it must stay open."""

    quote = reservation.quote
    if reservation.uncertainty_ref != f"{UNCERTAIN_PREFIX}{reservation.reservation_id}":
        return None, "other_uncertainty"
    if (
        not job_succeeded
        or not isinstance(receipt, dict)
        or receipt.get("schema") != _RECEIPT_SCHEMA
        or receipt.get("validation_state") != "validated"
        or receipt.get("cost_state") != "reconciliation_required"
    ):
        return None, "no_final_receipt"
    if (receipt.get("provider"), receipt.get("model")) != (
        quote.provider_id,
        quote.provider_model,
    ) or str(tenant_id) != quote.source.tenant_id:
        return None, "receipt_does_not_match_quote"
    estimate = estimate_provider_usage(
        quote.provider_id,
        quote.provider_model,
        receipt.get("usage") if isinstance(receipt.get("usage"), dict) else None,
        duration_ms=duration_ms,
    )
    paise = estimate["paise"]
    if estimate["state"] != "available" or type(paise) is not int:
        return None, "usage_or_rate_unavailable"
    if paise > quote.max_cost_paise:
        return None, "estimate_above_quote"
    pricing_ref = str((estimate["pricing_snapshot"] or {}).get("pricing_ref") or "unknown")
    if reservation.attempt_id is None:  # the ledger forbids this; never guess one
        return None, "attempt_missing"
    return (
        SettlementReceipt(
            reservation_id=reservation.reservation_id,
            quote_fingerprint=quote.fingerprint,
            provider_id=quote.provider_id,
            attempt_id=reservation.attempt_id,
            actual_seconds=quote.entitlement_seconds,
            actual_paise=paise,
            receipt_ref=f"{RECEIPT_PREFIX}:{pricing_ref}:job:{job_id}",
        ),
        "planned",
    )


async def _plan(
    db: AsyncSession, reservation: Reservation, skipped: Counter[str]
) -> _Planned | None:
    try:
        run_id = UUID(reservation.reservation_id)
    except ValueError:
        skipped["reservation_not_a_run"] += 1
        return None
    if reservation.uncertainty_ref != f"{UNCERTAIN_PREFIX}{run_id}":
        skipped["other_uncertainty"] += 1
        return None
    tasks = (
        await db.scalars(
            select(ConversationInferenceTask).where(ConversationInferenceTask.run_id == run_id)
        )
    ).all()
    if len(tasks) != 1 or tasks[0].job_id is None:
        skipped["task_missing_or_ambiguous"] += 1
        return None
    task = tasks[0]
    job = await db.get(Job, task.job_id)
    if job is None:
        skipped["no_final_receipt"] += 1
        return None
    receipt, reason = list_price_receipt(
        reservation,
        job.provider_receipt,
        job_id=job.id,
        job_succeeded=job.status == "succeeded",
        tenant_id=task.tenant_id,
        duration_ms=await _duration_ms(db, task),
    )
    if receipt is None:
        skipped[reason] += 1
        return None
    return _Planned(
        reservation_id=reservation.reservation_id,
        tenant_id=task.tenant_id,
        person_id=task.person_id,
        receipt=receipt,
        held_paise=reservation.quote.max_cost_paise,
    )


def _committed(budget: BudgetAccount) -> int:
    return sum(reservation.committed_paise for reservation in budget.reservations)


async def settle_provider_holds(
    db: AsyncSession,
    *,
    apply: bool,
    approver: str,
    issue: str,
    now: datetime,
) -> dict[str, Any]:
    """Plan (and with ``apply``, write) settlements for every budget scope.

    Runs inside the caller's single transaction. A dry run reads without row
    locks and writes nothing. Idempotent: a settled hold is never planned again.
    """
    query = select(ConversationBudgetAccount).order_by(ConversationBudgetAccount.scope_id)
    rows = (await db.scalars(query.with_for_update() if apply else query)).all()
    scopes: list[dict[str, Any]] = []
    audits: defaultdict[tuple[UUID, UUID], Counter[str]] = defaultdict(Counter)
    for row in rows:
        budget = BudgetAccount.from_dict(row.snapshot)
        before = _committed(budget)
        skipped: Counter[str] = Counter()
        planned: dict[tuple[UUID, UUID], list[_Planned]] = defaultdict(list)
        for reservation in budget.reservations:
            if reservation.state != "uncertain":
                continue
            item = await _plan(db, reservation, skipped)
            if item is not None:
                planned[(item.tenant_id, item.person_id)].append(item)
        settled = settled_paise = 0
        for (tenant_id, person_id), items in sorted(planned.items(), key=str):
            account_query = select(ConversationMinuteAccount).where(
                ConversationMinuteAccount.tenant_id == tenant_id,
                ConversationMinuteAccount.person_id == person_id,
            )
            account = await db.scalar(account_query.with_for_update() if apply else account_query)
            if account is None:
                skipped["minute_account_missing"] += len(items)
                continue
            minutes = MinuteAccount.from_dict(account.snapshot)
            changed = False
            for item in items:
                try:
                    transition = settle(minutes, budget, item.reservation_id, item.receipt)
                except ValueError:
                    skipped["ledger_refused"] += 1
                    continue
                minutes, budget = transition.minutes, transition.budget
                if transition.changed:
                    changed = True
                    settled += 1
                    settled_paise += item.receipt.actual_paise
                    audits[(tenant_id, row.scope_id)]["settled"] += 1
                    audits[(tenant_id, row.scope_id)]["settled_paise"] += item.receipt.actual_paise
                    audits[(tenant_id, row.scope_id)]["released_paise"] += (
                        item.held_paise - item.receipt.actual_paise
                    )
            if changed and apply:
                account.snapshot = minutes.as_dict()
                account.revision += 1
        if settled and apply:
            row.snapshot = budget.as_dict()
            row.revision += 1
        scopes.append(
            {
                "scope_id": str(row.scope_id),
                "cap_paise": budget.cap_paise,
                "committed_paise_before": before,
                "committed_paise_after": _committed(budget),
                "settled": settled,
                "settled_paise": settled_paise,
                "still_uncertain": sum(r.state == "uncertain" for r in budget.reservations),
                "skipped": dict(sorted(skipped.items())),
            }
        )
    events = 0
    if apply:
        repository = AuditRepository(db)
        for (tenant_id, scope_id), counts in sorted(audits.items(), key=str):
            await repository.append(
                tenant_id=tenant_id,
                actor_person_id=None,
                actor_type="operator",
                action=ACTION,
                resource_type="conversation_budget_account",
                resource_id=scope_id,
                payload={
                    "schema": "ac.sales-xray.provider-holds-settled/1",
                    "basis": RECEIPT_PREFIX,
                    "approver": approver,
                    "issue": issue,
                    **dict(counts),
                },
                reason=f"Owner-approved settlement of stuck provider holds ({issue}).",
                now=now,
            )
            events += 1
    return {
        "applied": apply,
        "approver": approver,
        "issue": issue,
        "scopes": scopes,
        "audit_events": events,
    }


async def settle_on_receipt(
    db: AsyncSession,
    *,
    minutes_row: ConversationMinuteAccount,
    budget_row: ConversationBudgetAccount,
    task: ConversationInferenceTask,
    job_id: UUID,
    receipt: Any,
    now: datetime,
) -> bool:
    """Settle one hold at list price as its validated receipt is saved (owner, 19 Oct).

    Runs inside the worker's receipt transaction, on the account rows it has
    just updated. Idempotent: a settled hold is left as it is and no second
    audit event is written. A hold these rules can't price stays open.
    """

    minutes = MinuteAccount.from_dict(minutes_row.snapshot)
    budget = BudgetAccount.from_dict(budget_row.snapshot)
    reservation = next(
        (r for r in budget.reservations if r.reservation_id == str(task.run_id)), None
    )
    if reservation is None or reservation.state != "uncertain":
        return False
    settlement, _reason = list_price_receipt(
        reservation,
        receipt,
        job_id=job_id,
        job_succeeded=True,
        tenant_id=task.tenant_id,
        duration_ms=await _duration_ms(db, task),
    )
    if settlement is None:
        return False
    transition = settle(minutes, budget, reservation.reservation_id, settlement)
    if not transition.changed:
        return False
    minutes_row.snapshot = transition.minutes.as_dict()
    budget_row.snapshot = transition.budget.as_dict()
    minutes_row.revision += 1
    budget_row.revision += 1
    await AuditRepository(db).append(
        tenant_id=task.tenant_id,
        actor_person_id=None,
        actor_type="system",
        action=AUTO_ACTION,
        resource_type="conversation_budget_account",
        resource_id=budget_row.scope_id,
        payload={
            "schema": "ac.sales-xray.provider-hold-settled/1",
            "basis": RECEIPT_PREFIX,
            "approval": APPROVAL,
            "reservation_id": reservation.reservation_id,
            "job_id": str(job_id),
            "receipt_ref": settlement.receipt_ref,
            "settled_paise": settlement.actual_paise,
            "released_paise": reservation.quote.max_cost_paise - settlement.actual_paise,
        },
        reason="Settled at list price when the validated provider receipt was saved.",
        now=now,
    )
    return True
