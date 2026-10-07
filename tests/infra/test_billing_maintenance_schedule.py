"""Dormant UTC schedule and fictional CLI/outbox/expiry proof in loopback PostgreSQL."""

import asyncio
import configparser
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from ac_platform.application.release_identity import ReleaseIdentityError
from ac_platform.billing.ledger import BillingLedger
from ac_platform.billing.models import BillingAccount, BillingLedgerEntry
from ac_platform.outbox.models import Job
from ac_platform.outbox.policy import ReconciliationRequiredError
from ac_platform.outbox.repository import JobRepository, RecoveryStateRepository
from ac_platform.payments import cli
from tests.database.test_billing_expiry_postgresql import (
    NOW,
    acquisition,
    expiry_rows,
    lot,
    projection,
    settle,
)
from tests.database.test_billing_ledger_postgresql import raw_usage, source
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.integration.test_billing_jobs_postgresql import count_audits, ready_lab, worker

ROOT = Path(__file__).parents[2]
UNITS = ROOT / "infra/application/systemd"


@pytest.fixture
def postgres_harness():
    # The existing harness refuses missing/remote URLs and removes its own schema.
    yield from _postgres_harness.__wrapped__()


def settings(state):
    return SimpleNamespace(
        billing_enabled=True,
        public_learner_tenant_id=state.public.tenant_id,
        operations_tenant_id=state.operations.tenant_id,
        database_url=state.engine.url.render_as_string(hide_password=False),
        release_id="a" * 40,
    )


async def enqueue(state, at=NOW):
    return await cli.enqueue_expiry(
        settings=settings(state), session_factory=state.sessions, clock=lambda: at
    )


@pytest.mark.parametrize("environment", ["development", "staging"])
def test_isolated_cli_twice_one_expiry_and_unchanged_history(
    postgres_harness, monkeypatch, capsys, environment
):
    async def exercise():
        async with ready_lab(postgres_harness) as state:
            async with state.sessions() as db, db.begin():
                original = await lot(db, state)
                await lot(db, state, seconds=300, end=None)
                historical = await raw_usage(db, state.owner, 120, at=NOW - timedelta(days=30))
                await settle(db, state, historical, 0)
                history = (original.id, original.seconds, original.source_ref)
            configured = MagicMock(return_value=settings(state))
            baked = MagicMock()
            monkeypatch.setattr(cli, "Settings", configured)
            monkeypatch.setattr(cli, "require_baked_release_id", baked)
            monkeypatch.setenv("AC_ENVIRONMENT", environment)
            monkeypatch.setenv("AC_DATABASE_URL", "fictional-configuration-via-fixture")
            local = NOW.astimezone(timezone(timedelta(hours=5, minutes=30)))
            assert await cli._run(environment, clock=lambda: local) == 0
            assert (await worker(state).run_once()).expired_seconds == 600
            async with state.sessions() as db:
                job = await db.scalar(select(Job).where(Job.kind == cli.EXPIRY_JOB_KIND))
                stored = (job.id, job.available_at, job.attempt_count, job.updated_at)
                assert job.external_side_effect is False and job.recovery_generation == 0
                assert job.payload == {"account_id": str(state.account.id)}
                assert job.dedupe_key.endswith(f":{state.account.id}:2024-03-31")
            assert await cli._run(environment, clock=lambda: local + timedelta(minutes=1)) == 0
            assert (await worker(state).run_once()).outcome == "idle"
            async with state.sessions() as db:
                replayed = await db.get(Job, job.id)
                assert (
                    replayed.id,
                    replayed.available_at,
                    replayed.attempt_count,
                    replayed.updated_at,
                ) == stored
                preserved = await db.get(BillingLedgerEntry, original.id)
                assert (preserved.id, preserved.seconds, preserved.source_ref) == history
                assert len(await expiry_rows(db, state)) == await count_audits(db, state) == 1
                view = await projection(db, state)
                assert view.available == view.statement_balance == 300
            configured.assert_called_with(environment=environment, _env_file=None)
            assert baked.call_count == (2 if environment == "staging" else 0)

    run(exercise())
    outputs = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert (
        outputs
        == [{"job_kind": cli.EXPIRY_JOB_KIND, "run_date": "2024-03-31", "scheduled_accounts": 1}]
        * 2
    )


@pytest.mark.parametrize("organisation", [False, True])
def test_next_day_retries_pending_lot_without_yearly_activation(postgres_harness, organisation):
    async def exercise():
        async with ready_lab(postgres_harness, organisation=organisation) as state:
            async with state.sessions() as db, db.begin():
                original = await lot(db, state)
                future = await lot(
                    db, state, start=NOW + timedelta(days=2), end=NOW + timedelta(days=30)
                )
                if not organisation:
                    historical = await raw_usage(db, state.owner, 120, at=NOW - timedelta(days=30))
                    await settle(db, state, historical, 0)
                usage = await acquisition(db, state, NOW - timedelta(seconds=1)).reserve(
                    source(120), actor=state.owner.actor
                )
            await enqueue(state)
            assert (await worker(state).run_once()).deferred_lots == 1
            async with state.sessions() as db, db.begin():
                await settle(db, state, usage, 0)
                assert (await projection(db, state)).available == 0
            await enqueue(state)
            assert (await worker(state).run_once()).outcome == "idle"
            assert (await enqueue(state, NOW + timedelta(days=1)))["scheduled_accounts"] == 1
            assert (await worker(state).run_once()).expired_seconds == 600
            async with state.sessions() as db:
                (closing,) = await expiry_rows(db, state)
                assert closing.lot_id == original.id
                assert (await db.get(BillingLedgerEntry, future.id)).seconds == 600
                assert await db.scalar(select(func.count()).select_from(Job)) == 2
                assert (await projection(db, state, NOW + timedelta(days=2))).available == 600

    run(exercise())


