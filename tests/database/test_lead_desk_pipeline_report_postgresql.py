"""The pipeline's numbers through the HTTP API on PostgreSQL (Lead OS, spec section 9):
each lead counted once, Junk out of every conversion, Lost reasons in the business's
words, a seller sees only their own leads' numbers."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine

from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, later, world


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
