"""Undo an after-call answer through the HTTP API on PostgreSQL (orchestrator for the owner,
31 Oct 2026): the lead's latest, by the seller who saved it, within 5 minutes. It supersedes: the
previous stage, next call and its note come back with a history line, the answer stays, and the
call stays counted. Refused once anything went or will go outward."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import Engine, select

from ac_platform.lead_desk.journey.engine import not_undone
from ac_platform.lead_desk.models import LeadConversion, LeadEvent
from ac_platform.partner_events.models import PartnerWebhookEndpoint
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, World, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


LATER = (datetime.now(UTC) + timedelta(days=1)).isoformat()


async def answer(here: World, lead_id: str, step: str, **extra: Any) -> dict[str, Any]:
    done = await here.dispose(lead_id, connected=True, step=step, follow_up_at=LATER, **extra)
    assert done.status_code == 200, done.text
    body: dict[str, Any] = done.json()
    return body


async def last_answer(here: World, lead_id: str) -> str:
    return str([event for event in await here.events(lead_id) if event.kind == "result"][-1].id)


async def undo(here: World, lead: dict[str, Any], event_id: str) -> httpx.Response:
    return await here.client.post(
        f"{BASE}/leads/{lead['lead_id']}/results/{event_id}/undo",
        json={"command_id": str(uuid4()), "expected_revision": lead["revision"]},
        headers=WRITE,
    )


def test_a_seller_undoes_their_latest_answer_and_the_lead_comes_back(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            lead_id = await here.add("Fictional Undo Asha", "98760 61000")
            before = (await here.detail(lead_id))["lead"]
            saved = await answer(here, lead_id, "interested", remark="Wants the EMI sheet")
            assert saved["lead"]["step"] == "interested"
            offer = saved["undo_result"]
            assert offer is not None and offer["event_id"] == await last_answer(here, lead_id)
            undone = await undo(here, saved["lead"], offer["event_id"])
            assert undone.status_code == 200, undone.text
            back = undone.json()
            assert (back["lead"]["stage"], back["lead"]["step"]) == (
                before["stage"],
                before["step"],
            )
            assert back["lead"]["next_action_at"] == before["next_action_at"]
            # The call stays counted; the answer stays in the history, the undo after it.
            assert back["lead"]["attempts"] == before["attempts"] + 1
            assert back["undo_result"] is None
            kinds = [event["kind"] for event in back["events"]]
            assert "result" in kinds and "edited" in kinds
            # The answer's note stays, a note of its own (ph2-26, 1 Nov 2026).
            notes = [event["note"] for event in back["events"] if event["kind"] == "note"]
            assert notes == ["Wants the EMI sheet"]
            # Once only.
            again = await undo(here, back["lead"], offer["event_id"])
            assert again.status_code == 409, again.text
            # The conversion engine never turns the undone answer into a conversion.
            async with here.setup.sessions() as db:
                left = (
                    await db.scalars(
                        select(LeadEvent.id).where(
                            LeadEvent.lead_id == UUID(lead_id),
                            LeadEvent.kind == "result",
                            not_undone(),
                        )
                    )
                ).all()
            assert left == []

    run(exercise())


def test_undo_is_refused_when_it_must_be(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            n = 61100

            async def fresh(step: str = "interested", **extra: Any) -> tuple[str, dict[str, Any]]:
                nonlocal n
                n += 1
                lead_id = await here.add(f"Fictional Undo {n}", f"98760 {n}")
                return lead_id, await answer(here, lead_id, step, **extra)

            # Someone else (the admin), not the seller who saved it.
            lead_id, saved = await fresh()
            here.as_admin()
            other = await undo(here, saved["lead"], saved["undo_result"]["event_id"])
            assert other.status_code == 403, other.text
            here.as_seller()

            # Not the latest: the lead was answered again since.
            lead_id, first = await fresh()
            second = await answer(here, lead_id, "interested")
            moved = await undo(here, second["lead"], first["undo_result"]["event_id"])
            assert moved.status_code == 409 and "moved again" in moved.text

            # A booked meeting or a Won: never offered, and refused.
            lead_id, saved = await fresh(
                "meeting_scheduled", meeting={"starts_at": LATER, "mode": "phone"}
            )
            assert saved["undo_result"] is None
            meeting = await undo(here, saved["lead"], await last_answer(here, lead_id))
            assert meeting.status_code == 409 and "meeting" in meeting.text
            await answer(here, lead_id, "demo_completed")
            saved = await answer(here, lead_id, "won", deal_value="50000")
            assert saved["undo_result"] is None
            won = await undo(here, saved["lead"], await last_answer(here, lead_id))
            assert won.status_code == 409 and "Won" in won.text

            # An ad platform already has it.
            lead_id, saved = await fresh()
            now = datetime.now(UTC)
            async with here.setup.sessions() as db, db.begin():
                db.add(
                    LeadConversion(
                        id=uuid4(),
                        tenant_id=here.tenant_id,
                        lead_id=UUID(lead_id),
                        source_event_id=UUID(saved["undo_result"]["event_id"]),
                        provider="meta",
                        destination="fictional-dataset",
                        stage_key="interested",
                        event_name="Lead",
                        event_time=now,
                        payload={"fictional": True},
                        payload_sha256="0" * 64,
                        status="pending",
                        attempts=0,
                        next_attempt_at=now,
                        test=True,
                        created_at=now,
                    )
                )
            heard = await undo(here, saved["lead"], saved["undo_result"]["event_id"])
            assert heard.status_code == 409 and "ad platform" in heard.text

            # Too late: saved more than 5 minutes ago (the window, made nothing).
            lead_id, saved = await fresh()
            monkeypatch.setattr("ac_platform.lead_desk.store.RESULT_UNDO", timedelta(0))
            late = await undo(here, saved["lead"], saved["undo_result"]["event_id"])
            assert late.status_code == 409 and "5 minutes" in late.text
            monkeypatch.undo()

            # A partner app hears about stage changes: refused.
            async with here.setup.sessions() as db, db.begin():
                db.add(
                    PartnerWebhookEndpoint(
                        id=uuid4(),
                        tenant_id=here.tenant_id,
                        url="https://example.test/hook",
                        secret_ref="AC_PARTNER_WEBHOOK_SECRET__FICTIONAL",  # noqa: S106 (a name, not a secret)
                        events=["lead.stage_changed"],
                        status="active",
                        events_since=now - timedelta(hours=1),
                        created_by="fictional test",
                        reason="a fictional partner that hears about stage changes",
                        created_at=now,
                    )
                )
            lead_id, saved = await fresh()
            told = await undo(here, saved["lead"], saved["undo_result"]["event_id"])
            assert told.status_code == 409 and "partner" in told.text

    run(exercise())
