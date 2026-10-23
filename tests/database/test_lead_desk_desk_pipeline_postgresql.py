"""Start calling one pipeline at a time (orchestrator, 23 Oct 2026: cold partner outreach
apart from enquiries), through the Sales Xray CRM's HTTP API on PostgreSQL.

``GET /v1/lead-desk?pipeline=`` gives that pipeline's day (queue, counts, upcoming) and
``GET /v1/lead-desk/next?pipeline=`` its next lead to call; without it, every pipeline as
before. An unknown pipeline or any other key is refused.
"""

from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest

from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_journey_postgresql import _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
BASE = "/v1/lead-desk"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_the_desk_and_start_calling_take_one_pipeline(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                made = await client.post(
                    f"{BASE}/pipelines",
                    json={
                        "name": "Partner outreach",
                        "template": "b2b_services",
                        "sources": ["csv"],
                    },
                    headers=WRITE,
                )
                assert made.status_code == 200, made.text

                async def add(name: str, phone: str, pipeline: str | None) -> str:
                    added = await client.post(
                        f"{BASE}/leads",
                        json={
                            "command_id": str(uuid4()),
                            "name": name,
                            "phone": phone,
                            "assign": "me",
                            **({"pipeline": pipeline} if pipeline else {}),
                        },
                        headers=WRITE,
                    )
                    assert added.status_code == 201, added.text
                    return str(added.json()["lead"]["lead_id"])

                enquiry = await add("Fictional Enquiry", "98765 22222", None)
                partner = await add("Fictional Partner", "98765 11111", "partner_outreach")

                every = (await client.get(BASE)).json()
                assert {row["lead_id"] for row in every["queue"]} == {enquiry, partner}
                assert every["counts"]["new"] == 2

                outreach = (await client.get(f"{BASE}?pipeline=partner_outreach")).json()
                assert [row["lead_id"] for row in outreach["queue"]] == [partner]
                assert outreach["counts"]["new"] == 1 and outreach["counts"]["open"] == 1
                main = (await client.get(f"{BASE}?pipeline=main")).json()
                assert [row["lead_id"] for row in main["queue"]] == [enquiry]

                first = (await client.get(f"{BASE}/next?pipeline=partner_outreach")).json()
                assert first["lead"]["lead_id"] == partner
                after = await client.get(f"{BASE}/next?pipeline=partner_outreach&skip={partner}")
                assert after.status_code == 200 and after.json() is None
                assert (await client.get(f"{BASE}/next?pipeline=main")).json()["lead"][
                    "lead_id"
                ] == enquiry

                assert (await client.get(f"{BASE}?pipeline=nope")).status_code == 422
                assert (await client.get(f"{BASE}/next?pipeline=nope")).status_code == 422
                assert (await client.get(f"{BASE}?bogus=1")).status_code == 422
        finally:
            await setup.engine.dispose()

    run(exercise())
