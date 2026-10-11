"""AC Sandbox Coaching: the importer reads authored fictional coaching; nobody else."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import update

from ac_platform.coaching.sandbox import call_uuid, rep_uuid
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
    ConversationSyntheticRecord,
)
from ac_platform.tenancy.models import Membership, Organisation
from tests.database.test_coaching_postgresql import install
from tests.database.test_coaching_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_account_library_postgresql import _session
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.unit.coaching.test_sandbox import sandbox_bundle

CALLS = (
    ("syn-fixture-J01-C-01", "syn-fixture-R1", "Nikhil Nivsekar", "skill-7", "2026-07-21"),
    ("syn-fixture-J02-C-01", "syn-fixture-R2", "Asha Rao", "skill-2", "2026-07-22"),
    ("syn-fixture-J03-C-01", "syn-fixture-R1", "Nikhil Nivsekar", "skill-7", "2026-07-24"),
)


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_sandbox_coaching_is_the_importers_fictional_view_only(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        tenant, owner = setup.state.tenant_id, setup.state.person_id
        try:
            async with setup.sessions() as db, db.begin():
                db.add(
                    Organisation(
                        tenant_id=tenant,
                        created_by_person_id=owner,
                        creation_command_id=uuid4(),
                        domain_verification_token=uuid4().hex + uuid4().hex,
                    )
                )
                await db.execute(
                    update(Membership).where(Membership.person_id == owner).values(role="owner")
                )
            install(setup, organisation=True)
            other_admin = await seed(setup.engine, tenant_id=tenant, role="admin")
            member = await seed(setup.engine, tenant_id=tenant, role="member")
            admin_token = await _session(setup, other_admin)
            member_token = await _session(setup, member)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                rep = rep_uuid(tenant, "syn-fixture-R1")
                # Not a sandbox yet: no fictional reps, and Team stays anonymous.
                assert (await client.get(f"/v1/me/coaching/people/{rep}")).status_code == 404
                assert (await client.get("/v1/me/coaching/team")).json()["scope"] == "anonymous"
                async with setup.sessions() as db, db.begin():
                    db.add(
                        ConversationSandboxOrganisation(
                            tenant_id=tenant,
                            approved_by_person_id=owner,
                            approval_reference="fictional-owner-approval:AUT-1678",
                            created_at=setup.clock[0],
                        )
                    )
                    await db.flush()
                    for key, rep_key, name, skill, day in CALLS:
                        payload = sandbox_bundle(
                            key,
                            rep=rep_key,
                            rep_name=name,
                            skill=skill,
                            at=f"{day}T10:00:00+05:30",
                            cited=("syn-fixture-J01-C-01",) if key.endswith("J03-C-01") else (),
                        )
                        db.add(
                            ConversationSyntheticRecord(
                                tenant_id=tenant,
                                kind="call",
                                synthetic_key=key,
                                revision=1,
                                business_id="syn-fixture",
                                imported_by_person_id=owner,
                                payload_sha256=content_hash(payload),
                                payload=payload,
                                occurred_at=datetime.fromisoformat(f"{day}T10:00:00+05:30"),
                                imported_at=setup.clock[0],
                            )
                        )
                mine = (await client.get("/v1/me/coaching")).json()
                assert mine["sandbox_reps"] == 2 and mine["sandbox"] is False
                team = await client.get("/v1/me/coaching/team")
                assert team.status_code == 200, team.text
                assert team.headers["cache-control"] == "private, no-store"
                data = team.json()
                assert data["scope"] == "sandbox" and data["sandbox"] is True
                assert (data["analysed_calls"], data["rep_count"]) == (3, 2)
                assert [row["name"] for row in data["reps"]] == ["Nikhil Nivsekar", "Asha Rao"]
                person = await client.get(f"/v1/me/coaching/people/{rep}")
                assert person.status_code == 200, person.text
                view = person.json()
                assert view["person_id"] == str(rep) and view["sandbox"] is True
                assert view["focus"]["skill_id"] == "closing_decision_management"
                assert view["analysed_calls"] == 2 and len(view["calls"]) == 2
                assert {m["submission_id"] for m in view["evidence"]} == {
                    str(call_uuid(tenant, "syn-fixture-J03-C-01")),
                    str(call_uuid(tenant, "syn-fixture-J01-C-01")),
                }
                newest = call_uuid(tenant, "syn-fixture-J03-C-01")
                call = await client.get(f"/v1/me/coaching/calls/{newest}")
                assert call.status_code == 200, call.text
                body = call.json()
                assert body["state"] == "ready" and body["person_id"] == str(owner)
                assert body["mission"]["origin_submission_id"] == str(newest)
                assert not any(moment["playable"] for moment in body["evidence"])
                # Another admin and a member never read the importer's private coaching.
                for token in (admin_token, member_token):
                    client.cookies.set(setup.settings.session_cookie_name, token)
                    assert (await client.get(f"/v1/me/coaching/people/{rep}")).status_code == 404
                    assert (await client.get(f"/v1/me/coaching/calls/{newest}")).status_code == 404
                client.cookies.set(setup.settings.session_cookie_name, admin_token)
                assert (await client.get("/v1/me/coaching")).json()["sandbox_reps"] == 0
                anonymous = (await client.get("/v1/me/coaching/team")).json()
                assert anonymous["scope"] == "anonymous" and "Nikhil" not in json.dumps(anonymous)
                # A role change takes effect at once.
                async with setup.sessions() as db, db.begin():
                    demote = update(Membership).where(Membership.person_id == owner)
                    await db.execute(demote.values(role="member"))
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                assert (await client.get(f"/v1/me/coaching/people/{rep}")).status_code == 404
        finally:
            await setup.engine.dispose()

    run(exercise())
