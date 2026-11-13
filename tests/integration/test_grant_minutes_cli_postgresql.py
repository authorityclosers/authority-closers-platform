"""PostgreSQL proof of the grant-minutes command (owner, 13 Nov 2026: "a command line,
by user name / email id, so when someone's minutes run out we give them another hour
or two quickly").

A dry run writes nothing. ``--apply`` writes one grant through Admin's audited path:
the learner ledger grant the admin verifier accepts, an audit event naming the
approver, and the billing ledger lot with the same source. Someone without platform
access management can't approve, and an unknown email is refused. Fictional data.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.audit.models import AuditEvent
from ac_platform.authorization.application import CapabilityApplication
from ac_platform.billing.ledger import LEGACY_GRANT_PREFIX
from ac_platform.billing.models import BillingLedgerEntry
from ac_platform.conversation_intelligence.grant_minutes_cli import (
    CommandError,
    grant,
    masked,
    validate,
)
from ac_platform.conversation_intelligence.minute_account_admin import (
    MINUTE_GRANT_ACTION,
    audited_admin_grants,
    load_minute_account,
)
from tests.database.test_conversation_postgresql import seed
from tests.integration.test_operations_http_postgresql import (
    _Harness,
    _run_async,
    _settings,
)
from tests.integration.test_operations_http_postgresql import (
    _seed as seed_operations,
)
from tests.integration.test_operations_http_postgresql import (
    postgres_harness as operations_postgres_harness,
)

REASON = "Owner-approved fixture minutes"


@pytest.fixture(scope="function")
def postgres_harness() -> Iterator[_Harness]:
    yield from operations_postgres_harness.__wrapped__()


def test_grant_minutes_dry_run_then_apply_through_the_audited_path(
    postgres_harness: _Harness,
) -> None:
    operations = seed_operations(postgres_harness.engine)

    async def scenario() -> None:
        engine = create_async_engine(
            postgres_harness.schema_url,
            connect_args={"connect_timeout": 5},
            pool_pre_ping=True,
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            learner = await seed(engine)
            settings = _settings(
                operations_tenant_id=operations.tenant_id,
                public_learner_tenant_id=learner.tenant_id,
            )
            async with sessions() as database, database.begin():
                await CapabilityApplication(
                    database, operations_tenant_id=operations.tenant_id
                ).bootstrap_first_manager(
                    person_id=operations.person_id,
                    command_id=uuid4(),
                    reason="Disposable grant-minutes fixture",
                )
            approver = f"ops-{operations.person_id.hex}@example.test"
            email = f"worker-{learner.person_id.hex}@example.test"

            # A dry run says who, where and how much, and writes nothing.
            async with sessions() as database, database.begin():
                plan = await grant(
                    database,
                    settings=settings,
                    email=email.upper(),
                    hours=2,
                    approver_email=approver,
                    workspace=None,
                    reason=REASON,
                    apply=False,
                )
                await database.rollback()
            assert plan == {
                "person": masked(email),
                "workspace": learner.tenant_id.hex,
                "role": "learner",
                "minutes": 120,
                "approver": masked(approver),
                "granted_minutes_before": 0,
                "applied": False,
            }
            assert email not in str(plan)
            async with sessions() as database:
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(AuditEvent.action == MINUTE_GRANT_ACTION)
                    )
                    == 0
                )

            # --apply: one grant the admin verifier accepts, named for its approver.
            async with sessions() as database, database.begin():
                done = await grant(
                    database,
                    settings=settings,
                    email=email,
                    hours=2,
                    approver_email=approver,
                    workspace=learner.tenant_id.hex,
                    reason=REASON,
                    apply=True,
                )
            assert done["applied"] is True
            assert done["granted_minutes_after"] == 120
            async with sessions() as database, database.begin():
                state = await load_minute_account(
                    database, tenant_id=learner.tenant_id, person_id=learner.person_id
                )
                verified = await audited_admin_grants(
                    database,
                    account=state.account,
                    tenant_id=learner.tenant_id,
                    person_id=learner.person_id,
                    operations_tenant_id=operations.tenant_id,
                )
                assert [
                    (item.seconds, event.actor_person_id, event.reason) for item, event in verified
                ] == [(7200, operations.person_id, REASON)]
                assert str(verified[0][1].id) == done["audit_event_id"]
                lots = (
                    await database.scalars(
                        select(BillingLedgerEntry).where(
                            BillingLedgerEntry.source_ref
                            == f"{LEGACY_GRANT_PREFIX}{verified[0][1].id}"
                        )
                    )
                ).all()
                assert [(lot.kind, lot.seconds, lot.actor_person_id) for lot in lots] == [
                    ("grant", 7200, operations.person_id)
                ]

            # Nobody else approves, and nobody unknown is given minutes.
            async with sessions() as database, database.begin():
                with pytest.raises(CommandError, match="platform access management"):
                    await grant(
                        database,
                        settings=settings,
                        email=email,
                        hours=1,
                        approver_email=email,
                        workspace=None,
                        reason=REASON,
                        apply=True,
                    )
            async with sessions() as database, database.begin():
                with pytest.raises(CommandError, match="No single person"):
                    await grant(
                        database,
                        settings=settings,
                        email="nobody-fictional@example.test",
                        hours=1,
                        approver_email=approver,
                        workspace=None,
                        reason=REASON,
                        apply=True,
                    )
        finally:
            await engine.dispose()

    _run_async(scenario())


def _args(**changes: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "environment": "test",
        "email": "asha-fictional@example.test",
        "hours": 2,
        "approver": "owner-fictional@example.test",
        "workspace": None,
        "reason": REASON,
        "apply": False,
        "allow_production": False,
    }
    values.update(changes)
    return argparse.Namespace(**values)


def test_grant_minutes_takes_an_hour_or_two_and_guards_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AC_ENVIRONMENT", raising=False)
    assert validate(_args()) == "test"
    for hours in (0, 25):
        with pytest.raises(CommandError, match="hours"):
            validate(_args(hours=hours))
    with pytest.raises(CommandError, match="allow-production"):
        validate(_args(environment="production", apply=True))
    assert validate(_args(environment="production")) == "production"
    with pytest.raises(CommandError, match="email"):
        validate(_args(email="not-an-email"))
    monkeypatch.setenv("AC_ENVIRONMENT", "staging")
    with pytest.raises(CommandError, match="AC_ENVIRONMENT"):
        validate(_args(environment="production"))
    assert masked("asha-fictional@example.test") == "as***@example.test"
