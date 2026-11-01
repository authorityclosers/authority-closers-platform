"""Owner alerts and the day's summary on PostgreSQL (competitor teardown 19 and 20, 1 Nov
2026): the first pass sends nothing old; a missed incoming call nobody returned within 30
minutes reaches the admin's phone once, ids only, and its words name it on the admin's own
session; its list shows it until someone calls back; a quiet Interested lead is on its list;
the switches and the admin's own summary days save; the summary goes at 7 PM once a day, and
a test goes now, at most once a minute. Sellers never see any of it. Made-up people only."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Engine, update

from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk import owner_alerts
from ac_platform.lead_desk.models import Lead, LeadEvent
from ac_platform.lead_desk.owner_alerts_http import install_owner_alerts_http
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, World, world

IST = ZoneInfo("Asia/Kolkata")
SWITCHES = {"first_call": False, "missed_call": True, "no_follow_up": False, "seller_idle": False}


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


async def pushed(here: World, now: datetime) -> list[owner_alerts.OwnerAlert]:
    async with here.setup.sessions() as db, db.begin():
        alerts = await owner_alerts.collect(db, now)
    return [alert for alert in alerts if alert.tenant_id == here.tenant_id]


async def call(here: World, lead: str, at: datetime, **data: Any) -> None:
    async with here.setup.sessions() as db, db.begin():
        db.add(
            LeadEvent(
                id=uuid4(),
                tenant_id=here.tenant_id,
                lead_id=UUID(lead),
                kind="call",
                actor_person_id=here.seller.person_id,
                command_id=None,
                data={"via": "phone", **data},
                created_at=at,
            )
        )


def test_owner_alerts_list_words_and_summary(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            settings = here.setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
            install_owner_alerts_http(
                here.setup.app,
                RouteContext(settings, here.setup.require_actor, here.setup.sessions),
            )
            here.as_admin()
            token = "fictional-phone-" + uuid4().hex
            registered = await here.client.post(
                f"{BASE}/devices", json={"token": token}, headers=WRITE
            )
            assert registered.status_code == 200, registered.text

            # Three on by default, idle sellers offered and off.
            shown = await here.client.get(f"{BASE}/owner-alerts")
            assert shown.status_code == 200, shown.text
            assert {kind: shown.json()[kind] for kind in SWITCHES} == {
                "first_call": True,
                "missed_call": True,
                "no_follow_up": True,
                "seller_idle": False,
            }
            assert shown.json()["summary_days"] == [] and shown.json()["phones"] == 1
            saved = await here.client.put(
                f"{BASE}/owner-alerts", json={**SWITCHES, "summary_days": []}, headers=WRITE
            )
            assert saved.status_code == 200, saved.text

            caller = await here.add("Fictional Caller", "98760 83001")
            quiet = await here.add("Fictional Quiet", "98760 83002")
            here.as_admin()
            now = datetime.now(UTC)
            await call(here, caller, now - timedelta(minutes=40), direction="missed")

            # The first pass looks and sends nothing old.
            assert await pushed(here, now - timedelta(minutes=30)) == []
            alerts = await pushed(here, now)
            assert [(a.reason, a.count, a.lead_id, a.tokens) for a in alerts] == [
                ("missed_call", 1, UUID(caller), [token])
            ]
            assert set(alerts[0].data()) == {
                "type",
                "kind",
                "reason",
                "tenant",
                "alerts",
                "count",
                "lead",
            }
            assert await pushed(here, now + timedelta(minutes=2)) == []  # once

            said = await here.client.get(f"{BASE}/leads/{caller}/alert")
            assert said.status_code == 200, said.text
            assert said.json()["title"] == "Missed call not returned: Fictional Caller"
            assert said.json()["url"] == "/leads/alerts?kind=missed_call"

            listed = await here.client.get(
                f"{BASE}/owner-alerts/list", params={"kind": "missed_call"}
            )
            assert listed.status_code == 200, listed.text
            assert [item["lead_id"] for item in listed.json()["items"]] == [caller]
            assert listed.json()["title"] == "Missed calls not returned in 30 min"
            # A call back takes it off the list.
            await call(
                here, caller, now - timedelta(minutes=1), direction="outgoing", duration_seconds=95
            )
            listed = await here.client.get(
                f"{BASE}/owner-alerts/list", params={"kind": "missed_call"}
            )
            assert listed.json()["items"] == []

            # An Interested lead nobody has spoken to for over a week.
            async with here.setup.sessions() as db, db.begin():
                await db.execute(
                    update(Lead)
                    .where(Lead.id == UUID(quiet))
                    .values(
                        stage="interested",
                        last_contact_at=now - timedelta(days=8),
                        stage_at=now - timedelta(days=9),
                        created_at=now - timedelta(days=10),
                        next_action_at=None,
                    )
                )
            stale = await here.client.get(
                f"{BASE}/owner-alerts/list", params={"kind": "no_follow_up"}
            )
            assert [item["lead_id"] for item in stale.json()["items"]] == [quiet]

            # The summary: the admin's own days; at 7 PM once a day; a test now.
            days = await here.client.put(
                f"{BASE}/owner-alerts",
                json={**SWITCHES, "summary_days": [0, 1, 2, 3, 4, 5, 6]},
                headers=WRITE,
            )
            assert days.json()["summary_days"] == [0, 1, 2, 3, 4, 5, 6]
            evening = datetime.combine(
                now.astimezone(IST).date() + timedelta(days=1), time(19, 30), tzinfo=IST
            )
            summary = await pushed(here, evening)
            assert [(a.reason, a.lead_id) for a in summary] == [("summary", None)]
            assert await pushed(here, evening + timedelta(minutes=10)) == []  # once a day
            page = await here.client.get(f"{BASE}/owner-alerts/summary")
            assert page.status_code == 200, page.text
            assert set(page.json()["totals"]) == {"sellers", "tried", "connected", "wins"}
            test = await here.client.post(f"{BASE}/owner-alerts/summary/test", headers=WRITE)
            assert test.status_code == 200, test.text
            assert test.json()["phones"] == 1
            words = (await here.client.get(f"{BASE}/alert")).json()
            assert words["title"].startswith("Test · Today: ")
            assert words["url"] == "/leads/summary"
            again = await here.client.post(f"{BASE}/owner-alerts/summary/test", headers=WRITE)
            assert again.status_code == 429, again.text

            # Sellers see none of it.
            here.as_seller()
            assert (await here.client.get(f"{BASE}/owner-alerts")).status_code == 403
            assert (
                await here.client.get(f"{BASE}/owner-alerts/list", params={"kind": "missed_call"})
            ).status_code == 403

    run(exercise())
