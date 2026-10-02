"""PostgreSQL proof for the S1 billing ledger: schema, append-only history, admission parity.

The parity accounts are built the way production builds them: Admin grants
through the operations HTTP route (real ``append_minute_grant`` plus the
audit event), guest and account reservations through ``AcquisitionSessions``,
one legacy ``request_run`` reservation, settled and no-work receipts, and a
raw historical usage row from the former 100-minute trial. Every fixture is
fictional.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.audit.models import AuditEvent
from ac_platform.authorization.application import CapabilityApplication
from ac_platform.billing.ledger import LEGACY_GRANT_PREFIX, AccountProjection, BillingLedger
from ac_platform.billing.models import BillingAccount, BillingLedgerEntry
from ac_platform.billing.projection import LotKind, due_expiries
from ac_platform.billing.trial import TRIAL_LOT_ID, TrialPolicy
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionUsage,
)
from ac_platform.conversation_intelligence.acquisition_sessions import (
    AcquisitionSessions,
    MeasuredSource,
)
from ac_platform.conversation_intelligence.acquisition_usage import (
    ALLOWANCE_SECONDS,
    LONGEST_CALL_EXCEEDED_MESSAGE,
    TRIAL_ALLOWANCE_INSUFFICIENT_MESSAGE,
    shared_account_committed_seconds,
)
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationDenied,
)
from ac_platform.conversation_intelligence.entitlements import MinuteAccount, MinuteGrant
from ac_platform.conversation_intelligence.minute_account_admin import MINUTE_GRANT_ACTION
from ac_platform.conversation_intelligence.models import ConversationMinuteAccount
from ac_platform.db.models import model_metadata
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from tests.database.test_conversation_postgresql import (
    ROOT,
    ActorFixture,
    run,
    seed,
    seed_budget,
    seed_run_intent,
)
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.integration.test_c1_audited_minute_allowance_postgresql import (
    _AllowanceAuthority,
    _manager_app,
)
from tests.integration.test_operations_http_postgresql import _seed as seed_operations

BILLING_TABLES = ("billing_accounts", "billing_ledger_entries")
S1_REVISION = "20261001_0062"
ADMIN_ORIGIN = "https://admin.authorityclosers.test"


@pytest.fixture(scope="module")
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


@dataclass(frozen=True)
class Operations:
    tenant_id: UUID
    person_id: UUID
    session_id: UUID

    @property
    def manager(self) -> ActorContext:
        return ActorContext(
            person_id=self.person_id,
            session_id=self.session_id,
            tenant_id=self.tenant_id,
            permissions=frozenset({"admin_surface"}),
        )


@dataclass(frozen=True)
class ParityAccount:
    """One fictional Personal account with its legacy numbers computed by hand."""

    name: str
    learner: ActorFixture
    verified_grant_seconds: int
    committed_seconds: int
    grant_event_ids: tuple[UUID, ...] = ()

    @property
    def allowance_seconds(self) -> int:
        return ALLOWANCE_SECONDS + self.verified_grant_seconds

    @property
    def available_seconds(self) -> int:
        return max(0, self.allowance_seconds - self.committed_seconds)


@dataclass(frozen=True)
class Fixtures:
    operations: Operations
    accounts: tuple[ParityAccount, ...]


def source(seconds: int) -> MeasuredSource:
    return MeasuredSource(uuid4(), uuid4().hex * 2, seconds * 1000, uuid4().hex * 2)


def engine_for(postgres_harness):
    return create_async_engine(
        postgres_harness.url, connect_args={"connect_timeout": 5}, pool_pre_ping=True
    )


def sessions_for(
    database: AsyncSession,
    learner: ActorFixture,
    operations: Operations,
    *,
    clock: datetime | None = None,
    trial_policy: TrialPolicy | None = None,
) -> AcquisitionSessions:
    kwargs: dict[str, Any] = {}
    if clock is not None:
        kwargs["clock"] = lambda: clock
    return AcquisitionSessions(
        database,
        tenant_id=learner.tenant_id,
        policy_revision="billing-s1-test-v1",
        operations_tenant_id=operations.tenant_id,
        trial_policy=trial_policy,
        **kwargs,
    )


async def bootstrap_operations(
    sessions: async_sessionmaker[AsyncSession], operations: Operations
) -> None:
    """Give the seeded operations person a current session and the manager capability."""

    async with sessions() as database, database.begin():
        await database.execute(
            update(IdentitySession)
            .where(IdentitySession.id == operations.session_id)
            .values(expires_at=datetime.now(UTC) + timedelta(days=30))
        )
        await CapabilityApplication(
            database, operations_tenant_id=operations.tenant_id
        ).bootstrap_first_manager(
            person_id=operations.person_id,
            command_id=uuid4(),
            reason="Disposable billing ledger fixture",
        )


async def admin_grant(
    sessions: async_sessionmaker[AsyncSession],
    operations: Operations,
    learner: ActorFixture,
    *,
    minutes: int,
    reason: str,
) -> UUID:
    """Grant minutes through the real Admin route; return the audit event id."""

    app = _manager_app(
        sessions=sessions, actor=operations.manager, operations_tenant_id=operations.tenant_id
    )
    target = f"/v1/admin/conversation-minute-accounts/{learner.tenant_id}/{learner.person_id}"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=ADMIN_ORIGIN
    ) as client:
        response = await client.post(
            target + "/grants",
            json={"minutes": minutes, "reason": reason},
            headers={"Origin": ADMIN_ORIGIN, "Idempotency-Key": f"billing-s1-{uuid4().hex}"},
        )
    assert response.status_code == 200, response.text
    assert response.json()["replayed"] is False
    grant_id = response.json()["grant_id"]
    async with sessions() as database:
        event = await database.scalar(
            select(AuditEvent).where(
                AuditEvent.tenant_id == operations.tenant_id,
                AuditEvent.action == MINUTE_GRANT_ACTION,
                AuditEvent.resource_id == grant_id,
            )
        )
    assert event is not None
    return event.id


async def raw_usage(
    database: AsyncSession, learner: ActorFixture, seconds: int, *, at: datetime
) -> UUID:
    """A historical reservation written before the current trial (no admission)."""

    identifier = uuid4()
    database.add(
        ConversationAcquisitionUsage(
            id=identifier,
            tenant_id=learner.tenant_id,
            visitor_id=None,
            person_id=learner.person_id,
            submission_id=uuid4(),
            source_sha256=uuid4().hex * 2,
            duration_evidence_sha256=uuid4().hex * 2,
            reserved_seconds=seconds,
            policy_revision="former-100-minute-trial",
            created_at=at,
        )
    )
    await database.flush()
    return identifier


async def build_fixtures(postgres_harness) -> Fixtures:
    seeded = seed_operations(postgres_harness)
    operations = Operations(seeded.tenant_id, seeded.person_id, seeded.session_id)
    engine = engine_for(postgres_harness)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    accounts: list[ParityAccount] = []
    try:
        await bootstrap_operations(sessions, operations)

        # A: an audited grant, a claimed guest upload, pending, settled and no-work uploads.
        learner = await seed(engine)
        event_a = await admin_grant(
            sessions, operations, learner, minutes=100, reason="Fixture A add-on"
        )
        async with sessions() as database, database.begin():
            acquisition = sessions_for(database, learner, operations)
            guest = await acquisition.issue()
            await acquisition.reserve(source(3_500), token=guest.token)
            await acquisition.claim(guest.token, learner.actor)
            await acquisition.reserve(source(3_000), actor=learner.actor)
            settled = await acquisition.reserve(source(600), actor=learner.actor)
            await acquisition.settle(settled, charged_seconds=600, receipt_sha256="a" * 64)
            released = await acquisition.reserve(source(200), actor=learner.actor)
            await acquisition.settle(
                released, charged_seconds=0, receipt_sha256="b" * 64, no_work=True
            )
        accounts.append(ParityAccount("grant-and-mixed-uses", learner, 6_000, 7_100, (event_a,)))

        # B: no grant; a claimed guest upload plus an account upload.
        learner = await seed(engine)
        async with sessions() as database, database.begin():
            acquisition = sessions_for(database, learner, operations)
            guest = await acquisition.issue()
            await acquisition.reserve(source(1_200), token=guest.token)
            await acquisition.claim(guest.token, learner.actor)
            await acquisition.reserve(source(1_800), actor=learner.actor)
        accounts.append(ParityAccount("claimed-guest-no-grant", learner, 0, 3_000))

        # C: a historical 4000 s upload from the former trial, then a 10-minute grant.
        learner = await seed(engine)
        async with sessions() as database, database.begin():
            await raw_usage(database, learner, 4_000, at=datetime.now(UTC) - timedelta(days=30))
        event_c = await admin_grant(
            sessions, operations, learner, minutes=10, reason="Fixture C after overdraft"
        )
        accounts.append(ParityAccount("historical-overdraft", learner, 600, 4_000, (event_c,)))

        # D: a legacy processing run (120 s reservation), a claimed guest upload, a 5-minute grant.
        learner = await seed(engine)
        intent = await seed_run_intent(
            engine, learner, await seed_budget(engine), allowance_seconds=3_600
        )
        async with sessions() as database, database.begin():
            acquisition = sessions_for(database, learner, operations)
            guest = await acquisition.issue()
            await acquisition.reserve(source(1_000), token=guest.token)
            await acquisition.claim(guest.token, learner.actor)
        event_d = await admin_grant(
            sessions, operations, learner, minutes=5, reason="Fixture D with legacy run"
        )
        async with sessions() as database, database.begin():
            await ConversationApplication(database, clock=lambda: learner.now).request_run(
                learner.actor,
                intent,
                key="billing-s1-legacy-run",
                authority=cast(Any, _AllowanceAuthority(operations.tenant_id)),
            )
        accounts.append(ParityAccount("legacy-run-and-grant", learner, 300, 1_120, (event_d,)))

        # E: a grant marker that no operations audit event backs; one account upload.
        learner = await seed(engine)
        async with sessions() as database, database.begin():
            forged = MinuteAccount(
                tenant_id=str(learner.tenant_id),
                account_id=str(learner.person_id),
                grants=(
                    MinuteGrant(
                        tenant_id=str(learner.tenant_id),
                        account_id=str(learner.person_id),
                        grant_id=uuid4().hex,
                        seconds=6_000,
                        authorization_ref=f"audit-event:{uuid4()}",
                        granted_by=str(operations.person_id),
                        reason="synthetic marker without a canonical audit event",
                    ),
                ),
            )
            database.add(
                ConversationMinuteAccount(
                    tenant_id=learner.tenant_id,
                    person_id=learner.person_id,
                    snapshot=forged.as_dict(),
                    revision=1,
                )
            )
            await database.flush()
            await sessions_for(database, learner, operations).reserve(
                source(100), actor=learner.actor
            )
        accounts.append(ParityAccount("unverified-grant-marker", learner, 0, 100))

        # F: a fresh person who has never uploaded.
        accounts.append(ParityAccount("fresh-person", await seed(engine), 0, 0))
    finally:
        await engine.dispose()
    return Fixtures(operations, tuple(accounts))


@pytest.fixture(scope="module")
def fixtures(postgres_harness) -> Fixtures:
    return run(build_fixtures(postgres_harness))


# ---- (a) schema ----------------------------------------------------------------


def _billing_diffs(diffs: list[Any]) -> list[Any]:
    def touches_billing(item: Any) -> bool:
        text_form = repr(item)
        return any(table in text_form for table in BILLING_TABLES)

    return [item for item in diffs if touches_billing(item)]


def test_migration_0062_applies_and_models_match_the_schema(postgres_harness):
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "db/migrations"))
    script = ScriptDirectory.from_config(config)
    assert script.get_revision(S1_REVISION) is not None
    with postgres_harness.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            script.get_current_head()
        )
        applied = {
            revision.revision
            for revision in script.iterate_revisions(script.get_current_head(), "base")
        }
        assert S1_REVISION in applied
        tables = set(
            connection.scalars(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = current_schema() AND table_name LIKE 'billing_%'"
                )
            )
        )
        assert set(BILLING_TABLES) <= tables  # 0063/0064 add the order and subscription tables
        triggers = set(
            connection.scalars(
                text(
                    "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgrelid IN "
                    "(SELECT oid FROM pg_class WHERE relname IN "
                    "('billing_accounts', 'billing_ledger_entries') "
                    "AND relnamespace = current_schema()::regnamespace)"
                )
            )
        )
        assert triggers == {f"{table}_append_only" for table in BILLING_TABLES}
        diffs = compare_metadata(MigrationContext.configure(connection), model_metadata())
        assert _billing_diffs(diffs) == []
        # The whole registry matches too, as the existing drift proofs require.
        assert diffs == []


# ---- (b) and (c) append-only history and shape checks --------------------------


async def seeded_ledger_rows(engine, operations: Operations) -> tuple[UUID, UUID]:
    learner = await seed(engine)
    async with AsyncSession(engine) as database, database.begin():
        ledger = BillingLedger(database, operations_tenant_id=operations.tenant_id)
        account = await ledger.personal_account(
            tenant_id=learner.tenant_id, person_id=learner.person_id, create=True
        )
        assert account is not None
        lot = await ledger.write_lot(
            account=account,
            kind="grant",
            seconds=600,
            valid_from=datetime.now(UTC),
            source_ref=f"grant:{uuid4()}",
            actor_type="system",
        )
        return account.id, lot.id


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_billing_history_is_append_only(postgres_harness, fixtures: Fixtures, operation):
    async def exercise():
        engine = engine_for(postgres_harness)
        try:
            account_id, lot_id = await seeded_ledger_rows(engine, fixtures.operations)
            if operation == "update":
                statements = (
                    update(BillingAccount)
                    .where(BillingAccount.id == account_id)
                    .values(kind="organisation"),
                    update(BillingLedgerEntry)
                    .where(BillingLedgerEntry.id == lot_id)
                    .values(seconds=601),
                )
            else:
                statements = (
                    delete(BillingLedgerEntry).where(BillingLedgerEntry.id == lot_id),
                    delete(BillingAccount).where(BillingAccount.id == account_id),
                )
            for statement in statements:
                async with AsyncSession(engine) as database:
                    with pytest.raises(DBAPIError, match="billing history is append-only"):
                        async with database.begin():
                            await database.execute(statement)
            async with AsyncSession(engine) as database:
                account = await database.get(BillingAccount, account_id)
                lot = await database.get(BillingLedgerEntry, lot_id)
                assert account is not None and account.kind == "personal"
                assert lot is not None and lot.seconds == 600
        finally:
            await engine.dispose()

    run(exercise())


@pytest.mark.parametrize(
    ("change", "constraint"),
    [
        ({"kind": "grant", "seconds": 600, "lot_id": "lot"}, "kind_shape"),
        ({"kind": "expiry", "seconds": 600, "lot_id": "lot"}, "kind_shape"),
        ({"kind": "refund", "seconds": -1, "lot_id": None}, "kind_shape"),
        ({"kind": "refund_hold_release", "seconds": 10, "lot_id": "lot"}, "kind_shape"),
        ({"kind": "use", "seconds": -10, "lot_id": "lot"}, "kind_supported|kind_shape"),
        ({"expires_at": "valid_from"}, "window"),
        ({"expires_at": "before"}, "window"),
        ({"actor_type": "robot"}, "actor_type_supported"),
        ({"source_ref": "ab"}, "source_ref_length"),
    ],
)
def test_ledger_shape_checks_refuse_malformed_rows(
    postgres_harness, fixtures: Fixtures, change: dict[str, Any], constraint: str
):
    async def exercise():
        engine = engine_for(postgres_harness)
        try:
            account_id, lot_id = await seeded_ledger_rows(engine, fixtures.operations)
            valid_from = datetime.now(UTC)
            row: dict[str, Any] = {
                "id": uuid4(),
                "account_id": account_id,
                "kind": "purchase",
                "seconds": 100,
                "lot_id": None,
                "hold_id": None,
                "valid_from": valid_from,
                "expires_at": valid_from + timedelta(days=30),
                "plan_key": None,
                "source_ref": f"order:{uuid4()}",
                "actor_type": "provider",
                "actor_person_id": None,
                "reason": None,
                "audit_event_id": None,
                "created_at": valid_from,
            }
            for key, value in change.items():
                if value == "lot":
                    row[key] = lot_id
                elif value == "valid_from":
                    row[key] = valid_from
                elif value == "before":
                    row[key] = valid_from - timedelta(seconds=1)
                else:
                    row[key] = value
            async with AsyncSession(engine) as database:
                with pytest.raises(IntegrityError, match=constraint):
                    async with database.begin():
                        database.add(BillingLedgerEntry(**row))
                        await database.flush()
            async with AsyncSession(engine) as database:
                count = await database.scalar(
                    select(func.count())
                    .select_from(BillingLedgerEntry)
                    .where(BillingLedgerEntry.account_id == account_id)
                )
                assert count == 1
        finally:
            await engine.dispose()

    run(exercise())


def test_account_shape_checks_refuse_malformed_accounts(postgres_harness, fixtures: Fixtures):
    async def exercise():
        engine = engine_for(postgres_harness)
        try:
            learner = await seed(engine)
            for values, constraint in (
                ({"kind": "personal", "person_id": None}, "kind_owner"),
                ({"kind": "organisation", "person_id": learner.person_id}, "kind_owner"),
                ({"kind": "team", "person_id": learner.person_id}, "kind_supported|kind_owner"),
            ):
                async with AsyncSession(engine) as database:
                    with pytest.raises(IntegrityError, match=constraint):
                        async with database.begin():
                            database.add(
                                BillingAccount(
                                    id=uuid4(),
                                    tenant_id=learner.tenant_id,
                                    created_at=datetime.now(UTC),
                                    **values,
                                )
                            )
                            await database.flush()
            # One Personal account per (tenant, person); one Organisation account per tenant.
            async with AsyncSession(engine) as database, database.begin():
                database.add_all(
                    [
                        BillingAccount(
                            id=uuid4(),
                            tenant_id=learner.tenant_id,
                            person_id=learner.person_id,
                            kind="personal",
                            created_at=datetime.now(UTC),
                        ),
                        BillingAccount(
                            id=uuid4(),
                            tenant_id=learner.tenant_id,
                            person_id=None,
                            kind="organisation",
                            created_at=datetime.now(UTC),
                        ),
                    ]
                )
            for values in (
                {"person_id": learner.person_id, "kind": "personal"},
                {"person_id": None, "kind": "organisation"},
            ):
                async with AsyncSession(engine) as database:
                    with pytest.raises(IntegrityError):
                        async with database.begin():
                            database.add(
                                BillingAccount(
                                    id=uuid4(),
                                    tenant_id=learner.tenant_id,
                                    created_at=datetime.now(UTC),
                                    **values,
                                )
                            )
                            await database.flush()
        finally:
            await engine.dispose()

    run(exercise())


# ---- (d) and (g) golden parity and the projection invariant ---------------------


async def project(
    database: AsyncSession, account: ParityAccount, fixtures: Fixtures
) -> AccountProjection:
    return await sessions_for(database, account.learner, fixtures.operations).ledger.project_person(
        tenant_id=account.learner.tenant_id,
        person_id=account.learner.person_id,
        now=datetime.now(UTC),
    )


def test_golden_parity_with_the_legacy_allowance_for_every_fixture_account(
    postgres_harness, fixtures: Fixtures
):
    async def exercise():
        engine = engine_for(postgres_harness)
        try:
            assert len(fixtures.accounts) == 6
            for account in fixtures.accounts:
                async with AsyncSession(engine) as database, database.begin():
                    legacy_committed, legacy_grants = await shared_account_committed_seconds(
                        database,
                        tenant_id=account.learner.tenant_id,
                        person_id=account.learner.person_id,
                        operations_tenant_id=fixtures.operations.tenant_id,
                    )
                    # The hand-computed numbers pin the legacy formula itself.
                    assert (legacy_committed, legacy_grants) == (
                        account.committed_seconds,
                        account.verified_grant_seconds,
                    ), account.name
                    expected = {
                        "allowance_seconds": ALLOWANCE_SECONDS + legacy_grants,
                        "committed_seconds": legacy_committed,
                        "available_seconds": max(
                            0, ALLOWANCE_SECONDS + legacy_grants - legacy_committed
                        ),
                    }
                    assert expected["available_seconds"] == account.available_seconds
                    acquisition = sessions_for(database, account.learner, fixtures.operations)
                    assert await acquisition.allowance(actor=account.learner.actor) == expected, (
                        account.name
                    )
        finally:
            await engine.dispose()

    run(exercise())


def test_parity_numbers_are_the_expected_vectors(fixtures: Fixtures):
    by_name = {account.name: account for account in fixtures.accounts}
    assert by_name["grant-and-mixed-uses"].available_seconds == 2_500
    assert by_name["claimed-guest-no-grant"].available_seconds == 600
    assert by_name["historical-overdraft"].available_seconds == 200
    assert by_name["legacy-run-and-grant"].available_seconds == 2_780
    assert by_name["unverified-grant-marker"].available_seconds == 3_500
    assert by_name["fresh-person"].available_seconds == 3_600


def test_projection_invariant_statement_balance_equals_balance_under_v1(
    postgres_harness, fixtures: Fixtures
):
    async def exercise():
        engine = engine_for(postgres_harness)
        try:
            for account in fixtures.accounts:
                async with AsyncSession(engine) as database, database.begin():
                    projected = await project(database, account, fixtures)
                    projection = projected.projection
                    assert due_expiries(projection) == (), account.name
                    assert projection.statement_balance == projection.balance, account.name
                    assert projected.available_seconds == account.available_seconds, account.name
                    assert projected.committed_seconds == account.committed_seconds, account.name
                    assert projected.granted_seconds == account.allowance_seconds, account.name
                    assert projected.trial.kind is LotKind.TRIAL
                    assert projected.trial.expires_at is None
                    grant_lots = [
                        item.lot for item in projection.positions if item.lot.kind is LotKind.GRANT
                    ]
                    assert sum(lot.capacity for lot in grant_lots) == account.verified_grant_seconds
                    if account.name == "historical-overdraft":
                        assert projection.overdraft == 400
                        assert projection.balance == 200
        finally:
            await engine.dispose()

    run(exercise())


# ---- (e) reserve through the projection ------------------------------------------


def legacy_rows(database: AsyncSession, learner: ActorFixture):
    return database.scalars(
        select(BillingLedgerEntry)
        .join(BillingAccount, BillingAccount.id == BillingLedgerEntry.account_id)
        .where(
            BillingAccount.tenant_id == learner.tenant_id,
            BillingAccount.person_id == learner.person_id,
        )
        .order_by(BillingLedgerEntry.created_at)
    )


def test_reserve_mirrors_legacy_grants_once_and_refuses_over_balance_and_over_limit(
    postgres_harness, fixtures: Fixtures
):
    operations = fixtures.operations

    async def exercise():
        engine = engine_for(postgres_harness)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            learner = await seed(engine)
            event_id = await admin_grant(
                sessions, operations, learner, minutes=100, reason="Mirror fixture"
            )
            async with sessions() as database, database.begin():
                event = await database.get(AuditEvent, event_id)
                assert event is not None
                # The Admin grant route writes the grant lot with its audit event, under
                # the same source reference the mirror uses; admission never adds a second.
                acquisition = sessions_for(database, learner, operations)
                assert (await acquisition.allowance(actor=learner.actor))[
                    "available_seconds"
                ] == 9_600
                assert len((await legacy_rows(database, learner)).all()) == 1
                first_source = source(3_000)
                first = await acquisition.reserve(first_source, actor=learner.actor)
                rows = (await legacy_rows(database, learner)).all()
                assert len(rows) == 1
                (row,) = rows
                assert row.source_ref == f"{LEGACY_GRANT_PREFIX}{event_id}"
                assert (row.kind, row.seconds, row.lot_id, row.hold_id) == (
                    "grant",
                    6_000,
                    None,
                    None,
                )
                assert row.audit_event_id == event_id
                assert row.actor_type == "person"
                assert row.actor_person_id == operations.person_id
                assert row.valid_from == event.occurred_at
                assert row.expires_at is None
                assert row.reason == "Mirror fixture"
                second = await acquisition.reserve(source(1_000), actor=learner.actor)
                assert second != first
                assert len((await legacy_rows(database, learner)).all()) == 1
                # Replaying the first receipt is the same reservation and writes nothing.
                assert await acquisition.reserve(first_source, actor=learner.actor) == first
                assert len((await legacy_rows(database, learner)).all()) == 1
                assert (await acquisition.allowance(actor=learner.actor))[
                    "available_seconds"
                ] == 5_600
            async with sessions() as database, database.begin():
                acquisition = sessions_for(database, learner, operations)
                with pytest.raises(ConversationDenied) as denied:
                    await acquisition.reserve(source(5_601), actor=learner.actor)
                assert str(denied.value) == TRIAL_ALLOWANCE_INSUFFICIENT_MESSAGE
                assert len((await legacy_rows(database, learner)).all()) == 1
                assert (await acquisition.allowance(actor=learner.actor))[
                    "available_seconds"
                ] == 5_600
            # Under trial v2 the per-call limit is 3600 s while the trial has capacity.
            async with sessions() as database, database.begin():
                acquisition = sessions_for(
                    database, learner, operations, trial_policy=TrialPolicy("v2")
                )
                assert (await acquisition.allowance(actor=learner.actor))[
                    "available_seconds"
                ] == 8_000
                with pytest.raises(ConversationDenied) as denied:
                    await acquisition.reserve(source(3_601), actor=learner.actor)
                assert str(denied.value) == LONGEST_CALL_EXCEEDED_MESSAGE
                await acquisition.reserve(source(3_600), actor=learner.actor)
                assert (await acquisition.allowance(actor=learner.actor))[
                    "available_seconds"
                ] == 4_400
            # A plan in effect sets its own per-call limit through the same path.
            async with sessions() as database, database.begin():
                acquisition = sessions_for(database, learner, operations)
                projected = await acquisition.ledger.project_person(
                    tenant_id=learner.tenant_id, person_id=learner.person_id, now=datetime.now(UTC)
                )
                assert projected.account is not None
                await acquisition.ledger.write_lot(
                    account=projected.account,
                    kind="period_grant",
                    seconds=90 * 60 * 3,
                    valid_from=datetime.now(UTC) - timedelta(minutes=1),
                    expires_at=datetime.now(UTC) + timedelta(days=30),
                    plan_key="personal",
                    source_ref=f"period:{uuid4()}:m0",
                    actor_type="provider",
                )
                assert (await acquisition.allowance(actor=learner.actor))[
                    "available_seconds"
                ] == 2_000 + 90 * 60 * 3
                with pytest.raises(ConversationDenied) as denied:
                    await acquisition.reserve(source(90 * 60 + 1), actor=learner.actor)
                assert str(denied.value) == LONGEST_CALL_EXCEEDED_MESSAGE
                await acquisition.reserve(source(90 * 60), actor=learner.actor)
            # Guests take the same limits from the trial policy and write no ledger rows.
            async with sessions() as database, database.begin():
                acquisition = sessions_for(
                    database, learner, operations, trial_policy=TrialPolicy("v2")
                )
                guest = await acquisition.issue()
                with pytest.raises(ConversationDenied) as denied:
                    await acquisition.reserve(source(3_601), token=guest.token)
                assert str(denied.value) == LONGEST_CALL_EXCEEDED_MESSAGE
                await acquisition.reserve(source(3_600), token=guest.token)
                with pytest.raises(ConversationDenied) as denied:
                    await acquisition.reserve(source(2_401), token=guest.token)
                assert str(denied.value) == TRIAL_ALLOWANCE_INSUFFICIENT_MESSAGE
                assert (await acquisition.allowance(token=guest.token))[
                    "available_seconds"
                ] == 2_400
                assert len((await legacy_rows(database, learner)).all()) == 2
        finally:
            await engine.dispose()

    run(exercise())


# ---- (f) trial v2 vectors --------------------------------------------------------


def test_trial_v2_vectors_window_end_and_switch_instant(postgres_harness, fixtures: Fixtures):
    operations = fixtures.operations

    async def exercise():
        engine = engine_for(postgres_harness)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            learner = await seed(engine)
            await admin_grant(sessions, operations, learner, minutes=10, reason="v2 vector grant")
            v2 = TrialPolicy("v2")
            async with sessions() as database, database.begin():
                acquisition = sessions_for(database, learner, operations, trial_policy=v2)
                usage = await acquisition.reserve(source(120), actor=learner.actor)
                await acquisition.settle(usage, charged_seconds=120, receipt_sha256="c" * 64)
                assert await acquisition.allowance(actor=learner.actor) == {
                    "allowance_seconds": 6_600,
                    "committed_seconds": 120,
                    "available_seconds": 6_480,
                }
                first_use = await database.scalar(
                    select(ConversationAcquisitionUsage.created_at).where(
                        ConversationAcquisitionUsage.id == usage
                    )
                )
                assert first_use is not None
                projected = await acquisition.ledger.project_person(
                    tenant_id=learner.tenant_id, person_id=learner.person_id, now=first_use
                )
                assert projected.trial.valid_from == first_use
                assert projected.trial.expires_at == first_use + timedelta(days=14)
                assert projected.plan_key == TRIAL_LOT_ID
                assert projected.per_call_seconds == 3_600
                # Keep the learner's session current for the projection 15 days on.
                await database.execute(
                    update(IdentitySession)
                    .where(IdentitySession.id == learner.session_id)
                    .values(expires_at=first_use + timedelta(days=60))
                )

            later = first_use + timedelta(days=15)
            async with sessions() as database, database.begin():
                acquisition = sessions_for(
                    database, learner, operations, clock=later, trial_policy=v2
                )
                assert await acquisition.allowance(actor=learner.actor) == {
                    "allowance_seconds": 600,
                    "committed_seconds": 120,
                    "available_seconds": 600,
                }
                projected = await acquisition.ledger.project_person(
                    tenant_id=learner.tenant_id, person_id=learner.person_id, now=later
                )
                assert not projected.trial.valid_at(later)
                assert projected.plan_key is None
                assert projected.per_call_seconds == 6_000
                trial_position = projected.projection.position(TRIAL_LOT_ID)
                assert trial_position is not None and trial_position.allocated == 120
                assert due_expiries(projected.projection) == ()
                # The window is exclusive at its end.
                edge = acquisition.ledger.trial_policy.lot(first_use_at=first_use, now=later)
                assert edge.valid_at(first_use + timedelta(days=14) - timedelta(seconds=1))
                assert not edge.valid_at(first_use + timedelta(days=14))
                with pytest.raises(ConversationDenied) as denied:
                    await acquisition.reserve(source(601), actor=learner.actor)
                assert str(denied.value) == TRIAL_ALLOWANCE_INSUFFICIENT_MESSAGE

            # A switch instant after the first use: nobody's clock starts retroactively.
            switch_at = first_use + timedelta(hours=1)
            switched = TrialPolicy("v2", switch_at=switch_at)
            async with sessions() as database, database.begin():
                ledger = BillingLedger(
                    database, trial_policy=switched, operations_tenant_id=operations.tenant_id
                )
                before = await ledger.project_person(
                    tenant_id=learner.tenant_id,
                    person_id=learner.person_id,
                    now=switch_at - timedelta(minutes=1),
                )
                assert before.trial.seconds == 3_600
                assert before.trial.expires_at is None
                assert before.trial.valid_from == first_use
                assert before.per_call_seconds == 6_000
                assert before.available_seconds == 3_600 + 600 - 120
                after = await ledger.project_person(
                    tenant_id=learner.tenant_id,
                    person_id=learner.person_id,
                    now=switch_at + timedelta(hours=1),
                )
                assert after.trial.seconds == 6_000
                assert after.trial.valid_from == switch_at
                assert after.trial.expires_at == switch_at + timedelta(days=14)
                assert after.per_call_seconds == 3_600
                # The settled use predates the switched window, so it falls to the grant.
                assert after.available_seconds == 6_000 + 600 - 120
                grant_position = next(
                    item for item in after.projection.positions if item.lot.kind is LotKind.GRANT
                )
                assert grant_position.allocated == 120
        finally:
            await engine.dispose()

    run(exercise())
