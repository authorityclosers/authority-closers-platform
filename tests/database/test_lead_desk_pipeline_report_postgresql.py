"""The pipeline's numbers through the HTTP API on PostgreSQL (Lead OS, spec section 9):
each lead counted once, Junk out of every conversion, Lost reasons in the business's
words, a seller sees only their own leads' numbers."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine

from ac_platform.lead_desk.journey import engine
from ac_platform.lead_desk.journey import model as journeys
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN
from tests.database.test_lead_os_acceptance_postgresql import (
    BASE,
    ROOT,
    WRITE,
    later,
    world,
)


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_each_lead_counts_once_and_junk_stays_out_of_conversions(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            ids = [await here.add(f"Fictional Report {n}", f"98760 1000{n}") for n in range(6)]
            # Two talk and become interested; one of those books a meeting.
            for lead_id in ids[:2]:
                talked = await here.dispose(
                    lead_id, connected=True, step="interested", follow_up_at=later(days=1)
                )
                assert talked.status_code == 200, talked.text
            booked = await here.move(
                ids[0],
                "meeting_scheduled",
                meeting={"startsAt": later(days=2), "mode": "zoom"},
            )
            assert booked.status_code == 200, booked.text
            # Interested, then found to be junk: out of every conversion.
            assert (await here.move(ids[2], "interested", nextActionAt=later(days=1))).is_success
            assert (await here.move(ids[2], "junk", reason="fake")).is_success
            assert (await here.move(ids[3], "lost", reason="price")).is_success
            assert (await here.move(ids[4], "not_connected", ncReason="did_not_pick")).is_success

            here.as_admin()
            report = await here.client.get(f"{BASE}/reports/pipeline?days=30")
            assert report.status_code == 200, report.text
            body = report.json()
            assert body["total"] == 6 and not body["mine"]
            assert sum(stage["count"] for stage in body["stages"]) == 6
            assert body["groups"] == {"active": 4, "won": 0, "lost": 1, "junk": 1}
            # New → a first conversation: the five genuine leads, two of them talked.
            first = body["first_connect"]
            assert (first["entered"], first["passed"]) == (5, 2)
            steps = {item["key"]: item for item in body["conversions"]}
            assert (
                steps["interested_to_meeting"]["entered"],
                steps["interested_to_meeting"]["passed"],
            ) == (2, 1)
            assert body["lost_now"] == [{"label": "Price or budget", "count": 1}]
            assert (body["junk_now"], body["junk_moves"]) == (1, 1)
            assert not any("₹" in str(value) for value in body.values())

            # A seller sees their own leads' numbers only.
            here.as_seller()
            mine = (await here.client.get(f"{BASE}/reports/pipeline?days=30")).json()
            assert mine["mine"] is True and mine["total"] == 6
            assert (await here.client.get(f"{BASE}/reports/pipeline?days=12")).status_code == 422

    run(exercise())


def test_a_template_preview_shows_where_todays_leads_land(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            ids = [await here.add(f"Fictional Preview {n}", f"98760 2000{n}") for n in range(3)]
            assert (
                await here.move(ids[0], "discussion_incomplete", nextActionAt=later(hours=4))
            ).is_success
            assert (await here.move(ids[1], "junk", reason="spam_test")).is_success
            here.as_admin()
            journey = (await here.client.get(f"{BASE}/journey")).json()
            # The nine stages carry their moves and reasons.
            by_key = {stage["key"]: stage for stage in journey["stages"]}
            assert by_key["new"]["moves"][-1] == "junk"
            assert by_key["lost"]["reasons"][0]["key"] == "not_interested"
            assert by_key["interested"]["rotHours"] == 72
            preview = await here.client.post(
                f"{BASE}/journey/template/preview",
                json={"expectedVersion": journey["version"], "template": "simple"},
                headers={"Origin": ORIGIN, "Content-Type": "application/json"},
            )
            assert preview.status_code == 200, preview.text
            landings = {
                item["fromLabel"]: (item["toKey"], item["leads"])
                for item in preview.json()["landings"]
            }
            assert landings == {
                "New Lead": ("new", 1),
                "Discussion Incomplete": ("follow_up", 1),
                "Junk Lead": ("junk", 1),
            }
            # Nothing was saved.
            again = (await here.client.get(f"{BASE}/journey")).json()
            assert again["version"] == journey["version"]

    run(exercise())


def test_the_template_map_puts_each_old_stage_where_the_manager_picked(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """Moving a business onto the nine stages: the manager picks, per old stage, where its
    leads go. Each lead moves once, on the same record, with one history line; ad
    platforms and the numbers never count the rename as progress."""

    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            ids = [await here.add(f"Fictional Map {n}", f"98760 3000{n}") for n in range(5)]
            here.as_admin()
            journey = (await here.client.get(f"{BASE}/journey")).json()
            simple = await here.client.post(
                f"{BASE}/journey/template",
                json={"expectedVersion": journey["version"], "template": "simple"},
                headers=WRITE,
            )
            assert simple.status_code == 200, simple.text
            for lead_id, step, extra in (
                (ids[0], "follow_up", {}),
                (ids[1], "follow_up", {}),
                (ids[2], "interested", {}),
                (ids[3], "lost", {"reason": "price"}),
            ):
                moved = await here.move(lead_id, step, **extra)
                assert moved.status_code == 200, moved.text
            before = (await here.client.get(f"{BASE}/journey")).json()
            nine = {"expectedVersion": before["version"], "template": "inside_sales_demos"}

            # Preview: per old stage, how many leads and where they would go.
            preview = await here.client.post(
                f"{BASE}/journey/template/preview",
                json={**nine, "map": {"follow_up": "interested"}},
                headers=WRITE,
            )
            assert preview.status_code == 200, preview.text
            landings = {item["fromKey"]: item for item in preview.json()["landings"]}
            assert {key: (item["toKey"], item["leads"]) for key, item in landings.items()} == {
                "new": ("new", 1),
                "follow_up": ("interested", 2),
                "interested": ("interested", 1),
                "lost": ("lost", 1),
            }
            assert landings["follow_up"]["fromLabel"] == "Follow-up"
            assert "meeting_scheduled" in landings["follow_up"]["choices"]
            assert landings["lost"]["choices"] == ["lost"]
            plain = await here.client.post(
                f"{BASE}/journey/template/preview", json=nine, headers=WRITE
            )
            by_default = {item["fromKey"]: item["toKey"] for item in plain.json()["landings"]}
            assert by_default["follow_up"] == "discussion_incomplete"

            # A closed stage keeps its kind; an unknown stage is refused; nothing saved.
            for wrong in ({"lost": "interested"}, {"follow_up": "won"}, {"nowhere": "new"}):
                refused = await here.client.post(
                    f"{BASE}/journey/template", json={**nine, "map": wrong}, headers=WRITE
                )
                assert refused.status_code == 422, refused.text
            assert (await here.client.get(f"{BASE}/journey")).json()["version"] == before["version"]

            kept = len(await here.events(ids[2]))
            used = await here.client.post(
                f"{BASE}/journey/template",
                json={**nine, "map": {"follow_up": "interested"}},
                headers=WRITE,
            )
            assert used.status_code == 200, used.text
            for lead_id in ids[:2]:
                lead = await here.stored(lead_id)
                assert (lead.stage, lead.step) == ("interested", "interested")
                events = await here.events(lead_id)
                assert [event.kind for event in events].count("stage") == 2
                last = events[-1].data
                assert (last["source"], last["from_label"], last["to_label"]) == (
                    "template",
                    "Follow-up",
                    "Interested (In Follow-Up)",
                )
                async with here.setup.sessions() as db:
                    now = await journeys.read(db, here.tenant_id, journeys.MAIN_PIPELINE)
                assert engine.reached(now, events[-1].kind, events[-1].data) is None
            # Already in the picked stage, or not picked: untouched.
            assert len(await here.events(ids[2])) == kept
            new_lead = await here.stored(ids[4])
            assert (new_lead.stage, await here.leads()) == ("new", 5)
            lost = await here.stored(ids[3])
            assert (lost.stage, lost.outcome_reason) == ("lost", "price")

            # The numbers: only the lead that really became interested entered that step.
            report = (await here.client.get(f"{BASE}/reports/pipeline?days=30")).json()
            steps = {item["key"]: item for item in report["conversions"]}
            assert steps["interested_to_meeting"]["entered"] == 1
            assert sum(stage["count"] for stage in report["stages"]) == 5

    run(exercise())
