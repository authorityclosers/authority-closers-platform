"""Minutes given, used and left (owner, 18 Nov 2026): the projection's totals, no prices."""

from datetime import UTC, datetime, timedelta

from ac_platform.billing.ledger import AccountProjection
from ac_platform.billing.projection import Lot, LotKind, Use, project
from ac_platform.conversation_intelligence.minutes_summary import totals

NOW = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)


def account(lots, uses):
    return totals(account_of(lots, uses), uses)


def account_of(lots, uses):
    return AccountProjection(
        account=None,
        projection=project(lots, uses, NOW),
        trial=None,
        plan_key=None,
        per_call_seconds=7200,
    )


def lot(lot_id, seconds, *, days_left=None, started=10):
    return Lot(
        lot_id=lot_id,
        kind=LotKind.GRANT,
        seconds=seconds,
        valid_from=NOW - timedelta(days=started),
        expires_at=None if days_left is None else NOW + timedelta(days=days_left),
    )


def test_given_used_in_flight_left_and_the_next_expiry():
    current = account(
        [lot("never", 10_800), lot("soon", 600, days_left=3), lot("later", 600, days_left=9)],
        [
            Use("settled", NOW - timedelta(days=1), 700),
            Use("analysing", NOW - timedelta(minutes=5), 200, pending=True),
        ],
    )
    assert current.granted_seconds == 12_000
    assert current.used_seconds == 900
    assert current.pending_seconds == 200
    assert current.left_seconds == 11_100
    # Uses draw on the earliest-ending lot first: "soon" is spent, 300 of "later" is left.
    assert current.next_expiry_at == NOW + timedelta(days=9)
    assert current.expiring_seconds == 300
    view = current.view()
    assert set(view) == {
        "granted_seconds",
        "used_seconds",
        "pending_seconds",
        "left_seconds",
        "next_expiry_at",
        "expiring_seconds",
    }
    assert not any("price" in key or "inr" in key or "cost" in key for key in view)


def test_a_call_that_overdraws_is_still_counted_as_analysing():
    current = account([], [Use("analysing", NOW - timedelta(minutes=1), 120, pending=True)])
    assert current.granted_seconds == 0 and current.left_seconds == 0
    assert current.used_seconds == 120 and current.pending_seconds == 120


def test_expired_lots_are_not_given_and_nothing_left_never_goes_negative():
    current = account(
        [lot("old", 600, days_left=-1, started=40), lot("now", 300)],
        [Use("big", NOW - timedelta(hours=1), 500)],
    )
    assert current.granted_seconds == 300
    assert current.left_seconds == 0
    assert current.next_expiry_at is None and current.expiring_seconds == 0


def test_an_empty_workspace_has_nothing_given_and_nothing_left():
    current = account([], [])
    assert current.view() == {
        "granted_seconds": 0,
        "used_seconds": 0,
        "pending_seconds": 0,
        "left_seconds": 0,
        "next_expiry_at": None,
        "expiring_seconds": 0,
    }
