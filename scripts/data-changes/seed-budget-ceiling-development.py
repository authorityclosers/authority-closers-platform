#!/usr/bin/env python3
"""Owner-approved 19 Oct 2026 (via the orchestrator): dev's first AI budget ceiling, INR 10,000.

"Yes, seed dev's first ceiling row at ₹10,000 (dev only). Staging and production get
their rows through the release" (their sealed amount, INR 10,000, is the ceiling until
the owner saves one in Admin).

Development only. Dry-run by default; --apply writes, in one transaction, revision 1
of conversation_budget_settings for the pinned budget scope (lifetime, ceiling INR
10,000) and one audit event in the same shape as the Admin command, naming the
approver. The working cap in the ledger is unchanged: any Admin raises it in one
click. Idempotent: an existing settings row means nothing is written.
"""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.application.settings import Settings
from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.budget_admin import SETTINGS_ACTION
from ac_platform.conversation_intelligence.budget_settings import latest_setting
from ac_platform.conversation_intelligence.budget_settings_models import ConversationBudgetSetting
from ac_platform.conversation_intelligence.entitlements import BudgetAccount
from ac_platform.conversation_intelligence.hosted_runtime import load_pinned_approval
from ac_platform.conversation_intelligence.models import ConversationBudgetAccount
from ac_platform.identity.models import Person
from ac_platform.tenancy.models import Membership

CEILING_PAISE = 1_000_000
APPROVER = "admin@authorityclosers.com"
ISSUE = "orchestrator 19 Oct 2026, budget settings decision 3"
REASON = "Owner decision 19 Oct 2026 via the orchestrator: dev ceiling INR 10,000"


async def change(database, settings: Settings, *, apply: bool) -> dict:
    now, run_id = datetime.now(UTC), uuid4()
    bundle = load_pinned_approval(settings)
    if bundle.environment != "development":
        raise ValueError("Development only.")
    scope = bundle.budget_scope_id
    ledger = await database.scalar(
        select(ConversationBudgetAccount).where(ConversationBudgetAccount.scope_id == scope)
    )
    existing = await latest_setting(database, scope)
    cap = None if ledger is None else BudgetAccount.from_dict(ledger.snapshot).cap_paise
    result = {
        "run_id": str(run_id),
        "issue": ISSUE,
        "approver": "Suyash",
        "approver_email": APPROVER,
        "scope_id": str(scope),
        "before": {
            "setting_revision": 0 if existing is None else existing.revision,
            "ceiling_paise": bundle.budget_cap_paise
            if existing is None
            else existing.ceiling_paise,
            "from_release": existing is None,
            "ledger_cap_paise": cap,
        },
        "after": {
            "setting_revision": 1,
            "ceiling_paise": CEILING_PAISE,
            "period": "lifetime",
            "ledger_cap_paise": cap,
        },
        "applied": False,
    }
    if existing is not None:
        result["after"] = result["before"]
        result["skipped"] = "A settings row exists; the owner changes it in Admin."
        return result
    if ledger is None:
        raise ValueError("The dev budget ledger has not been created yet.")
    approver = await database.scalar(select(Person).where(func.lower(Person.email) == APPROVER))
    member = (
        await database.get(Membership, (settings.operations_tenant_id, approver.id))
        if approver
        else None
    )
    if approver is None or member is None or member.role != "owner":
        raise ValueError(f"{APPROVER} must hold the owner role in the AC operations workspace.")
    if not apply:
        return result
    database.add(
        ConversationBudgetSetting(
            id=uuid4(),
            scope_id=scope,
            revision=1,
            ceiling_paise=CEILING_PAISE,
            period="lifetime",
            period_cap_paise=None,
            set_by_person_id=approver.id,
            reason=REASON,
            created_at=now,
        )
    )
    await database.flush()
    await AuditRepository(database).append(
        tenant_id=settings.operations_tenant_id,
        actor_person_id=approver.id,
        action=SETTINGS_ACTION,
        resource_type="conversation_budget_account",
        resource_id=scope,
        payload={
            "schema": "ac.sales-xray.budget-settings/1",
            "environment": "development",
            "revision": 1,
            "before": {
                "ceiling_paise": bundle.budget_cap_paise,
                "period": "lifetime",
                "cap_paise": min(cap or 0, bundle.budget_cap_paise),
                "from_release": True,
            },
            "after": {
                "ceiling_paise": CEILING_PAISE,
                "period": "lifetime",
                "cap_paise": min(cap or 0, CEILING_PAISE),
            },
            "run_id": str(run_id),
            "issue": ISSUE,
            "approver_email": APPROVER,
        },
        reason=REASON,
        now=now,
    )
    result["applied"] = True
    return result


async def execute(args) -> dict:
    settings = Settings()
    if settings.environment != "development" or settings.operations_tenant_id is None:
        raise ValueError("Development only, with the AC operations workspace configured.")
    engine = create_async_engine(settings.database_url, echo=False, hide_parameters=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db, db.begin():
            return await change(db, settings, apply=args.apply)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=("development",), required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(execute(args)), sort_keys=True))


if __name__ == "__main__":
    main()
