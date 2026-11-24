"""The outreach ingest API for outside senders (v1.95, owner 22 Nov 2026; integrations/
outreach_api.py), through HTTP on PostgreSQL: senders bound to a key, a touch that makes its lead
(source label, side, tag) and lands on the timeline, idempotency by provider id and by
client_ref (same body 200, another body 409), phone forms and email case, the guard for
automations, reservations (two engines at the limit: one passes), release and the sweeper,
statuses forward only, replies that link and open the 24-hour window, STOP and the opt-out
list, internal contacts ignored, and the refusals: scope, sender binding, a paused sender, a
channel not allowed, another workspace's key, bad times and ids. Fictional people only."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain
from ac_platform.integrations import keys
from ac_platform.lead_desk import outreach
from ac_platform.lead_desk.models import (
    Lead,
    LeadEvent,
    LeadOutreachSender,
    LeadTag,
    LeadTagLink,
    LeadTouch,
    LeadTouchOverride,
    LeadTouchReply,
)
from ac_platform.tenancy.models import Organisation
from tests.database.test_conversation_account_library_postgresql import _session
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_integrations_platform_apps_postgresql import _install
from tests.database.test_lead_desk_postgresql import _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
API = "/v1/api/outreach"
ALL_DAY = {"days": [0, 1, 2, 3, 4, 5, 6], "start": "00:00", "end": "23:59"}


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


async def _key(setup: Any, tenant_id: UUID, person_id: UUID, scopes: list[str]) -> tuple[str, UUID]:
    async with setup.sessions() as db, db.begin():
        key, view = await db.run_sync(
            lambda sync: keys.create(
                sync.connection(),
                tenant_id=tenant_id,
                person_id=person_id,
                name="Outreach senders",
                scopes=list(scopes),
                expires_days=None,
                environment="test",
                now=datetime.now(UTC),
            )
        )
    return key, UUID(view["id"])


def _at(delta: timedelta = timedelta()) -> str:
    return (datetime.now(UTC) + delta).isoformat()


def test_outside_senders_log_touches_through_the_api(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            tenant, admin = setup.state.tenant_id, setup.state.person_id
            seller = await seed(setup.engine, tenant_id=tenant, role="member")
            await _session(setup, seller)  # gives the seller an email: a teammate's
            settings = setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
            _install(setup, settings)
            key, key_id = await _key(setup, tenant, admin, ["outreach:write", "outreach:read"])
            other_key, other_key_id = await _key(setup, tenant, admin, ["outreach:write"])
            reader_key, _ = await _key(setup, tenant, admin, ["leads:read"])
            # Another workspace, with its own key and its own "sx-engage".
            stranger = await seed(setup.engine)
            async with setup.sessions() as db, db.begin():
                db.add(
                    Organisation(
                        tenant_id=stranger.tenant_id,
                        created_by_person_id=stranger.person_id,
                        creation_command_id=uuid4(),
                        domain_verification_token=uuid4().hex + uuid4().hex,
                    )
                )
            their_key, their_key_id = await _key(
                setup, stranger.tenant_id, stranger.person_id, ["outreach:write", "outreach:read"]
            )
            transport = httpx.ASGITransport(app=setup.app)
            async with (
                httpx.AsyncClient(transport=transport, base_url=ORIGIN) as person,
                httpx.AsyncClient(transport=transport, base_url=ORIGIN) as engine,
            ):
                person.cookies.set(setup.settings.session_cookie_name, setup.token)

                async def session(method: str, path: str, body: Any, status: int = 200) -> Any:
                    answer = await person.request(
                        method, f"/v1/lead-desk{path}", json=body, headers=WRITE
                    )
                    assert answer.status_code == status, answer.text
                    return answer.json()

                def bearer(value: str) -> dict[str, str]:
                    return {"Authorization": f"Bearer {value}"}

                async def call(
                    path: str,
                    body: dict[str, Any],
                    status: int = 200,
                    *,
                    using: str = key,
                    code: str | None = None,
                ) -> Any:
                    answer = await engine.post(f"{API}{path}", json=body, headers=bearer(using))
                    assert answer.status_code == status, answer.text
                    if code is not None:
                        assert answer.json()["error"]["code"] == code, answer.text
                    return answer.json()

                # The team's sending hours all day, so the clock never decides these checks.
                rules = await session("GET", "/outreach/rules", None)
                await session(
                    "PUT",
                    "/outreach/rules",
                    {
                        "expected_revision": rules["revision"],
                        "quiet": ALL_DAY,
                        "never_lead": ["+91 99999 00000"],
                    },
                )
                # Senders, each bound to one key (owners and admins).
                engine_sender = await session(
                    "POST",
                    "/outreach/senders",
                    {
                        "command_id": str(uuid4()),
                        "key": "sx-engage",
                        "label": "sx-engage",
                        "kind": "automation",
                        "api_key_id": str(key_id),
                        "channels": ["whatsapp"],
                        "lead_defaults": {"create": True, "side": "cold", "tags": ["Tester"]},
                        "guard_mode": "hold",
                    },
                    201,
                )
                assert engine_sender["api_key_prefix"] and engine_sender["guard_mode"] == "hold"
                owner_tool = await session(
                    "POST",
                    "/outreach/senders",
                    {
                        "command_id": str(uuid4()),
                        "key": "owner-mac-whatsapp",
                        "label": "Owner's WhatsApp (Mac)",
                        "kind": "person_tool",
                        "person_id": str(admin),
                        "api_key_id": str(key_id),
                        "channels": ["whatsapp", "email"],
                    },
                    201,
                )
                await session(
                    "POST",
                    "/outreach/senders",
                    {
                        "command_id": str(uuid4()),
                        "key": "elsewhere",
                        "label": "Bound elsewhere",
                        "kind": "automation",
                        "api_key_id": str(other_key_id),
                        "channels": ["whatsapp"],
                    },
                    201,
                )
                await session(
                    "POST",
                    "/outreach/senders",
                    {
                        "command_id": str(uuid4()),
                        "key": "bad-tool",
                        "label": "No person",
                        "kind": "person_tool",
                        "channels": ["whatsapp"],
                    },
                    422,
                )
                async with setup.sessions() as db, db.begin():
                    db.add(
                        LeadOutreachSender(
                            id=uuid4(),
                            tenant_id=stranger.tenant_id,
                            key="sx-engage",
                            label="Their engine",
                            kind="automation",
                            api_key_id=their_key_id,
                            channels=["whatsapp"],
                            lead_defaults={"create": True},
                            guard_mode="hold",
                            status="active",
                            revision=1,
                            created_at=datetime.now(UTC),
                            updated_at=datetime.now(UTC),
                        )
                    )

                # A first touch makes its lead: source label, cold side, the Tester tag.
                first = {
                    "sender": "sx-engage",
                    "to": {"phone": "+91 98111 22201", "name": "Manas Fictional"},
                    "channel": "whatsapp",
                    "provider": "meta_cloud",
                    "provider_message_id": "wamid.FICTIONAL-A1",
                    "sent_at": _at(),
                    "by": {"automation": "first_report"},
                    "content": {
                        "kind": "template",
                        "summary": "First report card: one strength and one try-this",
                        "template": "sx_first_report_a",
                        "attachment": {"kind": "image", "name": "card.png", "bytes": 812345},
                    },
                    "lead": {"create": True, "tags": ["Tester"], "side": "cold"},
                }
                made = await call("/touches", first, 201)
                assert (made["lead_created"], made["duplicate"], made["counted"]) == (
                    True,
                    False,
                    True,
                )
                assert made["guard"]["verdict"] == "block"  # an automation: 1 a day
                manas = made["lead_id"]
                async with setup.sessions() as db:
                    lead = await db.get(Lead, UUID(manas))
                    assert lead is not None
                    assert (lead.source, lead.source_label, lead.pipeline, lead.phone) == (
                        "webhook",
                        "sx-engage",
                        "cold",
                        "+919811122201",
                    )
                    tagged = await db.scalar(
                        select(LeadTag.name)
                        .join(LeadTagLink, LeadTagLink.tag_id == LeadTag.id)
                        .where(LeadTagLink.lead_id == lead.id)
                    )
                    assert tagged == "Tester"
                    captured = await db.scalar(
                        select(LeadEvent.data).where(
                            LeadEvent.lead_id == lead.id, LeadEvent.kind == "captured"
                        )
                    )
                    assert captured["source_label"] == "sx-engage"
                # The same touch again: one row; the same id with other words: refused.
                again = await call("/touches", first, 200)
                assert (again["duplicate"], again["touch_id"]) == (True, made["touch_id"])
                await call(
                    "/touches",
                    {**first, "content": {**first["content"], "summary": "Something else"}},
                    409,
                    code="idempotency_mismatch",
                )
                # Two calls with the same id at once: one row, the other answers as its duplicate
                # (the lead they make is one lead too).
                twins = await asyncio.gather(
                    *(
                        engine.post(
                            f"{API}/touches",
                            json={
                                **first,
                                "to": {"phone": "98111 22209"},
                                "provider_message_id": "wamid.FICTIONAL-TWIN",
                            },
                            headers=bearer(key),
                        )
                        for _ in range(2)
                    )
                )
                assert sorted(answer.status_code for answer in twins) == [200, 201], [
                    answer.text for answer in twins
                ]
                assert len({answer.json()["touch_id"] for answer in twins}) == 1
                assert len({answer.json()["lead_id"] for answer in twins}) == 1
                # Every phone form is the same lead.
                for form in ("9811122201", "0091 98111 22201", "098111 22201", "+919811122201"):
                    seen = await call("/check", {"sender": "sx-engage", "to": {"phone": form}})
                    assert seen["lead_id"] == manas, form
                    assert seen["verdict"] == "block"
                    assert seen["next_ok_at"] is not None
                # The timeline line names the sender.
                detail = await session("GET", f"/leads/{manas}", None)
                (line,) = [e for e in detail["events"] if e["kind"] == "message"]
                assert line["touch"]["sender_label"] == "sx-engage"
                assert line["touch"]["by_name"] == "sx-engage"
                assert line["touch"]["summary"].startswith("First report card")
                assert line["actor_name"] is None  # an automation is nobody's work

                # Sending past a block is stored, counted, flagged and audited.
                past = await call(
                    "/touches",
                    {**first, "provider_message_id": "wamid.FICTIONAL-A2", "sent_at": _at()},
                    201,
                )
                assert (past["after_block"], past["counted"]) == (True, True)

                # Reservations: two engines at once on a fresh lead, one passes.
                fresh = await call(
                    "/touches",
                    {
                        **first,
                        "to": {"phone": "98111 22202"},
                        "provider_message_id": None,
                        "provider": None,
                        "client_ref": "q:seed",
                        "status": "failed",
                        "error_code": "131026",
                    },
                    201,
                )
                assert fresh["counted"] is False  # a failed send never counts
                riya = fresh["lead_id"]

                async def hold(ref: str) -> Any:
                    return await call(
                        "/check",
                        {
                            "sender": "sx-engage",
                            "to": {"phone": "98111 22202"},
                            "hold": True,
                            "client_ref": ref,
                        },
                    )

                both = await asyncio.gather(hold("q:10"), hold("q:11"))
                passed = [answer for answer in both if answer["reservation_id"]]
                assert len(passed) == 1
                assert {answer["verdict"] for answer in both} == {"ok", "block"}
                ref = "q:10" if both[0]["reservation_id"] else "q:11"
                # A retry of the passing hold keeps its verdict and its place (PR #663 review:
                # its own reservation never counts against itself).
                again = await hold(ref)
                assert (again["verdict"], again["reservation_id"]) == (
                    "ok",
                    passed[0]["reservation_id"],
                )
                sent = await call(
                    "/touches",
                    {
                        **first,
                        "to": {"phone": "98111 22202"},
                        "client_ref": ref,
                        "reservation_id": passed[0]["reservation_id"],
                        "provider_message_id": "wamid.FICTIONAL-B1",
                    },
                    201,
                )
                assert sent["touch_id"] == passed[0]["reservation_id"]
                assert sent["lead_id"] == riya
                # A released reservation frees the place; the sweeper ends the forgotten ones.
                ravi = (
                    await call(
                        "/touches",
                        {
                            **first,
                            "to": {"phone": "98111 22203"},
                            "provider_message_id": "wamid.FICTIONAL-C0",
                            "status": "failed",
                        },
                        201,
                    )
                )["lead_id"]
                assert ravi not in (manas, riya)
                held = await call(
                    "/check",
                    {"sender": "sx-engage", "to": {"phone": "98111 22203"}, "hold": True},
                )
                assert held["reservation_id"]
                blocked = await call(
                    "/check", {"sender": "sx-engage", "to": {"phone": "98111 22203"}}
                )
                assert blocked["verdict"] == "block"
                gone = await engine.delete(
                    f"{API}/reservations/{held['reservation_id']}", headers=bearer(key)
                )
                assert gone.status_code == 200, gone.text
                free = await call("/check", {"sender": "sx-engage", "to": {"phone": "98111 22203"}})
                assert free["verdict"] == "ok"
                other_hold = await call(
                    "/check",
                    {"sender": "sx-engage", "to": {"phone": "98111 22203"}, "hold": True},
                )
                async with setup.sessions() as db, db.begin():
                    ended = await outreach.expire_reservations(
                        db, datetime.now(UTC) + timedelta(minutes=16)
                    )
                    assert ended >= 1
                    lapsed = await db.get(LeadTouch, UUID(other_hold["reservation_id"]))
                    assert lapsed is not None
                    assert (lapsed.status, lapsed.counted, lapsed.expires_at) == (
                        "expired",
                        False,
                        None,
                    )
                missing = await engine.delete(f"{API}/reservations/{uuid4()}", headers=bearer(key))
                assert missing.status_code == 404

                # A manager's one-time override lets one reservation through; once that is
                # sent the override is used (and audited), so the next check is held again
                # (PR #663 review).
                assert (
                    await call("/check", {"sender": "sx-engage", "to": {"phone": "98111 22202"}})
                )["verdict"] == "block"
                granted = await session(
                    "POST",
                    f"/leads/{riya}/overrides",
                    {"command_id": str(uuid4()), "channel": "whatsapp", "reason_key": "lead_asked"},
                    201,
                )
                let_through = await call(
                    "/check",
                    {
                        "sender": "sx-engage",
                        "to": {"phone": "98111 22202"},
                        "hold": True,
                        "client_ref": "q:20",
                    },
                )
                assert let_through["reservation_id"]
                await call(
                    "/touches",
                    {
                        **first,
                        "to": {"phone": "98111 22202"},
                        "client_ref": "q:20",
                        "reservation_id": let_through["reservation_id"],
                        "provider_message_id": "wamid.FICTIONAL-B2",
                    },
                    201,
                )
                async with setup.sessions() as db, db.begin():
                    used = await db.get(LeadTouchOverride, UUID(granted["override_id"]))
                    assert used is not None
                    assert used.used_by_touch_id == UUID(let_through["reservation_id"])
                    audited = await db.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(
                            AuditEvent.action == "lead_desk.outreach.override_used",
                            AuditEvent.resource_id == granted["override_id"],
                        )
                    )
                    assert audited == 1
                assert (
                    await call("/check", {"sender": "sx-engage", "to": {"phone": "98111 22202"}})
                )["verdict"] == "block"

                # A reservation sent to an address no lead has is refused, not put on the
                # reserved lead (PR #663 review).
                ravi_hold = await call(
                    "/check",
                    {
                        "sender": "sx-engage",
                        "to": {"phone": "98111 22203"},
                        "hold": True,
                        "client_ref": "q:30",
                    },
                )
                assert ravi_hold["reservation_id"]
                wrong = await engine.post(
                    f"{API}/touches",
                    json={
                        **first,
                        "to": {"phone": "98111 22299"},
                        "client_ref": "q:30",
                        "reservation_id": ravi_hold["reservation_id"],
                        "provider_message_id": "wamid.FICTIONAL-C9",
                    },
                    headers=bearer(key),
                )
                assert wrong.status_code == 409, wrong.text
                # The hold lapses; a late send with its client_ref is a touch of its own, not
                # a "duplicate" of the lapsed hold (PR #663 review).
                async with setup.sessions() as db, db.begin():
                    assert (
                        await outreach.expire_reservations(
                            db, datetime.now(UTC) + timedelta(minutes=16)
                        )
                        >= 1
                    )
                late = await call(
                    "/touches",
                    {
                        **first,
                        "to": {"phone": "98111 22203"},
                        "client_ref": "q:30",
                        "provider_message_id": "wamid.FICTIONAL-C10",
                    },
                    201,
                )
                assert late["lead_id"] == ravi
                assert late["touch_id"] != ravi_hold["reservation_id"]
                assert late.get("duplicate") is not True

                # Statuses move forward only; a late older one is ignored.
                start = datetime.now(UTC)
                moved = await call(
                    "/statuses",
                    {
                        "sender": "sx-engage",
                        "statuses": [
                            {
                                "provider": "meta_cloud",
                                "provider_message_id": "wamid.FICTIONAL-A1",
                                "status": "delivered",
                                "at": (start + timedelta(seconds=1)).isoformat(),
                            },
                            {
                                "provider": "meta_cloud",
                                "provider_message_id": "wamid.FICTIONAL-A1",
                                "status": "read",
                                "at": (start + timedelta(seconds=2)).isoformat(),
                            },
                            {
                                "provider": "meta_cloud",
                                "provider_message_id": "wamid.FICTIONAL-A1",
                                "status": "delivered",
                                "at": (start + timedelta(seconds=3)).isoformat(),
                            },
                            {
                                "provider": "meta_cloud",
                                "provider_message_id": "wamid.NOT-OURS",
                                "status": "read",
                                "at": start.isoformat(),
                            },
                        ],
                    },
                )
                assert (moved["updated"], moved["ignored"], moved["unknown"]) == (2, 1, 1)
                # A failed send that a retry delivers ends delivered.
                retried = await call(
                    "/statuses",
                    {
                        "sender": "sx-engage",
                        "statuses": [
                            {
                                "provider": "meta_cloud",
                                "provider_message_id": "wamid.FICTIONAL-B1",
                                "status": "failed",
                                "at": (start + timedelta(seconds=1)).isoformat(),
                                "error_code": "131049",
                            },
                            {
                                "provider": "meta_cloud",
                                "provider_message_id": "wamid.FICTIONAL-B1",
                                "status": "delivered",
                                "at": (start + timedelta(seconds=2)).isoformat(),
                            },
                        ],
                    },
                )
                assert retried["updated"] == 2
                async with setup.sessions() as db:
                    b1 = await db.get(LeadTouch, UUID(sent["touch_id"]))
                    assert b1 is not None and (b1.status, b1.counted) == ("delivered", True)

                # A reply links to the newest unanswered touch and opens the 24-hour window;
                # its words are kept only when the workspace says so (it doesn't).
                replied = await call(
                    "/replies",
                    {
                        "sender": "sx-engage",
                        "provider": "wa_linked",
                        "provider_message_id": "3EB0FICTIONAL-R1",
                        "provider_chat_id": "919811122201@s.whatsapp.net",
                        "from": {"phone": "919811122201@s.whatsapp.net"},
                        "at": _at(),
                        "kind": "text",
                        "excerpt": "Thanks, will try",
                    },
                    201,
                )
                assert replied["lead_id"] == manas
                assert replied["touch_id"] == past["touch_id"]
                async with setup.sessions() as db:
                    stored = await db.get(LeadTouchReply, UUID(replied["reply_id"]))
                    assert stored is not None and stored.excerpt is None
                window = await call(
                    "/check", {"sender": "sx-engage", "to": {"phone": "9811122201"}}
                )
                assert (window["verdict"], window["in_reply_window"]) == ("ok", True)
                dup = await call(
                    "/replies",
                    {
                        "sender": "sx-engage",
                        "provider": "wa_linked",
                        "provider_message_id": "3EB0FICTIONAL-R1",
                        "provider_chat_id": "919811122201@s.whatsapp.net",
                        "from": {"phone": "919811122201@s.whatsapp.net"},
                        "at": _at(),
                    },
                )
                assert dup["duplicate"] is True
                reaction = await call(
                    "/replies",
                    {
                        "sender": "sx-engage",
                        "provider": "wa_linked",
                        "provider_message_id": "3EB0FICTIONAL-R2",
                        "from": {"phone": "9811122201"},
                        "at": _at(),
                        "kind": "reaction",
                    },
                )
                assert reaction["ignored"] == "reaction"
                # A STOP: blocked, and on the opt-out list every engine reads.
                await call(
                    "/replies",
                    {
                        "sender": "sx-engage",
                        "provider": "wa_linked",
                        "provider_message_id": "3EB0FICTIONAL-R3",
                        "from": {"phone": "9811122202"},
                        "at": _at(),
                        "opt_out": True,
                    },
                    201,
                )
                stop = await call("/check", {"sender": "sx-engage", "to": {"phone": "9811122202"}})
                assert (stop["verdict"], stop["opted_out"]) == ("block", True)

                # A person's own tool: the touch is that person's, a lead is theirs, email
                # matches whatever the letters.
                tool = {
                    "sender": "owner-mac-whatsapp",
                    "to": {"email": "Riya.Fictional@Example.test", "name": "Riya Fictional"},
                    "channel": "email",
                    "provider": "gmail",
                    "provider_message_id": "gm-fictional-1",
                    "sent_at": _at(),
                    "by": {"person": "self"},
                    "content": {"summary": "Sent the proposal"},
                }
                skipped = await call("/touches", tool, 200)
                assert skipped == {"lead_id": None, "stored": False}  # no lead, none made
                mine = await call("/touches", {**tool, "lead": {"create": True}}, 201)
                async with setup.sessions() as db:
                    made_lead = await db.get(Lead, UUID(mine["lead_id"]))
                    assert made_lead is not None and made_lead.created_by_person_id == admin
                    row = await db.get(LeadTouch, UUID(mine["touch_id"]))
                    assert row is not None
                    assert (row.sender_type, row.person_id) == ("person", admin)
                second = await call(
                    "/touches",
                    {
                        **tool,
                        "to": {"email": "riya.fictional@example.test"},
                        "provider_message_id": "gm-fictional-2",
                    },
                    201,
                )
                assert second["lead_id"] == mine["lead_id"]
                await call(
                    "/touches",
                    {**tool, "provider_message_id": "gm-x", "by": {"automation": "x"}},
                    422,
                    code="bad_by",
                )
                recorded = await call(
                    "/opt-outs",
                    {
                        "sender": "owner-mac-whatsapp",
                        "to": {"email": "riya.fictional@example.test"},
                        "channel": "email",
                    },
                )
                assert recorded["recorded"] is True
                listed = await engine.get(f"{API}/opt-outs", headers=bearer(key))
                assert listed.status_code == 200, listed.text
                assert {
                    (item["lead_id"], item["channel"]) for item in listed.json()["opt_outs"]
                } == {
                    (riya, "whatsapp"),
                    (mine["lead_id"], "email"),
                }
                # next_since is "<time>|<event id>": a page ending inside a timestamp tie skips
                # nothing (PR #663 review); a plain time still works, a broken cursor is refused.
                tied = await engine.get(
                    f"{API}/opt-outs",
                    params={"since": f"{_at(timedelta(days=-1))}|{uuid4()}"},
                    headers=bearer(key),
                )
                assert tied.status_code == 200, tied.text
                assert len(tied.json()["opt_outs"]) == 2
                broken = await engine.get(
                    f"{API}/opt-outs", params={"since": "yesterday|x"}, headers=bearer(key)
                )
                assert broken.status_code == 422, broken.text
                history = await engine.get(
                    f"{API}/touches", params={"phone": "+91 98111 22201"}, headers=bearer(key)
                )
                assert history.status_code == 200, history.text
                assert [t["provider_message_id"] for t in history.json()["touches"]] == [
                    "wamid.FICTIONAL-A2",
                    "wamid.FICTIONAL-A1",
                ]
                # The lead's name only for a key that may read leads.
                assert all("lead_name" not in t for t in history.json()["touches"])
                leads_key, _ = await _key(setup, tenant, admin, ["outreach:read", "leads:read"])
                named = await engine.get(
                    f"{API}/touches", params={"lead_id": manas}, headers=bearer(leads_key)
                )
                assert {t["lead_name"] for t in named.json()["touches"]} == {"Manas Fictional"}

                # Teammates and the Never a lead list are never leads.
                teammate = await call(
                    "/touches",
                    {
                        **tool,
                        "to": {"email": f"library-{seller.person_id.hex}@example.test"},
                        "provider_message_id": "gm-team",
                    },
                )
                never = await call(
                    "/touches",
                    {**first, "to": {"phone": "99999 00000"}, "provider_message_id": "wamid.N"},
                )
                assert teammate == never == {"ignored": "internal", "stored": False}

                # The refusals.
                await call(
                    "/check", {"sender": "sx-engage", "to": {"phone": "1"}}, 422, code="bad_phone"
                )
                await call(
                    "/check",
                    {"sender": "sx-engage", "to": {"phone": "12345@lid"}},
                    422,
                    code="phone_needed",
                )
                await call(
                    "/touches",
                    {**first, "provider_message_id": None, "provider": None},
                    422,
                    code="needs_id",
                )
                await call(
                    "/touches",
                    {**first, "provider_message_id": "w.f", "sent_at": _at(timedelta(hours=1))},
                    422,
                    code="bad_time",
                )
                await call(
                    "/touches",
                    {**first, "provider_message_id": "w.n", "sent_at": "2026-11-23T10:00:00"},
                    422,
                    code="bad_time",
                )
                await call(
                    "/touches",
                    {
                        **first,
                        "provider_message_id": "w.l",
                        "content": {"summary": "x" * 281},
                    },
                    422,
                    code="summary_too_long",
                )
                await call(
                    "/check",
                    {"sender": "sx-engage", "to": {"phone": "9811122201"}},
                    403,
                    using=reader_key,
                    code="scope_missing",
                )
                await call(
                    "/check",
                    {"sender": "elsewhere", "to": {"phone": "9811122201"}},
                    403,
                    code="sender_not_bound",
                )
                await call(
                    "/check",
                    {"sender": "sx-engage", "to": {"phone": "9811122201"}},
                    403,
                    using=other_key,
                    code="sender_not_bound",
                )
                await call(
                    "/check",
                    {"sender": "sx-engage", "channel": "email", "to": {"email": "a@example.test"}},
                    403,
                    code="channel_not_allowed",
                )
                # Another workspace's key: its own sender and leads, never ours.
                await call(
                    "/check",
                    {"sender": "owner-mac-whatsapp", "to": {"phone": "9811122201"}},
                    403,
                    using=their_key,
                    code="sender_not_bound",
                )
                theirs = await call(
                    "/touches",
                    {**first, "provider_message_id": "wamid.THEIRS"},
                    201,
                    using=their_key,
                )
                assert theirs["lead_id"] != manas and theirs["lead_created"] is True
                peek = await engine.get(
                    f"{API}/touches", params={"lead_id": manas}, headers=bearer(their_key)
                )
                assert peek.json() == {"lead_id": None, "touches": [], "next_cursor": None}
                # A paused sender is refused.
                paused = await session(
                    "POST",
                    f"/outreach/senders/{engine_sender['sender_id']}/pause",
                    {"expected_revision": engine_sender["revision"]},
                )
                assert paused["status"] == "paused"
                await call(
                    "/check",
                    {"sender": "sx-engage", "to": {"phone": "9811122201"}},
                    403,
                    code="sender_paused",
                )
                listed_senders = await session("GET", "/outreach/senders", None)
                # sx-engage: six sends, the one a manager's override let through, and the late
                # send after a lapsed hold.
                assert {s["key"]: s["touches_week"] for s in listed_senders["senders"]} == {
                    "sx-engage": 8,
                    "owner-mac-whatsapp": 2,
                    "elsewhere": 0,
                }
                assert owner_tool["person_name"]

            async with setup.sessions() as db:
                actions = dict(
                    (
                        await db.execute(
                            select(AuditEvent.action, func.count())
                            .where(
                                AuditEvent.tenant_id == tenant,
                                AuditEvent.action.like("lead_desk.outreach.%"),
                            )
                            .group_by(AuditEvent.action)
                        )
                    )
                    .tuples()
                    .all()
                )
                assert actions == {
                    "lead_desk.outreach.settings_changed": 1,
                    "lead_desk.outreach.sender_created": 3,
                    "lead_desk.outreach.sent_past_block": 1,
                    "lead_desk.outreach.sender_paused": 1,
                    "lead_desk.outreach.override_granted": 1,
                    "lead_desk.outreach.override_used": 1,
                }
                past_block = await db.scalar(
                    select(AuditEvent).where(
                        AuditEvent.tenant_id == tenant,
                        AuditEvent.action == "lead_desk.outreach.sent_past_block",
                    )
                )
                assert past_block is not None and past_block.actor_type == "api_key"
                assert "phone" not in str(past_block.payload)
                assert (await verify_audit_chain(db, tenant)).valid
                theirs_count = await db.scalar(
                    select(func.count())
                    .select_from(LeadTouch)
                    .where(LeadTouch.tenant_id == stranger.tenant_id)
                )
                assert theirs_count == 1
        finally:
            await setup.engine.dispose()

    run(asyncio.wait_for(exercise(), timeout=300))
