"""The Leads stage pick over every pipeline, through the Sales Xray CRM's HTTP API on
PostgreSQL (Dipak, 3 Nov 2026: in an organisation with several pipelines, "All stages" was
the only row). With no pipeline picked, the list counts and filters by the main pipeline's
stages, so the page lists those: every count is one of its stages, the counts add up to the
list, and picking a stage gives exactly the leads it counted, from every pipeline."""

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


def test_all_pipelines_count_and_filter_by_the_main_stages(
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

                enquiry = await add("Fictional Enquiry", "98765 33333", None)
                partner = await add("Fictional Partner", "98765 44444", "partner_outreach")

                journey = await client.get(f"{BASE}/journey")
                assert journey.status_code == 200, journey.text
                main_keys = {stage["key"] for stage in journey.json()["stages"]}
                new_key = next(
                    stage["key"] for stage in journey.json()["stages"] if stage["kind"] == "new"
                )

                every = await client.get(
                    f"{BASE}/leads", params={"scope": "mine", "side": "inbound", "view": "all"}
                )
                assert every.status_code == 200, every.text
                page = every.json()
                assert page["total"] == 2
                # Every count is one of the main pipeline's stages, and they add up to the list.
                assert set(page["step_counts"]) <= main_keys
                assert sum(page["step_counts"].values()) == page["total"]
                assert page["step_counts"][new_key] == 2
                # Picking that stage gives exactly the leads it counted, both pipelines'.
                picked = await client.get(
                    f"{BASE}/leads",
                    params={"scope": "mine", "side": "inbound", "view": "all", "step": new_key},
                )
                assert picked.status_code == 200, picked.text
                assert {row["lead_id"] for row in picked.json()["leads"]} == {enquiry, partner}
        finally:
            await setup.engine.dispose()

    run(exercise())
