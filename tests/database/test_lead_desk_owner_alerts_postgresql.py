"""Owner alerts and the day's summary on PostgreSQL (competitor teardown 19 and 20, 1 Nov
2026): the first pass sends nothing old; a missed incoming call nobody returned within 30
minutes reaches the admin's phone once, ids only, and its words name it on the admin's own
session; its list shows it until someone calls back; a quiet Interested lead is on its list;
the switches and the admin's own summary days save; the summary goes at 7 PM once a day, and
a test goes now, at most once a minute. Sellers never see any of it. Anyone sets their own
notifications (teardown 26): the admin's team alerts off means no owner alert reaches them,
and a test's words answer their plain alert read. Made-up people only."""

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
from ac_platform.lead_desk import owner_alerts, push
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


def test_each_person_sets_their_own_notifications(postgres_harness: Any, tmp_path: Path) -> None:
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
            saved = await here.client.put(
                f"{BASE}/owner-alerts", json={**SWITCHES, "summary_days": []}, headers=WRITE
            )
            assert saved.status_code == 200, saved.text

            # A seller sets their own: every type on and on time by default.
            here.as_seller()
            mine = await here.client.get(f"{BASE}/notifications")
            assert mine.status_code == 200, mine.text
            assert mine.json()["manager"] is False
            assert mine.json()["due_lead_minutes"] == 0 and mine.json()["quiet"] is False
            changed = await here.client.put(
                f"{BASE}/notifications",
                json={
                    "new_enquiry": True,
                    "follow_up_due": True,
                    "missed_follow_up": False,
                    "team_alerts": True,
                    "due_lead_minutes": 15,
                    "quiet": False,
                },
                headers=WRITE,
            )
            assert changed.status_code == 200, changed.text
            assert changed.json()["missed_follow_up"] is False
            assert changed.json()["due_lead_minutes"] == 15
            refused = await here.client.put(
                f"{BASE}/notifications",
                json={
                    "new_enquiry": True,
                    "follow_up_due": True,
                    "missed_follow_up": True,
                    "team_alerts": True,
                    "due_lead_minutes": 7,
                    "quiet": True,
                },
                headers=WRITE,
            )
            assert refused.status_code == 422, refused.text

            # The admin turns team alerts off: a missed call alerts nobody's phone.
            here.as_admin()
            off = await here.client.put(
                f"{BASE}/notifications",
                json={
                    "new_enquiry": True,
                    "follow_up_due": True,
                    "missed_follow_up": True,
                    "team_alerts": False,
                    "due_lead_minutes": 0,
                    "quiet": False,
                },
                headers=WRITE,
            )
            assert off.status_code == 200 and off.json()["manager"] is True, off.text
            caller = await here.add("Fictional Missed", "98760 83011")
            now = datetime.now(UTC)
            await call(here, caller, now - timedelta(minutes=40), direction="missed")
            assert await pushed(here, now - timedelta(minutes=30)) == []
            assert await pushed(here, now) == []

            # A test reaches the admin's own phone, and its words answer the plain read.
            here.as_admin()
            test = await here.client.post(f"{BASE}/notifications/test", headers=WRITE)
            assert test.status_code == 200, test.text
            assert test.json()["phones"] == 1
            words = (await here.client.get(f"{BASE}/alert")).json()
            assert words["title"] == "Test notification" and words["url"] == "/leads"
            again = await here.client.post(f"{BASE}/notifications/test", headers=WRITE)
            assert again.status_code == 429, again.text

    run(exercise())


PREFS = {
    "new_enquiry": True,
    "follow_up_due": True,
    "missed_follow_up": True,
    "team_alerts": True,
    "due_lead_minutes": 0,
    "quiet": False,
}


async def lead_pushes(here: World, now: datetime) -> list[tuple[str, str]]:
    """The seller's lead alerts in one pass: (kind, lead) pairs."""
    async with here.setup.sessions() as db, db.begin():
        alerts = await push.collect(db, now)
    return [
        (kind, str(lead))
        for alert in alerts
        if alert.tenant_id == here.tenant_id and alert.person_id == here.seller.person_id
        for kind, lead in alert.leads
    ]


