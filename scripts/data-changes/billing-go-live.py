"""Put plans on sale with Razorpay in staging or production (owner-approved billing change).

Billing, payment settings and live payments need the owner's own "yes" (AGENTS.md, rule 5).
Run this only after that yes, with the approver's words in --reason. In one transaction it:
  1. moves the plans named by --plans (default personal, organisation) from ``coming_soon``
     to ``active`` when they carry a price; each changed row's revision goes up by 1. Prices,
     minutes, seats and packs stay as stored. Enterprise stays ``coming_soon`` ("talk to us");
  2. writes a new ``billing_provider_settings`` revision enabling ``razorpay`` in --mode
     (``test`` or ``live``), unless the latest revision already does; provider plan
     references carry over only within the same provider and mode;
  3. writes one audit event naming the approver, the issue and the reason.
It refuses unless the deployed API settings already hold billing (AC_BILLING_ENABLED), the
three AC_RAZORPAY_* values (Infisical), and, for live, AC_BILLING_ALLOW_LIVE in production.
Development uses billing-dev-on-sale.py instead. Dry run unless --apply; idempotent.

Production: take a database snapshot first (ac-db-snapshot), show the owner the dry run, then
apply. Run inside the deployed API container (its environment holds the settings):
    docker exec -i <api container> python - --environment production --allow-production \\
      --mode live --approver-email <owner email> --issue <reference> \\
      --reason "<the owner's words>" [--apply] < scripts/data-changes/billing-go-live.py
Prints plan keys, statuses, revisions and settings revisions only; never a key.
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

DATA_CHANGE = "scripts/data-changes/billing-go-live.py"


class Refused(RuntimeError):
    """A stable, content-free reason the change was not made."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="billing-go-live", allow_abbrev=False)
    parser.add_argument("--environment", required=True, choices=("staging", "production"))
    parser.add_argument("--allow-production", action="store_true")
    parser.add_argument("--mode", required=True, choices=("test", "live"))
    parser.add_argument("--plans", default="personal,organisation")
    parser.add_argument("--approver-email", required=True)
    parser.add_argument("--issue", required=True)
    parser.add_argument("--reason", required=True, help="the owner's approval, in their words")
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


def check_settings(args: argparse.Namespace) -> None:
    settings = get_settings()
    if settings.environment != args.environment:
        raise Refused("environment_does_not_match_the_deployed_settings")
    if args.environment == "production" and not args.allow_production:
        raise Refused("production_needs_allow_production")
    if not settings.billing_enabled or settings.operations_tenant_id is None:
        raise Refused("billing_is_not_enabled_in_the_deployed_settings")
    if (
        settings.razorpay_key_id is None
        or settings.razorpay_key_secret is None
        or settings.razorpay_webhook_secret is None
    ):
        raise Refused("razorpay_values_are_not_in_the_deployed_settings")
    if (args.mode == "live") != settings.billing_allow_live:
        raise Refused("mode_does_not_match_AC_BILLING_ALLOW_LIVE")
    if args.mode == "live" and args.environment != "production":
        raise Refused("live_payments_are_production_only")
    reason = " ".join(args.reason.split())
    if not 1 <= len(reason) <= 300 or not args.issue.strip():
        raise Refused("reason_and_issue_are_required")


async def change(database: AsyncSession, args: argparse.Namespace) -> dict[str, object]:
    check_settings(args)
    settings = get_settings()
    assert settings.operations_tenant_id is not None  # checked above
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
        latest.enabled and latest.provider == "razorpay" and latest.mode == args.mode
    )
    same = latest is not None and latest.provider == "razorpay" and latest.mode == args.mode
    if enable:
        database.add(
            BillingProviderSettings(
                id=uuid4(),
                revision=1 if latest is None else latest.revision + 1,
                provider="razorpay",
                mode=args.mode,
                enabled=True,
                plan_refs=dict(latest.plan_refs or {}) if same and latest else {},
                key_alias=None,
                actor_person_id=approver[0].id,
                reason=f"{args.issue}: razorpay ({args.mode}) on sale",
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
            action="billing.go_live_data_change",
            resource_type="tenant",
            resource_id=settings.operations_tenant_id,
            request_id=str(uuid5(NAMESPACE_URL, f"{DATA_CHANGE}:{args.issue}:{now.isoformat()}")),
            reason=" ".join(args.reason.split()),
            payload={
                "issue": args.issue,
                "data_change": DATA_CHANGE,
                "environment": args.environment,
                "plans_activated": changed,
                "provider_enabled": f"razorpay/{args.mode}" if enable else None,
            },
        )
    latest_after = await database.scalar(
        select(BillingProviderSettings).order_by(BillingProviderSettings.revision.desc()).limit(1)
    )
    return {
        "applied": bool(args.apply),
        "environment": args.environment,
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
