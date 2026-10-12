"""Person-entered call outcomes and the derived prospect deal stage (AUT-1677), via real routes.

Fictional calls only. Proves: unrecorded reads, append-only revisions,
idempotent repeats, stale-revision, moved-link and stage conflicts, refused
invalid, AI-shaped and deeply nested bodies, a quiet 403 for a call that is
not the person's, the stage derived from the most recent linked call (linking
an older call or correcting it never rolls the stage back), stage filters,
audit events and the history trigger.
"""

from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, text, update

from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence.prospect_call_outcome_models import (
    ConversationCallOutcomeRevision,
)
from ac_platform.tenancy.models import Membership, Organisation
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import _setup
from tests.database.test_prospect_library_postgresql import snapshot
from tests.database.test_prospect_profile_edit_postgresql import PREFIX, client_for, private
from tests.database.test_prospect_store_postgresql import direct_call


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def body(
    value: dict[str, Any],
    revision: int = 0,
    membership: str | None = None,
    stage: int | None = None,
) -> dict[str, Any]:
    return {
        "value": {"lost_reason": None, "follow_up_on": None, "deal_value": None, **value},
        "expected_revision": revision,
        "expected_membership_id": membership,
        "expected_prospect_stage_revision": stage,
    }


def test_outcomes_append_fence_derive_the_prospect_stage_and_keep_history(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        async with client_for(setup) as client:
            older = await direct_call(setup)
            await snapshot(setup, older)
            path = f"{PREFIX}/calls/{older}/outcome"

            # Unrecorded: revision 0, no value, never an inferred outcome.
            first = await client.get(path)
            private(first, 200)
            unrecorded = first.json()
            assert unrecorded["schema"] == "ac.sales-xray.call-outcome/1"
            assert unrecorded["revision"] == 0 and unrecorded["value"] is None
            assert unrecorded["basis"] is None and unrecorded["locked"] is False
            assert unrecorded["prospect_binding"] is None and unrecorded["can_edit"] is True

            # Not this person's call: a quiet 403 with a stable code.
            stranger = await client.get(f"{PREFIX}/calls/{uuid4()}/outcome")
            private(stranger, 403)
            assert stranger.json()["detail"] == "not_call_owner"

            # A person records "won" on an unlinked call.
            setup.clock[0] += timedelta(seconds=1)
            saved = await client.put(path, json=body({"outcome": "won"}))
            private(saved, 200)
            won = saved.json()
            assert won["revision"] == 1 and won["value"]["outcome"] == "won"
            assert won["basis"] == "person" and won["locked"] is True
            assert won["set_by_person_id"] == str(setup.state.actor.person_id)
            assert (await client.get(path)).json() == won

            # Repeating the current fact is a no-op; a stale revision conflicts.
            private(await client.put(path, json=body({"outcome": "won"}, 1)), 200)
            stale = await client.put(path, json=body({"outcome": "lost", "lost_reason": "x"}))
            private(stale, 409)

            # Invalid human values are refused before any write.
            private(await client.put(path, json=body({"outcome": "lost"}, 1)), 422)
            private(
                await client.put(path, json=body({"outcome": "won", "score": 0.9}, 1)),
                422,
            )
            private(
                await client.put(
                    path, content=b"[" * 4000, headers={"content-type": "application/json"}
                ),
                422,
            )
            private(await client.put(path, content=b"{}"), 415)

            # Link the call; the prospect's stage now derives from its outcome.
            created = await client.post(
                f"{PREFIX}/calls/{older}/create", json={"display_name": "Fictional Mehta"}
            )
            assert created.status_code == 201
            membership = created.json()["membership"]
            prospect_id = membership["prospect_id"]
            linked = (await client.get(path)).json()
            assert linked["prospect_binding"] == {
                "prospect_id": prospect_id,
                "membership_id": membership["membership_id"],
                "stage_revision": 1,
            }
            detail = f"{PREFIX}/{prospect_id}"
            assert (await client.get(detail)).json()["prospect"]["stage"] == "Won"

            # The old unlinked intent is now a conflict (the link moved).
            private(await client.put(path, json=body({"outcome": "no_decision"}, 1)), 409)

            setup.clock[0] += timedelta(seconds=1)
            follow = await client.put(
                path,
                json=body(
                    {
                        "outcome": "follow_up",
                        "follow_up_on": "2026-10-16",
                        "deal_value": {"amount": "200000", "currency_code": "INR"},
                    },
                    1,
                    membership["membership_id"],
                    1,
                ),
            )
            private(follow, 200)
            assert follow.json()["revision"] == 2
            assert follow.json()["prospect_binding"]["stage_revision"] == 2
            assert follow.json()["value"]["deal_value"] == {
                "amount": "200000",
                "currency_code": "INR",
            }
            assert (await client.get(detail)).json()["prospect"]["stage"] == "Follow-up Set"
            page = (await client.get(PREFIX)).json()
            assert page["stage_filters"] == ["Follow-up Set"]
            found = (await client.get(PREFIX, params={"stage": "Follow-up Set"})).json()
            assert [p["prospect_id"] for p in found["prospects"]] == [prospect_id]
            missing = (await client.get(PREFIX, params={"stage": "__missing__"})).json()
            assert missing["prospects"] == []

            # A stale stage revision is a conflict, not an overwrite.
            private(
                await client.put(
                    path, json=body({"outcome": "won"}, 2, membership["membership_id"], 0)
                ),
                409,
            )

            # A newer call, lost, linked to the same prospect: it sets the stage.
            setup.clock[0] += timedelta(minutes=10)
            newer = await direct_call(setup)
            await snapshot(setup, newer)
            newer_path = f"{PREFIX}/calls/{newer}/outcome"
            private(
                await client.put(
                    newer_path, json=body({"outcome": "lost", "lost_reason": "Budget frozen"})
                ),
                200,
            )
            confirmed = await client.post(
                f"{PREFIX}/calls/{newer}/confirm",
                json={"prospect_id": prospect_id, "expected_membership_id": None},
            )
            assert confirmed.status_code == 200, confirmed.text
            assert (await client.get(detail)).json()["prospect"]["stage"] == "Lost"

            # Correcting the older call never rolls the stage back.
            current = (await client.get(path)).json()
            assert current["prospect_binding"]["stage_revision"] == 3
            setup.clock[0] += timedelta(seconds=1)
            private(
                await client.put(
                    path, json=body({"outcome": "won"}, 2, membership["membership_id"], 3)
                ),
                200,
            )
            assert (await client.get(detail)).json()["prospect"]["stage"] == "Lost"

        async with setup.sessions() as db:
            outcomes = (
                await db.scalars(
                    select(ConversationCallOutcomeRevision).order_by(
                        ConversationCallOutcomeRevision.created_at
                    )
                )
            ).all()
            assert [(o.submission_id, o.revision, o.outcome) for o in outcomes] == [
                (older, 1, "won"),
                (older, 2, "follow_up"),
                (newer, 1, "lost"),
                (older, 3, "won"),
            ]
            assert outcomes[0].prospect_id is None
            assert outcomes[1].prospect_id == UUID(prospect_id)
            actions = [
                e.action
                for e in (await db.scalars(select(AuditEvent).order_by(AuditEvent.id))).all()
            ]
            assert actions.count("conversation.call_outcome_set") == 4
            # Won → Follow-up Set on the linked call; the older-call correction changed nothing.
            assert actions.count("conversation.prospect_stage_changed") == 1

        # History is append-only in the database itself.
        for statement in (
            "UPDATE conversation_call_outcome_revisions SET revision = revision",
            "DELETE FROM conversation_call_outcome_revisions",
        ):
            async with setup.sessions() as db:
                with pytest.raises(Exception, match="preserve history"):
                    async with db.begin():
                        await db.execute(text(statement))

    run(exercise())


def test_organisation_admins_read_a_teammates_outcome_read_only(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """The rep records; an owner or admin of the organisation sees it with can_edit false."""

    from tests.database.test_coaching_postgresql import install
    from tests.database.test_conversation_account_library_postgresql import _session
    from tests.database.test_conversation_postgresql import seed as seed_person
    from tests.database.test_conversation_submission_http_postgresql import ORIGIN

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
            await snapshot(setup, call)
            path = f"{PREFIX}/calls/{call}/outcome"
            admin = await seed_person(setup.engine, tenant_id=setup.state.tenant_id, role="admin")
            member = await seed_person(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            admin_token, member_token = await _session(setup, admin), await _session(setup, member)
            async with client_for(setup) as rep:
                setup.clock[0] += timedelta(seconds=1)
                private(
                    await rep.put(path, json=body({"outcome": "lost", "lost_reason": "Budget"})),
                    200,
                )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, admin_token)
                seen = await client.get(path)
                private(seen, 200)
                view = seen.json()
                assert view["value"] == {
                    "outcome": "lost",
                    "lost_reason": "Budget",
                    "follow_up_on": None,
                    "deal_value": None,
                }
                assert view["basis"] == "person" and view["locked"] is True
                assert view["set_by_person_id"] == str(setup.state.actor.person_id)
                assert view["can_edit"] is False
                # Reading never grants recording: the admin's save is refused untouched.
                refused = await client.put(
                    path, json=body({"outcome": "won"}, 1), headers={"Origin": ORIGIN}
                )
                private(refused, 403)
                assert refused.json()["detail"] == "not_call_owner"
                # A plain teammate still sees nothing to record.
                client.cookies.set(setup.settings.session_cookie_name, member_token)
                hidden = await client.get(path)
                private(hidden, 403)
                assert hidden.json()["detail"] == "not_call_owner"
            async with setup.sessions() as db:
                rows = (
                    await db.scalars(
                        select(ConversationCallOutcomeRevision).where(
                            ConversationCallOutcomeRevision.submission_id == call
                        )
                    )
                ).all()
                assert [row.revision for row in rows] == [1]
        finally:
            await setup.engine.dispose()

    run(exercise())
