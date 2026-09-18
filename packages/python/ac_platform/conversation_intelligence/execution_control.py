"""Pause new provider effects independently of saved recordings and reports.

The worker and Admin command serialize the durable effect-start decision under
a short transaction lock. Ordinary quote checks do not take that lock: the final
effect fence closes the race without reversing existing identity lock order.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
    ConversationDenied,
    ConversationError,
    utc,
)
from ac_platform.conversation_intelligence.entitlements import BudgetAccount
from ac_platform.conversation_intelligence.execution_control_models import (
    ConversationExecutionControl,
)
from ac_platform.conversation_intelligence.models import ConversationBudgetAccount
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.kernel.authz import ActorContext

PAUSED_MESSAGE = (
    "New analysis is temporarily paused. Your saved calls and reports are still available. "
    "Contact the AC team at admin@authorityclosers.com."
)
ENVIRONMENTS = frozenset({"local", "test", "staging", "production"})
_STARTED_SCOPE: ContextVar[tuple[str, UUID] | None] = ContextVar("xray_started_scope", default=None)


@contextmanager
def already_started_effect(*, environment: str, operations_tenant_id: UUID) -> Iterator[None]:
    """Worker only, after lock_for_dispatch proves the committed effect marker.

    Suppresses only the pause check for that already-started effect. Consent,
    source, tenant, revocation, job lease and provider approval checks still run.
    """
    _scope(environment, operations_tenant_id)
    token = _STARTED_SCOPE.set((environment, operations_tenant_id))
    try:
        yield
    finally:
        _STARTED_SCOPE.reset(token)


class ConversationExecutionPaused(ConversationError):
    status = 503

    def __init__(self) -> None:
        super().__init__(PAUSED_MESSAGE)


def _scope(environment: str, operations_tenant_id: UUID) -> None:
    if environment not in ENVIRONMENTS or not isinstance(operations_tenant_id, UUID):
        raise ValueError("execution_control_scope_required")


async def lock_execution_control(
    database: AsyncSession, *, environment: str, operations_tenant_id: UUID, shared: bool
) -> None:
    _scope(environment, operations_tenant_id)
    key = int.from_bytes(
        hashlib.sha256(
            f"ac-xray-execution-v1:{environment}:{operations_tenant_id}".encode("ascii")
        ).digest()[:8],
        "big",
    ) % (2**63)
    function = func.pg_advisory_xact_lock_shared if shared else func.pg_advisory_xact_lock
    await database.execute(select(function(key)))


async def execution_state(
    database: AsyncSession, *, environment: str, operations_tenant_id: UUID
) -> dict[str, Any]:
    _scope(environment, operations_tenant_id)
    row = await database.scalar(
        select(ConversationExecutionControl)
        .where(
            ConversationExecutionControl.tenant_id == operations_tenant_id,
            ConversationExecutionControl.environment == environment,
        )
        .order_by(ConversationExecutionControl.revision.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return {
        "revision": 0 if row is None else row.revision,
        "paused": False if row is None else row.paused,
        "changed_at": None if row is None else utc(row.created_at).isoformat(),
    }


async def require_execution_enabled(
    database: AsyncSession, *, environment: str, operations_tenant_id: UUID
) -> None:
    if _STARTED_SCOPE.get() == (environment, operations_tenant_id):
        return
    if (
        await execution_state(
            database, environment=environment, operations_tenant_id=operations_tenant_id
        )
    )["paused"]:
        raise ConversationExecutionPaused()


def budget_view(snapshot: BudgetAccount) -> dict[str, Any]:
    committed = snapshot.cap_paise - snapshot.available_paise
    settled = sum(
        r.committed_paise
        for r in snapshot.reservations
        if r.state in {"settled", "reconciliation_required"}
    )
    uncertain = sum(r.committed_paise for r in snapshot.reservations if r.state == "uncertain")
    if snapshot.has_overrun or snapshot.available_paise <= 0:
        level = "exhausted"
    elif committed * 100 >= snapshot.cap_paise * 90:
        level = "critical"
    elif committed * 100 >= snapshot.cap_paise * 80:
        level = "warning"
    else:
        level = "normal"
    return {
        "cap_paise": snapshot.cap_paise,
        "available_paise": snapshot.available_paise,
        "committed_paise": committed,
        "settled_paise": settled,
        "held_paise": committed - settled,
        "uncertain_paise": uncertain,
        "reservation_count": len(snapshot.reservations),
        "warning": level,
        "warning_percent": 80,
        "critical_percent": 90,
    }


class ExecutionControls:
    def __init__(
        self, application: ConversationApplication, *, environment: str, operations_tenant_id: UUID
    ) -> None:
        _scope(environment, operations_tenant_id)
        self.app, self.database = application, application.database
        self.environment, self.operations_tenant_id = environment, operations_tenant_id

    async def admit(self, actor: ActorContext) -> None:
        if actor.tenant_id != self.operations_tenant_id:
            raise ConversationDenied("Use the AC operations workspace for execution controls.")
        # Same current identity predicates; shared locks still serialize revocation
        # but permit an emergency pause while an earlier provider request finishes.
        await ConversationProviderAdmin(self.app).admit(actor, shared_identity_locks=True)

    async def current(
        self, actor: ActorContext, *, budget_scope_id: UUID | None = None
    ) -> dict[str, Any]:
        await self.admit(actor)
        state = await execution_state(
            self.database,
            environment=self.environment,
            operations_tenant_id=self.operations_tenant_id,
        )
        budget = None
        if budget_scope_id is not None:
            row = await self.database.scalar(
                select(ConversationBudgetAccount)
                .where(ConversationBudgetAccount.scope_id == budget_scope_id)
                .execution_options(populate_existing=True)
            )
            if row is not None:
                budget = budget_view(BudgetAccount.from_dict(row.snapshot))
        history = (
            await self.database.scalars(
                select(ConversationExecutionControl)
                .where(
                    ConversationExecutionControl.tenant_id == self.operations_tenant_id,
                    ConversationExecutionControl.environment == self.environment,
                )
                .order_by(ConversationExecutionControl.revision.desc())
                .limit(10)
            )
        ).all()
        return {
            "environment": self.environment,
            "control": state,
            "budget": budget,
            "history": [
                {
                    "revision": r.revision,
                    "paused": r.paused,
                    "changed_at": utc(r.created_at).isoformat(),
                }
                for r in history
            ],
        }

    async def set_paused(
        self, actor: ActorContext, *, paused: bool, expected_revision: int, key: str
    ) -> dict[str, Any]:
        # Domain admission precedes the short execution fence; no provider
        # identity locks are acquired after this fence in either writer.
        await self.admit(actor)
        await lock_execution_control(
            self.database,
            environment=self.environment,
            operations_tenant_id=self.operations_tenant_id,
            shared=False,
        )
        if (
            type(paused) is not bool
            or type(expected_revision) is not int
            or not 0 <= expected_revision < 2147483647
        ):
            raise ConversationError("Use the current execution-control revision.")
        intent = {
            "environment": self.environment,
            "paused": paused,
            "expected_revision": expected_revision,
        }
        replay = await self.app._replay(actor, key, "execution_control", intent)
        if replay is not None:
            row = await self.database.get(ConversationExecutionControl, replay.result_id)
            if (
                row is None
                or row.tenant_id != self.operations_tenant_id
                or row.environment != self.environment
            ):
                raise ConversationConflict("The execution-control receipt is unavailable.")
            return {
                "revision": row.revision,
                "paused": row.paused,
                "changed_at": utc(row.created_at).isoformat(),
            }
        current = await execution_state(
            self.database,
            environment=self.environment,
            operations_tenant_id=self.operations_tenant_id,
        )
        if current["revision"] != expected_revision:
            raise ConversationConflict("Execution controls changed. Refresh before saving.")
        now = utc(self.app.clock())
        row = ConversationExecutionControl(
            id=uuid4(),
            tenant_id=self.operations_tenant_id,
            person_id=actor.person_id,
            session_id=actor.session_id,
            environment=self.environment,
            revision=expected_revision + 1,
            paused=paused,
            created_at=now,
        )
        self.database.add(row)
        await self.database.flush()
        await self.app._receipt(
            actor,
            key,
            "execution_control",
            intent,
            row.id,
            now,
            resource_type="conversation_execution_control",
        )
        return {"revision": row.revision, "paused": row.paused, "changed_at": now.isoformat()}
