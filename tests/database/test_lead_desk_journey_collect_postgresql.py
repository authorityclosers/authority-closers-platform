"""The ad-platform collector on PostgreSQL (16 Nov 2026, Wise Life: only "Lead" ever reached
Meta). A seller's stage move becomes the platform's events; a lead moved from one pipeline
into another reaches no stage; a capture still becomes "Lead". Made-up leads only; no test
calls Meta (collecting only freezes the events to send)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, select

from ac_platform.lead_desk.journey import engine, mapping
from ac_platform.lead_desk.journey import model as journeys
from ac_platform.lead_desk.models import Lead, LeadConversion, LeadDeskSettings, LeadEvent
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import (
    BASE,
    ROOT,
    WRITE,
    World,
    later,
    world,
)

DATASET = "555000111222333"


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


async def meta_lead(here: World, name: str, phone: str, ref: str) -> str:
    """A lead as a Meta lead form brings it (the only leads Meta can match)."""
    lead_id = await here.add(name, phone)
    async with here.setup.sessions() as db, db.begin():
        lead = await db.get(Lead, UUID(lead_id))
        assert lead is not None
        lead.source, lead.source_ref = "meta", ref
    return lead_id


async def switch_meta_on(here: World, since: datetime) -> dict[str, str]:
    """Every live stage matched to its own key as the event name, sending on from ``since``."""
    async with here.setup.sessions() as db, db.begin():
        journey = await journeys.read(db, here.tenant_id)
        names = {stage.key: stage.key for stage in journey.live}
        config = mapping.confirmed({}, "meta", journey, names, by=here.setup.state.person_id, now=1)
        config = mapping.destination_saved(
            config,
            "meta",
            destination_id=DATASET,
            destination_name="Fictional dataset",
            on=True,
            test_code=None,
            now=int(since.timestamp()),
        )
        row = await db.get(LeadDeskSettings, here.tenant_id)
        if row is None:
            db.add(
                LeadDeskSettings(
                    tenant_id=here.tenant_id,
                    revision=1,
                    config=config,
                    updated_by_person_id=None,
                    updated_at=since,
                )
            )
        else:
            row.config = {**(row.config or {}), **config}
    return names


async def to_pipeline(here: World, lead_id: str, pipeline: str) -> None:
    here.as_admin()
    revision = (await here.detail(lead_id))["lead"]["revision"]
    moved = await here.client.post(
        f"{BASE}/leads/{lead_id}/pipeline",
        json={"command_id": str(uuid4()), "expected_revision": revision, "pipeline": pipeline},
        headers=WRITE,
    )
    assert moved.status_code == 200, moved.text
    here.as_seller()


async def conversions(here: World, lead_id: str) -> list[LeadConversion]:
    async with here.setup.sessions() as db:
        return list(
            (
                await db.scalars(
                    select(LeadConversion)
                    .where(LeadConversion.lead_id == UUID(lead_id))
                    .order_by(LeadConversion.event_name)
                )
            ).all()
        )


async def lines(here: World, lead_id: str, kind: str) -> list[LeadEvent]:
    return [event for event in await here.events(lead_id) if event.kind == kind]


def test_stage_moves_reach_meta_and_moves_between_pipelines_do_not(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            here.as_admin()
            made = await here.client.post(
                f"{BASE}/pipelines",
                json={"name": "Partner outreach", "template": "b2b_services", "sources": ["csv"]},
                headers=WRITE,
            )
            assert made.status_code == 200, made.text
            here.as_seller()
            mover = await meta_lead(here, "Fictional Mover", "98760 81001", "120000000081001")
            switched = await meta_lead(here, "Fictional Switch", "98760 81002", "120000000081002")
            # Sending starts after both captures: what these two reach comes from their moves.
            since = datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=1)
            names = await switch_meta_on(here, since)
            await asyncio.sleep(max(0.0, (since - datetime.now(UTC)).total_seconds()) + 0.2)

            # The two ways a seller moves a lead: a call's answer, then the stage by hand.
            answered = await here.dispose(
                mover, connected=True, step="interested", follow_up_at=later(days=1)
            )
            assert answered.status_code == 200, answered.text
            moved = await here.move(
                mover,
                "meeting_scheduled",
                meeting={"startsAt": later(days=2), "mode": "zoom", "link": "https://zoom.us/j/1"},
            )
            assert moved.status_code == 200, moved.text
            [result_line] = await lines(here, mover, "result")
            [stage_line] = await lines(here, mover, "stage")
            # What hid every move from Meta: each names the lead's own pipeline.
            for line in (result_line, stage_line):
                assert line.data["pipeline"] == "main"
                assert "from_pipeline" not in line.data

            await to_pipeline(here, switched, "partner_outreach")
            await to_pipeline(here, switched, "main")
            between = await lines(here, switched, "stage")
            assert [(e.data["from_pipeline"], e.data["pipeline"]) for e in between] == [
                ("main", "partner_outreach"),
                ("partner_outreach", "main"),
            ]

            captured = await meta_lead(here, "Fictional New", "98760 81003", "120000000081003")

            collected = await engine.collect(
                here.setup.sessions,
                environment="test",
                now=datetime.now(UTC) + engine.SETTLE + timedelta(minutes=1),
            )
            async with here.setup.sessions() as db:
                journey = await journeys.read(db, here.tenant_id)

            # A seller's moves: each stage reached and the funnel before it, once per name,
            # from the move that first reached it.
            sent = await conversions(here, mover)
            by_answer = journey.with_earlier("interested")
            by_hand = [k for k in journey.with_earlier("meeting_scheduled") if k not in by_answer]
            assert "interested" in by_answer and "meeting_scheduled" in by_hand
            assert sorted((c.event_name, c.source_event_id) for c in sent) == sorted(
                [(names[key], result_line.id) for key in by_answer]
                + [(names[key], stage_line.id) for key in by_hand]
            )
            assert {(c.provider, c.destination, c.status) for c in sent} == {
                ("meta", DATASET, "pending")
            }

            # From one pipeline into another and back: no stage reached, nothing sent.
            assert await conversions(here, switched) == []

            # A capture after sending began: the first stage ("Lead" at Wise Life), as before.
            [new_line] = await lines(here, captured, "captured")
            first_stage = journey.resolve("new", None)
            assert first_stage is not None
            first = await conversions(here, captured)
            assert [(c.event_name, c.source_event_id) for c in first] == [
                (names[first_stage.key], new_line.id)
            ]
            assert collected == len(sent) + len(first)

            # Collecting again (the cursor rewound) makes nothing twice.
            async with here.setup.sessions() as db, db.begin():
                row = await db.get(LeadDeskSettings, here.tenant_id)
                assert row is not None
                row.config = mapping.with_cursor(
                    dict(row.config), since - timedelta(seconds=1), UUID(int=0)
                )
            again = await engine.collect(
                here.setup.sessions,
                environment="test",
                now=datetime.now(UTC) + engine.SETTLE + timedelta(minutes=2),
            )
            assert again == 0
            assert len(await conversions(here, mover)) == len(sent)

    run(exercise())
