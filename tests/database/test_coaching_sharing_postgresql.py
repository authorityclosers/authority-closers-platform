"""Private by default; one revocable share opens a rep's Coaching to owners/admins."""

import asyncio
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

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
from ac_platform.coaching.sharing_store import (
    erase_coaching_context_for_person,
    record_context,
    record_feedback,
)
from ac_platform.conversation_intelligence.application import ConversationConflict
from ac_platform.conversation_intelligence.sensitive_segments_store import SensitiveSegmentsStore
from ac_platform.tenancy.models import Membership, Organisation
from tests.database import test_prospect_store_postgresql as call_fixtures
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
                # The admin reads about the rep: "their calls", not "your calls".
                assert "reading of their calls" in view.json()["limitations"][0]

                # An ordinary teammate never reads it, shared or not.
                as_(teammate_token)
                assert (await client.get(f"/v1/me/coaching/people/{rep}")).status_code == 404
                assert (await client.get(TEAM)).status_code == 403

                as_(setup.token)
                # Two tabs stop sharing at once: one revision, no deadlock.
                stops = await asyncio.gather(
                    *(
                        client.put(
                            SHARING, json={"shared": False, "expected_revision": 1}, headers=WRITE
                        )
                        for _ in range(2)
                    )
                )
                assert [r.status_code for r in stops] == [200, 200], [r.text for r in stops]
                assert {r.json()["revision"] for r in stops} == {2}
                as_(admin_token)
                assert (await client.get(f"/v1/me/coaching/people/{rep}")).status_code == 404
                assert (await client.get(TEAM)).json()["reps"] == []

                # Consent does not survive a membership change (removal and
                # re-adding, or a new role): coaching is private until shared again.
                as_(setup.token)
                again = await client.put(
                    SHARING, json={"shared": True, "expected_revision": 2}, headers=WRITE
                )
                assert again.status_code == 200 and again.json()["shared"] is True
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(Membership)
                        .where(Membership.person_id == setup.state.person_id)
                        .values(revision=Membership.revision + 1)
                    )
                assert (await client.get(SHARING)).json()["shared"] is False
                as_(admin_token)
                assert (await client.get(f"/v1/me/coaching/people/{rep}")).status_code == 404
                assert (await client.get(TEAM)).json()["reps"] == []
                as_(setup.token)
                renewed = await client.put(
                    SHARING, json={"shared": True, "expected_revision": 3}, headers=WRITE
                )
                assert renewed.status_code == 200 and renewed.json()["revision"] == 4
                as_(admin_token)
                assert (await client.get(f"/v1/me/coaching/people/{rep}")).status_code == 200
                as_(setup.token)
                assert (
                    await client.put(
                        SHARING, json={"shared": False, "expected_revision": 4}, headers=WRITE
                    )
                ).status_code == 200

                # Feedback: idempotent per command, own focus and own call only.
                as_(setup.token)
                command = str(uuid4())
                body = {
                    "command_id": command,
                    "agreement": "agree",
                    "focus_skill_id": focus,
                    "mission_origin_submission_id": origin,
                }
                # A repeat of the same command, even at the same moment, is one answer.
                repeats = await asyncio.gather(
                    *(client.post(FEEDBACK, json=body, headers=WRITE) for _ in range(2))
                )
                assert [r.status_code for r in repeats] == [204, 204], [r.text for r in repeats]
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
                assert [row.shared for row in revisions] == [True, False, True, True, False]
                assert len((await db.scalars(select(CoachingFeedback))).all()) == 1
                events = (
                    await db.scalars(select(AuditEvent).where(AuditEvent.action.like("coaching.%")))
                ).all()
                assert sorted(event.action for event in events) == [
                    "coaching.context_added",
                    "coaching.feedback_recorded",
                    *["coaching.share_changed"] * 5,
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


async def _withhold(setup: Any, recording_id: Any, revision: str, key: str) -> None:
    """Mark the fictional call's only line sensitive: still owned, no coaching."""
    async with setup.sessions() as db, db.begin():
        await SensitiveSegmentsStore(db).mark(
            setup.state.actor,
            recording_id=recording_id,
            transcript_revision=revision,
            segments=[("s1", "SENSITIVE_FINANCIAL")],
            reason_ref="AUT-1678",
            idempotency_key=key,
        )


def test_feedback_names_the_current_focus_and_a_retry_survives_its_change(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CTO f70dc356 scenarios 1-6 through the handler, on two fictional calls."""

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        install(setup)
        try:
            first = await direct_call(setup)
            first_recording, first_revision = await draft_for(setup, first)
            audio = call_fixtures._wav_one_second_48k()
            # A second fictional source: one sample differs, so it is another call.
            with monkeypatch.context() as patch:
                patch.setattr(
                    call_fixtures, "_wav_one_second_48k", lambda: audio[:-2] + b"\x01\x00"
                )
                second = await direct_call(setup)
            second_recording, second_revision = await draft_for(
                setup, second, line="Fictional line: the buyer asks about the delivery date."
            )
            recordings = {
                str(first): (first_recording, first_revision),
                str(second): (second_recording, second_revision),
            }
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                # Authenticate first: a signed-out write is 401 whatever its body.
                for path in (FEEDBACK, CONTEXT):
                    for headers, content in (
                        (WRITE, b"{"),
                        ({"Origin": ORIGIN, "Content-Type": "text/plain"}, b"x"),
                        (WRITE, b"x" * 5000),
                    ):
                        signed_out = await client.post(path, content=content, headers=headers)
                        assert signed_out.status_code == 401, (path, signed_out.text)

                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                own = (await client.get("/v1/me/coaching")).json()
                assert len(own["calls"]) == 2
                focus, origin = own["focus"]["skill_id"], own["mission"]["origin_submission_id"]
                stale = next(call for call in recordings if call != origin)
                valid = {
                    "command_id": str(uuid4()),
                    "agreement": "agree",
                    "focus_skill_id": focus,
                    "mission_origin_submission_id": origin,
                }

                async def post(body: dict[str, str]) -> int:
                    return (await client.post(FEEDBACK, json=body, headers=WRITE)).status_code

                # (1) a different supported skill on the current mission.
                assert (
                    await post(
                        {**valid, "command_id": str(uuid4()), "focus_skill_id": "qualification"}
                    )
                    == 409
                )
                # (2) the learner's other, still-owned call is not the mission's origin.
                assert (
                    await post(
                        {**valid, "command_id": str(uuid4()), "mission_origin_submission_id": stale}
                    )
                    == 409
                )
                # (4) the current pair is accepted.
                assert await post(valid) == 204

                # The focus advances: the origin call's line becomes sensitive.
                await _withhold(setup, *recordings[origin], "fictional-advance")
                moved = (await client.get("/v1/me/coaching")).json()
                assert moved["mission"]["origin_submission_id"] == stale
                # (5) the identical command still answers 204, without another append.
                assert await post(valid) == 204
                # (6) an altered retry conflicts, even when it names the new focus.
                assert await post({**valid, "agreement": "not_completely"}) == 409
                assert await post({**valid, "mission_origin_submission_id": stale}) == 409
                # (2) again: the old, still-owned origin is now stale for a new command.
                assert await post({**valid, "command_id": str(uuid4())}) == 409
                # Context notes follow the same rule.
                note = {
                    "command_id": str(uuid4()),
                    "focus_skill_id": focus,
                    "mission_origin_submission_id": origin,
                    "context": "Fictional: the buyer had to leave early.",
                }
                assert (await client.post(CONTEXT, json=note, headers=WRITE)).status_code == 409
                current_note = {**note, "mission_origin_submission_id": stale}
                assert (
                    await client.post(CONTEXT, json=current_note, headers=WRITE)
                ).status_code == 204

                # (3) no current pair: both calls withheld, both still owned.
                await _withhold(setup, *recordings[stale], "fictional-none")
                empty = (await client.get("/v1/me/coaching")).json()
                assert empty["focus"] is None and len(empty["calls"]) == 2
                for owned in (origin, stale):
                    body = {
                        **valid,
                        "command_id": str(uuid4()),
                        "mission_origin_submission_id": owned,
                    }
                    assert await post(body) == 409
                assert await post(valid) == 204  # the recorded command still retries
                assert (
                    await client.post(CONTEXT, json=current_note, headers=WRITE)
                ).status_code == 204

            async with setup.sessions() as db:
                feedback = (await db.scalars(select(CoachingFeedback))).all()
                assert [(row.command_id, row.agreement) for row in feedback] == [
                    (UUID(valid["command_id"]), "agree")
                ]
                assert len((await db.scalars(select(CoachingLearnerContext))).all()) == 1
                actions = (
                    await db.scalars(
                        select(AuditEvent.action).where(AuditEvent.action.like("coaching.%"))
                    )
                ).all()
                assert sorted(actions) == ["coaching.context_added", "coaching.feedback_recorded"]
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_storage_checks_the_current_pair_before_any_append(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """The same rules at the storage boundary: nothing is appended on a conflict."""

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        actor, tenant = setup.state.actor, setup.state.tenant_id
        origin, other_origin = uuid4(), uuid4()
        asked: list[str] = []

        def current(pair: tuple[str, Any] | None) -> Any:
            async def read() -> tuple[str, Any] | None:
                asked.append("current")
                return pair

            return read

        async def never() -> None:
            raise AssertionError("a retry must not need the current focus")

        async def feedback(
            command: Any,
            focus: Any,
            *,
            skill: str = "qualification",
            where: Any = origin,
            agreement: Any = "agree",
        ) -> None:
            async with setup.sessions() as db, db.begin():
                await record_feedback(
                    db,
                    actor=actor,
                    tenant_id=tenant,
                    command_id=command,
                    agreement=agreement,
                    focus_skill_id=skill,
                    mission_origin_submission_id=where,
                    current_focus=focus,
                )

        async def context(
            command: Any, focus: Any, *, where: Any = origin, text: str = "Fictional note."
        ) -> None:
            async with setup.sessions() as db, db.begin():
                await record_context(
                    db,
                    actor=actor,
                    tenant_id=tenant,
                    command_id=command,
                    focus_skill_id="qualification",
                    mission_origin_submission_id=where,
                    context=text,
                    current_focus=focus,
                )

        async def appended() -> tuple[int, int, int]:
            async with setup.sessions() as db:
                return (
                    len((await db.scalars(select(CoachingFeedback))).all()),
                    len((await db.scalars(select(CoachingLearnerContext))).all()),
                    len(
                        (
                            await db.scalars(
                                select(AuditEvent).where(AuditEvent.action.like("coaching.%"))
                            )
                        ).all()
                    ),
                )

        try:
            command = uuid4()
            for mismatch in (
                None,  # (3) no current pair
                ("problem_impact_desire", origin),  # (1) another supported skill
                ("qualification", other_origin),  # (2) a stale origin
            ):
                with pytest.raises(ConversationConflict, match="Your focus changed"):
                    await feedback(command, current(mismatch))
                with pytest.raises(ConversationConflict, match="Your focus changed"):
                    await context(command, current(mismatch))
                assert await appended() == (0, 0, 0)
            # (4) the current pair is recorded once, with one audit event each.
            await feedback(command, current(("qualification", origin)))
            await context(command, current(("qualification", origin)))
            assert await appended() == (1, 1, 2)
            asked.clear()
            # (5) identical retries never ask for the (since moved) focus.
            await feedback(command, never)
            await context(command, never)
            assert asked == [] and await appended() == (1, 1, 2)
            # (6) altered retries conflict, even naming a now-current pair.
            for altered in (
                feedback(command, never, agreement="not_completely"),
                feedback(command, never, where=other_origin),
                context(command, never, text="Another note."),
            ):
                with pytest.raises(ConversationConflict, match="differently"):
                    await altered
            assert await appended() == (1, 1, 2)
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_concurrent_commands_append_once_and_keep_notes_out_of_audit(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """Racing copies of one command: one row and one audit event, never two.

    Every copy passes the "already recorded?" read before any inserts (a
    barrier inside the current-focus check), so the unique command index is
    what decides. A changed copy racing the original conflicts.
    """

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        actor, tenant = setup.state.actor, setup.state.tenant_id
        origin = uuid4()
        note_text = "Fictional: the buyer's finance lead joined late."

        def racing(copies: int) -> Any:
            barrier = asyncio.Barrier(copies)

            async def read() -> tuple[str, Any]:
                await barrier.wait()
                return ("qualification", origin)

            return read

        async def feedback(command: Any, focus: Any, agreement: Any = "agree") -> str:
            try:
                async with setup.sessions() as db, db.begin():
                    await record_feedback(
                        db,
                        actor=actor,
                        tenant_id=tenant,
                        command_id=command,
                        agreement=agreement,
                        focus_skill_id="qualification",
                        mission_origin_submission_id=origin,
                        current_focus=focus,
                    )
            except ConversationConflict:
                return "conflict"
            return "ok"

        async def context(command: Any, focus: Any) -> str:
            async with setup.sessions() as db, db.begin():
                await record_context(
                    db,
                    actor=actor,
                    tenant_id=tenant,
                    command_id=command,
                    focus_skill_id="qualification",
                    mission_origin_submission_id=origin,
                    context=note_text,
                    current_focus=focus,
                )
            return "ok"

        try:
            same_feedback, same_note = uuid4(), uuid4()
            focus = racing(3)
            assert await asyncio.gather(*(feedback(same_feedback, focus) for _ in range(3))) == [
                "ok",
                "ok",
                "ok",
            ]
            focus = racing(3)
            assert await asyncio.gather(*(context(same_note, focus) for _ in range(3))) == [
                "ok",
                "ok",
                "ok",
            ]
            # The original and a changed copy race: one lands, the other conflicts.
            changed, focus = uuid4(), racing(2)
            outcomes = await asyncio.gather(
                feedback(changed, focus), feedback(changed, focus, "not_completely")
            )
            assert sorted(outcomes) == ["conflict", "ok"]
            async with setup.sessions() as db:
                feedback_rows = (await db.scalars(select(CoachingFeedback))).all()
                assert sorted(row.command_id for row in feedback_rows) == sorted(
                    [same_feedback, changed]
                )
                notes = (await db.scalars(select(CoachingLearnerContext))).all()
                assert [row.command_id for row in notes] == [same_note]
                events = (
                    await db.scalars(select(AuditEvent).where(AuditEvent.action.like("coaching.%")))
                ).all()
                assert sorted((event.action, event.resource_id) for event in events) == sorted(
                    [
                        ("coaching.feedback_recorded", str(same_feedback)),
                        ("coaching.feedback_recorded", str(changed)),
                        ("coaching.context_added", str(same_note)),
                    ]
                )
                # The note itself is never copied into the audit trail.
                added = next(e for e in events if e.action == "coaching.context_added")
                assert added.payload == {"length": len(note_text)}
                assert all("finance lead" not in str(event.payload) for event in events)
        finally:
            await setup.engine.dispose()

    run(exercise())
