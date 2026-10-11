"""Private by default; one revocable share opens a rep's Coaching to owners/admins."""

from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError

from ac_platform.audit.models import AuditEvent
from ac_platform.coaching.models import (
    CoachingFeedback,
    CoachingLearnerContext,
    CoachingShareRevision,
)
from ac_platform.coaching.sharing_store import erase_coaching_context_for_person
from ac_platform.tenancy.models import Membership, Organisation
from tests.database.test_coaching_postgresql import draft_for, install
from tests.database.test_coaching_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_account_library_postgresql import _session
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_prospect_store_postgresql import direct_call

SHARING = "/v1/me/coaching/sharing"
TEAM = "/v1/me/coaching/team"
FEEDBACK = "/v1/me/coaching/feedback"
WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
JSON_ONLY = {"Content-Type": "application/json"}
CONTEXT = "/v1/me/coaching/context"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_personal_workspace_has_nobody_to_share_with(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        install(setup)
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                view = (await client.get(SHARING)).json()
                assert view == {"available": False, "shared": False, "revision": 0, "reaches": []}
                changed = await client.put(
                    SHARING, json={"shared": True, "expected_revision": 0}, headers=WRITE
                )
                assert changed.status_code == 409
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_share_reaches_admins_only_and_revocation_is_immediate(
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
                    .values(role="member")
                )
            install(setup, organisation=True)
            call = await direct_call(setup)
            await draft_for(setup, call)
            admin = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="admin")
            teammate = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            admin_token, teammate_token = (
                await _session(setup, admin),
                await _session(setup, teammate),
            )
            rep = str(setup.state.person_id)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:

                def as_(token: str) -> None:
                    client.cookies.set(setup.settings.session_cookie_name, token)

                as_(setup.token)
                before = (await client.get(SHARING)).json()
                assert before["available"] is True and before["shared"] is False
                assert before["revision"] == 0 and len(before["reaches"]) == 1
                own = (await client.get("/v1/me/coaching")).json()
                focus, origin = own["focus"]["skill_id"], own["mission"]["origin_submission_id"]

                # Private by default: org admin role alone never reads it.
                as_(admin_token)
                assert (await client.get(f"/v1/me/coaching/people/{rep}")).status_code == 404
                private = (await client.get(TEAM)).json()
                assert private["reps"] == [] and private["named_rep_details"] is False

                as_(setup.token)
                assert (
                    await client.put(
                        SHARING,
                        json={"shared": True, "expected_revision": 0},
                        headers={"Content-Type": "application/json"},
                    )
                ).status_code == 403  # writes need this Sales Xray page's Origin
                shared = await client.put(
                    SHARING, json={"shared": True, "expected_revision": 0}, headers=WRITE
                )
                assert shared.status_code == 200, shared.text
                assert shared.json()["shared"] is True and shared.json()["revision"] == 1
                # A stale retry of the same choice is harmless; a stale change conflicts.
                again = await client.put(
                    SHARING, json={"shared": True, "expected_revision": 0}, headers=WRITE
                )
                assert again.status_code == 200 and again.json()["revision"] == 1
                stale = await client.put(
                    SHARING, json={"shared": False, "expected_revision": 0}, headers=WRITE
                )
                assert stale.status_code == 409

                as_(admin_token)
                team = (await client.get(TEAM)).json()
                assert team["reps_basis"] == "shared" and team["named_rep_details"] is True
                assert [row["person_id"] for row in team["reps"]] == [rep]
                assert team["reps"][0]["shared_at"] and team["reps"][0]["calls"] == 1
                view = await client.get(f"/v1/me/coaching/people/{rep}")
                assert view.status_code == 200, view.text
                assert view.json()["person_id"] == rep and view.json()["person_name"]
                assert view.json()["mission"]["behavior"] == "Ask before presenting."

                # An ordinary teammate never reads it, shared or not.
                as_(teammate_token)
                assert (await client.get(f"/v1/me/coaching/people/{rep}")).status_code == 404
                assert (await client.get(TEAM)).status_code == 403

                as_(setup.token)
                stopped = await client.put(
                    SHARING, json={"shared": False, "expected_revision": 1}, headers=WRITE
                )
                assert stopped.status_code == 200 and stopped.json()["revision"] == 2
                as_(admin_token)
                assert (await client.get(f"/v1/me/coaching/people/{rep}")).status_code == 404
                assert (await client.get(TEAM)).json()["reps"] == []

                # Feedback: idempotent per command, own focus and own call only.
                as_(setup.token)
                command = str(uuid4())
                body = {
                    "command_id": command,
                    "agreement": "agree",
                    "focus_skill_id": focus,
                    "mission_origin_submission_id": origin,
                }
                assert (await client.post(FEEDBACK, json=body, headers=WRITE)).status_code == 204
                assert (await client.post(FEEDBACK, json=body, headers=WRITE)).status_code == 204
                changed = {**body, "agreement": "not_completely"}
                assert (await client.post(FEEDBACK, json=changed, headers=WRITE)).status_code == 409
                foreign = {
                    **body,
                    "command_id": str(uuid4()),
                    "mission_origin_submission_id": str(uuid4()),
                }
                assert (await client.post(FEEDBACK, json=foreign, headers=WRITE)).status_code == 409
                unknown = {**body, "command_id": str(uuid4()), "focus_skill_id": "made_up"}
                assert (await client.post(FEEDBACK, json=unknown, headers=WRITE)).status_code == 409

                # Add context: the learner's own words, shown back with the reason.
                note = {
                    "command_id": str(uuid4()),
                    "focus_skill_id": focus,
                    "mission_origin_submission_id": origin,
                    "context": "  ग्राहक was in a hurry; I skipped the impact question.  ",
                }
                assert (await client.post(CONTEXT, json=note, headers=WRITE)).status_code == 204
                assert (await client.post(CONTEXT, json=note, headers=WRITE)).status_code == 204
                rewritten = {**note, "context": "Something else"}
                assert (
                    await client.post(CONTEXT, json=rewritten, headers=WRITE)
                ).status_code == 409
                for bad in ({**note, "context": "   "}, {**note, "context": "x" * 1001}):
                    bad["command_id"] = str(uuid4())
                    assert (await client.post(CONTEXT, json=bad, headers=WRITE)).status_code == 422
                assert (
                    await client.post(
                        CONTEXT, json={**note, "command_id": str(uuid4())}, headers=JSON_ONLY
                    )
                ).status_code == 403  # writes need this Sales Xray page's Origin
                mine = (await client.get("/v1/me/coaching")).json()
                assert mine["root_cause"]["learner_context"] == (
                    "ग्राहक was in a hurry; I skipped the impact question."
                )

            async with setup.sessions() as db:
                revisions = (
                    await db.scalars(
                        select(CoachingShareRevision).order_by(CoachingShareRevision.revision)
                    )
                ).all()
                assert [row.shared for row in revisions] == [True, False]
                assert len((await db.scalars(select(CoachingFeedback))).all()) == 1
                events = (
                    await db.scalars(select(AuditEvent).where(AuditEvent.action.like("coaching.%")))
                ).all()
                assert sorted(event.action for event in events) == [
                    "coaching.context_added",
                    "coaching.feedback_recorded",
                    "coaching.share_changed",
                    "coaching.share_changed",
                ]
                assert all("Ask before presenting" not in str(e.payload) for e in events)
                assert all("hurry" not in str(e.payload) for e in events)
            # History is append-only: supersede, never rewrite.
            with pytest.raises(DBAPIError):
                async with setup.sessions() as db, db.begin():
                    await db.execute(text("UPDATE coaching_share_revisions SET shared = true"))
            # A note is never edited, but account erasure purges its text.
            with pytest.raises(DBAPIError):
                async with setup.sessions() as db, db.begin():
                    await db.execute(text("UPDATE coaching_learner_context SET context = 'x'"))
            async with setup.sessions() as db, db.begin():
                removed = await erase_coaching_context_for_person(
                    db, person_id=setup.state.person_id
                )
            assert removed == 1
            async with setup.sessions() as db:
                assert (await db.scalars(select(CoachingLearnerContext))).all() == []
        finally:
            await setup.engine.dispose()

    run(exercise())
