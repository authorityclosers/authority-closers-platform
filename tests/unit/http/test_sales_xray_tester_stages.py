"""Where a Sales X-Ray Play tester stands (owner, 13 Nov 2026): rows fold into one standing,
the stage is the furthest step reached (installed and active from app sessions), a listed
tester's production facts stand in where this environment has none, and the export is safe
to open in a spreadsheet."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from ac_platform.testers import store
from ac_platform.testers.models import SalesXrayTesterEvent

NOW = datetime(2026, 11, 13, 14, 0, tzinfo=UTC)


def _row(kind: str, minutes: int = 0, **values: Any) -> SalesXrayTesterEvent:
    return SalesXrayTesterEvent(
        id=uuid4(),
        email="ravi.tester@example.test",
        kind=kind,
        actor_person_id=uuid4(),
        created_at=NOW - timedelta(days=3) + timedelta(minutes=minutes),
        **values,
    )


def test_an_applicant_folds_from_waiting_to_ready() -> None:
    applied = _row("applied", phone_model="Redmi 13", role="seller", business="Solar")
    standing = store.fold([applied])
    assert standing.id == applied.id and standing.source == "applied"
    assert standing.public_state == "waiting"
    approved = _row("approved", 1)
    assert store.fold([applied, approved]).public_state == "approved"
    added = _row("added_to_group", 2, via="admin")
    emailed = _row("emailed", 3, via="app")
    standing = store.fold([applied, approved, added, emailed])
    assert standing.public_state == "ready"
    assert standing.phone_model == "Redmi 13" and standing.email_event_id == emailed.id
    # The newest decision stands; a later decline holds over the group.
    assert store.fold([applied, approved, added, _row("declined", 4)]).public_state == "declined"


def test_a_listed_member_is_already_in_the_group() -> None:
    standing = store.fold([_row("listed", name="Ravi K"), _row("added_to_group", 1, via="seed")])
    assert standing.public_state == "ready" and standing.in_group_via == "seed"
    assert store.first_name(standing.name) == "Ravi"
    assert store.first_name(None) == "there"


@pytest.mark.parametrize(
    ("activity", "status", "stage"),
    [
        (store.Activity(), None, "in_group"),
        (store.Activity(), "queued", "emailed"),
        (store.Activity(), "failed", "in_group"),
        (
            store.Activity(
                first_app_at=NOW - timedelta(days=20), last_app_at=NOW - timedelta(days=9)
            ),
            "sent",
            "installed",
        ),
        (
            store.Activity(
                first_app_at=NOW - timedelta(days=20), last_app_at=NOW - timedelta(days=2)
            ),
            "sent",
            "active",
        ),
    ],
)
def test_the_stage_is_the_furthest_step(
    activity: store.Activity, status: str | None, stage: str
) -> None:
    rows = [_row("applied", phone_model="x1", role="owner", business="b"), _row("approved", 1)]
    rows.append(_row("added_to_group", 2, via="admin"))
    if status is not None:
        rows.append(_row("emailed", 3, via="app"))
    assert store.stage_of(store.fold(rows), activity, status, NOW) == stage


def test_waiting_approved_and_declined_stages() -> None:
    applied = _row("applied", phone_model="x1", role="owner", business="b")
    assert store.stage_of(store.fold([applied]), store.Activity(), None, NOW) == "applied"
    assert (
        store.stage_of(store.fold([applied, _row("approved", 1)]), store.Activity(), None, NOW)
        == "approved"
    )
    active = store.Activity(first_app_at=NOW, last_app_at=NOW)
    assert (
        store.stage_of(store.fold([applied, _row("declined", 1)]), active, None, NOW) == "declined"
    )


def test_production_facts_stand_in_beside_live_sessions() -> None:
    facts = {
        "has_account": True,
        "app_sessions": 9,
        "first_app_at": "2026-10-23T05:00:00+00:00",
        "last_app_at": "2026-11-12T05:00:00+00:00",
        "app_version": "1.0.99",
        "bugs": 2,
    }
    merged = store.with_facts(store.Activity(), facts)
    assert merged.has_account and merged.app_sessions == 9 and merged.bugs == 2
    assert merged.app_version == "1.0.99"
    assert merged.last_app_at == datetime(2026, 11, 12, 5, tzinfo=UTC)
    live = store.Activity(
        has_account=True,
        app_sessions=1,
        first_app_at=datetime(2026, 11, 13, 1, tzinfo=UTC),
        last_app_at=datetime(2026, 11, 13, 1, tzinfo=UTC),
        app_version="1.0.101",
    )
    merged = store.with_facts(live, facts)
    assert merged.first_app_at == datetime(2026, 10, 23, 5, tzinfo=UTC)
    assert merged.last_app_at == datetime(2026, 11, 13, 1, tzinfo=UTC)
    assert merged.app_version == "1.0.101" and merged.app_sessions == 9
    assert store.with_facts(live, None) is live


def test_the_app_version_comes_from_the_user_agent() -> None:
    agent = "Mozilla/5.0 (Linux; Android 14) Chrome/130 Mobile SalesXrayApp/1.0.99"
    match = store.APP_AGENT.search(agent)
    assert match is not None and match.group(1) == "1.0.99"
    assert store.APP_AGENT.search("Mozilla/5.0 (Linux; Android 14) Chrome/130") is None


def test_emails_are_normalised_and_checked() -> None:
    assert store.normal_email("  Ravi.Tester@Example.TEST ") == "ravi.tester@example.test"
    for bad in ("", "ravi", "ravi@", "@example.test", "a b@example.test"):
        with pytest.raises(ValueError):
            store.normal_email(bad)


def test_the_export_never_runs_a_cell_as_a_formula() -> None:
    text = store.to_csv(
        [
            {
                "email": "ravi.tester@example.test",
                "name": "=HYPERLINK(1)",
                "stage": "active",
                "has_account": True,
                "app_sessions": 3,
                "business": "-dash",
            }
        ]
    )
    header, line = text.strip().split("\n")
    assert header.split(",")[:3] == ["email", "name", "stage"]
    assert "'=HYPERLINK(1)" in line and "'-dash" in line and ",yes," in line
