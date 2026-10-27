"""Seller chip choices through the API, on PostgreSQL (owner bug #49, 27 Oct 2026): the
values an organisation's leads carry, and how many of last month's leads a profile fits."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine

from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def _counts(body: dict[str, Any], field: str) -> dict[str, int]:
    return {chip["key"]: chip["leads"] for chip in body[field]}


def test_choices_come_from_the_teams_leads_and_a_profile_fits_some(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            here.as_admin()
            before = (await here.client.get(f"{BASE}/team/choices")).json()
            fit_before = (
                await here.client.post(
                    f"{BASE}/team/choices/fit",
                    json={"languages": ["Hindi"], "areas": ["Navi Mumbai"]},
                    headers=WRITE,
                )
            ).json()
            for number, (city, language, interest) in enumerate(
                [
                    ("Navi Mumbai", "Hindi", "Fictional Home Loan"),
                    ("navi-mumbai", "Hindi, English", "Fictional Home Loan"),
                    ("Fictional Town", "Marathi", "Fictional Car Loan"),
                ]
            ):
                added = await here.client.post(
                    f"{BASE}/leads",
                    json={
                        "command_id": str(uuid4()),
                        "name": f"Fictional Choice {number}",
                        "phone": f"98760 85{number:03d}",
                        "city": city,
                        "language": language,
                        "interest": interest,
                    },
                    headers=WRITE,
                )
                assert added.status_code == 201, added.text

            found = await here.client.get(f"{BASE}/team/choices")
            assert found.status_code == 200, found.text
            body = found.json()
            assert body["schema"] == "lead-desk/1" and body["days"] == 90
            assert body["leads"] == before["leads"] + 3
            areas, was = _counts(body, "areas"), _counts(before, "areas")
            # "Navi Mumbai" and "navi-mumbai" are one chip.
            assert areas["navi mumbai"] == was.get("navi mumbai", 0) + 2
            assert areas["fictional town"] == was.get("fictional town", 0) + 1
            spoken, said = _counts(body, "languages"), _counts(before, "languages")
            assert spoken["hi"] == said.get("hi", 0) + 2
            assert spoken["en"] == said.get("en", 0) + 1
            assert spoken["mr"] == said.get("mr", 0) + 1
            assert (
                next(chip for chip in body["languages"] if chip["key"] == "hi")["value"] == "Hindi"
            )
            assert _counts(body, "products")["fictional home loan"] == 2
            assert body["suggested_products"] == []

            fit = await here.client.post(
                f"{BASE}/team/choices/fit",
                json={"languages": ["Hindi"], "areas": ["Navi Mumbai"]},
                headers=WRITE,
            )
            assert fit.status_code == 200, fit.text
            assert fit.json()["days"] == 30
            assert fit.json()["leads"] == fit_before["leads"] + 3
            assert fit.json()["fits"] == fit_before["fits"] + 2

            assert (await here.client.get(f"{BASE}/team/choices?days=3")).status_code == 422
            assert (await here.client.get(f"{BASE}/team/choices?other=1")).status_code == 422

            # Sellers don't manage lead rules, so they don't read the team's choices.
            here.as_seller()
            refused = await here.client.get(f"{BASE}/team/choices")
            assert refused.status_code == 403
            assert (
                refused.json()["detail"] == "Only owners and admins manage the team's lead rules."
            )

    run(exercise())
