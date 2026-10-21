"""Several pipelines per organisation through the Sales Xray CRM's HTTP API on PostgreSQL
(owner, 22 Oct 2026: partner outreach and enquiries side by side).

An organisation starts with one pipeline, "main". A manager makes a second with a kind of
business's stages and picks file imports for it; an imported lead lands there and sees its
stages, a lead added by hand stays in main; lists, counts and stage choices follow each
lead's pipeline; a manager moves a lead back; a source feeds one pipeline at a time.
"""

from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest

from tests.database.test_conversation_account_library_postgresql import _session
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_journey_postgresql import _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
BASE = "/v1/lead-desk"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_pipelines_each_with_their_own_stages_and_sources(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            seller = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            seller_token = await _session(setup, seller)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:

                def as_(token: str) -> None:
                    client.cookies.set(setup.settings.session_cookie_name, token)

                as_(setup.token)
                first = (await client.get(f"{BASE}/pipelines")).json()
                assert [(p["key"], p["name"], p["main"]) for p in first["pipelines"]] == [
                    ("main", "Leads", True)
                ]
                assert "csv" in first["sources"] and first["canEdit"] is True

                as_(seller_token)
                refused = await client.post(
                    f"{BASE}/pipelines",
                    json={"name": "Partners", "template": "b2b_services", "sources": ["csv"]},
                    headers=WRITE,
                )
                assert refused.status_code == 403

                as_(setup.token)
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
                listed = made.json()["pipelines"]
                assert [(p["key"], p["sources"], p["industry"]) for p in listed] == [
                    ("main", [], None),
                    ("partner_outreach", ["csv"], "b2b_services"),
                ]
                partner = (await client.get(f"{BASE}/journey?pipeline=partner_outreach")).json()
                assert partner["pipeline"] == "partner_outreach" and partner["version"] == 1
                assert [s["label"] for s in partner["stages"]][:3] == [
                    "New lead",
                    "Couldn't reach",
                    "Discovery call",
                ]
                main = (await client.get(f"{BASE}/journey")).json()
                assert main["pipeline"] == "main" and main["version"] == 0
                assert (await client.get(f"{BASE}/journey?pipeline=nope")).status_code == 422

                imported = await client.post(
                    f"{BASE}/imports",
                    json={
                        "command_id": str(uuid4()),
                        "file_name": "partners.csv",
                        "mapping": {"name": "Name", "phone": "Phone"},
                        "rows": [{"Name": "fictional partner", "Phone": "98765 11111"}],
                    },
                    headers=WRITE,
                )
                assert imported.status_code == 200, imported.text
                added = await client.post(
                    f"{BASE}/leads",
                    json={
                        "command_id": str(uuid4()),
                        "name": "Fictional Enquiry",
                        "phone": "98765 22222",
                    },
                    headers=WRITE,
                )
                assert added.status_code == 201, added.text
                assert added.json()["lead"]["pipeline"] == "main"
                assert added.json()["lead"]["stage_label"] == "New"

                page = (
                    await client.get(f"{BASE}/leads?scope=team&pipeline=partner_outreach")
                ).json()
                assert page["total"] == 1 and page["stage_counts"] == {"new": 1}
                lead = page["leads"][0]
                assert (lead["pipeline"], lead["stage_label"]) == ("partner_outreach", "New lead")
                assert (await client.get(f"{BASE}/leads?scope=team&pipeline=main")).json()[
                    "total"
                ] == 1
                assert (
                    await client.get(f"{BASE}/leads?scope=team&pipeline=nope")
                ).status_code == 422

                detail = (await client.get(f"{BASE}/leads/{lead['lead_id']}")).json()
                labels = [choice["label"] for choice in detail["stage_choices"]]
                assert "Discovery call" in labels and "Meeting booked" in labels
                counts = (await client.get(f"{BASE}/journey?pipeline=partner_outreach")).json()
                assert {s["key"]: s["leads"] for s in counts["stages"]}["new"] == 1

                command = str(uuid4())
                moved = await client.post(
                    f"{BASE}/leads/{lead['lead_id']}/pipeline",
                    json={
                        "command_id": command,
                        "expected_revision": detail["lead"]["revision"],
                        "pipeline": "main",
                    },
                    headers=WRITE,
                )
                assert moved.status_code == 200, moved.text
                body = moved.json()
                assert (body["lead"]["pipeline"], body["lead"]["stage_label"]) == ("main", "New")
                assert body["events"][0]["kind"] == "stage"
                assert body["events"][0]["stage_label"] == "Leads · New"
                again = await client.post(
                    f"{BASE}/leads/{lead['lead_id']}/pipeline",
                    json={
                        "command_id": str(uuid4()),
                        "expected_revision": body["lead"]["revision"],
                        "pipeline": "main",
                    },
                    headers=WRITE,
                )
                assert again.status_code == 409

                # Main takes every lead the others don't, so its sources aren't picked.
                main_sources = await client.patch(
                    f"{BASE}/pipelines/main", json={"sources": ["meta"]}, headers=WRITE
                )
                assert main_sources.status_code == 422
                renamed = await client.patch(
                    f"{BASE}/pipelines/main", json={"name": "Enquiries"}, headers=WRITE
                )
                assert renamed.status_code == 200, renamed.text
                # A source feeds one pipeline: picking it for another takes it from the first.
                website = await client.post(
                    f"{BASE}/pipelines",
                    json={"name": "Website", "template": "simple", "sources": ["csv", "webhook"]},
                    headers=WRITE,
                )
                assert website.status_code == 200, website.text
                assert [(p["name"], p["sources"]) for p in website.json()["pipelines"]] == [
                    ("Enquiries", []),
                    ("Partner outreach", []),
                    ("Website", ["csv", "webhook"]),
                ]
                taken = await client.post(
                    f"{BASE}/pipelines",
                    json={"name": "website", "template": "simple"},
                    headers=WRITE,
                )
                assert taken.status_code == 422
        finally:
            await setup.engine.dispose()

    run(exercise())
