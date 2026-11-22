"""The outreach log in the app (v1.95, owner 22 Nov 2026: "every person we contact is a lead,
every message we send them is tracked, so we never feel spammy"; lead_desk/outreach.py), through
the HTTP API on PostgreSQL: a ready message and a call become touches on the lead's timeline
(the timeline merge), the counter on the lead page, Lead rules › Outreach limits (revision,
managers only, audit), a block refusing a send, a manager's audited "send anyway" used once, a
STOP that nothing passes, Log a touch, the touch list, the bulk counts, a seller's own leads
only, a merge carrying touches and a delete removing them. Fictional people only."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain
from ac_platform.lead_desk.models import Lead, LeadTouch, LeadTouchOverride
from ac_platform.lead_desk.store import LeadDesk, Viewer
from tests.database.test_conversation_account_library_postgresql import _session
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _admin_sells, _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
BASE = "/v1/lead-desk"
ALL_DAY = {"days": [0, 1, 2, 3, 4, 5, 6], "start": "00:00", "end": "23:59"}


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


async def _audits(setup: Any, action: str) -> list[AuditEvent]:
    async with setup.sessions() as db:
        rows = await db.scalars(
            select(AuditEvent)
            .where(AuditEvent.tenant_id == setup.state.tenant_id, AuditEvent.action == action)
            .order_by(AuditEvent.sequence_no)
        )
        return list(rows.all())


def test_touches_counter_rules_overrides_and_stop_in_the_app(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            await _admin_sells(setup)
            tenant = setup.state.tenant_id
            seller = await seed(setup.engine, tenant_id=tenant, role="member")
            seller_token = await _session(setup, seller)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:

                def as_(token: str) -> None:
                    client.cookies.set(setup.settings.session_cookie_name, token)

                async def post(path: str, body: dict[str, Any], status: int = 200) -> Any:
                    answer = await client.post(f"{BASE}{path}", json=body, headers=WRITE)
                    assert answer.status_code == status, answer.text
                    return answer.json()

                async def put(path: str, body: dict[str, Any], status: int = 200) -> Any:
                    answer = await client.put(f"{BASE}{path}", json=body, headers=WRITE)
                    assert answer.status_code == status, answer.text
                    return answer.json()

                async def get(path: str, status: int = 200) -> Any:
                    answer = await client.get(f"{BASE}{path}")
                    assert answer.status_code == status, answer.text
                    return answer.json()

                async def message(lead_id: str, status: int = 200) -> Any:
                    return await post(
                        f"/leads/{lead_id}/messages",
                        {"command_id": str(uuid4()), "channel": "whatsapp"},
                        status,
                    )

                as_(setup.token)
                ids: list[str] = []
                for index in range(3):
                    added = await post(
                        "/leads",
                        {
                            "command_id": str(uuid4()),
                            "name": f"Outreach Fictional {index}",
                            "phone": f"98765 4321{index}",
                        },
                        201,
                    )
                    ids.append(added["lead"]["lead_id"])
                one, two, three = ids

                # Lead rules › Outreach limits: read by all, saved by managers with a revision.
                rules = await get("/outreach/rules")
                assert (rules["per_day"], rules["per_week"], rules["rest_after"]) == (1, 3, 3)
                assert rules["modes"]["whatsapp"] == {"people": "warn", "automations": "block"}
                assert rules["modes"]["call"] == {"people": "show", "automations": "show"}
                assert rules["hours_in_use"] == {
                    "days": [0, 1, 2, 3, 4, 5],
                    "start": "10:00",
                    "end": "20:00",
                }
                saved = await put(
                    "/outreach/rules",
                    {"expected_revision": rules["revision"], "quiet": ALL_DAY},
                )
                assert saved["revision"] == rules["revision"] + 1
                assert saved["quiet"]["days"] == ALL_DAY["days"]
                await put(
                    "/outreach/rules",
                    {"expected_revision": rules["revision"], "per_day": 2},
                    409,
                )
                changed = await _audits(setup, "lead_desk.outreach.settings_changed")
                assert [event.payload["fields"] for event in changed] == [["quiet"]]

                # Not contacted yet, then a ready message: a touch on the timeline line.
                detail = await get(f"/leads/{one}")
                assert detail["outreach"]["words"] == "Not contacted yet"
                assert detail["outreach"]["verdict"] == "ok"
                sent = await message(one)
                (line,) = [event for event in sent["events"] if event["kind"] == "message"]
                touch = line["touch"]
                assert (touch["channel"], touch["via"], touch["status"]) == (
                    "whatsapp",
                    "app_link",
                    "opened",
                )
                assert touch["sender_type"] == "person" and touch["counted"] is True
                assert touch["by_name"] == line["actor_name"]
                assert sent["outreach"]["counts"]["today"] == 1
                assert sent["outreach"]["words"].startswith("Touched today at ")
                assert sent["outreach"]["words"].endswith("· 1 touch this week")
                # The second one today: people are warned, never stopped (WhatsApp, warn).
                warned = await get(f"/leads/{one}/outreach?channel=whatsapp")
                assert warned["verdict"] == "warn"
                assert "day_cap" in {reason["code"] for reason in warned["reasons"]}
                await message(one)

                # A block mode refuses the send; a manager's "send anyway" passes it once.
                current = await get("/outreach/rules")
                await put(
                    "/outreach/rules",
                    {
                        "expected_revision": current["revision"],
                        "modes": {"whatsapp": {"people": "block", "automations": "block"}},
                    },
                )
                refused = await client.post(
                    f"{BASE}/leads/{one}/messages",
                    json={"command_id": str(uuid4()), "channel": "whatsapp"},
                    headers=WRITE,
                )
                assert refused.status_code == 409, refused.text
                assert "outreach limits" in refused.json()["detail"]
                override = await post(
                    f"/leads/{one}/overrides",
                    {
                        "command_id": str(uuid4()),
                        "channel": "whatsapp",
                        "reason_key": "lead_asked",
                    },
                    201,
                )
                assert override["guard"]["verdict"] == "ok"
                assert override["guard"]["override_id"] == override["override_id"]
                anyway = await message(one)
                lines = [event for event in anyway["events"] if event["kind"] == "message"]
                newest = lines[0]["touch"]
                assert newest["override_by_name"] == lines[0]["actor_name"]
                assert newest["override_reason"] == "lead asked for it"
                await message(one, 409)  # used once
                granted = await _audits(setup, "lead_desk.outreach.override_granted")
                assert len(granted) == 1
                assert granted[0].payload["reason_key"] == "lead_asked"
                assert granted[0].payload["lead_id"] == one
                used = await _audits(setup, "lead_desk.outreach.override_used")
                assert [event.resource_id for event in used] == [override["override_id"]]
                await post(
                    f"/leads/{one}/overrides",
                    {
                        "command_id": str(uuid4()),
                        "channel": "whatsapp",
                        "reason_key": "other",
                    },
                    422,
                )

                # Log a touch: an email from Gmail; the same command again is that touch.
                command = str(uuid4())
                logged = await post(
                    f"/leads/{two}/touches",
                    {
                        "command_id": command,
                        "channel": "email",
                        "summary": "Sent the price list",
                    },
                    201,
                )
                assert logged["touch"]["channel"] == "email"
                assert logged["touch"]["summary"] == "Sent the price list"
                again = await post(
                    f"/leads/{two}/touches",
                    {"command_id": command, "channel": "email", "summary": "Sent the price list"},
                    201,
                )
                assert again["touch"]["touch_id"] == logged["touch"]["touch_id"]
                detail = await get(f"/leads/{two}")
                emails = [event for event in detail["events"] if event["kind"] == "email"]
                assert emails[0]["touch"]["touch_id"] == logged["touch"]["touch_id"]
                # A call from the app is a touch too: shown, not counted.
                called = await post(
                    f"/leads/{two}/calls/phone",
                    {"command_id": str(uuid4()), "duration_seconds": 40},
                )
                calls = [event for event in called["events"] if event["kind"] == "call"]
                assert calls[0]["touch"]["channel"] == "call"
                assert calls[0]["touch"]["counted"] is False
                assert called["outreach"]["counts"]["calls_week"] == 1
                assert called["outreach"]["words"].endswith("· 1 call")
                page = await get(f"/leads/{one}/touches")
                assert {t["lead_name"] for t in page["touches"]} == {"Outreach Fictional 0"}
                assert len(page["touches"]) == 3
                assert page["touches"][0]["override_by_name"] is not None

                # A STOP blocks WhatsApp, and nobody can send anyway.
                async with setup.sessions() as db, db.begin():
                    lead = await db.get(Lead, UUID(three))
                    assert lead is not None
                    desk = LeadDesk(
                        db,
                        Viewer(
                            person_id=setup.state.person_id,
                            tenant_id=tenant,
                            role="admin",
                            name="Fictional admin",
                        ),
                    )
                    desk._event(
                        lead, "edited", {"whatsapp_opt_in": False, "how": "STOP"}, actor=None
                    )
                stopped = await get(f"/leads/{three}/outreach")
                assert (stopped["verdict"], stopped["opted_out"]) == ("block", True)
                await message(three, 409)
                await post(
                    f"/leads/{three}/overrides",
                    {
                        "command_id": str(uuid4()),
                        "channel": "whatsapp",
                        "reason_key": "time_sensitive",
                    },
                    409,
                )
                # Email is still fine for them.
                assert (await get(f"/leads/{three}/outreach?channel=email"))["verdict"] == "ok"
                # The bulk counts, people warned again: two had an email today (all messages
                # count together), three said stop.
                current = await get("/outreach/rules")
                await put(
                    "/outreach/rules",
                    {
                        "expected_revision": current["revision"],
                        "modes": {"whatsapp": {"people": "warn", "automations": "block"}},
                    },
                )
                counts = await post("/outreach/guard", {"lead_ids": [two, three]})
                assert counts["words"] == "0 ok · 1 warned · 1 held (1 said stop)"

                # A seller: only their own leads; no rules, no overrides, no bulk counts.
                as_(seller_token)
                await get(f"/leads/{one}/outreach", 404)
                await get(f"/leads/{one}/touches", 404)
                assert (await get("/outreach/rules"))["can_edit"] is False
                await put("/outreach/rules", {"expected_revision": 9, "per_day": 2}, 403)
                await post(
                    f"/leads/{two}/overrides",
                    {
                        "command_id": str(uuid4()),
                        "channel": "whatsapp",
                        "reason_key": "lead_asked",
                    },
                    403,
                )
                await post("/outreach/guard", {"lead_ids": [two]}, 403)
                await get("/outreach/senders", 403)

                # A merge carries the touches (the counter never resets); a delete removes them.
                as_(setup.token)
                merged = await post(
                    "/duplicates/merge",
                    {"command_id": str(uuid4()), "lead_ids": [two, one], "keep": two},
                )
                assert merged["kept_lead_id"] == two
                page = await get(f"/leads/{two}/touches")
                assert len(page["touches"]) == 5
                await post(f"/leads/{two}/delete", {"command_id": str(uuid4())})
                async with setup.sessions() as db:
                    left = await db.scalar(
                        select(func.count())
                        .select_from(LeadTouch)
                        .where(LeadTouch.lead_id.in_([UUID(one), UUID(two)]))
                    )
                    overrides = await db.scalar(
                        select(func.count())
                        .select_from(LeadTouchOverride)
                        .where(LeadTouchOverride.lead_id == UUID(one))
                    )
                assert (left, overrides) == (0, 1)  # the merged-away lead keeps its override row
            async with setup.sessions() as db:
                assert (await verify_audit_chain(db, tenant)).valid
        finally:
            await setup.engine.dispose()

    run(asyncio.wait_for(exercise(), timeout=240))
