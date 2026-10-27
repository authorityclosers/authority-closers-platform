"""A pipeline can take Google Ads lead forms apart from website forms (leads setup audit,
27 Oct 2026). A Google Ads lead posts like a website form; until a pipeline picks "Google
Ads lead forms" it goes with the website forms, as before."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, select

from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk.connectors.http import install_connectors_http
from ac_platform.lead_desk.models import Lead
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_google_ads_leads_go_to_the_pipeline_that_picked_them(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            settings = here.setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
            install_connectors_http(
                here.setup.app,
                RouteContext(settings, here.setup.require_actor, here.setup.sessions),
            )
            here.as_admin()

            async def pipeline(name: str, sources: list[str]) -> str:
                made = await here.client.post(
                    f"{BASE}/pipelines",
                    json={"name": name, "template": "inside_sales_demos", "sources": sources},
                    headers=WRITE,
                )
                assert made.status_code == 200, made.text
                return str(
                    next(item["key"] for item in made.json()["pipelines"] if item["name"] == name)
                )

            source = await here.client.post(
                f"{BASE}/sources",
                json={"kind": "webhook", "label": "Google Ads lead form"},
                headers=WRITE,
            )
            assert source.status_code == 201, source.text
            source_id, key = source.json()["source_id"], source.json()["token"]

            async def google(lead_id: str, phone: str) -> str:
                sent = await here.client.post(
                    f"/v1/lead-desk/capture/{source_id}/google-ads",
                    json={
                        "lead_id": lead_id,
                        "google_key": key,
                        "user_column_data": [
                            {"column_id": "FULL_NAME", "string_value": f"Fictional {lead_id}"},
                            {"column_id": "PHONE_NUMBER", "string_value": phone},
                        ],
                    },
                )
                assert sent.status_code == 200, sent.text
                return str(sent.json()["lead_id"])

            async def website(name: str, phone: str) -> str:
                sent = await here.client.post(
                    f"/v1/lead-desk/capture/{source_id}",
                    json={"name": name, "phone": phone},
                    headers={"X-Lead-Desk-Key": key},
                )
                assert sent.status_code == 202, sent.text
                return str(sent.json()["lead_id"])

            async def pipeline_of(lead_id: str) -> str:
                async with here.setup.sessions() as db:
                    return str(
                        await db.scalar(select(Lead.pipeline_key).where(Lead.id == UUID(lead_id)))
                    )

            web = await pipeline("Website", ["webhook"])
            # Nobody picked Google Ads yet: it goes with the website forms, as before.
            assert await pipeline_of(await google("g-1", "+919876500041")) == web
            ads = await pipeline("Google Ads", ["google_ads"])
            assert await pipeline_of(await google("g-2", "+919876500042")) == ads
            assert await pipeline_of(await website("Fictional Web", "+919876500043")) == web

    run(exercise())
