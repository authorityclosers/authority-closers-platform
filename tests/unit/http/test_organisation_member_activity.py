"""Fictional per-person activity for the people pages: scope, weeks, totals and the call cap."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from ac_platform.organisations import person_activity as person_module
from ac_platform.tenancy.models import Membership
from tests.unit.http.test_organisation import call, state  # noqa: F401
from tests.unit.http.test_organisation_activity import calls, seed_call  # noqa: F401
from tests.unit.http.test_workspaces import OTHER_TOKEN, TOKEN, workspace_state  # noqa: F401


async def test_owner_and_admin_read_a_members_weeks_totals_and_calls(calls):  # noqa: F811
    for token in (TOKEN, OTHER_TOKEN):
        response = await call(calls, path=f"/members/{calls.member}/activity", token=token)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "private, no-store"
        body = response.json()
        ids = calls.calls
        assert body["person_id"] == str(calls.member)
        # Twelve weeks reach the 40-day-old call; Personal and deleted calls stay out.
        assert [row["id"] for row in body["calls"]] == [
            str(ids[name]) for name in ("fresh", "reported", "old")
        ]
        assert {row["owner_person_id"] for row in body["calls"]} == {str(calls.member)}
        assert body["calls"][1]["label"] == "Fictional discovery call"
        assert body["calls"][1]["state"] == "report_ready"
        assert body["totals"] == dict(calls=3, recorded_minutes=4.5, reports_ready=1)
        weeks = body["weeks"]
        assert len(weeks) == 12
        assert [week["calls"] for week in weeks][-1] == 2
        assert weeks[-6]["calls"] == 1  # 40 days ago: the sixth week back
        assert sum(week["calls"] for week in weeks) == 3
        starts = [datetime.fromisoformat(week["start"]) for week in weeks]
        assert starts == sorted(starts)
        assert starts[1] - starts[0] == timedelta(days=7)


async def test_members_read_only_themselves(calls):  # noqa: F811
    with Session(calls.engine) as db, db.begin():
        db.get(Membership, (calls.tenant, calls.other)).role = "member"
    own = await call(calls, path=f"/members/{calls.other}/activity", token=OTHER_TOKEN)
    assert own.status_code == 200
    assert [row["id"] for row in own.json()["calls"]] == [str(calls.calls["held"])]
    other = await call(calls, path=f"/members/{calls.member}/activity", token=OTHER_TOKEN)
    assert other.status_code == 404


async def test_weeks_bounds_and_call_cap(calls, monkeypatch):  # noqa: F811
    path = f"/members/{calls.member}/activity"
    for weeks in ("0", "14", "many"):
        assert (await call(calls, path=f"{path}?weeks={weeks}")).status_code == 422
    short = (await call(calls, path=f"{path}?weeks=4")).json()
    assert len(short["weeks"]) == 4 and short["totals"]["calls"] == 2
    monkeypatch.setattr(person_module, "MAX_CALLS", 1)
    capped = (await call(calls, path=path)).json()
    assert [row["id"] for row in capped["calls"]] == [str(calls.calls["fresh"])]
    # Weeks and totals still count every call, not only the listed ones.
    assert capped["totals"]["calls"] == 3
    assert sum(week["calls"] for week in capped["weeks"]) == 3


async def test_someone_without_calls_reads_zeros(state):  # noqa: F811
    with Session(state.engine) as db, db.begin():
        seed_call(db, state.tenant, state.other, created_at=datetime.now(UTC) - timedelta(days=1))
    body = (await call(state, path=f"/members/{state.member}/activity")).json()
    assert body["calls"] == []
    assert body["totals"] == dict(calls=0, recorded_minutes=0.0, reports_ready=0)
    assert [week["calls"] for week in body["weeks"]] == [0] * 12
