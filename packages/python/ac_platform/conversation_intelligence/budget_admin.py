"""Verified Admin changes to the shared provider budget (owner decision, 19 Oct 2026).

- The owner sets the ceiling and the period (lifetime, monthly or daily) in Admin,
  after a confirm step. Each change is a new settings revision with an audit event
  naming the old and new values. Until the first one, the release approval's sealed
  amount is the ceiling; no Root reseal is needed to change it.
- Any verified Admin moves the working cap anywhere up to the ceiling in one click.
  For lifetime that is the ledger's own cap; for monthly and daily it is the cap per
  period, a new settings revision.

Existing reservations are carried forward by the pure ledger transition; no
settlement, access grant, or provider call is inferred here.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

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
from ac_platform.conversation_intelligence.budget_settings import (
    LEDGER_OPEN_CAP_PAISE,
    PERIOD_HELP,
    PERIODS,
    BudgetLimits,
    latest_setting,
    limits_from,
    period_end,
    period_start,
)
from ac_platform.conversation_intelligence.budget_settings_models import ConversationBudgetSetting
from ac_platform.conversation_intelligence.entitlements import (
    OWNER_CEILING_PAISE,
    BudgetAccount,
    BudgetCapApproval,
    committed_since,
    revise_budget_cap,
)
from ac_platform.conversation_intelligence.execution_control import budget_view
from ac_platform.conversation_intelligence.models import ConversationBudgetAccount
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext

SETTINGS_ACTION = "conversation.budget_settings_changed"
# Who may change the AI budget ceiling and period: the owner's own accounts, by explicit
# allowlist (orchestrator, 19 Oct 2026: "owner" means Suyash personally, not every
# organisation owner). Any verified Admin still raises the working cap up to the ceiling.
CEILING_OWNER_EMAILS = frozenset({"admin@authorityclosers.com", "suyash@authorityclosers.com"})
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


def _bounded_reason(reason: str, limit: int = 512) -> str:
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > limit:
        raise ConversationError("A bounded budget-change reason is required.")
    return reason.strip()


def _amount(value: int, message: str, *, most: int = MAX_CAP_PAISE) -> int:
    if type(value) is not int or not 0 <= value <= most:
        raise ConversationError(message)
    return value


def _rupees(paise: int) -> str:
    return f"₹{paise / 100:,.0f}"


class ConversationBudgetAdmin:
    """Append-only audited budget changes for the release-approved budget scope."""

    def __init__(
        self,
        application: ConversationApplication,
        *,
        environment: str,
        operations_tenant_id: UUID,
        ceiling_owners: frozenset[str] = CEILING_OWNER_EMAILS,
    ) -> None:
        if environment not in {"local", "test", "development", "staging", "production"}:
            raise ValueError("budget_admin_environment_invalid")
        self.ceiling_owners = frozenset(email.casefold() for email in ceiling_owners)
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

    async def is_owner(self, actor: ActorContext) -> bool:
        """The owner's own verified account, on the ceiling allowlist (after ``admit``)."""

        person = await self.database.get(Person, actor.person_id)
        return (
            person is not None
            and person.email_verified_at is not None
            and (person.email or "").casefold() in self.ceiling_owners
        )

    def _sealed_cap(self, bundle: HostedApprovalBundle, now_epoch: int) -> int:
        try:
            bundle.current(now_epoch, self.environment)
        except ValueError:
            raise ConversationDenied("The pinned budget approval is unavailable.") from None
        if bundle.provider_control_tenant_id != self.operations_tenant_id:
            raise ConversationDenied("The pinned budget approval is for another workspace.")
        return bundle.budget_cap_paise

    async def _ledger(
        self, bundle: HostedApprovalBundle, *, lock: bool
    ) -> ConversationBudgetAccount | None:
        query = select(ConversationBudgetAccount).where(
            ConversationBudgetAccount.scope_id == bundle.budget_scope_id
        )
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        row: ConversationBudgetAccount | None = await self.database.scalar(query)
        return row

    async def _view(
        self,
        actor: ActorContext,
        bundle: HostedApprovalBundle,
        row: ConversationBudgetAccount | None,
        *,
        sealed: int,
        now: datetime,
    ) -> dict[str, Any]:
        snapshot = None if row is None else BudgetAccount.from_dict(row.snapshot)
        setting = await latest_setting(self.database, bundle.budget_scope_id)
        limits = limits_from(
            setting,
            sealed_ceiling_paise=sealed,
            ledger_cap_paise=sealed if snapshot is None else snapshot.cap_paise,
            now=now,
        )
        history = (
            await self.database.scalars(
                select(ConversationBudgetSetting)
                .where(ConversationBudgetSetting.scope_id == bundle.budget_scope_id)
                .order_by(ConversationBudgetSetting.revision.desc())
                .limit(10)
            )
        ).all()
        start, end = period_start(now, limits.period), period_end(now, limits.period)
        return {
            "scope_id": str(bundle.budget_scope_id),
            "revision": 0 if row is None else row.revision,
            "approved_cap_paise": limits.ceiling_paise,
            "budget": None if snapshot is None else budget_view(snapshot, limits),
            "settings": {
                "revision": limits.setting_revision,
                "ceiling_paise": limits.ceiling_paise,
                "sealed_ceiling_paise": sealed,
                "from_release": limits.sealed,
                "period": limits.period,
                "cap_paise": min(limits.cap_paise, limits.ceiling_paise),
                "lifetime_committed_paise": None
                if snapshot is None
                else committed_since(snapshot, None),
                "period_starts_at": None if start is None else start.isoformat(),
                "period_ends_at": None if end is None else end.isoformat(),
                "can_change_ceiling": await self.is_owner(actor),
                "periods": [{"value": p, "help": PERIOD_HELP[p]} for p in PERIODS],
                "history": [
                    {
                        "revision": item.revision,
                        "ceiling_paise": item.ceiling_paise,
                        "period": item.period,
                        "cap_paise": item.period_cap_paise,
                        "reason": item.reason,
                        "changed_at": utc(item.created_at).isoformat(),
                    }
                    for item in history
                ],
            },
        }

    async def current(self, actor: ActorContext, *, bundle: HostedApprovalBundle) -> dict[str, Any]:
        await self.admit(actor)
        now = utc(self.app.clock())
        sealed = self._sealed_cap(bundle, int(now.timestamp()))
        return await self._view(
            actor, bundle, await self._ledger(bundle, lock=False), sealed=sealed, now=now
        )

    async def _limits(
        self, bundle: HostedApprovalBundle, before: BudgetAccount, *, sealed: int, now: datetime
    ) -> BudgetLimits:
        return limits_from(
            await latest_setting(self.database, bundle.budget_scope_id),
            sealed_ceiling_paise=sealed,
            ledger_cap_paise=before.cap_paise,
            now=now,
        )

    @staticmethod
    def _revise(
        bundle: HostedApprovalBundle,
        actor: ActorContext,
        before: BudgetAccount,
        new_cap_paise: int,
        *,
        approval_ref: str,
        reason: str,
    ) -> BudgetAccount:
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
        return revise_budget_cap(before, new_cap_paise, approval)

    async def _audit(
        self,
        actor: ActorContext,
        bundle: HostedApprovalBundle,
        saved: ConversationBudgetSetting,
        before: BudgetLimits,
        *,
        cap_paise: int,
        reason: str,
        now: datetime,
    ) -> None:
        """One audit event per settings revision, old and new (the alerts read these)."""

        await AuditRepository(self.database).append_for_actor(
            actor,
            action=SETTINGS_ACTION,
            resource_type="conversation_budget_account",
            resource_id=bundle.budget_scope_id,
            payload={
                "schema": "ac.sales-xray.budget-settings/1",
                "environment": self.environment,
                "revision": saved.revision,
                "before": {
                    "ceiling_paise": before.ceiling_paise,
                    "period": before.period,
                    "cap_paise": min(before.cap_paise, before.ceiling_paise),
                    "from_release": before.sealed,
                },
                "after": {
                    "ceiling_paise": saved.ceiling_paise,
                    "period": saved.period,
                    "cap_paise": cap_paise,
                },
            },
            reason=reason,
            now=now,
        )

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
        """Any Admin: move the working cap (per period, if one applies) up to the ceiling."""

        await self.admit(actor)
        now = utc(self.app.clock())
        sealed = self._sealed_cap(bundle, int(now.timestamp()))
        new_cap_paise = _amount(new_cap_paise, "Enter a budget cap of INR 0 or more.")
        if type(expected_revision) is not int or not 0 <= expected_revision < 2_147_483_647:
            raise ConversationError("Use the current budget revision.")
        reason = _bounded_reason(reason, 300)
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
            return await self._view(actor, bundle, row, sealed=sealed, now=now)
        row = await self._ledger(bundle, lock=True)
        if row is None:
            raise ConversationConflict("The approved project budget has not been initialized.")
        if row.revision != expected_revision:
            raise ConversationConflict("Budget settings changed. Reload before saving.")
        try:
            before = BudgetAccount.from_dict(row.snapshot)
        except ValueError:
            raise ConversationConflict("The current budget ledger is unavailable.") from None
        limits = await self._limits(bundle, before, sealed=sealed, now=now)
        if new_cap_paise > limits.ceiling_paise:
            raise ConversationDenied(
                "The budget cap cannot exceed the ceiling. The owner can raise the ceiling "
                "in Budget settings."
            )
        changed = False
        if limits.period == "lifetime":
            try:
                after = self._revise(
                    bundle, actor, before, new_cap_paise, approval_ref=approval_ref, reason=reason
                )
            except ValueError:
                raise ConversationConflict(
                    "The budget approval or current ledger is unavailable."
                ) from None
            if after is not before:
                row.snapshot = after.as_dict()
                row.revision += 1
                changed = True
        elif new_cap_paise != limits.cap_paise:
            saved = ConversationBudgetSetting(
                id=uuid4(),
                scope_id=bundle.budget_scope_id,
                revision=limits.setting_revision + 1,
                ceiling_paise=limits.ceiling_paise,
                period=limits.period,
                period_cap_paise=new_cap_paise,
                set_by_person_id=actor.person_id,
                reason=reason,
                created_at=now,
            )
            self.database.add(saved)
            await self._audit(
                actor, bundle, saved, limits, cap_paise=new_cap_paise, reason=reason, now=now
            )
            changed = True
        if changed:
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
        return await self._view(actor, bundle, row, sealed=sealed, now=now)

    async def save_settings(
        self,
        actor: ActorContext,
        *,
        bundle: HostedApprovalBundle,
        ceiling_paise: int,
        period: str,
        cap_paise: int,
        expected_setting_revision: int,
        reason: str,
        key: str,
    ) -> dict[str, Any]:
        """The owner only: set the ceiling, the period and its cap (one audited revision).

        Lifetime sets the ledger's own cap, which must cover what is already spent or
        held. Monthly and daily lift the ledger's cap out of the way (it must always
        cover all spend ever); the cap per period is then the limit.
        """

        await self.admit(actor)
        if not await self.is_owner(actor):
            raise ConversationDenied(
                "Only the owner (Suyash) can change the budget ceiling and period."
            )
        now = utc(self.app.clock())
        sealed = self._sealed_cap(bundle, int(now.timestamp()))
        ceiling_paise = _amount(ceiling_paise, "Enter a ceiling of INR 0 or more.")
        if period not in PERIODS:
            raise ConversationError("Choose lifetime, monthly or daily.")
        cap_paise = _amount(
            cap_paise, "The cap must be between INR 0 and the ceiling.", most=ceiling_paise
        )
        if (
            type(expected_setting_revision) is not int
            or not 0 <= expected_setting_revision < 2_147_483_647
        ):
            raise ConversationError("Use the current budget settings revision.")
        reason = _bounded_reason(reason, 300)
        approval_ref = admin_budget_approval_ref(bundle.digest, actor.person_id, key)
        intent = {
            "scope_id": str(bundle.budget_scope_id),
            "ceiling_paise": ceiling_paise,
            "period": period,
            "cap_paise": cap_paise,
            "expected_setting_revision": expected_setting_revision,
            "reason": reason,
            "approval_ref": approval_ref,
        }
        replay = await self.app._replay(actor, key, "budget_settings", intent)
        if replay is not None and replay.result_id is not None:
            saved = await self.database.get(ConversationBudgetSetting, replay.result_id)
            if saved is None or saved.scope_id != bundle.budget_scope_id:
                raise ConversationConflict("The saved budget settings receipt is unavailable.")
            return await self._view(
                actor, bundle, await self._ledger(bundle, lock=False), sealed=sealed, now=now
            )
        row = await self._ledger(bundle, lock=True)
        if row is None:
            raise ConversationConflict("The approved project budget has not been initialized.")
        try:
            before = BudgetAccount.from_dict(row.snapshot)
        except ValueError:
            raise ConversationConflict("The current budget ledger is unavailable.") from None
        limits = await self._limits(bundle, before, sealed=sealed, now=now)
        if limits.setting_revision != expected_setting_revision:
            raise ConversationConflict("Budget settings changed. Reload before saving.")
        if period == "lifetime":
            spent = committed_since(before, None)
            if cap_paise < spent:
                raise ConversationConflict(
                    f"{_rupees(spent)} is already spent or held in total. Set a lifetime cap "
                    "of at least that, or choose a monthly or daily period."
                )
            ledger_cap = cap_paise
        else:
            ledger_cap = LEDGER_OPEN_CAP_PAISE
        if before.cap_paise != ledger_cap:
            try:
                after = self._revise(
                    bundle, actor, before, ledger_cap, approval_ref=approval_ref, reason=reason
                )
            except ValueError:
                raise ConversationConflict(
                    "The budget approval or current ledger is unavailable."
                ) from None
            row.snapshot = after.as_dict()
            row.revision += 1
        saved = ConversationBudgetSetting(
            id=uuid4(),
            scope_id=bundle.budget_scope_id,
            revision=limits.setting_revision + 1,
            ceiling_paise=ceiling_paise,
            period=period,
            period_cap_paise=None if period == "lifetime" else cap_paise,
            set_by_person_id=actor.person_id,
            reason=reason,
            created_at=now,
        )
        self.database.add(saved)
        await self.database.flush()
        await self._audit(actor, bundle, saved, limits, cap_paise=cap_paise, reason=reason, now=now)
        await self.app._receipt(
            actor,
            key,
            "budget_settings",
            intent,
            saved.id,
            now,
            resource_type="conversation_budget_setting",
        )
        return await self._view(actor, bundle, row, sealed=sealed, now=now)


__all__ = [
    "CEILING_OWNER_EMAILS",
    "MAX_CAP_PAISE",
    "SETTINGS_ACTION",
    "ConversationBudgetAdmin",
    "admin_budget_approval_ref",
    "is_any_admin_budget_approval_ref",
    "is_admin_budget_approval_ref",
]