def test_concurrent_passes_select_only_public_people_and_organisation_pools(postgres_harness):
    async def exercise():
        async with ready_lab(postgres_harness) as state:
            org = await seed(state.engine)
            member = await seed(state.engine, tenant_id=org.tenant_id, role="member")
            async with state.sessions() as db, db.begin():
                ledger = BillingLedger(db, clock=lambda: NOW)
                pool = await ledger.organisation_account(tenant_id=org.tenant_id, create=True)
                await ledger.personal_account(
                    tenant_id=member.tenant_id, person_id=member.person_id, create=True
                )
                await ledger.personal_account(
                    tenant_id=state.operations.tenant_id,
                    person_id=state.operations.person_id,
                    create=True,
                )
                await ledger.organisation_account(tenant_id=state.public.tenant_id, create=True)
                # Operations accounts must be excluded even when they have pool shape.
                await ledger.organisation_account(tenant_id=state.operations.tenant_id, create=True)
                before = await db.scalar(select(func.count()).select_from(BillingAccount))
            receipts = await asyncio.gather(enqueue(state), enqueue(state))
            assert all(receipt["scheduled_accounts"] == 2 for receipt in receipts)
            async with state.sessions() as db:
                jobs = list(await db.scalars(select(Job)))
                assert {job.payload["account_id"] for job in jobs} == {
                    str(state.account.id),
                    str(pool.id),
                }
                assert all(job.external_side_effect is False for job in jobs)
                assert await db.scalar(select(func.count()).select_from(BillingAccount)) == before
                assert await db.scalar(select(func.count()).select_from(BillingLedgerEntry)) == 0

    run(exercise())


def test_partial_failure_commits_only_first_intent_then_restart_replays(
    postgres_harness, monkeypatch
):
    async def exercise():
        async with ready_lab(postgres_harness) as state:
            second = await seed(state.engine, tenant_id=state.public.tenant_id)
            async with state.sessions() as db, db.begin():
                await BillingLedger(db).personal_account(
                    tenant_id=second.tenant_id, person_id=second.person_id, create=True
                )
            original = JobRepository.enqueue
            calls = 0

            async def fail_second(self, **kwargs):
                nonlocal calls
                calls += 1
                result = await original(self, **kwargs)
                if calls == 2:
                    raise RuntimeError("fictional process interruption")
                return result

            with monkeypatch.context() as patch:
                patch.setattr(JobRepository, "enqueue", fail_second)
                with pytest.raises(RuntimeError, match="fictional process interruption"):
                    await enqueue(state)
            async with state.sessions() as db:
                assert await db.scalar(select(func.count()).select_from(Job)) == 1
            assert (await enqueue(state))["scheduled_accounts"] == 2
            async with state.sessions() as db:
                assert await db.scalar(select(func.count()).select_from(Job)) == 2

    run(exercise())


def test_recovery_and_admission_locks_precede_enqueue_and_refusal_writes_nothing(
    postgres_harness, monkeypatch
):
    async def exercise():
        async with ready_lab(postgres_harness) as state:
            order = []
            ready, lock, write = (
                RecoveryStateRepository.require_ready,
                cli.take_admission_lock,
                JobRepository.enqueue,
            )

            async def require_ready(self, **kwargs):
                assert kwargs == {"lock": True, "shared_lock": True}
                order.append("recovery")
                return await ready(self, **kwargs)

            async def admission(db, tenant_id):
                order.append("admission")
                await lock(db, tenant_id)

            async def enqueue_job(self, **kwargs):
                order.append("enqueue")
                return await write(self, **kwargs)

            monkeypatch.setattr(RecoveryStateRepository, "require_ready", require_ready)
            monkeypatch.setattr(cli, "take_admission_lock", admission)
            monkeypatch.setattr(JobRepository, "enqueue", enqueue_job)
            await enqueue(state)
            assert order == ["recovery", "admission", "enqueue"]
            async with state.sessions() as db, db.begin():
                recovery = await RecoveryStateRepository(db).get()
                recovery.status = "held"
                recovery.reconciled_at = recovery.reconciled_by = recovery.reconciliation_reason = (
                    None
                )
            with pytest.raises(ReconciliationRequiredError, match="held pending"):
                await enqueue(state, NOW + timedelta(days=1))
            async with state.sessions() as db:
                assert await db.scalar(select(func.count()).select_from(Job)) == 1

    run(exercise())


