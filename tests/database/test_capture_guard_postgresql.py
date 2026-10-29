"""Real PostgreSQL HTTP contract: missing calls, attachments, scope and privacy."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, select, update

from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.models import ConversationRecording, ConversationRun
from ac_platform.lead_desk.models import LeadEvent
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import _upload_for_read_test
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_capture_guard_scope_missing_attachment_and_privacy(postgres_harness: Any, tmp_path: Path):
    async def exercise():
        async with world(postgres_harness, tmp_path) as here:
            lead = UUID(await here.add("Alex Example", "+12025550123"))
            now = datetime.now(UTC)
            old, waiting, other, attachment, simulated = [uuid4() for _ in range(5)]
            async with here.setup.sessions() as db, db.begin():
                for eid, actor, data, at in [
                    (
                        old,
                        here.seller.person_id,
                        {"via": "phone", "duration_seconds": 45},
                        now - timedelta(minutes=31),
                    ),
                    (waiting, here.seller.person_id, {"via": "phone", "duration_seconds": 20}, now),
                    (other, here.setup.state.person_id, {"via": "phone"}, now),
                    (
                        attachment,
                        here.seller.person_id,
                        {"recording": True, "for_call": str(old), "submission_id": str(uuid4())},
                        now,
                    ),
                    (simulated, here.seller.person_id, {"simulated": True}, now),
                ]:
                    db.add(
                        LeadEvent(
                            id=eid,
                            tenant_id=here.tenant_id,
                            lead_id=lead,
                            kind="call",
                            actor_person_id=actor,
                            command_id=uuid4(),
                            data=data,
                            created_at=at,
                        )
                    )
            here.as_seller()
            result = await here.client.get(f"{BASE}/capture-guard")
            assert result.status_code == 200, result.text
            calls = {row["event_id"]: row for row in result.json()["calls"]}
            assert set(calls) == {str(old), str(waiting)}
            assert (
                calls[str(old)]["state"] == "missing"
            )  # A claimed attachment isn't a server receipt.
            assert calls[str(waiting)]["state"] == "waiting"
            assert result.json()["rates"][0]["calls"] == 2
            assert result.json()["rates"][0]["received"] == 0
            hidden = await here.client.get(f"{BASE}/capture-guard?event_id={other}")
            assert hidden.json()["calls"] == []
            assert (await here.client.get(f"{BASE}/capture-guard?days=32")).status_code == 422
            here.as_admin()
            assert len((await here.client.get(f"{BASE}/capture-guard")).json()["calls"]) == 3
            # A real synthetic source upload, linked twice, counts as one received call.
            _, submission = await _upload_for_read_test(here.setup, here.client)
            for _ in range(2):
                attached = await here.client.post(
                    f"{BASE}/leads/{lead}/recordings",
                    json={
                        "command_id": str(uuid4()),
                        "submission_id": str(submission),
                        "call_event_id": str(old),
                    },
                    headers=WRITE,
                )
                assert attached.status_code == 200, attached.text
            captured = (await here.client.get(f"{BASE}/capture-guard?event_id={old}")).json()
            assert captured["calls"][0]["state"] in {"uploaded", "analysing"}
            assert captured["rates"][0]["calls"] == captured["rates"][0]["received"] == 1
            async with here.setup.sessions() as db, db.begin():
                recording_id = await db.scalar(
                    select(ConversationGuestSubmission.recording_id).where(
                        ConversationGuestSubmission.tenant_id == here.tenant_id,
                        ConversationGuestSubmission.submission_id == submission,
                    )
                )
                await db.execute(
                    update(ConversationRun)
                    .where(ConversationRun.recording_id == recording_id)
                    .values(state="failed")
                )
            failed = (await here.client.get(f"{BASE}/capture-guard?event_id={old}")).json()[
                "calls"
            ][0]
            assert failed["state"] == "uploaded"  # Failure never claims a report.
            assert failed["attention"] is True
            async with here.setup.sessions() as db, db.begin():
                await db.execute(
                    update(ConversationRun)
                    .where(ConversationRun.recording_id == recording_id)
                    .values(state="running")
                )
            assert (await here.client.get(f"{BASE}/capture-guard?event_id={old}")).json()["calls"][
                0
            ]["state"] == "analysing"
            # Relational fixture only: no provider request, scoring or certified report evidence.
            report_id = uuid4()
            async with here.setup.sessions() as db, db.begin():
                run_row = await db.scalar(
                    select(ConversationRun).where(ConversationRun.recording_id == recording_id)
                )
                recording_row = await db.get(ConversationRecording, recording_id)
                assert run_row is not None and recording_row is not None
                run_row.state = "completed"
                db.add(
                    ConversationReportDraft(
                        id=report_id,
                        tenant_id=here.tenant_id,
                        person_id=run_row.person_id,
                        recording_id=recording_id,
                        run_id=run_row.id,
                        source_revision=1,
                        source_sha256=recording_row.source_sha256,
                        report_sha256="c" * 64,
                        transcript_sha256="d" * 64,
                        profile_sha256="e" * 64,
                        evidence_receipt_sha256="f" * 64,
                        payload={},
                        transcript={},
                        evidence_receipt={"fixture": "capture-state-only"},
                        created_at=now,
                    )
                )
            ready = (await here.client.get(f"{BASE}/capture-guard?event_id={old}")).json()
            assert ready["calls"][0]["state"] == "report_ready"
            assert ready["rates"][0]["analysed"] == 1
            async with here.setup.sessions() as db, db.begin():
                await db.execute(
                    update(ConversationReportDraft)
                    .where(ConversationReportDraft.id == report_id)
                    .values(erased_at=now, payload=None)
                )
            assert (await here.client.get(f"{BASE}/capture-guard?event_id={old}")).json()["rates"][
                0
            ]["analysed"] == 0
            async with here.setup.sessions() as db, db.begin():
                await db.execute(
                    update(ConversationRecording)
                    .where(ConversationRecording.id == recording_id)
                    .values(state="deleted", deleted_at=datetime.now(UTC))
                )
            erased = (await here.client.get(f"{BASE}/capture-guard?event_id={old}")).json()
            assert erased["calls"][0]["state"] == "missing"
            assert erased["rates"][0]["received"] == 0
            here.as_seller()
            private = await here.client.post(
                f"{BASE}/calls/{old}/private",
                json={"command_id": str(uuid4()), "private": True},
                headers=WRITE,
            )
            assert private.status_code == 200, private.text
            here.as_admin()
            assert str(old) not in {
                c["event_id"]
                for c in (await here.client.get(f"{BASE}/capture-guard")).json()["calls"]
            }
            here.client.cookies.clear()
            assert (await here.client.get(f"{BASE}/capture-guard")).status_code in {401, 403}

    run(exercise())
