"""Verified Admin amendments to the shared provider budget.

The release approval remains the authority for the budget scope and ceiling.
This service only persists a cap that is already present in that pinned
approval.  Existing reservations are carried forward by the pure ledger
transition; no settlement, access grant, or provider call is inferred here.
"""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from sqlalchemy import select

from ac_platform.conversation_intelligence.activation_contract import HostedApprovalBundle
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
    ConversationDenied,
    ConversationError,
    utc,
)
from ac_platform.conversation_intelligence.entitlements import (
    OWNER_CEILING_PAISE,
    BudgetAccount,
    BudgetCapApproval,
    revise_budget_cap,
)
from ac_platform.conversation_intelligence.execution_control import budget_view
from ac_platform.conversation_intelligence.models import ConversationBudgetAccount
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.kernel.authz import ActorContext

# The user-authorized ceiling is INR 10,000.  The pinned release approval must
# still carry the exact amount before this service can persist it.
ADMIN_BUDGET_CEILING_PAISE = 1_000_000


def admin_budget_approval_ref(bundle_digest: str, actor_id: UUID, key: str) -> str:
    """Bind an Admin amendment to the exact release approval and request."""

    suffix = hashlib.sha256(f"{actor_id}:{key}".encode()).hexdigest()
    return f"ref:budget-admin/{bundle_digest}/{suffix}"


def is_admin_budget_approval_ref(value: str, bundle_digest: str) -> bool:
    prefix = f"ref:budget-admin/{bundle_digest}/"
    suffix = value[len(prefix) :] if value.startswith(prefix) else ""
    return len(suffix) == 64 and all(character in "0123456789abcdef" for character in suffix)


def _bounded_reason(reason: str) -> str:
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 512:
        raise ConversationError("A bounded budget-change reason is required.")
    return reason.strip()


class ConversationBudgetAdmin:
    """Append-only audited cap changes for the release-approved budget scope."""

    def __init__(
        self,
        application: ConversationApplication,
        *,
        environment: str,
        operations_tenant_id: UUID,
    ) -> None:
        if environment not in {"local", "test", "staging", "production"}:
            raise ValueError("budget_admin_environment_invalid")
        if not isinstance(operations_tenant_id, UUID):
            raise ValueError("budget_admin_scope_required")
        self.app = application
        self.database = application.database
        self.environment = environment
        self.operations_tenant_id = operations_tenant_id

    async def admit(self, actor: ActorContext) -> None:
        if actor.tenant_id != self.operations_tenant_id:
            raise ConversationDenied("Use the AC operations workspace for budget settings.")
        await ConversationProviderAdmin(self.app).admit(actor)

    def _approved_cap(self, bundle: HostedApprovalBundle, now_epoch: int) -> int:
        try:
            bundle.current(now_epoch, self.environment)
        except ValueError:
            raise ConversationDenied("The pinned budget approval is unavailable.") from None
        if (
            bundle.provider_control_tenant_id != self.operations_tenant_id
            or bundle.budget_cap_paise > ADMIN_BUDGET_CEILING_PAISE
        ):
            raise ConversationDenied("The pinned budget approval is outside the Admin ceiling.")
        return bundle.budget_cap_paise

    @staticmethod
    def _view(row: ConversationBudgetAccount, *, approved_cap_paise: int) -> dict[str, Any]:
        snapshot = BudgetAccount.from_dict(row.snapshot)
        return {
            "scope_id": str(row.scope_id),
            "revision": row.revision,
            "approved_cap_paise": approved_cap_paise,
            "budget": budget_view(snapshot),
        }

    async def current(self, actor: ActorContext, *, bundle: HostedApprovalBundle) -> dict[str, Any]:
        await self.admit(actor)
        now = utc(self.app.clock())
        approved_cap = self._approved_cap(bundle, int(now.timestamp()))
        row = await self.database.scalar(
            select(ConversationBudgetAccount).where(
                ConversationBudgetAccount.scope_id == bundle.budget_scope_id
            )
        )
        if row is None:
            return {
                "scope_id": str(bundle.budget_scope_id),
                "revision": 0,
                "approved_cap_paise": approved_cap,
                "budget": None,
            }
        return self._view(row, approved_cap_paise=approved_cap)

    async def save(
        self,
        actor: ActorContext,
        *,
        bundle: HostedApprovalBundle,
        new_cap_paise: int,
        expected_revision: int,
        reason: str,
        key: str,
    ) -> dict[str, Any]:
        await self.admit(actor)
        now = utc(self.app.clock())
        approved_cap = self._approved_cap(bundle, int(now.timestamp()))
        if type(new_cap_paise) is not int or not 0 <= new_cap_paise <= ADMIN_BUDGET_CEILING_PAISE:
            raise ConversationError("The budget cap must be between INR 0 and INR 10,000.")
        if new_cap_paise > approved_cap:
            raise ConversationDenied("The budget cap cannot exceed the pinned release approval.")
        if type(expected_revision) is not int or not 0 <= expected_revision < 2_147_483_647:
            raise ConversationError("Use the current budget revision.")
        reason = _bounded_reason(reason)
        approval_ref = admin_budget_approval_ref(bundle.digest, actor.person_id, key)
        intent = {
            "scope_id": str(bundle.budget_scope_id),
            "new_cap_paise": new_cap_paise,
            "expected_revision": expected_revision,
            "reason": reason,
            "approval_ref": approval_ref,
        }
        replay = await self.app._replay(actor, key, "budget_cap", intent)
        if replay is not None and replay.result_id is not None:
            row = await self.database.get(ConversationBudgetAccount, replay.result_id)
            if row is None or row.scope_id != bundle.budget_scope_id:
                raise ConversationConflict("The saved budget receipt is unavailable.")
            return self._view(row, approved_cap_paise=approved_cap)
        row = await self.database.scalar(
            select(ConversationBudgetAccount)
            .where(ConversationBudgetAccount.scope_id == bundle.budget_scope_id)
            .with_for_update()
        )
        if row is None:
            raise ConversationConflict("The approved project budget has not been initialized.")
        if row.revision != expected_revision:
            raise ConversationConflict("Budget settings changed. Reload before saving.")
        try:
            before = BudgetAccount.from_dict(row.snapshot)
            if before.scope_id != str(bundle.budget_scope_id):
                raise ValueError("scope")
            approval = BudgetCapApproval(
                scope_id=str(bundle.budget_scope_id),
                approval_ref=approval_ref,
                owner_actor_id=str(actor.person_id),
                approved_cap_paise=new_cap_paise,
                previous_budget_fingerprint=before.fingerprint,
                reason=reason,
                explicit_above_ceiling=new_cap_paise > OWNER_CEILING_PAISE,
            )
            after = revise_budget_cap(before, new_cap_paise, approval)
        except ValueError:
            raise ConversationConflict(
                "The budget approval or current ledger is unavailable."
            ) from None
        if after is not before:
            row.snapshot = after.as_dict()
            row.revision += 1
            await self.database.flush()
            await self.app._receipt(
                actor,
                key,
                "budget_cap",
                intent,
                row.scope_id,
                now,
                resource_type="conversation_budget_account",
            )
        return self._view(row, approved_cap_paise=approved_cap)


__all__ = [
    "ADMIN_BUDGET_CEILING_PAISE",
    "ConversationBudgetAdmin",
    "admin_budget_approval_ref",
    "is_admin_budget_approval_ref",
]
