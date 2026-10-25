"""Whole phone numbers in lists and per-seller counts on PostgreSQL (owner, 25 Oct 2026:
"Always show full phone numbers", and All leads by seller): off by default, rows show the
last four digits; an owner or admin turns it on and every row carries the number; a seller
may not; the team's list counts leads per seller for its filters, the seller picked left
out. Made-up people only."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, update

from ac_platform.lead_desk.models import Lead
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_full_phones_and_counts_per_seller(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            await here.add("Fictional Held", "98760 75001")
            waiting = await here.add("Fictional Waiting", "98760 75002")
            async with here.setup.sessions() as db, db.begin():
                await db.execute(
                    update(Lead)
                    .where(Lead.id == UUID(waiting))
                    .values(owner_person_id=None, assigned_at=None)
                )
            seller = str(here.seller.person_id)
            here.as_admin()
            page = (await here.client.get(f"{BASE}/leads", params={"scope": "team"})).json()
            assert {row["phone_last4"] for row in page["leads"]} == {"5001", "5002"}
            assert all(row["phone"] is None for row in page["leads"])
            assert page["owner_counts"] == {seller: 1, "none": 1}

            team = (await here.client.get(f"{BASE}/team")).json()
            assert team["settings"]["show_full_phones"] is False
            body = {
                "expected_revision": team["settings"]["revision"],
                "auto_reassign": False,
                "reassign_minutes": 10,
                "show_full_phones": True,
            }
            here.as_seller()
            refused = await here.client.put(f"{BASE}/settings", json=body, headers=WRITE)
            assert refused.status_code == 403
            here.as_admin()
            saved = await here.client.put(f"{BASE}/settings", json=body, headers=WRITE)
            assert saved.status_code == 200, saved.text
            assert saved.json()["settings"]["show_full_phones"] is True

            page = (await here.client.get(f"{BASE}/leads", params={"scope": "team"})).json()
            assert {row["phone"] for row in page["leads"]} == {"+919876075001", "+919876075002"}
            # One seller picked: their leads, and the chips' counts as before.
            theirs = (
                await here.client.get(f"{BASE}/leads", params={"scope": "team", "owner": seller})
            ).json()
            assert [row["phone"] for row in theirs["leads"]] == ["+919876075001"]
            assert theirs["owner_counts"] == {seller: 1, "none": 1}

            # A seller's own list shows the numbers too, and no counts of others.
            here.as_seller()
            mine = (await here.client.get(f"{BASE}/leads", params={"scope": "mine"})).json()
            assert [row["phone"] for row in mine["leads"]] == ["+919876075001"]
            assert mine["owner_counts"] == {}

            # Saving the other settings without it keeps it on.
            here.as_admin()
            kept = await here.client.put(
                f"{BASE}/settings",
                json={
                    "expected_revision": saved.json()["settings"]["revision"],
                    "auto_reassign": False,
                    "reassign_minutes": 15,
                },
                headers=WRITE,
            )
            assert kept.status_code == 200, kept.text
            assert kept.json()["settings"]["show_full_phones"] is True

    run(exercise())
