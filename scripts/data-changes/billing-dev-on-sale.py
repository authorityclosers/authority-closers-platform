"""Put the stored plans on sale on dev, through the fake payment provider (approved data change).

Orchestrator brief, 23 Oct 2026 (owner order ~05:35 IST: "making economically strong app which
can earn money ... ready just to add payment portal and take money"): a fictional user must be
able to buy each plan and a top-up on dev with the fake provider. This does, in one
transaction:
  1. the plans named by --plans (default personal, organisation) become ``active`` when they
     are ``coming_soon`` and carry a price; each changed row's revision goes up by 1. Prices,
     minutes, seats and packs are not touched: they stay the owner-confirmed stored values.
     Enterprise stays ``coming_soon`` ("talk to us");
  2. a new ``billing_provider_settings`` revision enables ``--provider`` (``fake``, the default,
     or ``razorpay``) in ``test`` mode, unless the latest revision already does. Provider plan
     references carry over only within the same provider. ``razorpay`` needs the deployed API
     to hold the three AC_RAZORPAY_* test values (ac-secret-drop ... dev), else it refuses;
  3. one audit event names the approver and the issue.
Development only: it refuses any other environment, and the fake provider is forbidden in
production by the settings anyway. Dry run unless --apply; a rerun after apply changes nothing.

Run on ac with the dev-live API's settings (the database URL and tenants come from its env):
    sudo bash -c 'set -a; . /etc/authority-closers/development/api-live.env; set +a;
      cd /srv/authority-closers/development/live-backend/a &&
      .venv/bin/python - --approver-email <email> --issue <reference> [--apply]' \\
      < scripts/data-changes/billing-dev-on-sale.py
Prints plan keys, statuses, revisions and settings revisions only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ac_platform.application.settings import get_settings
from ac_platform.audit.service import append_audit_event
from ac_platform.billing.order_models import BillingProviderSettings
from ac_platform.identity.models import Person
from ac_platform.plans.models import Plan

DATA_CHANGE = "scripts/data-changes/billing-dev-on-sale.py"


class Refused(RuntimeError):
    """A stable, content-free reason the change was not made."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="billing-dev-on-sale", allow_abbrev=False)
    parser.add_argument("--plans", default="personal,organisation")
    parser.add_argument("--provider", choices=("fake", "razorpay"), default="fake")
    parser.add_argument("--approver-email", required=True)
    parser.add_argument("--issue", required=True)
    parser.add_argument("--apply", action="store_true")
    return parser


def _plan_row(plan: Plan) -> dict[str, object]:
    return {"key": plan.key, "status": plan.status, "revision": plan.revision}


def _settings_row(row: BillingProviderSettings | None) -> dict[str, object] | None:
    if row is None:
        return None
    return {
        "revision": row.revision,
        "provider": row.provider,
        "mode": row.mode,
        "enabled": row.enabled,
    }


async def change(database: AsyncSession, args: argparse.Namespace) -> dict[str, object]:
    settings = get_settings()
    if settings.environment != "development":
        raise Refused("development_only")
    if settings.operations_tenant_id is None:
        raise Refused("operations_tenant_missing")
    if args.provider == "razorpay" and (
        settings.razorpay_key_id is None
        or settings.razorpay_key_secret is None
        or settings.razorpay_webhook_secret is None
        or settings.billing_allow_live
    ):
        raise Refused("razorpay_test_keys_are_not_in_the_dev_api_settings")
    keys = [key.strip() for key in args.plans.split(",") if key.strip()]
    if not keys or "enterprise" in keys:
        raise Refused("plans_must_be_named_and_enterprise_stays_talk_to_us")
    approver = list(
        await database.scalars(
            select(Person).where(Person.email.ilike(args.approver_email.strip())).limit(2)
        )
    )
    if len(approver) != 1:
        raise Refused("exactly_one_person_must_match_the_approver_email")
    now = datetime.now(UTC)
    plans = list(await database.scalars(select(Plan).where(Plan.key.in_(keys)).with_for_update()))
    if sorted(plan.key for plan in plans) != sorted(keys):
        raise Refused("unknown_plan_key")
    before = [_plan_row(plan) for plan in plans]
    changed: list[str] = []
    for plan in plans:
        if plan.status == "active":
            continue
        if plan.status != "coming_soon":
            raise Refused(f"plan_{plan.key}_is_{plan.status}")
        if plan.monthly_price_paise is None and plan.yearly_price_paise is None:
            raise Refused(f"plan_{plan.key}_has_no_price")
        plan.status = "active"
        plan.revision += 1
        plan.updated_at = now
        changed.append(plan.key)
    latest = await database.scalar(
        select(BillingProviderSettings)
        .order_by(BillingProviderSettings.revision.desc())
        .limit(1)
        .with_for_update()
    )
    settings_before = _settings_row(latest)
    enable = latest is None or not (
        latest.enabled and latest.provider == args.provider and latest.mode == "test"
    )
    same_provider = latest is not None and latest.provider == args.provider
    if enable:
        database.add(
            BillingProviderSettings(
                id=uuid4(),
                revision=1 if latest is None else latest.revision + 1,
                provider=args.provider,
                mode="test",
                enabled=True,
                plan_refs=dict(latest.plan_refs or {}) if same_provider and latest else {},
                key_alias=None,
                actor_person_id=approver[0].id,
                reason=f"{args.issue}: {args.provider} provider (test) on dev",
                audit_event_id=None,
                created_at=now,
            )
        )
    await database.flush()
    if changed or enable:
        await append_audit_event(
            database,
            tenant_id=settings.operations_tenant_id,
            actor_person_id=approver[0].id,
            actor_type="operator",
            action="billing.dev_on_sale_data_change",
            resource_type="tenant",
            resource_id=settings.operations_tenant_id,
            request_id=str(uuid5(NAMESPACE_URL, f"{DATA_CHANGE}:{args.issue}:{now.isoformat()}")),
            reason=f"{args.issue}: plans on sale on dev with the {args.provider} provider",
            payload={
                "issue": args.issue,
                "data_change": DATA_CHANGE,
                "plans_activated": changed,
                "provider_enabled": f"{args.provider}/test" if enable else None,
            },
        )
    latest_after = await database.scalar(
        select(BillingProviderSettings).order_by(BillingProviderSettings.revision.desc()).limit(1)
    )
    return {
        "applied": bool(args.apply),
        "plans_before": before,
        "plans_after": [_plan_row(plan) for plan in plans],
        "provider_settings_before": settings_before,
        "provider_settings_after": _settings_row(latest_after),
        "changed": bool(changed or enable),
    }


async def main(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    engine = create_async_engine(get_settings().database_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as database:
            await database.begin()
            try:
                report = await change(database, args)
            except Refused as error:
                await database.rollback()
                print(json.dumps({"refused": str(error)}))
                return 1
            if args.apply:
                await database.commit()
            else:
                await database.rollback()
        print(json.dumps(report, indent=2))
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
