"""Explicit internal maintenance enqueue; activation belongs to release controls."""

import argparse
import json
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.application.asyncio_runtime import run_async
from ac_platform.application.release_identity import require_baked_release_id
from ac_platform.application.settings import Settings
from ac_platform.billing.expiry_jobs import EXPIRY_JOB_KIND, ExpirySessionFactory
from ac_platform.billing.models import BillingAccount
from ac_platform.conversation_intelligence.admission_lock import take_admission_lock
from ac_platform.outbox.repository import JobRepository, RecoveryStateRepository


async def enqueue_expiry(
    *,
    settings: Settings,
    session_factory: ExpirySessionFactory,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, str | int]:
    """One account intent per UTC day; partial/crashed passes can be replayed.

    Recovery then admission is the existing lock order. Each account commits
    independently; a deferred pending lot gets another intent on the next day.
    No lots, closings, provider state or yearly activation are written here.
    """
    public, operations = settings.public_learner_tenant_id, settings.operations_tenant_id
    if settings.billing_enabled is not True or public is None or operations is None:
        raise ValueError("billing_maintenance_refused")
    if public == operations:
        raise ValueError("billing_maintenance_refused")
    now = clock()
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("billing_maintenance_clock_refused")
    now = now.astimezone(UTC)
    day = now.date().isoformat()
    async with session_factory() as db:
        accounts = (
            await db.execute(
                select(BillingAccount.tenant_id, BillingAccount.id)
                .where(
                    BillingAccount.tenant_id != operations,
                    or_(
                        and_(
                            BillingAccount.tenant_id == public,
                            BillingAccount.kind == "personal",
                            BillingAccount.person_id.is_not(None),
                        ),
                        and_(
                            BillingAccount.tenant_id != public,
                            BillingAccount.kind == "organisation",
                            BillingAccount.person_id.is_(None),
                        ),
                    ),
                )
                .order_by(BillingAccount.tenant_id, BillingAccount.id)
            )
        ).all()
    for tenant_id, account_id in accounts:
        async with session_factory() as db, db.begin():
            await RecoveryStateRepository(db).require_ready(lock=True, shared_lock=True)
            await take_admission_lock(db, tenant_id)
            await JobRepository(db).enqueue(
                kind=EXPIRY_JOB_KIND,
                tenant_id=tenant_id,
                payload={"account_id": str(account_id)},
                dedupe_key=f"{EXPIRY_JOB_KIND}:{account_id}:{day}",
                available_at=now,
                external_side_effect=False,
            )
    return {"job_kind": EXPIRY_JOB_KIND, "run_date": day, "scheduled_accounts": len(accounts)}


async def _run(
    environment: str, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
) -> int:
    if os.getenv("AC_ENVIRONMENT") != environment or not os.getenv("AC_DATABASE_URL"):
        raise ValueError("billing_maintenance_refused")
    settings = Settings(environment=environment, _env_file=None)
    if environment in {"staging", "production"}:
        require_baked_release_id(settings.release_id)
    engine = create_async_engine(settings.database_url, pool_pre_ping=True, hide_parameters=True)
    try:
        receipt = await enqueue_expiry(
            settings=settings,
            session_factory=async_sessionmaker(engine, expire_on_commit=False),
            clock=clock,
        )
        print(json.dumps(receipt, sort_keys=True))
        return 0
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("action", choices=("enqueue-expiry",))
    parser.add_argument(
        "--environment",
        required=True,
        choices=("local", "test", "development", "staging", "production"),
    )
    args = parser.parse_args(argv)
    try:
        return run_async(_run(args.environment))
    except Exception:
        # Never echo configuration, database parameters or raw exception text.
        print("billing_maintenance_refused", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
