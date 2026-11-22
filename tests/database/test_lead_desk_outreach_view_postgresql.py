"""The Outreach view, "what the owner sent" (v1.95.3, owner 22 Nov 2026; spec §5;
GET /v1/lead-desk/outreach), through HTTP on PostgreSQL: by lead and by message, the hero, what
each lead received in order, the filters (who, channel, dates, over a limit), paging with the
cursor, the roles (managers and viewers see the team, a seller only their own with the filter
locked, finance nothing) and tenancy (another workspace's touches never show). Fictional people
only."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest

from ac_platform.lead_desk.models import Lead, LeadTouch
from ac_platform.tenancy.models import Organisation
from tests.database.test_conversation_account_library_postgresql import _session
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
BASE = "/v1/lead-desk"
ALL_DAY = {"days": [0, 1, 2, 3, 4, 5, 6], "start": "00:00", "end": "23:59"}


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_the_outreach_view_by_lead_and_message_roles_paging_and_tenancy(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            tenant, admin = setup.state.tenant_id, setup.state.person_id
            seller = await seed(setup.engine, tenant_id=tenant, role="member")
            viewer = await seed(setup.engine, tenant_id=tenant, role="viewer")
            finance = await seed(setup.engine, tenant_id=tenant, role="finance")
            tokens = {
                "seller": await _session(setup, seller),
                "viewer": await _session(setup, viewer),
                "finance": await _session(setup, finance),
                "admin": setup.token,
            }
            # Another workspace with a lead and a touch of its own.
            stranger = await seed(setup.engine)
            now = datetime.now(UTC)
            async with setup.sessions() as db, db.begin():
                db.add(
                    Organisation(
                        tenant_id=stranger.tenant_id,
                        created_by_person_id=stranger.person_id,
                        creation_command_id=uuid4(),
                        domain_verification_token=uuid4().hex + uuid4().hex,
                    )
                )
                their_lead = Lead(
                    id=uuid4(),
                    tenant_id=stranger.tenant_id,
                    revision=1,
                    source="manual",
                    payload={},
                    name="Their Fictional Lead",
                    stage="new",
                    attempts=0,
                    calls=0,
                    repeats=0,
                    test_data=False,
                    created_at=now,
                    updated_at=now,
                )
                db.add(their_lead)
                await db.flush()
                db.add(
                    LeadTouch(
                        id=uuid4(),
                        tenant_id=stranger.tenant_id,
                        lead_id=their_lead.id,
                        channel="whatsapp",
                        content_kind="text",
                        initiated="outreach",
                        sender_type="automation",
                        automation="drip",
                        via="cloud",
                        status="sent",
                        sent_at=now,
                        counted=True,
                        guard={"verdict": "block"},
                        created_at=now,
                        updated_at=now,
                    )
                )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:

                def as_(who: str) -> None:
                    client.cookies.set(setup.settings.session_cookie_name, tokens[who])

                async def post(path: str, body: dict[str, Any], status: int = 200) -> Any:
                    answer = await client.post(f"{BASE}{path}", json=body, headers=WRITE)
                    assert answer.status_code == status, answer.text
                    return answer.json()

                async def view(status: int = 200, **params: Any) -> Any:
                    answer = await client.get(f"{BASE}/outreach", params=params)
                    assert answer.status_code == status, answer.text
                    return answer.json()

                as_("admin")
                rules = (await client.get(f"{BASE}/outreach/rules")).json()
                answer = await client.put(
                    f"{BASE}/outreach/rules",
                    json={"expected_revision": rules["revision"], "quiet": ALL_DAY},
                    headers=WRITE,
                )
                assert answer.status_code == 200, answer.text
                # The admin adds three leads and messages each; one also gets an email.
                mine = []
                for index in range(3):
                    added = await post(
                        "/leads",
                        {
                            "command_id": str(uuid4()),
                            "name": f"View Fictional {index}",
                            "phone": f"98760 1100{index}",
                            "assign": "me",
                        },
                        201,
                    )
                    lead_id = added["lead"]["lead_id"]
                    mine.append(lead_id)
                    await post(
                        f"/leads/{lead_id}/messages",
                        {"command_id": str(uuid4()), "channel": "whatsapp"},
                    )
                await post(
                    f"/leads/{mine[0]}/touches",
                    {"command_id": str(uuid4()), "channel": "email", "summary": "Sent the deck"},
                    201,
                )
                # The seller adds two leads and messages one.
                as_("seller")
                theirs = []
                for index in range(2):
                    added = await post(
                        "/leads",
                        {
                            "command_id": str(uuid4()),
                            "name": f"Seller Fictional {index}",
                            "phone": f"98760 2200{index}",
                        },
                        201,
                    )
                    theirs.append(added["lead"]["lead_id"])
                await post(
                    f"/leads/{theirs[0]}/messages",
                    {"command_id": str(uuid4()), "channel": "whatsapp"},
                )

                # A seller: their own, the filter locked to them; another's is refused.
                own = await view()
                assert own["filter"]["locked_to_self"] is True
                assert own["filter"]["by"] == f"person:{seller.person_id}"
                assert own["hero"]["touches"] == 1 and own["hero"]["leads_added"] == 2
                assert {row["lead_id"] for row in own["leads"]} == set(theirs)
                untouched = next(row for row in own["leads"] if row["lead_id"] == theirs[1])
                assert (untouched["touches"], untouched["received"]) == (0, [])
                assert untouched["added_by_person_id"] == str(seller.person_id)
                assert len((await view(view="touches"))["touches"]) == 1
                await view(403, by=f"person:{admin}")
                assert (await view(by="person:me"))["hero"]["touches"] == 1

                # The team: every touch in this workspace, never another's.
                as_("admin")
                team = await view(view="touches")
                assert team["filter"]["locked_to_self"] is False
                assert len(team["touches"]) == team["hero"]["touches"] == 5
                # Whose message it was: each touch names its lead.
                assert {t["lead_name"] for t in team["touches"]} == {
                    "View Fictional 0",
                    "View Fictional 1",
                    "View Fictional 2",
                    "Seller Fictional 0",
                }
                assert team["hero"]["leads"] == 4
                assert team["hero"]["period"] == "Last 7 days"
                assert team["hero"]["words"] == "5 touches · 4 leads · 0 replied"
                assert all(t["lead_id"] != str(their_lead.id) for t in team["touches"])
                assert (await view(view="touches", by=f"person:{stranger.person_id}"))[
                    "touches"
                ] == []
                assert (await view(view="touches", by="automation:drip"))["touches"] == []
                # The admin's leads, each with what it received, oldest first.
                by_admin = await view(by=f"person:{admin}")
                assert {row["lead_id"] for row in by_admin["leads"]} == set(mine)
                first = next(row for row in by_admin["leads"] if row["lead_id"] == mine[0])
                assert [t["channel"] for t in first["received"]] == ["whatsapp", "email"]
                assert first["touches"] == 2 and first["added_by_name"]
                assert by_admin["hero"]["leads_added"] == 3
                # Filters: channel, and the touch sent past a limit (the email the same day).
                assert len((await view(view="touches", channel="email"))["touches"]) == 1
                over = await view(view="touches", over="true")
                assert [t["channel"] for t in over["touches"]] == ["email"]
                assert over["hero"]["sentence"] == "1 was sent past a limit."
                assert (await view(view="touches", replied="replied"))["touches"] == []
                old = await view(view="touches", **{"from": "2026-01-01", "to": "2026-01-31"})
                assert old["touches"] == [] and old["hero"]["touches"] == 0
                await view(422, **{"from": "2026-01-01", "to": "2026-12-31"})
                await view(422, by="nobody")
                await view(422, channel="fax")

                # Paging: by message and by lead, the cursor to the end.
                seen: list[str] = []
                cursor: str | None = None
                for _ in range(5):
                    params: dict[str, Any] = {"view": "touches", "limit": 2}
                    if cursor:
                        params["cursor"] = cursor
                    page = await view(**params)
                    seen += [t["touch_id"] for t in page["touches"]]
                    cursor = page["next_cursor"]
                    if cursor is None:
                        break
                assert seen == [t["touch_id"] for t in team["touches"]]
                assert len(set(seen)) == 5
                leads_seen: list[str] = []
                cursor = None
                for _ in range(5):
                    params = {"limit": 3}
                    if cursor:
                        params["cursor"] = cursor
                    page = await view(**params)
                    leads_seen += [row["lead_id"] for row in page["leads"]]
                    cursor = page["next_cursor"]
                    if cursor is None:
                        break
                assert sorted(leads_seen) == sorted([*mine, theirs[0]])
                assert len(set(leads_seen)) == 4

                # A viewer reads the team; finance has no entry.
                as_("viewer")
                assert (await view(view="touches"))["hero"]["touches"] == 5
                as_("finance")
                await view(403)
        finally:
            await setup.engine.dispose()

    run(asyncio.wait_for(exercise(), timeout=240))
