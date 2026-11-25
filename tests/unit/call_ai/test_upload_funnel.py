"""The upload funnel (owner, 17 Nov 2026: "upload/analysis required"): counts only."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from ac_platform.call_ai import upload_funnel

NOW = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)
ORG = uuid4()


def _event(person: object, **data: object) -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), tenant_id=ORG, actor_person_id=person, data=data)


def test_only_connected_calls_out_by_a_seller_are_seen() -> None:
    seller = uuid4()
    rows = [
        _event(seller, via="phone", duration_seconds=40),
        _event(seller, via="phone", duration_seconds=0),
        _event(seller, direction="missed", duration_seconds=12),
        _event(seller, simulated=True, duration_seconds=50),
        _event(seller, for_call=str(uuid4()), recording=True),
        _event(None, via="phone", duration_seconds=40),
    ]
    assert [call.event_id for call in upload_funnel.seen(rows)] == [str(rows[0].id)]


def test_tally_counts_sellers_and_calls() -> None:
    a, b, c = uuid4(), uuid4(), uuid4()
    calls = [
        upload_funnel.CallSeen("1", ORG, a),
        upload_funnel.CallSeen("2", ORG, a),
        upload_funnel.CallSeen("3", ORG, b),
    ]
    found = upload_funnel.tally(calls, {"2"}, {(ORG, a), (ORG, c)})
    assert found == {
        "sellers": {
            "calling": 2,
            "uploads_on": 1,
            "uploaded": 1,
            "uploads_on_share": 0.5,
            "uploaded_share": 0.5,
            "uploads_on_all": 2,
        },
        "calls": {"seen": 3, "uploaded": 1, "uploaded_share": 0.333},
    }
    assert upload_funnel.tally([], set(), set())["calls"]["uploaded_share"] is None


def test_uploads_on_is_each_phones_newest_finish() -> None:
    a, b = uuid4(), uuid4()

    def row(person: object, minutes: int, **payload: object) -> SimpleNamespace:
        return SimpleNamespace(
            id=uuid4(),
            tenant_id=ORG,
            resource_id=str(person),
            payload=payload,
            occurred_at=NOW - timedelta(minutes=minutes),
        )

    rows = [  # newest first
        row(a, 1, outcome="completed", device="x", uploads=False),
        row(a, 5, outcome="completed", device="x", uploads=True),
        row(b, 2, outcome="completed", device="y", uploads=True),
        row("not-a-person", 3, outcome="completed", device="z", uploads=True),
    ]
    assert upload_funnel.uploads_on_of(rows) == {(ORG, b)}
