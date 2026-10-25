"""The duplicate review queue on PostgreSQL (docs/product/lead-desk/duplicates.md, D4):
- owners and admins see the pairs, the likeliest first, with counts by band; a seller sees
  neither the queue nor the Leads "Duplicates" filter;
- another organisation's pair is never here, whatever its id;
- the compare names the reasons, the lead kept and who has it; the lead's page names its
  possible duplicate to the admin only;
- "Not the same" takes the pair out for good (a retry is one decision, a scan keeps it out);
- after a merge, the merged lead's page points to the kept lead, and the seller who worked on
  it lately reads the kept lead without editing it ("worked before"); nobody else does;
- Admin's counts per organisation.
Made-up people only."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine, func, select

from ac_platform.lead_desk import duplicate_queue, duplicate_scan
from ac_platform.lead_desk.models import LeadDuplicateDecision, LeadDuplicatePair, LeadEvent
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_account_library_postgresql import _session
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_lead_desk_duplicate_scan_postgresql import NOW, lead
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_the_queue_compare_not_same_filter_banner_and_admin_counts(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            mine = here.tenant_id
            other = (await seed(here.setup.engine)).tenant_id
            seller = here.seller.person_id
            kavya_login = await seed(here.setup.engine, tenant_id=mine, role="member")
            kavya = kavya_login.person_id
            ids = {key: uuid4() for key in ("asha", "asha2", "neha", "neha2")}
            async with here.setup.sessions() as db, db.begin():
                db.add_all(
                    [
                        lead(
                            mine,
                            "Asha Example",
                            "+919876078001",
                            "asha@gamil.com",
                            id=ids["asha"],
                            owner_person_id=seller,
                            assigned_at=NOW,
                        ),
                        lead(
                            mine,
                            "Asha Example",
                            "+19876078001",
                            "asha@gmail.com",
                            id=ids["asha2"],
                            owner_person_id=kavya,
                            assigned_at=NOW,
                        ),
                        lead(
                            mine,
                            "Neha Demo",
                            "+919876078003",
                            id=ids["neha"],
                            payload={"Alternate Contact No": "98760 78004"},
                        ),
                        lead(mine, "Neha D", "+919876078004", id=ids["neha2"]),
                        # The same two people in another organisation: its own pair only.
                        lead(other, "Asha Example", "+919876078001", "asha@gamil.com"),
                        lead(other, "Asha Example", "+19876078001", "asha@gmail.com"),
                    ]
                )
            async with here.setup.sessions() as db, db.begin():
                await duplicate_scan.scan(db, other, NOW)
            async with here.setup.sessions() as db:
                theirs = await db.scalar(
                    select(LeadDuplicatePair.id).where(LeadDuplicatePair.tenant_id == other)
                )
            assert theirs is not None

            here.as_seller()
            assert (await here.client.get(f"{BASE}/duplicates")).status_code == 403
            filtered = await here.client.get(
                f"{BASE}/leads", params={"scope": "mine", "duplicates": "review"}
            )
            assert filtered.status_code == 403

            here.as_admin()
            scanned = await here.client.post(f"{BASE}/duplicates/scan", headers=WRITE)
            assert scanned.status_code == 200, scanned.text
            queue = scanned.json()
            assert queue["total"] == 2
            assert queue["counts"] == {"certain": 1, "probable": 1}
            assert [pair["band"] for pair in queue["pairs"]] == ["certain", "probable"]
            shown = {
                side["lead_id"]
                for pair in queue["pairs"]
                for side in (pair["first"], pair["second"])
            }
            assert shown == {str(lead_id) for lead_id in ids.values()}
            assert all(
                side["phone"] is None
                for pair in queue["pairs"]
                for side in (pair["first"], pair["second"])
            )
            # Another organisation's pair is not here, whatever its id.
            assert (await here.client.get(f"{BASE}/duplicates/{theirs}")).status_code == 404
            crossed = await here.client.post(
                f"{BASE}/duplicates/{theirs}/not-same",
                json={"command_id": str(uuid4())},
                headers=WRITE,
            )
            assert crossed.status_code == 404

            listed = await here.client.get(
                f"{BASE}/leads", params={"scope": "team", "duplicates": "review"}
            )
            assert listed.status_code == 200, listed.text
            assert listed.json()["total"] == 4

            asha_pair = queue["pairs"][1]
            compared = await here.client.get(f"{BASE}/duplicates/{asha_pair['pair_id']}")
            assert compared.status_code == 200, compared.text
            body = compared.json()
            assert "same email apart from a typo" in body["pair"]["reasons"]
            assert body["keep_lead_id"] in {str(ids["asha"]), str(ids["asha2"])}
            assert body["owner_why"] == "first" and body["choose_owner"] is False
            assert body["pair"]["first"]["activity"] == 0
            detail = await here.detail(str(ids["asha"]))
            assert [hint["other_lead_id"] for hint in detail["duplicates"]] == [str(ids["asha2"])]
            assert detail["merged_into"] is None
            here.as_seller()
            assert (await here.detail(str(ids["asha"])))["duplicates"] == []

            # Not the same: out for good; a retry is one decision; a scan keeps it out.
            here.as_admin()
            command = {"command_id": str(uuid4()), "note": "Two different people"}
            for _ in range(2):
                refused = await here.client.post(
                    f"{BASE}/duplicates/{queue['pairs'][0]['pair_id']}/not-same",
                    json=command,
                    headers=WRITE,
                )
                assert refused.status_code == 200, refused.text
                assert refused.json()["total"] == 1
            again = await here.client.post(f"{BASE}/duplicates/scan", headers=WRITE)
            assert again.json()["counts"] == {"probable": 1}
            async with here.setup.sessions() as db:
                decisions = await db.scalar(
                    select(func.count())
                    .select_from(LeadDuplicateDecision)
                    .where(LeadDuplicateDecision.tenant_id == mine)
                )
            assert decisions == 1

            # Both sellers worked on Asha lately: the most recent keeps her, the other reads.
            now = datetime.now(UTC)
            async with here.setup.sessions() as db, db.begin():
                for lead_id, actor, at in (
                    (ids["asha"], seller, now - timedelta(minutes=5)),
                    (ids["asha2"], kavya, now - timedelta(hours=1)),
                ):
                    db.add(
                        LeadEvent(
                            id=uuid4(),
                            tenant_id=mine,
                            lead_id=lead_id,
                            kind="note",
                            actor_person_id=actor,
                            data={"text": "Fictional note"},
                            created_at=at,
                        )
                    )
            compared = await here.client.get(f"{BASE}/duplicates/{asha_pair['pair_id']}")
            body = compared.json()
            assert body["owner_why"] == "asked" and body["choose_owner"] is True
            assert body["owner_person_id"] == str(seller)
            assert [item["person_id"] for item in body["owner_choices"]] == [
                str(seller),
                str(kavya),
            ]
            merged = await here.client.post(
                f"{BASE}/duplicates/merge",
                json={
                    "command_id": str(uuid4()),
                    "lead_ids": [str(ids["asha"]), str(ids["asha2"])],
                },
                headers=WRITE,
            )
            assert merged.status_code == 200, merged.text
            kept, gone = merged.json()["kept_lead_id"], merged.json()["merged_lead_id"]
            banner = (await here.detail(gone))["merged_into"]
            assert banner["lead_id"] == kept and banner["can_open"] is True

            here.client.cookies.set(
                here.setup.settings.session_cookie_name,
                await _session(here.setup, kavya_login),
            )
            read = await here.client.get(f"{BASE}/leads/{kept}")
            assert read.status_code == 200, read.text
            assert read.json()["worked_before"] is True and read.json()["can_edit"] is False
            wrote = await here.client.post(
                f"{BASE}/leads/{kept}/notes",
                json={"command_id": str(uuid4()), "note": "Fictional note"},
                headers=WRITE,
            )
            assert wrote.status_code == 404
            stranger = await seed(here.setup.engine, tenant_id=mine, role="member")
            here.client.cookies.set(
                here.setup.settings.session_cookie_name, await _session(here.setup, stranger)
            )
            assert (await here.client.get(f"{BASE}/leads/{kept}")).status_code == 404

            async with here.setup.sessions() as db:
                counts = await duplicate_queue.admin_overview(db)
            rows = {row["tenant_id"]: row for row in counts["organisations"]}
            assert rows[str(mine)]["merged"] == 1 and rows[str(mine)]["not_same"] == 1
            assert rows[str(mine)]["probable"] == 0 and rows[str(mine)]["certain"] == 0
            assert rows[str(other)]["probable"] == 1 and rows[str(other)]["merged"] == 0
            assert counts["totals"]["merged"] >= 1

    run(exercise())
