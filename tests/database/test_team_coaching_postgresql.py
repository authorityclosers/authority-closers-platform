"""Current org authority gates counts; private rep coaching is never opened."""

from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select, update

from ac_platform.conversation_intelligence.sensitive_segments_store import SensitiveSegmentsStore
from ac_platform.tenancy.models import Membership, Organisation
from tests.database.test_coaching_postgresql import draft_for, install
from tests.database.test_coaching_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_account_library_postgresql import _session
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_prospect_store_postgresql import direct_call

PATH = "/v1/me/coaching/team"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_anonymous_team_aggregates_respect_private_rep_evidence_and_current_roles(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
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
                    .values(role="owner")
                )
            install(setup, organisation=True)
            own_call = await direct_call(setup)
            await draft_for(setup, own_call)
            rep = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            rep_token = await _session(setup, rep)
            rep_call = await direct_call(setup, rep.actor)
            rep_recording, revision = await draft_for(setup, rep_call)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                assert (await client.get(PATH)).status_code == 401
                client.cookies.set(setup.settings.session_cookie_name, rep_token)
                assert (await client.get(PATH)).status_code == 403
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                response = await client.get(PATH)
                assert response.status_code == 200, response.text
                assert response.headers["cache-control"] == "private, no-store"
                data = response.json()
                assert data["analysed_calls"] == 2 and data["named_rep_details"] is False
                assert data["suggestions"][0]["suggestion_calls"] == 2
                for private in (
                    str(rep.person_id),
                    str(rep_call),
                    str(rep_recording),
                    "buyer asks",
                    "Ask before presenting",
                ):
                    assert private not in response.text
                assert (await client.get(f"/v1/me/coaching/calls/{rep_call}")).status_code == 404
                assert (
                    await client.get(PATH, params={"person_id": str(rep.person_id)})
                ).status_code == 422
                async with setup.sessions() as db, db.begin():
                    await SensitiveSegmentsStore(db).mark(
                        rep.actor,
                        recording_id=rep_recording,
                        transcript_revision=revision,
                        segments=[("s1", "SENSITIVE_FINANCIAL")],
                        reason_ref="AUT-1678",
                        idempotency_key="fictional-team-withheld",
                    )
                    member = await db.scalar(
                        select(Membership).where(Membership.person_id == setup.state.person_id)
                    )
                    member.role = "admin"
                refreshed = await client.get(PATH)
                assert refreshed.status_code == 200
                assert refreshed.json()["analysed_calls"] == 2, refreshed.json()
                # Canonical withholding follows a shared transcript revision,
                # even across recordings. These fictional drafts share that revision.
                assert refreshed.json()["suggestions"] == []
                assert "buyer asks" not in refreshed.text
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(Membership)
                        .where(Membership.person_id == setup.state.person_id)
                        .values(role="member")
                    )
                assert (await client.get(PATH)).status_code == 403
        finally:
            await setup.engine.dispose()

    run(exercise())
