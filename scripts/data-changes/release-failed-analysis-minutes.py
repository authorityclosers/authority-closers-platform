#!/usr/bin/env python3
"""AUT-1801: preview an exact failed-plan list; release through the app after approval."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.asyncio_runtime import run_async
from ac_platform.application.release_identity import require_baked_release_id
from ac_platform.application.settings import Settings
from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.application import ConversationError
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.guest_models import ConversationProcessingLease
from ac_platform.conversation_intelligence.models import ConversationProcessingPlan
from ac_platform.conversation_intelligence.processing_cli import _Parser
from ac_platform.conversation_intelligence.report_minutes import ReportMinutes


async def snapshot(
    database: AsyncSession, plans: list[ConversationProcessingPlan]
) -> list[dict[str, Any]]:
    result = []
    minutes = ReportMinutes(database)
    for plan in plans:
        lease = (
            await database.get(ConversationProcessingLease, plan.processing_lease_id)
            if plan.processing_lease_id is not None
            else None
        )
        event = await minutes.latest(lease.usage_id) if lease is not None else None
        result.append(
            {
                "plan_id": str(plan.id),
                "recording_id": str(plan.recording_id),
                "state": plan.state,
                "failure_code": plan.progress.get("failure_code"),
                "processing_lease_id": str(plan.processing_lease_id)
                if plan.processing_lease_id
                else None,
                "minute_kind": event.kind if event is not None else None,
                "minute_revision": event.revision if event is not None else None,
            }
        )
    return result


async def change(database: AsyncSession, args: argparse.Namespace) -> dict[str, Any]:
    """Caller owns one transaction. App locks and the minute journal own eligibility."""
    identifiers = sorted(set(args.plan_id), key=str)
    if not 1 <= len(identifiers) <= 20 or len(identifiers) != len(args.plan_id):
        raise ValueError("One to 20 distinct plans are required.")
    query = (
        select(ConversationProcessingPlan)
        .where(ConversationProcessingPlan.id.in_(identifiers))
        .order_by(ConversationProcessingPlan.id)
    )
    if args.apply:
        query = query.with_for_update()
    plans = list(await database.scalars(query))
    if len(plans) != len(identifiers) or any(
        plan.erased_at is not None or plan.state not in {"held", "cancelled"} for plan in plans
    ):
        raise ValueError("Every exact target must be a retained terminal failed plan.")
    before = await snapshot(database, plans)
    fingerprint = content_hash({"environment": args.environment, "plans": before})
    if (
        args.apply
        and fingerprint != args.expected_fingerprint
        and not all(row["minute_kind"] in {"released", "delivered"} for row in before)
    ):
        raise ValueError("The reviewed plan state changed; a fresh preview is required.")
    changed = []
    if args.apply:
        minutes = ReportMinutes(database)
        for plan in plans:
            if await minutes.release_plan(plan):
                now: datetime | None = await database.scalar(select(func.clock_timestamp()))
                assert now is not None
                await AuditRepository(database).append(
                    tenant_id=plan.tenant_id,
                    actor_person_id=None,
                    actor_type="system",
                    action="conversation.owner_approved_failed_minutes_released",
                    resource_type="conversation_processing_plan",
                    resource_id=plan.id,
                    payload={
                        "issue": "AUT-1801",
                        "approver": args.approver,
                        "approval_reference": str(args.approval_reference),
                        "operator_reference": str(args.operator_reference),
                        "run_reference": str(args.run_reference),
                        "snapshot_reference": str(args.snapshot_reference)
                        if args.snapshot_reference
                        else None,
                        "preview_fingerprint": fingerprint,
                        "provider_calls": 0,
                    },
                    now=now,
                )
                changed.append(str(plan.id))
        await database.flush()
    return {
        "schema": "ac.sales-xray.failed-minutes-data-change/1",
        "environment": args.environment,
        "apply": args.apply,
        "before": before,
        "after": await snapshot(database, plans),
        "preview_fingerprint": fingerprint,
        "changed_plan_ids": changed,
        "provider_calls": 0,
        "run_reference": str(args.run_reference),
    }


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    if os.getenv("AC_ENVIRONMENT") != args.environment or not os.getenv("AC_DATABASE_URL"):
        raise ValueError("Matching injected runtime required.")
    if args.apply and (
        not args.approver
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,79}", args.approver)
        or args.approval_reference is None
        or args.operator_reference is None
        or args.expected_fingerprint is None
        or not re.fullmatch(r"[0-9a-f]{64}", args.expected_fingerprint)
        or (args.environment == "production" and args.snapshot_reference is None)
    ):
        raise ValueError("Recorded approval, operator, preview and production snapshot required.")
    settings = Settings(_env_file=None, environment=args.environment)
    if args.environment == "production":
        require_baked_release_id(settings.release_id)
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db, db.begin():
            if not args.apply:
                await db.execute(text("SET TRANSACTION READ ONLY"))
            await db.execute(text("SET LOCAL statement_timeout = '30s'"))
            return await change(db, args)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--environment", required=True, choices=("staging", "production"))
    parser.add_argument("--plan-id", type=UUID, action="append", required=True)
    parser.add_argument("--run-reference", type=UUID, required=True)
    parser.add_argument("--approver")
    for name in ("approval-reference", "operator-reference", "snapshot-reference"):
        parser.add_argument(f"--{name}", type=UUID)
    parser.add_argument("--expected-fingerprint")
    parser.add_argument("--apply", action="store_true")
    try:
        result = run_async(execute(parser.parse_args(argv)))
    except (ValueError, OSError, SQLAlchemyError, ConversationError):
        print(
            "Data change refused; check exact targets, approval and runtime state.", file=sys.stderr
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