def test_lead_alerts_follow_each_persons_choices(postgres_harness: Any, tmp_path: Path) -> None:
    """The Leads session's conditions (1 Nov 2026): a person with New enquiry off hears no new
    lead; one who hears follow-ups 15 minutes early hears it then, once; by default a follow-up
    still comes at the time."""

    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            settings = here.setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
            install_owner_alerts_http(
                here.setup.app,
                RouteContext(settings, here.setup.require_actor, here.setup.sessions),
            )
            here.as_seller()
            token = "fictional-phone-" + uuid4().hex
            registered = await here.client.post(
                f"{BASE}/devices", json={"token": token}, headers=WRITE
            )
            assert registered.status_code == 200, registered.text
            off = await here.client.put(
                f"{BASE}/notifications", json={**PREFS, "new_enquiry": False}, headers=WRITE
            )
            assert off.status_code == 200, off.text
            quiet = await here.add("Fictional Unheard", "98760 83021")
            now = datetime.now(UTC)
            assert ("new", quiet) not in await lead_pushes(here, now)

            here.as_seller()
            early = await here.client.put(
                f"{BASE}/notifications", json={**PREFS, "due_lead_minutes": 15}, headers=WRITE
            )
            assert early.status_code == 200, early.text
            soon = now + timedelta(minutes=10)
            async with here.setup.sessions() as db, db.begin():
                await db.execute(
                    update(Lead).where(Lead.id == UUID(quiet)).values(next_action_at=soon)
                )
            assert ("due", quiet) in await lead_pushes(here, now)
            assert (await here.stored(quiet)).alerted_due_at == soon
            assert ("due", quiet) not in await lead_pushes(here, now + timedelta(minutes=1))

            # At the time, as before, for someone who never chose.
            here.as_seller()
            back = await here.client.put(f"{BASE}/notifications", json=PREFS, headers=WRITE)
            assert back.status_code == 200, back.text
            later = await here.add("Fictional On Time", "98760 83022")
            async with here.setup.sessions() as db, db.begin():
                await db.execute(
                    update(Lead).where(Lead.id == UUID(later)).values(next_action_at=soon)
                )
            assert ("due", later) not in await lead_pushes(here, now + timedelta(minutes=2))
            assert ("due", later) in await lead_pushes(here, soon + timedelta(seconds=5))

    run(exercise())


def test_an_enquiry_never_called_stays_listed_until_it_is(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """Phone personas ph1-57 (1 Nov 2026): an Inbound enquiry nobody had called for three days
    fell out of the first-response clock's two-day look-back, and "Enquiries not called in 15
    min" said Nothing here. However old, it is listed until someone calls; a Cold lead never."""

    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            # An organisation workspace, as the first test's (Leads work only there).
            settings = here.setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
            install_owner_alerts_http(
                here.setup.app,
                RouteContext(settings, here.setup.require_actor, here.setup.sessions),
            )
            waiting = await here.add("Fictional Waiting", "98760 83011")
            cold = await here.add("Fictional Cold", "98760 83012")
            here.as_admin()
            now = datetime.now(UTC)
            old = now - timedelta(days=3)
            async with here.setup.sessions() as db, db.begin():
                for lead in (waiting, cold):
                    await db.execute(
                        update(Lead).where(Lead.id == UUID(lead)).values(created_at=old)
                    )
                    await db.execute(
                        update(LeadEvent)
                        .where(LeadEvent.lead_id == UUID(lead))
                        .values(created_at=old)
                    )
                await db.execute(update(Lead).where(Lead.id == UUID(cold)).values(pipeline="cold"))

            async def listed() -> list[str]:
                answer = await here.client.get(
                    f"{BASE}/owner-alerts/list", params={"kind": "first_call"}
                )
                assert answer.status_code == 200, answer.text
                return [item["lead_id"] for item in answer.json()["items"]]

            assert await listed() == [waiting]
            # Someone calls: off the list.
            await call(here, waiting, now - timedelta(minutes=1), direction="outgoing")
            async with here.setup.sessions() as db, db.begin():
                await db.execute(
                    update(Lead)
                    .where(Lead.id == UUID(waiting))
                    .values(first_contact_at=now - timedelta(minutes=1))
                )
            assert await listed() == []

    run(exercise())