@pytest.mark.parametrize(
    "field,value",
    [
        ("billing_enabled", False),
        ("public_learner_tenant_id", None),
        ("operations_tenant_id", None),
    ],
)
def test_disabled_or_unconfigured_enqueue_opens_no_database(field, value):
    configured = SimpleNamespace(
        billing_enabled=True, public_learner_tenant_id=uuid4(), operations_tenant_id=uuid4()
    )
    setattr(configured, field, value)
    sessions = MagicMock()
    with pytest.raises(ValueError, match="billing_maintenance_refused"):
        run(cli.enqueue_expiry(settings=configured, session_factory=sessions))
    sessions.assert_not_called()


def test_naive_clock_is_refused_before_database_access():
    sessions = MagicMock()
    configured = SimpleNamespace(
        billing_enabled=True, public_learner_tenant_id=uuid4(), operations_tenant_id=uuid4()
    )
    with pytest.raises(ValueError, match="clock_refused"):
        run(
            cli.enqueue_expiry(
                settings=configured, session_factory=sessions, clock=lambda: datetime(2026, 10, 7)
            )
        )
    sessions.assert_not_called()


def test_cli_requires_explicit_environment_and_database_and_redacts_errors(monkeypatch, capsys):
    engine = MagicMock()
    monkeypatch.setattr(cli, "create_async_engine", engine)
    monkeypatch.setenv("AC_ENVIRONMENT", "production")
    assert cli.main(["enqueue-expiry", "--environment", "development"]) == 2
    monkeypatch.setenv("AC_ENVIRONMENT", "development")
    monkeypatch.delenv("AC_DATABASE_URL", raising=False)
    assert cli.main(["enqueue-expiry", "--environment", "development"]) == 2
    engine.assert_not_called()
    monkeypatch.setattr(
        cli, "_run", AsyncMock(side_effect=RuntimeError("fictional secret and SQL parameters"))
    )
    assert cli.main(["enqueue-expiry", "--environment", "development"]) == 2
    captured = capsys.readouterr()
    assert not captured.out and captured.err == "billing_maintenance_refused\n" * 3


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_deployed_cli_requires_baked_identity_before_database(monkeypatch, environment, capsys):
    monkeypatch.setenv("AC_ENVIRONMENT", environment)
    monkeypatch.setenv("AC_DATABASE_URL", "fictional")
    monkeypatch.setattr(
        cli, "Settings", MagicMock(return_value=SimpleNamespace(release_id="a" * 40))
    )
    monkeypatch.setattr(
        cli,
        "require_baked_release_id",
        MagicMock(side_effect=ReleaseIdentityError("fictional marker failure")),
    )
    engine = MagicMock()
    monkeypatch.setattr(cli, "create_async_engine", engine)
    assert cli.main(["enqueue-expiry", "--environment", environment]) == 2
    engine.assert_not_called()
    assert capsys.readouterr().err == "billing_maintenance_refused\n"


def test_versioned_schedule_uses_utc_and_dormant_release_activation(tmp_path):
    timer, service = (
        configparser.ConfigParser(interpolation=None),
        configparser.ConfigParser(interpolation=None),
    )
    timer.read(UNITS / "ac-billing-maintenance.timer")
    service.read(UNITS / "ac-billing-maintenance.service")
    assert timer["Timer"]["Unit"] == "ac-billing-maintenance.service"
    assert timer["Timer"].getboolean("Persistent")
    result = subprocess.run(  # noqa: S603 - fixed local systemd parser, no runtime activation
        [
            "/usr/bin/systemd-analyze",
            "calendar",
            "--iterations=2",
            "--base-time=2026-10-07 12:00:00 UTC",
            timer["Timer"]["OnCalendar"],
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "2026-10-08 00:15:00 UTC" in result.stdout
    assert "2026-10-09 00:15:00 UTC" in result.stdout
    assert service["Service"]["Type"] == "oneshot"
    assert service["Service"]["User"] == "10001"
    assert service["Service"]["RootDirectory"].endswith("/rootfs")
    assert "ConditionPathExists" in service["Unit"]
    assert (
        "-m ac_platform.payments.cli enqueue-expiry --environment ${AC_ENVIRONMENT}"
        in service["Service"]["ExecStart"]
    )
    assert "Install" not in service
    # Verify a disposable release root instead of editing/installing host units.
    rootfs = tmp_path / "rootfs"
    executable = rootfs / "app/.venv/bin/python"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    fixture_service = tmp_path / "ac-billing-maintenance.service"
    fixture_timer = tmp_path / "ac-billing-maintenance.timer"
    fixture_service.write_text(
        (UNITS / fixture_service.name)
        .read_text()
        .replace("/srv/authority-closers/billing-maintenance/rootfs", str(rootfs))
        .replace("ExecStart=/app/.venv/bin/python", f"ExecStart={executable}")
    )
    fixture_timer.write_text((UNITS / fixture_timer.name).read_text())
    verified = subprocess.run(  # noqa: S603 - fixed local syntax check, no activation
        ["/usr/bin/systemd-analyze", "verify", str(fixture_service), str(fixture_timer)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert verified.returncode == 0, verified.stderr
