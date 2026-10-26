"""A lead's own page shows people's photos (v0.99 lead sheet, 27 Oct 2026): the owner's,
each seller's in the assign list, and whoever did each line of the history. A person
without a photo reads null, and the app draws their character from their id."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine

from ac_platform.identity.sales_xray_profile_models import PersonPhoto
from ac_platform.lead_desk.models import LeadEvent
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import ROOT, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_a_leads_page_carries_the_owner_sellers_and_actors_photos(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            lead = await here.add("Fictional Photo Lead", "98760 71001")
            seller = here.seller.person_id
            admin = here.setup.state.person_id
            photo = f"/v1/people/{seller}/photo?v=eeeeeeee"
            async with here.setup.sessions() as db, db.begin():
                db.add(
                    PersonPhoto(
                        person_id=seller,
                        source="upload",
                        content_type="image/webp",
                        photo=b"RIFF....WEBP",
                        byte_size=12,
                        sha256="e" * 64,
                        revision=1,
                        updated_at=datetime.now(UTC),
                    )
                )
                db.add(
                    LeadEvent(
                        id=uuid4(),
                        tenant_id=here.tenant_id,
                        lead_id=UUID(lead),
                        kind="note",
                        actor_person_id=seller,
                        data={"text": "Fictional note"},
                        created_at=datetime.now(UTC),
                    )
                )

            # A manager: the owner's photo, every seller's in the assign list, the actors'.
            here.as_admin()
            shown = await here.detail(lead)
            assert shown["lead"]["owner_person_id"] == str(seller)
            assert shown["lead"]["owner_photo_url"] == photo
            reps = {rep["person_id"]: rep.get("photo_url") for rep in shown["reps"]}
            assert reps[str(seller)] == photo
            assert reps[str(admin)] is None
            actors = {
                (line["actor_person_id"], line.get("actor_photo_url"))
                for line in shown["events"]
                if line.get("actor_person_id")
            }
            assert (str(seller), photo) in actors
            assert (str(admin), None) in actors

            # The seller: their own photo on their lead, and no assign list.
            here.as_seller()
            own = await here.detail(lead)
            assert own["lead"]["owner_photo_url"] == photo
            assert own["reps"] == []

            # Lists leave it out: only the lead's own page reads photos.
            listed = await here.client.get("/v1/lead-desk/leads")
            assert listed.status_code == 200, listed.text
            assert all(row.get("owner_photo_url") is None for row in listed.json()["leads"])

    run(exercise())
