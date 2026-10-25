"""The duplicate scan on PostgreSQL (docs/product/lead-desk/duplicates.md, D2): one
organisation's leads only, never another's with the same people; an alternate number in a
lead's form matches another lead's phone; test data and merged leads are left out; "not the
same" keeps a pair out for good; a pair no longer found is removed. Made-up people only."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, select, update

from ac_platform.lead_desk import duplicate_scan
from ac_platform.lead_desk.models import Lead, LeadDuplicateDecision, LeadDuplicatePair
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_lead_os_acceptance_postgresql import ROOT, world

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def lead(
    tenant: UUID,
    name: str,
    phone: str | None = None,
    email: str | None = None,
    **extra: Any,
) -> Lead:
    return Lead(
        id=extra.pop("id", uuid4()),
        tenant_id=tenant,
        revision=1,
        source="manual",
        payload=extra.pop("payload", {"name": name}),
        name=name,
        phone=phone,
        email=email,
        stage="new",
        attempts=0,
        calls=0,
        repeats=0,
        test_data=extra.pop("test_data", False),
        created_at=NOW,
        updated_at=NOW,
        **extra,
    )


def test_one_organisation_at_a_time_and_what_is_left_out(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            other = (await seed(here.setup.engine)).tenant_id
            mine = here.tenant_id
            ids = {key: uuid4() for key in ("asha", "asha2", "neha", "neha2", "ravi", "ravi2")}
            async with here.setup.sessions() as db, db.begin():
                db.add_all(
                    [
                        # The same email apart from a typo, the same last ten digits, one name.
                        lead(
                            mine, "Asha Example", "+919876077001", "asha@gamil.com", id=ids["asha"]
                        ),
                        lead(
                            mine, "Asha Example", "+19876077001", "asha@gmail.com", id=ids["asha2"]
                        ),
                        # The same person in another organisation: never a pair.
                        lead(other, "Asha Example", "+919876077001", "asha@gamil.com"),
                        # An alternate number in one lead's form is the other lead's phone.
                        lead(
                            mine,
                            "Neha Demo",
                            "+919876077003",
                            id=ids["neha"],
                            payload={"Alternate Contact No": "98760 77004"},
                        ),
                        lead(mine, "Neha D", "+919876077004", id=ids["neha2"]),
                        # Test data never pairs.
                        lead(
                            mine, "Ravi Sample", "+919876077005", "ravi@example.com", id=ids["ravi"]
                        ),
                        lead(
                            mine,
                            "Ravi Sample",
                            "+919876077006",
                            "ravi@example.com",
                            id=ids["ravi2"],
                            test_data=True,
                        ),
                    ]
                )

            async def pairs() -> dict[frozenset[UUID], LeadDuplicatePair]:
                async with here.setup.sessions() as db:
                    rows = (
                        await db.scalars(
                            select(LeadDuplicatePair).where(LeadDuplicatePair.tenant_id == mine)
                        )
                    ).all()
                return {frozenset((row.first_lead_id, row.second_lead_id)): row for row in rows}

            async def scan(tenant: UUID) -> dict[str, Any]:
                async with here.setup.sessions() as db, db.begin():
                    return await duplicate_scan.scan(db, tenant, NOW)

            done = await scan(mine)
            found = await pairs()
            asha = frozenset((ids["asha"], ids["asha2"]))
            neha = frozenset((ids["neha"], ids["neha2"]))
            assert set(found) == {asha, neha}
            assert found[asha].band == "probable"
            assert "same email apart from a typo" in found[asha].reasons
            assert found[neha].band == "certain" and "same phone number" in found[neha].reasons
            assert done["pairs"] == 2
            # The other organisation has one lead: nothing, and nothing of ours.
            assert (await scan(other))["pairs"] == 0
            async with here.setup.sessions() as db:
                theirs = (
                    await db.scalars(
                        select(LeadDuplicatePair).where(LeadDuplicatePair.tenant_id == other)
                    )
                ).all()
            assert theirs == []

            # "Not the same" keeps the pair out for good; a merged lead pairs no more.
            first, second = sorted(neha)
            async with here.setup.sessions() as db, db.begin():
                db.add(
                    LeadDuplicateDecision(
                        id=uuid4(),
                        tenant_id=mine,
                        first_lead_id=first,
                        second_lead_id=second,
                        decision="not_same",
                        decided_by_person_id=here.setup.state.person_id,
                        decided_at=NOW,
                    )
                )
                await db.execute(
                    update(Lead)
                    .where(Lead.id == ids["asha2"])
                    .values(merged_into_id=ids["asha"], merged_at=NOW)
                )
            again = await scan(mine)
            assert again["pairs"] == 0 and again["removed"] == 2
            assert again["not_same_kept_out"] == 1
            assert await pairs() == {}

    run(exercise())
