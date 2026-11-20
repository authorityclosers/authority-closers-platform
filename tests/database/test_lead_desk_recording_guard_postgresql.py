"""One recording, one call (lead_desk/recording_guard.py; Oppo CPH2835 at Wise Life, 19 and 20
Nov 2026: a phone sent the previous call's recording for the next call, twice).

The same audio already on another call is refused for this one (409, the phone looks again)
and a durable ``capture.duplicate_recording`` audit event says so; the same recording for the
same call again changes nothing; audio of its own is added as before.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, update

from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionUsage,
)
from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk import recording_guard
from ac_platform.lead_desk.http import install_lead_desk_http
from ac_platform.lead_desk.models import LeadEvent
from ac_platform.tenancy.models import Membership, Organisation
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
BASE = "/v1/lead-desk"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def _organisation(setup: Any) -> None:
    async with setup.sessions() as db, db.begin():
        db.add(
            Organisation(
                tenant_id=setup.state.tenant_id,
                created_by_person_id=setup.state.person_id,
                creation_command_id=uuid4(),
                domain_verification_token=uuid4().hex + uuid4().hex,
            )
        )
        await db.execute(
            update(Membership)
            .where(Membership.person_id == setup.state.person_id)
            .values(role="admin")
        )
    settings = setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
    install_lead_desk_http(setup.app, RouteContext(settings, setup.require_actor, setup.sessions))


async def _upload(setup: Any, audio: str) -> str:
    """An uploaded recording of this audio (its usage row, as an upload leaves it)."""
    submission = uuid4()
    async with setup.sessions() as db, db.begin():
        db.add(
            ConversationAcquisitionUsage(
                id=uuid4(),
                tenant_id=setup.state.tenant_id,
                person_id=setup.state.person_id,
                visitor_id=None,
                submission_id=submission,
                source_sha256=_digest(audio),
                duration_evidence_sha256=_digest("fictional-duration"),
                reserved_seconds=200,
                policy_revision="guest-processing-v1",
                created_at=datetime.now(UTC),
            )
        )
    return str(submission)


def test_one_recording_goes_on_one_call(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)

                async def lead(name: str, phone: str) -> str:
                    made = await client.post(
                        f"{BASE}/leads",
                        json={
                            "command_id": str(uuid4()),
                            "name": name,
                            "phone": phone,
                            "assign": "me",
                        },
                        headers=WRITE,
                    )
                    assert made.status_code == 201, made.text
                    return str(made.json()["lead"]["lead_id"])

                async def call(lead_id: str) -> str:
                    called = await client.post(
                        f"{BASE}/leads/{lead_id}/calls/phone",
                        json={"command_id": str(uuid4()), "duration_seconds": 95},
                        headers=WRITE,
                    )
                    assert called.status_code == 200, called.text
                    return str(called.json()["events"][0]["event_id"])

                async def attach(lead_id: str, submission: str, for_call: str | None) -> Any:
                    body = {"command_id": str(uuid4()), "submission_id": submission}
                    if for_call is not None:
                        body["call_event_id"] = for_call
                    return await client.post(
                        f"{BASE}/leads/{lead_id}/recordings", json=body, headers=WRITE
                    )

                asha = await lead("Asha", "9800000041")
                ravi = await lead("Ravi", "9800000042")
                first_call = await call(asha)
                second_call = await call(asha)
                ravi_call = await call(ravi)

                # The first call's recording goes on it.
                first = await _upload(setup, "audio-of-call-1")
                one = await attach(asha, first, first_call)
                assert one.status_code == 200, one.text

                # The same file sent again for the same call (a retry, a second upload): no change.
                again = await attach(asha, first, first_call)
                assert again.status_code == 200, again.text
                resent = await _upload(setup, "audio-of-call-1")
                same_call = await attach(asha, resent, first_call)
                assert same_call.status_code == 200, same_call.text
                recorded = [e for e in same_call.json()["events"] if e.get("recording")]
                assert len(recorded) == 1

                # The same audio for the lead's next call, or another lead's call, is refused:
                # retryable, the phone looks for that call's own recording.
                for lead_id, other_call in ((asha, second_call), (ravi, ravi_call), (ravi, None)):
                    copy = await _upload(setup, "audio-of-call-1")
                    refused = await attach(lead_id, copy, other_call)
                    assert refused.status_code == 409, refused.text
                    assert refused.json()["detail"] == recording_guard.DUPLICATE

                # That call's own recording goes on it as before.
                own = await _upload(setup, "audio-of-call-2")
                second = await attach(asha, own, second_call)
                assert second.status_code == 200, second.text
                # A submission with no upload in this workspace is not checked (as before).
                loose = await attach(ravi, str(uuid4()), None)
                assert loose.status_code == 200, loose.text

            async with setup.sessions() as db:
                audits = (
                    await db.scalars(
                        select(AuditEvent)
                        .where(
                            AuditEvent.tenant_id == setup.state.tenant_id,
                            AuditEvent.action == recording_guard.ACTION,
                        )
                        .order_by(AuditEvent.sequence_no)
                    )
                ).all()
                # Each refusal left its audit event although its request was rolled back.
                assert len(audits) == 3
                assert {a.payload["other_lead_id"] for a in audits} == {asha}
                assert {a.payload["other_call"] for a in audits} == {first_call}
                assert audits[0].payload["call_event_id"] == second_call
                assert audits[0].payload["source_sha256_prefix"] == _digest("audio-of-call-1")[:12]
                # Nothing was attached by a refused request.
                refused_on = (
                    await db.scalars(
                        select(LeadEvent.lead_id).where(
                            LeadEvent.tenant_id == setup.state.tenant_id,
                            LeadEvent.kind == "call",
                            LeadEvent.lead_id == UUID(ravi),
                        )
                    )
                ).all()
                assert len(refused_on) == 2
        finally:
            await setup.engine.dispose()

    run(exercise())
