"""Verified Admin amendments to the shared provider budget.

The release approval remains the authority for the budget scope and ceiling.
This service persists a working cap anywhere up to that sealed ceiling (owner,
19 Oct 2026: one click, no code limit of its own); above it, Admin files an
audited request for Root to reseal a higher ceiling. Existing reservations are
carried forward by the pure ledger transition; no settlement, access grant, or
provider call is inferred here.
"""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from sqlalchemy import select

from ac_platform.audit.service import AuditRepository
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

CEILING_REQUEST_ACTION = "conversation.budget_ceiling_requested"
MAX_CAP_PAISE = 2_147_483_647


def admin_budget_approval_ref(bundle_digest: str, actor_id: UUID, key: str) -> str:
    """Bind an Admin amendment to the exact release approval and request."""

    suffix = hashlib.sha256(f"{actor_id}:{key}".encode()).hexdigest()
    return f"ref:budget-admin/{bundle_digest}/{suffix}"


def is_admin_budget_approval_ref(value: str, bundle_digest: str) -> bool:
    prefix = f"ref:budget-admin/{bundle_digest}/"
    suffix = value[len(prefix) :] if value.startswith(prefix) else ""
    return len(suffix) == 64 and all(character in "0123456789abcdef" for character in suffix)


def is_any_admin_budget_approval_ref(value: str) -> bool:
    """Recognize an audited Admin cap from any earlier release digest."""

    parts = (
        value.removeprefix("ref:budget-admin/").split("/")
        if isinstance(value, str) and value.startswith("ref:budget-admin/")
        else []
    )
    return (
        len(parts) == 2
        and len(parts[0]) == 64
        and all(character in "0123456789abcdef" for character in parts[0])
        and len(parts[1]) == 64
        and all(character in "0123456789abcdef" for character in parts[1])
    )


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
        if environment not in {"local", "test", "development", "staging", "production"}:
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
        if bundle.provider_control_tenant_id != self.operations_tenant_id:
            raise ConversationDenied("The pinned budget approval is for another workspace.")
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
        if type(new_cap_paise) is not int or not 0 <= new_cap_paise <= MAX_CAP_PAISE:
            raise ConversationError("Enter a budget cap of INR 0 or more.")
        if new_cap_paise > approved_cap:
            raise ConversationDenied(
                "The budget cap cannot exceed the sealed release ceiling; ask Root to raise it."
            )
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

    async def request_ceiling(
        self,
        actor: ActorContext,
        *,
        bundle: HostedApprovalBundle,
        requested_cap_paise: int,
        reason: str,
        key: str,
    ) -> dict[str, Any]:
        """Ask Root for a higher sealed ceiling: one audited request, idempotent per key.

        The host's budget bridge turns each request into a Root card. Nothing here
        changes the approval or the ledger.
        """

        await self.admit(actor)
        now = utc(self.app.clock())
        approved_cap = self._approved_cap(bundle, int(now.timestamp()))
        if (
            type(requested_cap_paise) is not int
            or not approved_cap < requested_cap_paise <= MAX_CAP_PAISE
        ):
            raise ConversationError("Ask for a ceiling above the current sealed ceiling.")
        reason = _bounded_reason(reason)
        intent = {
            "scope_id": str(bundle.budget_scope_id),
            "requested_cap_paise": requested_cap_paise,
            "reason": reason,
        }
        replay = await self.app._replay(actor, key, "budget_ceiling_request", intent)
        if replay is None or replay.result_id is None:
            event = await AuditRepository(self.database).append_for_actor(
                actor,
                action=CEILING_REQUEST_ACTION,
                resource_type="conversation_budget_account",
                resource_id=bundle.budget_scope_id,
                payload={
                    "schema": "ac.sales-xray.budget-ceiling-request/1",
                    "environment": self.environment,
                    "requested_cap_paise": requested_cap_paise,
                    "sealed_ceiling_paise": approved_cap,
                    "reason": reason,
                },
                reason=reason,
                now=now,
            )
            request_id = event.id
            await self.app._receipt(
                actor,
                key,
                "budget_ceiling_request",
                intent,
                request_id,
                now,
                resource_type="conversation_budget_account",
            )
        else:
            request_id = replay.result_id
        return {
            "request_id": str(request_id),
            "requested_cap_paise": requested_cap_paise,
            "sealed_ceiling_paise": approved_cap,
            "status": "sent_to_root",
        }


__all__ = [
    "CEILING_REQUEST_ACTION",
    "MAX_CAP_PAISE",
    "ConversationBudgetAdmin",
    "admin_budget_approval_ref",
    "is_any_admin_budget_approval_ref",
    "is_admin_budget_approval_ref",
]
