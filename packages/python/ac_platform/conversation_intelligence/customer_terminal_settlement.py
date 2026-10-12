"""Canonical customer failure writer; no worker/HTTP activation in this slice.

Admission/source/usage locks, acquisition receipt, existing Report minute journal,
paired provider snapshots and audit share a single transaction. Provider evidence
and cost exposure survive customer release. No grant or no-work receipt is made.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionSettlement,
    ConversationAcquisitionUsage,
)
from ac_platform.conversation_intelligence.application import ConversationConflict
from ac_platform.conversation_intelligence.customer_failure_candidate import (
    locked_recovered_customer_failure,
)
from ac_platform.conversation_intelligence.customer_terminal_receipt import (
    CustomerTerminalFailureReceipt,
    validate_terminal_failure_binding,
)
from ac_platform.conversation_intelligence.entitlements import (
    BudgetAccount,
    ExecutionPermission,
    MinuteAccount,
    Quote,
    record_customer_terminal_failure,
)
from ac_platform.conversation_intelligence.models import (
    ConversationBudgetAccount,
    ConversationInferenceTask,
    ConversationMinuteAccount,
    ConversationQuote,
)
from ac_platform.conversation_intelligence.processing_actor import ProcessingActor
from ac_platform.conversation_intelligence.report_minutes import ReportMinutes

ACTION = "conversation.customer_terminal_failure_settled"


@dataclass(frozen=True)
class CustomerTerminalSettlement:
    usage_id: UUID
    receipt_sha256: str
    changed: bool


def _conflict() -> ConversationConflict:
    return ConversationConflict("The customer failure conflicts with its canonical reservation.")


async def _source_snapshots(
    database: AsyncSession,
    actor: ProcessingActor,
    receipt: CustomerTerminalFailureReceipt,
    *,
    task_state: str,
    replay: bool = False,
) -> None:
    # Discover scopes without taking the minute lock; workers acquire budgets
    # before minutes. Recheck discovery after all locks, never reverse that order.
    minute_row = await database.get(
        ConversationMinuteAccount, (actor.tenant_id, actor.person_id), populate_existing=True
    )
    if minute_row is None:
        raise _conflict()
    initial = MinuteAccount.from_dict(minute_row.snapshot)
    scopes = {
        UUID(item.quote.budget_scope_id)
        for item in initial.reservations
        if item.quote.source == receipt.source
    }
    if not scopes:
        raise _conflict()
    budgets = {}
    for scope in sorted(scopes, key=str):
        row = await database.scalar(
            select(ConversationBudgetAccount)
            .where(ConversationBudgetAccount.scope_id == scope)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise _conflict()
        budgets[scope] = row
    minute_row = await database.scalar(
        select(ConversationMinuteAccount)
        .where(
            ConversationMinuteAccount.tenant_id == actor.tenant_id,
            ConversationMinuteAccount.person_id == actor.person_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if minute_row is None:
        raise _conflict()
    minutes = MinuteAccount.from_dict(minute_row.snapshot)
    if (minutes.tenant_id, minutes.account_id) != (str(actor.tenant_id), str(actor.person_id)):
        raise _conflict()
    matching = [item for item in minutes.reservations if item.quote.source == receipt.source]
    if {UUID(item.quote.budget_scope_id) for item in matching} != scopes:
        raise _conflict()
    snapshots = {scope: BudgetAccount.from_dict(row.snapshot) for scope, row in budgets.items()}
    changed_scopes = set()
    for item in matching:
        quoted = await database.get(ConversationQuote, UUID(item.quote.quote_id))
        if quoted is None or (
            quoted.tenant_id,
            quoted.person_id,
            str(quoted.recording_id),
            quoted.budget_scope_id,
            Quote.from_dict(quoted.quote),
            ExecutionPermission.from_dict(quoted.execution_permission),
        ) != (
            actor.tenant_id,
            actor.person_id,
            receipt.source.recording_id,
            UUID(item.quote.budget_scope_id),
            item.quote,
            item.permission,
        ):
            raise _conflict()
        scope = quoted.budget_scope_id
        transition = record_customer_terminal_failure(
            minutes,
            snapshots[scope],
            item.reservation_id,
            receipt,
            receipt,
            run_state="failed",
            task_state=task_state,
            report_published=False,
        )
        minutes, snapshots[scope] = transition.minutes, transition.budget
        if replay and transition.changed:
            raise _conflict()
        if transition.changed:
            changed_scopes.add(scope)
    if changed_scopes:
        minute_row.snapshot = minutes.as_dict()
        minute_row.revision += 1
        for scope in changed_scopes:
            row = budgets[scope]
            row.snapshot = snapshots[scope].as_dict()
            row.revision += 1


async def settle_recovered_customer_failure(
    database: AsyncSession,
    *,
    actor: ProcessingActor,
    run_id: UUID,
    event_id: UUID,
    receipt: CustomerTerminalFailureReceipt,
) -> CustomerTerminalSettlement:
    """Revalidate exact failed-work evidence; identical committed replay is a no-op.

    Only the retained provider-recovery event path is admitted here. Ordinary
    failure/C1 and attempt authority require their own controlled source adapter.
    A fresh session is required; any exception rolls back every appended fact.
    """
    async with locked_recovered_customer_failure(
        database, actor=actor, run_id=run_id, event_id=event_id, allow_terminal_replay=True
    ) as canonical:
        task = await database.get(ConversationInferenceTask, run_id)
        assert task is not None
        try:
            validate_terminal_failure_binding(
                receipt,
                canonical,
                run_state="failed",
                task_state=task.state,
                report_published=False,
            )
        except ValueError:
            raise _conflict() from None
        usage_id = UUID(canonical.usage_id)
        previous = await database.get(ConversationAcquisitionSettlement, usage_id)
        journal = ReportMinutes(database)
        latest = await journal.latest(usage_id)
        key = f"terminal-failure:{canonical.run_id}"
        if previous is not None:
            if latest is None or (latest.kind, latest.seconds, latest.key) != ("released", 0, key):
                raise _conflict()
            await _source_snapshots(database, actor, canonical, task_state=task.state, replay=True)
            usage = await database.get(ConversationAcquisitionUsage, usage_id)
            assert usage is not None
            await journal._append(usage, latest, key=key, kind="released")
            return CustomerTerminalSettlement(usage_id, canonical.fingerprint, False)
        if latest is not None and latest.kind != "reserved":
            # Never silently replace an old release or delivered journal event.
            raise _conflict()
        if latest is not None and latest.plan_id is not None:
            # This bounded recovery adapter is not a terminal-plan adapter.
            raise _conflict()
        await _source_snapshots(database, actor, canonical, task_state=task.state)
        usage = await database.get(ConversationAcquisitionUsage, usage_id)
        assert usage is not None
        now = datetime.now(UTC)
        database.add(
            ConversationAcquisitionSettlement(
                usage_id=usage_id,
                charged_seconds=0,
                kind="terminal_failure",
                receipt_sha256=canonical.fingerprint,
                created_at=now,
            )
        )
        await journal._append(usage, latest, key=key, kind="released")
        await AuditRepository(database).append(
            tenant_id=actor.tenant_id,
            actor_type="system",
            actor_person_id=None,
            action=ACTION,
            resource_type="conversation_acquisition_usage",
            resource_id=usage_id,
            payload={
                "schema": "ac.sales-xray.customer-terminal-settlement/1",
                "receipt": canonical.as_dict(),
                "receipt_sha256": canonical.fingerprint,
                "charged_seconds": 0,
                "minute_event_revision": 1 if latest is None else latest.revision + 1,
            },
            now=now,
        )
        return CustomerTerminalSettlement(usage_id, canonical.fingerprint, True)
