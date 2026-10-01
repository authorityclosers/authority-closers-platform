"""The ledger service on SQLite: netting, idempotent writes, plan in effect, per-call limits.

SQLite drops the UTC offset of ``DateTime(timezone=True)`` columns and the
ledger refuses naive times, so the session adapter below restores UTC on
column rows (as PostgreSQL's timestamptz carries it) and every ledger row a
test writes stays referenced (``state.rows``) so the identity map, which holds
weak references, serves the aware values instead of reloading the row. Locks,
triggers and the real admission path are PostgreSQL evidence in
``tests/database/test_billing_ledger_postgresql.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from ac_platform.billing.ledger import (
    PER_CALL_DEFAULT_SECONDS,
    PLAN_PER_CALL_SECONDS,
    BillingConflict,
    BillingError,
    BillingLedger,
    plan_in_effect,
)
from ac_platform.billing.models import BillingAccount, BillingLedgerEntry
from ac_platform.billing.projection import Lot, LotKind, Use, project
from ac_platform.billing.trial import TRIAL_LOT_ID, TrialPolicy
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionSettlement,
    ConversationAcquisitionUsage,
    ConversationVisitor,
    ConversationVisitorClaim,
)
from ac_platform.db.models import model_metadata
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.tenancy.models import Membership, Tenant
from tests.unit.test_practice_engine import AwaitableSession

T0 = datetime(2026, 10, 1, 12, tzinfo=UTC)


def day(number: float) -> datetime:
    return T0 + timedelta(days=number)


class BillingSession(AwaitableSession):
    """Column rows with the UTC offset SQLite dropped; ORM rows come from the identity map."""

    async def execute(self, statement: Any) -> Any:
        return [
            tuple(
                value.replace(tzinfo=UTC)
                if isinstance(value, datetime) and value.tzinfo is None
                else value
                for value in row
            )
            for row in self.database.execute(statement)
        ]


@pytest.fixture
def state() -> Iterator[SimpleNamespace]:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection: Any, _record: Any) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    model_metadata().create_all(engine)
    with Session(engine, expire_on_commit=False) as db, db.begin():
        state = SimpleNamespace(db=db, now=T0)
        state.tenant, state.person, state.operations = uuid4(), uuid4(), uuid4()
        state.session = uuid4()
        db.add_all(
            [
                Tenant(id=state.tenant, slug="billing-test", name="Billing test"),
                Tenant(id=state.operations, slug="ops-test", name="Operations"),
                Person(id=state.person, email_verified_at=T0),
            ]
        )
        db.flush()
        db.add(Membership(tenant_id=state.tenant, person_id=state.person, role="learner"))
        db.flush()
        db.add(
            IdentitySession(
                id=state.session,
                person_id=state.person,
                selected_tenant_id=state.tenant,
                token_hash=state.session.bytes * 2,
                created_at=T0,
                expires_at=day(30),
            )
        )
        db.flush()
        state.async_db = BillingSession(db)
        state.ledger = BillingLedger(
            state.async_db,
            clock=lambda: state.now,
            operations_tenant_id=state.operations,
        )
        state.rows = []
        yield state
    engine.dispose()


async def write_lot(state: SimpleNamespace, **facts: Any) -> BillingLedgerEntry:
    row = await state.ledger.write_lot(**facts)
    state.rows.append(row)
    return row


async def write_closing(state: SimpleNamespace, **facts: Any) -> BillingLedgerEntry:
    row = await state.ledger.write_closing(**facts)
    state.rows.append(row)
    return row


def entry(
    account_id: UUID,
    kind: str,
    seconds: int,
    *,
    lot_id: UUID | None = None,
    hold_id: UUID | None = None,
    start: float = 0,
    end: float | None = None,
    plan_key: str | None = None,
) -> BillingLedgerEntry:
    return BillingLedgerEntry(
        id=uuid4(),
        account_id=account_id,
        kind=kind,
        seconds=seconds,
        lot_id=lot_id,
        hold_id=hold_id,
        valid_from=day(start),
        expires_at=None if end is None else day(end),
        plan_key=plan_key,
        source_ref=f"test:{uuid4()}",
        actor_type="system",
        created_at=day(start),
    )


async def personal(state: SimpleNamespace) -> BillingAccount:
    account = await state.ledger.personal_account(
        tenant_id=state.tenant, person_id=state.person, create=True
    )
    assert account is not None
    return account


def count_entries(state: SimpleNamespace) -> int:
    return state.db.scalar(select(func.count()).select_from(BillingLedgerEntry))


def visitor(state: SimpleNamespace, *, claimed: bool = False) -> UUID:
    identifier = uuid4()
    state.db.add(
        ConversationVisitor(
            id=identifier,
            tenant_id=state.tenant,
            token_hash=identifier.bytes * 2,
            created_at=day(-2),
            expires_at=day(-1),
        )
    )
    state.db.flush()
    if claimed:
        state.db.add(
            ConversationVisitorClaim(
                visitor_id=identifier,
                tenant_id=state.tenant,
                person_id=state.person,
                session_id=state.session,
                created_at=day(-1),
            )
        )
        state.db.flush()
    return identifier


def usage(
    state: SimpleNamespace,
    seconds: int,
    *,
    at: datetime,
    visitor_id: UUID | None = None,
    charged: int | None = None,
) -> UUID:
    """One admitted source, pending unless ``charged`` settles it (0 = no work)."""

    identifier = uuid4()
    state.db.add(
        ConversationAcquisitionUsage(
            id=identifier,
            tenant_id=state.tenant,
            visitor_id=visitor_id,
            person_id=None if visitor_id is not None else state.person,
            submission_id=uuid4(),
            source_sha256="a" * 64,
            duration_evidence_sha256="b" * 64,
            reserved_seconds=seconds,
            policy_revision="unit-v1",
            created_at=at,
        )
    )
    state.db.flush()
    if charged is not None:
        state.db.add(
            ConversationAcquisitionSettlement(
                usage_id=identifier,
                charged_seconds=charged,
                kind="no_work_performed" if charged == 0 else "completed",
                receipt_sha256="c" * 64,
                created_at=at + timedelta(minutes=5),
            )
        )
        state.db.flush()
    return identifier


# ---- lots_from_entries ------------------------------------------------------


def test_lots_from_entries_nets_closings_and_gives_hold_releases_back() -> None:
    account_id = uuid4()
    purchase = entry(account_id, "purchase", 1000, start=0, end=30, plan_key="personal")
    hold = entry(account_id, "refund_hold", -1000, lot_id=purchase.id, start=1)
    release = entry(account_id, "refund_hold_release", 1000, lot_id=purchase.id, hold_id=hold.id)
    refund = entry(account_id, "refund", -300, lot_id=purchase.id, start=2)
    grant = entry(account_id, "grant", 600, start=0)
    expiry = entry(account_id, "expiry", -600, lot_id=grant.id, start=3)
    positive_correction = entry(account_id, "correction", 120, start=0)
    negative_correction = entry(account_id, "correction", -20, lot_id=positive_correction.id)

    lots = BillingLedger.lots_from_entries(
        [purchase, hold, release, refund, grant, expiry, positive_correction, negative_correction]
    )

    by_id = {lot.lot_id: lot for lot in lots}
    assert set(by_id) == {str(purchase.id), str(grant.id), str(positive_correction.id)}
    assert by_id[str(purchase.id)].closed_seconds == 300
    assert by_id[str(purchase.id)].capacity == 700
    assert by_id[str(purchase.id)].kind is LotKind.PURCHASE
    assert by_id[str(purchase.id)].plan_key == "personal"
    assert by_id[str(purchase.id)].expires_at == day(30)
    assert by_id[str(grant.id)].closed_seconds == 600
    assert by_id[str(grant.id)].capacity == 0
    assert by_id[str(positive_correction.id)].kind is LotKind.CORRECTION
    assert by_id[str(positive_correction.id)].capacity == 100


def test_lots_from_entries_keeps_a_hold_closed_until_released() -> None:
    account_id = uuid4()
    purchase = entry(account_id, "purchase", 500)
    hold = entry(account_id, "refund_hold", -500, lot_id=purchase.id)
    (lot,) = BillingLedger.lots_from_entries([purchase, hold])
    assert lot.capacity == 0
    (lot,) = BillingLedger.lots_from_entries(
        [purchase, hold, entry(account_id, "refund_hold_release", 500, lot_id=purchase.id)]
    )
    assert lot.capacity == 500


def test_lots_from_entries_refuses_closings_beyond_the_lot() -> None:
    account_id = uuid4()
    grant = entry(account_id, "grant", 100)
    with pytest.raises(ValueError, match="closings cannot be negative or exceed the lot"):
        BillingLedger.lots_from_entries([grant, entry(account_id, "refund", -101, lot_id=grant.id)])
    with pytest.raises(ValueError, match="closings cannot be negative or exceed the lot"):
        BillingLedger.lots_from_entries(
            [grant, entry(account_id, "refund_hold_release", 1, lot_id=grant.id)]
        )


def test_lots_from_entries_refuses_naive_times() -> None:
    row = entry(uuid4(), "grant", 100)
    row.valid_from = row.valid_from.replace(tzinfo=None)
    with pytest.raises(ValueError, match="timezone-aware"):
        BillingLedger.lots_from_entries([row])


# ---- accounts ---------------------------------------------------------------


async def test_personal_account_is_created_once_and_never_for_operations(
    state: SimpleNamespace,
) -> None:
    ledger = state.ledger
    assert await ledger.personal_account(tenant_id=state.tenant, person_id=state.person) is None
    account = await personal(state)
    assert (account.kind, account.tenant_id, account.person_id) == (
        "personal",
        state.tenant,
        state.person,
    )
    assert account.created_at == T0
    again = await personal(state)
    assert again.id == account.id
    assert state.db.scalar(select(func.count()).select_from(BillingAccount)) == 1
    with pytest.raises(BillingError, match="operations tenant"):
        await ledger.personal_account(tenant_id=state.operations, person_id=state.person)


def test_ledger_composition_is_validated(state: SimpleNamespace) -> None:
    with pytest.raises(ValueError, match="Invalid billing composition"):
        BillingLedger(state.async_db, operations_tenant_id="not-a-uuid")
    assert BillingLedger(state.async_db).trial_policy == TrialPolicy()


# ---- write_lot --------------------------------------------------------------


async def test_write_lot_is_idempotent_on_source_ref_with_the_same_facts(
    state: SimpleNamespace,
) -> None:
    account = await personal(state)
    first = await write_lot(
        state,
        account=account,
        kind="grant",
        seconds=600,
        valid_from=day(-1),
        source_ref="legacy-grant:fixture-1",
        actor_type="person",
        actor_person_id=state.person,
        reason="fixture",
    )
    assert (first.kind, first.seconds, first.lot_id, first.hold_id) == ("grant", 600, None, None)
    assert first.valid_from == day(-1)
    assert first.expires_at is None
    assert first.created_at == T0
    again = await write_lot(
        state,
        account=account,
        kind="grant",
        seconds=600,
        valid_from=day(-1),
        source_ref="legacy-grant:fixture-1",
        actor_type="person",
    )
    assert again is first
    assert count_entries(state) == 1


@pytest.mark.parametrize("change", ["seconds", "kind", "account"])
async def test_write_lot_refuses_a_source_ref_that_names_different_facts(
    state: SimpleNamespace, change: str
) -> None:
    account = await personal(state)
    facts: dict[str, Any] = {
        "account": account,
        "kind": "grant",
        "seconds": 600,
        "valid_from": day(0),
        "source_ref": "legacy-grant:fixture-2",
        "actor_type": "system",
    }
    await write_lot(state, **facts)
    if change == "seconds":
        changed: dict[str, Any] = {"seconds": 601}
    elif change == "kind":
        changed = {"kind": "purchase"}
    else:
        other_person = uuid4()
        state.db.add(Person(id=other_person, email_verified_at=T0))
        state.db.flush()
        changed = {
            "account": await state.ledger.personal_account(
                tenant_id=state.tenant, person_id=other_person, create=True
            )
        }
    with pytest.raises(BillingConflict, match="already names a different entry"):
        await write_lot(state, **{**facts, **changed})
    assert count_entries(state) == 1


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"kind": "expiry"}, "supported kind and positive seconds"),
        ({"kind": "correction"}, "supported kind and positive seconds"),
        ({"seconds": 0}, "supported kind and positive seconds"),
        ({"seconds": -5}, "supported kind and positive seconds"),
        ({"seconds": True}, "supported kind and positive seconds"),
        ({"actor_type": "robot"}, "Unsupported ledger actor type"),
        ({"source_ref": "ab"}, "source reference is required"),
        ({"source_ref": "x" * 161}, "source reference is required"),
        ({"valid_from": T0.replace(tzinfo=None)}, "timezone-aware"),
        ({"expires_at": T0.replace(tzinfo=None)}, "timezone-aware"),
    ],
)
async def test_write_lot_refuses_bad_input_without_writing(
    state: SimpleNamespace, kwargs: dict[str, Any], message: str
) -> None:
    account = await personal(state)
    facts: dict[str, Any] = {
        "account": account,
        "kind": "purchase",
        "seconds": 100,
        "valid_from": day(0),
        "source_ref": "order:fixture",
        "actor_type": "provider",
        **kwargs,
    }
    with pytest.raises((BillingError, ValueError), match=message):
        await write_lot(state, **facts)
    assert count_entries(state) == 0


# ---- write_closing ----------------------------------------------------------


async def test_write_closing_writes_negative_seconds_against_the_lot(
    state: SimpleNamespace,
) -> None:
    account = await personal(state)
    lot = await write_lot(
        state,
        account=account,
        kind="purchase",
        seconds=1000,
        valid_from=day(0),
        expires_at=day(30),
        plan_key="personal",
        source_ref="order:fixture-3",
        actor_type="provider",
    )
    closing = await write_closing(
        state,
        lot=lot,
        kind="refund_hold",
        seconds=1000,
        remainder=1000,
        source_ref="refund-hold:fixture-3",
        actor_type="person",
        actor_person_id=state.person,
        reason="refund requested",
    )
    assert closing.seconds == -1000
    assert closing.lot_id == lot.id
    assert closing.hold_id is None
    assert closing.account_id == account.id
    assert (closing.valid_from, closing.expires_at, closing.plan_key) == (day(0), None, "personal")
    assert closing.created_at == T0
    lots = BillingLedger.lots_from_entries(await state.ledger.entries(account.id))
    assert [item.capacity for item in lots] == [0]
    # The same closing again is the same row; the remainder check runs first,
    # so a replay must carry the remainder the projection showed before the write.
    again = await write_closing(
        state,
        lot=lot,
        kind="refund_hold",
        seconds=1000,
        remainder=1000,
        source_ref="refund-hold:fixture-3",
        actor_type="person",
    )
    assert again is closing
    with pytest.raises(BillingConflict, match="cannot exceed the lot's remaining capacity"):
        await write_closing(
            state,
            lot=lot,
            kind="refund_hold",
            seconds=1000,
            remainder=0,
            source_ref="refund-hold:fixture-3",
            actor_type="person",
        )
    assert count_entries(state) == 2


@pytest.mark.parametrize("seconds", [1001, 0, -1, True])
async def test_write_closing_refuses_more_than_the_remainder(
    state: SimpleNamespace, seconds: int
) -> None:
    account = await personal(state)
    lot = await write_lot(
        state,
        account=account,
        kind="grant",
        seconds=1000,
        valid_from=day(0),
        source_ref="grant:fixture-4",
        actor_type="system",
    )
    with pytest.raises(BillingConflict, match="cannot exceed the lot's remaining capacity"):
        await write_closing(
            state,
            lot=lot,
            kind="expiry",
            seconds=seconds,
            remainder=1000,
            source_ref="expiry:fixture-4",
            actor_type="system",
        )
    # ``remainder`` is what the projection left, not the lot's face value.
    with pytest.raises(BillingConflict, match="cannot exceed the lot's remaining capacity"):
        await write_closing(
            state,
            lot=lot,
            kind="expiry",
            seconds=400,
            remainder=399,
            source_ref="expiry:fixture-4",
            actor_type="system",
        )
    assert count_entries(state) == 1


async def test_write_closing_refuses_non_lot_targets_and_unknown_kinds(
    state: SimpleNamespace,
) -> None:
    account = await personal(state)
    lot = await write_lot(
        state,
        account=account,
        kind="grant",
        seconds=1000,
        valid_from=day(0),
        source_ref="grant:fixture-5",
        actor_type="system",
    )
    closing = await write_closing(
        state,
        lot=lot,
        kind="refund",
        seconds=100,
        remainder=1000,
        source_ref="refund:fixture-5",
        actor_type="provider",
    )
    with pytest.raises(BillingError, match="Closings reference a lot"):
        await write_closing(
            state,
            lot=closing,
            kind="refund",
            seconds=1,
            remainder=100,
            source_ref="refund:fixture-5b",
            actor_type="provider",
        )
    for kind in ("refund_hold_release", "grant", "purchase"):
        with pytest.raises(BillingError, match="supported kind"):
            await write_closing(
                state,
                lot=lot,
                kind=kind,
                seconds=1,
                remainder=900,
                source_ref=f"{kind}:fixture-5b",
                actor_type="provider",
            )
    assert count_entries(state) == 2


# ---- plan_in_effect ---------------------------------------------------------


def trial(seconds: int = 3600, *, start: float = 0, end: float | None = None) -> Lot:
    return Lot(
        lot_id=TRIAL_LOT_ID,
        kind=LotKind.TRIAL,
        seconds=seconds,
        valid_from=day(start),
        expires_at=None if end is None else day(end),
    )


def period(lot_id: str, plan_key: str | None, *, start: float, end: float) -> Lot:
    return Lot(
        lot_id=lot_id,
        kind=LotKind.PERIOD_GRANT,
        seconds=5400,
        valid_from=day(start),
        expires_at=day(end),
        plan_key=plan_key,
    )


def test_plan_in_effect_prefers_the_latest_valid_period_grant() -> None:
    lots = [
        trial(start=-100),
        period("p-old", "personal", start=-60, end=-30),
        period("p-current", "personal", start=-20, end=10),
        period("p-org", "organisation", start=-5, end=25),
        period("p-future", "personal", start=3, end=33),
    ]
    assert plan_in_effect(project(lots, [], day(0))) == "organisation"
    assert plan_in_effect(project(lots, [], day(-10))) == "personal"
    assert plan_in_effect(project(lots, [], day(-45))) == "personal"
    # The future lot starts before the projection time: it is now the latest.
    assert plan_in_effect(project(lots, [], day(4))) == "personal"
    # Between periods (p-old ended, p-current not started) the trial decides.
    assert plan_in_effect(project(lots, [], day(-25))) == TRIAL_LOT_ID
    # Before any period lot started, the trial decides too.
    assert plan_in_effect(project(lots, [], day(-70))) == TRIAL_LOT_ID


def test_plan_in_effect_ignores_period_lots_without_a_plan_key() -> None:
    lots = [trial(), period("p-unkeyed", None, start=-1, end=10)]
    assert plan_in_effect(project(lots, [], day(0))) == TRIAL_LOT_ID


def test_plan_in_effect_is_trial_while_the_trial_lot_has_unallocated_capacity() -> None:
    # The grant starts after the trial, so first-out order takes the trial first.
    grant = Lot(lot_id="g", kind=LotKind.GRANT, seconds=600, valid_from=day(0.25))
    assert plan_in_effect(project([trial(), grant], [], day(1))) == TRIAL_LOT_ID
    partly = [Use(use_id="u1", at=day(0.5), seconds=3599)]
    assert plan_in_effect(project([trial(), grant], partly, day(1))) == TRIAL_LOT_ID
    exhausted = [Use(use_id="u1", at=day(0.5), seconds=3600)]
    assert plan_in_effect(project([trial(), grant], exhausted, day(1))) is None
    # A pending reservation counts as allocated too.
    pending = [Use(use_id="u1", at=day(0.5), seconds=3600, pending=True)]
    assert plan_in_effect(project([trial(), grant], pending, day(1))) is None


def test_plan_in_effect_is_none_once_the_trial_window_ends() -> None:
    lots = [trial(6000, start=0, end=14), Lot("g", LotKind.GRANT, 600, day(0))]
    assert plan_in_effect(project(lots, [], day(13.9))) == TRIAL_LOT_ID
    assert plan_in_effect(project(lots, [], day(14))) is None
    assert plan_in_effect(project([Lot("p", LotKind.PURCHASE, 600, day(0))], [], day(1))) is None
    assert plan_in_effect(project([], [], day(1))) is None


# ---- projections -------------------------------------------------------------


async def test_project_visitor_gives_the_trial_lot_only(state: SimpleNamespace) -> None:
    projected = await state.ledger.project_visitor(
        tenant_id=state.tenant, visitor_id=uuid4(), now=T0
    )
    assert projected.account is None
    assert [item.lot.lot_id for item in projected.projection.positions] == [TRIAL_LOT_ID]
    assert projected.trial.lot_id == TRIAL_LOT_ID
    assert projected.trial.valid_from == T0
    assert projected.available_seconds == 3600
    assert projected.granted_seconds == 3600
    assert projected.committed_seconds == 0
    assert projected.plan_key == TRIAL_LOT_ID
    assert projected.per_call_seconds == 6000


async def test_project_visitor_counts_its_own_uses_only(state: SimpleNamespace) -> None:
    guest, other = visitor(state), visitor(state)
    usage(state, 1200, at=day(-1), visitor_id=guest)
    usage(state, 300, at=day(-0.5), visitor_id=guest, charged=300)
    usage(state, 200, at=day(-0.25), visitor_id=guest, charged=0)
    usage(state, 3000, at=day(-1), visitor_id=other)
    projected = await state.ledger.project_visitor(tenant_id=state.tenant, visitor_id=guest, now=T0)
    assert projected.trial.valid_from == day(-1)
    assert projected.committed_seconds == 1500
    assert projected.available_seconds == 2100
    (position,) = projected.projection.positions
    assert (position.allocated, position.pending_allocated) == (1500, 1200)
    assert projected.account is None


async def test_project_person_without_account_or_legacy_grants_gives_the_trial_lot(
    state: SimpleNamespace,
) -> None:
    projected = await state.ledger.project_person(
        tenant_id=state.tenant, person_id=state.person, now=T0
    )
    assert projected.account is None
    assert [item.lot.lot_id for item in projected.projection.positions] == [TRIAL_LOT_ID]
    assert projected.available_seconds == 3600
    assert projected.plan_key == TRIAL_LOT_ID
    assert projected.per_call_seconds == 6000
    assert state.db.scalar(select(func.count()).select_from(BillingAccount)) == 0

    # Mirroring creates the account under the caller's lock, still trial only.
    mirrored = await state.ledger.project_person(
        tenant_id=state.tenant, person_id=state.person, now=T0, mirror=True
    )
    assert mirrored.account is not None
    assert mirrored.account.person_id == state.person
    assert [item.lot.lot_id for item in mirrored.projection.positions] == [TRIAL_LOT_ID]
    assert count_entries(state) == 0


async def test_project_person_counts_claimed_guest_uses_once(state: SimpleNamespace) -> None:
    claimed, unclaimed = visitor(state, claimed=True), visitor(state)
    usage(state, 1000, at=day(-2), visitor_id=claimed)
    usage(state, 500, at=day(-1), visitor_id=unclaimed)
    usage(state, 1800, at=day(-0.5))
    usage(state, 100, at=day(-0.25), charged=0)
    projected = await state.ledger.project_person(
        tenant_id=state.tenant, person_id=state.person, now=T0
    )
    assert projected.trial.valid_from == day(-2)
    assert projected.committed_seconds == 2800
    assert projected.available_seconds == 800
    assert projected.granted_seconds == 3600


async def test_project_person_refuses_naive_now(state: SimpleNamespace) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        await state.ledger.project_person(
            tenant_id=state.tenant, person_id=state.person, now=T0.replace(tzinfo=None)
        )


async def test_project_person_under_v2_uses_the_v2_trial(state: SimpleNamespace) -> None:
    ledger = BillingLedger(state.async_db, clock=lambda: T0, trial_policy=TrialPolicy("v2"))
    projected = await ledger.project_person(tenant_id=state.tenant, person_id=state.person, now=T0)
    assert projected.available_seconds == 6000
    assert projected.trial.expires_at == T0 + timedelta(days=14)
    assert projected.per_call_seconds == 3600


@pytest.mark.parametrize(
    ("plan_key", "expected"),
    [("personal", 90 * 60), ("organisation", 120 * 60)],
)
async def test_per_call_limit_follows_the_plan_in_effect(
    state: SimpleNamespace, plan_key: str, expected: int
) -> None:
    assert PLAN_PER_CALL_SECONDS[plan_key] == expected
    account = await personal(state)
    await write_lot(
        state,
        account=account,
        kind="period_grant",
        seconds=5400,
        valid_from=day(-1),
        expires_at=day(29),
        plan_key=plan_key,
        source_ref=f"period:{plan_key}:m0",
        actor_type="provider",
    )
    projected = await state.ledger.project_person(
        tenant_id=state.tenant, person_id=state.person, now=T0
    )
    assert projected.plan_key == plan_key
    assert projected.per_call_seconds == expected
    assert projected.available_seconds == 3600 + 5400
    assert projected.granted_seconds == 3600 + 5400


async def test_per_call_limit_on_trial_follows_the_trial_policy(state: SimpleNamespace) -> None:
    account = await personal(state)
    for version, expected in (("v1", 6000), ("v2", 3600)):
        ledger = BillingLedger(state.async_db, clock=lambda: T0, trial_policy=TrialPolicy(version))
        projected = await ledger.project_person(
            tenant_id=state.tenant, person_id=state.person, now=T0
        )
        assert projected.account is account
        assert projected.plan_key == TRIAL_LOT_ID
        assert projected.per_call_seconds == expected


async def test_per_call_limit_for_grant_only_accounts_is_the_default(
    state: SimpleNamespace,
) -> None:
    assert PER_CALL_DEFAULT_SECONDS == 6000
    account = await personal(state)
    # The use predates the grant, so only the trial can absorb it.
    usage(state, 3600, at=day(-0.5))
    await write_lot(
        state,
        account=account,
        kind="grant",
        seconds=600,
        valid_from=day(-0.25),
        source_ref="grant:fixture-6",
        actor_type="person",
        actor_person_id=state.person,
    )
    # v1: the trial never ends, so grant-only means the trial is used up.
    projected = await state.ledger.project_person(
        tenant_id=state.tenant, person_id=state.person, now=T0
    )
    assert projected.plan_key is None
    assert projected.per_call_seconds == PER_CALL_DEFAULT_SECONDS
    assert projected.available_seconds == 600
    assert projected.granted_seconds == 4200

    # v2: the window has ended; only the grant is left.
    v2 = BillingLedger(state.async_db, clock=lambda: T0, trial_policy=TrialPolicy("v2"))
    later = day(15)
    grant_only = await v2.project_person(tenant_id=state.tenant, person_id=state.person, now=later)
    assert grant_only.trial.expires_at == day(-0.5) + timedelta(days=14)
    assert grant_only.plan_key is None
    assert grant_only.per_call_seconds == PER_CALL_DEFAULT_SECONDS
    # The 3600 s use took the trial first (it expires first); the grant is untouched.
    assert grant_only.available_seconds == 600
    assert grant_only.granted_seconds == 600
