"""Meta Lead Ads in the Sales Xray CRM on PostgreSQL, with Meta's Graph API faked.

Turning a Page on brings in only the leads sent after it (owner, 2 Nov 2026); the
older ones Meta keeps (90 days) come in only when a manager asks, and the puller
finishes that in the background; every form on the Page is covered (a new form too);
"Bring in older leads" again adds nothing twice. Leads imported from a file before the
Page was connected are linked, not made repeats.
"""

import base64
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select, update

from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk import owner_alerts, sla
from ac_platform.lead_desk.connectors import meta, meta_backfill, meta_pull
from ac_platform.lead_desk.connectors.http import install_connectors_http
from ac_platform.lead_desk.models import Lead, LeadDeskSettings, LeadEvent, LeadMerge, LeadSource
from ac_platform.lead_desk.store import LeadDesk, Viewer
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
META = "/v1/lead-desk/meta"
KEY = base64.urlsafe_b64encode(b"k" * 32).decode()
ENV = {
    "AC_META_APP_ID": "1234567890",
    "AC_META_APP_SECRET": "app-secret",
    "AC_META_LOGIN_CONFIG_ID": "987654321",
    "AC_META_WEBHOOK_VERIFY_TOKEN": "verify-me",
    "AC_LEAD_DESK_TOKEN_KEY": KEY,
}
DAY = 86400


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


CREATED: dict[str, int] = {}


def _lead(n: int, form: str, age_days: int) -> dict[str, Any]:
    at = int(time.time()) - age_days * DAY
    CREATED[f"{100000000000000 + n}"] = at
    created = time.strftime("%Y-%m-%dT%H:%M:%S+0000", time.gmtime(at))
    return {
        "id": f"{100000000000000 + n}",
        "created_time": created,
        "form_id": form,
        "field_data": [
            {"name": "full_name", "values": [f"Test Lead {n}"]},
            {"name": "phone_number", "values": [f"+9199990{n:05d}"]},
        ],
    }


# Form A: two leads this week, two older; form B (made later): one older lead.
LEADS = {
    "fa": [_lead(1, "fa", 1), _lead(2, "fa", 3), _lead(3, "fa", 20), _lead(4, "fa", 80)],
    "fb": [_lead(5, "fb", 45)],
}


class FakeGraph:
    """Meta's Graph API for one Page; leads newest first, two to a page."""

    forms_listed: list[str] = ["fa"]
    unsubscribed: list[str] = []

    def __init__(self, cfg: meta.MetaConfig, client: Any = None, timeout: float = 20) -> None:
        self.cfg = cfg

    async def require_lead_access(self, page_id: str, page_token: str) -> None:
        assert page_token == "page-token-1"  # noqa: S105 - a fake Page's token

    async def subscribe(self, page_id: str, page_token: str) -> None:
        return None

    async def unsubscribe(self, page_id: str, page_token: str) -> None:
        FakeGraph.unsubscribed.append(page_id)

    async def forms(self, page_id: str, page_token: str) -> list[dict[str, str]]:
        names = {"fa": "Enquiry", "fb": "Site visit"}
        return [{"id": f, "name": names[f], "status": "ACTIVE"} for f in self.forms_listed]

    def _since(self, form_id: str, since: int) -> list[dict[str, Any]]:
        return [lead for lead in LEADS[form_id] if CREATED[lead["id"]] > since]

    async def recent_leads(
        self, form_ids: list[str], page_token: str, *, since: int, limit: int = 1000
    ) -> list[dict[str, Any]]:
        return [lead for form in form_ids for lead in self._since(form, since)][:limit]

    async def leads_page(
        self, form_id: str, page_token: str, *, since: int, after: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        rows = self._since(form_id, since)
        start = int(after or 0)
        nxt = start + 2
        return rows[start:nxt], str(nxt) if nxt < len(rows) else None

    async def lead_times(
        self, form_ids: list[str], page_token: str, *, since: int, limit: int = 2000
    ) -> list[int]:
        return [CREATED[lead["id"]] for form in form_ids for lead in self._since(form, since)]

    # Continue with Meta, and the organisation's datasets.
    async def user_token(self, *, code: str, redirect_uri: str) -> meta.UserToken:
        assert code == "meta-code"
        return meta.UserToken(token=USER_TOKEN, expires_at=int(time.time()) + 60 * DAY)

    async def pages(self, user_token: str) -> list[dict[str, str]]:
        assert user_token == USER_TOKEN
        return [{"id": "p1", "name": "Fictional Homes", "token": "page-token-1"}]

    async def me(self, user_token: str) -> dict[str, str]:
        # Who signed in, shown on each Page shared (bug report #8).
        assert user_token == USER_TOKEN
        return {"id": "77", "name": "Fictional Owner"}

    async def ad_accounts(self, user_token: str) -> list[dict[str, str]]:
        assert user_token == USER_TOKEN
        return [{"id": "act_10000001", "name": "Fictional Homes ads"}]

    async def datasets(self, user_token: str) -> list[dict[str, str]]:
        return [{"id": "777000111", "name": "Fictional Homes website"}]

    async def create_dataset(
        self, user_token: str, *, ad_account_id: str, name: str
    ) -> dict[str, str]:
        assert (user_token, ad_account_id) == (USER_TOKEN, "act_10000001")
        return {"id": "777000222", "name": name}


USER_TOKEN = "fake-user-token"  # noqa: S105 - a stand-in, never a real token


def test_turning_a_page_on_brings_in_only_newer_leads_and_older_ones_on_purpose(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Owner, 2 Nov 2026: connecting a Page filed its last week at once and its last 90
    days in the background, as fresh enquiries. Now nothing sent before it comes in by
    itself, from the pull or the webhook's path; a lead sent after it does; the older
    ones come in when a manager asks; changing a live Page's forms keeps its time."""
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(meta, "Graph", FakeGraph)
    FakeGraph.forms_listed = ["fa"]
    # Sent a minute after the Page is switched on (Meta's fake answers by time sent).
    fresh = {
        **_lead(9, "fa", 0),
        "created_time": time.strftime("%Y-%m-%dT%H:%M:%S+0000", time.gmtime(int(time.time()) + 60)),
    }
    monkeypatch.setitem(LEADS, "fa", [*LEADS["fa"], fresh])
    monkeypatch.setitem(CREATED, fresh["id"], int(time.time()) + 60)
    cfg = meta.config()
    assert cfg is not None

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            settings = setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
            install_connectors_http(
                setup.app, RouteContext(settings, setup.require_actor, setup.sessions)
            )
            # What Continue with Meta leaves behind: the Page, its sealed token, off.
            async with setup.sessions() as db, db.begin():
                db.add(
                    LeadSource(
                        id=uuid4(),
                        tenant_id=setup.state.tenant_id,
                        kind="meta",
                        label="Meta · Fictional Homes",
                        token_sha256=None,
                        config={
                            "page_id": "p1",
                            "page_name": "Fictional Homes",
                            "token": meta.seal(cfg.token_key, "page-token-1", page_id="p1"),
                            "forms": "all",
                        },
                        active=False,
                        received=0,
                        created_by_person_id=setup.state.person_id,
                        created_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                    )
                )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)

                on = await client.post(f"{META}/pages/p1", json={}, headers=WRITE)
                assert on.status_code == 200, on.text
                body = on.json()
                assert body["imported"] == 0  # this week's two stay at Meta
                page = body["page"]
                assert page["active"] is True and page["forms"] == "all"
                assert [f["name"] for f in page["formsCovered"]] == ["Enquiry"]
                assert page["backfill"] is None  # no older leads started
                async with setup.sessions() as db:
                    assert await db.scalar(select(func.count()).select_from(Lead)) == 0
                    source = await db.scalar(select(LeadSource).where(LeadSource.kind == "meta"))
                    assert source is not None
                    connected = source.config["connected_at"]
                    assert abs(connected - time.time()) < 60

                # A form made after connecting is covered without asking. The pull reads
                # from when the Page went on: the lead sent since comes in, nothing older.
                FakeGraph.forms_listed = ["fa", "fb"]
                async with setup.sessions() as db, db.begin():
                    source = await db.scalar(select(LeadSource).where(LeadSource.kind == "meta"))
                    assert source is not None
                    source.config = {**source.config, "last_pulled_at": 1}
                    assert meta_pull.since(source.config, int(time.time())) == connected - 1
                pulled = await meta_pull.pull_due(
                    setup.sessions, cfg, FakeGraph(cfg), now=int(time.time())
                )
                assert pulled == 1
                async with setup.sessions() as db:
                    refs = set((await db.scalars(select(Lead.source_ref))).all())
                    assert refs == {fresh["id"]}

                # The webhook's path, handed a lead sent before the Page went on (a late
                # or repeated delivery): left out, unless older leads were asked for.
                async with setup.sessions() as db, db.begin():
                    source = await db.scalar(select(LeadSource).where(LeadSource.kind == "meta"))
                    assert source is not None
                    desk = LeadDesk(
                        db,
                        Viewer(
                            person_id=setup.state.person_id,
                            tenant_id=setup.state.tenant_id,
                            role="system",
                            name=source.label,
                        ),
                    )
                    old = LEADS["fa"][0]
                    assert await meta_backfill.file_lead(desk, source, old, page_name="P") == (
                        "older"
                    )
                    assert await db.scalar(select(func.count()).select_from(Lead)) == 1

                # Changing a live Page's forms keeps its time and starts nothing.
                kept = await client.post(f"{META}/pages/p1", json={"forms": ["fa"]}, headers=WRITE)
                assert kept.status_code == 200, kept.text
                assert kept.json()["imported"] == 0 and kept.json()["page"]["backfill"] is None
                back = await client.post(f"{META}/pages/p1", json={"forms": "all"}, headers=WRITE)
                assert back.status_code == 200, back.text
                async with setup.sessions() as db:
                    source = await db.scalar(select(LeadSource).where(LeadSource.kind == "meta"))
                    assert source is not None and source.config["connected_at"] == connected
                    assert await db.scalar(select(func.count()).select_from(Lead)) == 1

                # Older leads on purpose: every form's 90 days, the fresh lead already here.
                older = await client.post(f"{META}/pages/p1/backfill", headers=WRITE)
                assert older.status_code == 200, older.text
                assert older.json()["imported"] == 5

                status = (await client.get(f"{META}/status")).json()
                page = status["pages"][0]
                assert page["backfill"]["state"] == "done"
                assert page["backfill"]["created"] == 5  # 1, 3, 20, 45 and 80 days old
                assert [f["name"] for f in page["formsCovered"]] == ["Enquiry", "Site visit"]
                assert page["received"] == 6 and page["problem"] is None

                again = await client.post(f"{META}/pages/p1/backfill", headers=WRITE)
                assert again.status_code == 200, again.text
                assert again.json()["imported"] == 0
                assert again.json()["page"]["backfill"]["state"] == "done"
                assert again.json()["page"]["backfill"]["seen"] == 6

            async with setup.sessions() as db:
                assert await db.scalar(select(func.count()).select_from(Lead)) == 6
                refs = set((await db.scalars(select(Lead.source_ref))).all())
                assert refs == {lead["id"] for leads in LEADS.values() for lead in leads}
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_leads_imported_from_a_file_first_are_linked_not_made_repeats(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Owner's demo prep, 25 Oct 2026: a team imports its Page's leads from a file (one is
    already Lost), then connects the Page. Turning it on and the pull file nothing sent
    before it; bringing in older leads finds the same people: each lead gets one note with
    its Meta lead id, and no follow-up, stage or repeat count changes."""
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(meta, "Graph", FakeGraph)
    FakeGraph.forms_listed = ["fa"]
    cfg = meta.config()
    assert cfg is not None

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            settings = setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
            install_connectors_http(
                setup.app, RouteContext(settings, setup.require_actor, setup.sessions)
            )
            tenant = setup.state.tenant_id
            async with setup.sessions() as db, db.begin():
                desk = LeadDesk(
                    db,
                    Viewer(
                        person_id=setup.state.person_id,
                        tenant_id=tenant,
                        role="admin",
                        name="Admin",
                    ),
                )
                for lead in LEADS["fa"]:
                    record = {answer["name"]: answer["values"][0] for answer in lead["field_data"]}
                    await desk.ingest(
                        record,
                        source="csv",
                        source_label="File: Meta leads",
                        source_ref=f"h:{lead['id']}",
                        actor=None,
                    )
                db.add(
                    LeadSource(
                        id=uuid4(),
                        tenant_id=tenant,
                        kind="meta",
                        label="Meta · Fictional Homes",
                        token_sha256=None,
                        config={
                            "page_id": "p1",
                            "page_name": "Fictional Homes",
                            "token": meta.seal(cfg.token_key, "page-token-1", page_id="p1"),
                            "forms": "all",
                        },
                        active=False,
                        received=0,
                        created_by_person_id=setup.state.person_id,
                        created_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                    )
                )
            lost = LEADS["fa"][2]["id"]
            async with setup.sessions() as db, db.begin():
                await db.execute(
                    update(Lead).where(Lead.source_ref == f"h:{lost}").values(stage="lost")
                )

            def kept(lead: Lead) -> tuple[Any, ...]:
                return (lead.stage, lead.next_action_at, lead.repeats, lead.revision, lead.source)

            async with setup.sessions() as db:
                before = {lead.id: kept(lead) for lead in (await db.scalars(select(Lead))).all()}
            assert len(before) == 4

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                on = await client.post(f"{META}/pages/p1", json={}, headers=WRITE)
                assert on.status_code == 200, on.text
                assert on.json()["imported"] == 0  # nothing from before the Page went on

                async with setup.sessions() as db, db.begin():
                    source = await db.scalar(select(LeadSource).where(LeadSource.kind == "meta"))
                    assert source is not None
                    source.config = {**source.config, "last_pulled_at": 1}
                await meta_pull.pull_due(setup.sessions, cfg, FakeGraph(cfg), now=int(time.time()))

                again = await client.post(f"{META}/pages/p1/backfill", headers=WRITE)
                assert again.status_code == 200, again.text
                assert again.json()["imported"] == 0

            async with setup.sessions() as db:
                after = {lead.id: kept(lead) for lead in (await db.scalars(select(Lead))).all()}
                assert after == before  # no new lead; Lost stays Lost; nothing reset
                notes = (
                    await db.scalars(
                        select(LeadEvent).where(
                            LeadEvent.tenant_id == tenant, LeadEvent.kind == "note"
                        )
                    )
                ).all()
                linked = {note.data["source_ref"] for note in notes if note.data.get("linked")}
                assert len(notes) == 4 and linked == {lead["id"] for lead in LEADS["fa"]}
                assert len({note.lead_id for note in notes}) == 4
                repeats = await db.scalar(
                    select(func.count()).select_from(LeadEvent).where(LeadEvent.kind == "repeat")
                )
                assert repeats == 0
                source = await db.scalar(select(LeadSource).where(LeadSource.kind == "meta"))
                assert source is not None and source.received == 0
                assert source.config["backfill"]["created"] == 0
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_a_newer_meta_lead_with_a_known_email_is_merged_by_the_duplicate_engine(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Owner, 26 Oct 2026 (bug reports #12, #13): Meta leads go through the duplicate engine
    as they arrive. A person who wrote in before from another number sends the form: the
    same email is certain, so the new lead is merged into the one the team works on."""
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(meta, "Graph", FakeGraph)
    FakeGraph.forms_listed = ["fa"]
    now = int(time.time())
    fresh = {
        "id": "100000000000901",
        "created_time": time.strftime("%Y-%m-%dT%H:%M:%S+0000", time.gmtime(now)),
        "form_id": "fa",
        "field_data": [
            {"name": "full_name", "values": ["Asha Fictional"]},
            {"name": "phone_number", "values": ["+919999011111"]},
            {"name": "email", "values": ["asha.fictional@example.com"]},
        ],
    }
    monkeypatch.setitem(LEADS, "fa", [fresh])
    monkeypatch.setitem(CREATED, fresh["id"], now)
    cfg = meta.config()
    assert cfg is not None

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            tenant = setup.state.tenant_id
            async with setup.sessions() as db, db.begin():
                desk = LeadDesk(
                    db,
                    Viewer(
                        person_id=setup.state.person_id,
                        tenant_id=tenant,
                        role="admin",
                        name="Admin",
                    ),
                    now=datetime.fromtimestamp(now - 30 * DAY, UTC),
                )
                await desk.ingest(
                    {
                        "full_name": "Asha Fictional",
                        "phone": "+919999022222",
                        "email": "asha.fictional@example.com",
                    },
                    source="manual",
                    actor=setup.state.person_id,
                )
                db.add(
                    LeadSource(
                        id=uuid4(),
                        tenant_id=tenant,
                        kind="meta",
                        label="Meta · Fictional Homes",
                        token_sha256=None,
                        config={
                            "page_id": "p1",
                            "page_name": "Fictional Homes",
                            "token": meta.seal(cfg.token_key, "page-token-1", page_id="p1"),
                            "forms": "all",
                        },
                        active=True,
                        received=0,
                        created_by_person_id=setup.state.person_id,
                        created_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                    )
                )
            assert await meta_pull.pull_due(setup.sessions, cfg, FakeGraph(cfg), now=now) == 1
            async with setup.sessions() as db:
                leads = {lead.source: lead for lead in (await db.scalars(select(Lead))).all()}
                assert set(leads) == {"manual", "meta"}
                assert leads["meta"].merged_into_id == leads["manual"].id
                assert leads["manual"].merged_into_id is None
                merges = await db.scalar(select(func.count()).select_from(LeadMerge))
                assert merges == 1
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_older_leads_asked_for_wait_on_cold_and_start_no_clock_or_alert(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Owner, 2 Nov 2026: older enquiries posed as new ones. Now the manager sees how many
    there are before anything is filed (7, 30 or 90 days before the Page went on) and
    brings in the 30 days: they wait on Cold, given to nobody, with Meta's date, and start
    no first-response clock, no 15-minute alert and no To Call place; a person already a
    lead is left as they are. The lead sent after connecting goes on as before. "Came in
    today" reads when each was sent, and "older=only" lists the older ones."""
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(meta, "Graph", FakeGraph)
    FakeGraph.forms_listed = ["fa", "fb"]
    fresh = {
        **_lead(9, "fa", 0),
        "created_time": time.strftime("%Y-%m-%dT%H:%M:%S+0000", time.gmtime(int(time.time()) + 60)),
    }
    monkeypatch.setitem(LEADS, "fa", [*LEADS["fa"], fresh])
    monkeypatch.setitem(CREATED, fresh["id"], int(time.time()) + 60)
    known = LEADS["fa"][2]  # sent 20 days ago, by a person already a lead for months
    cfg = meta.config()
    assert cfg is not None

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            settings = setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
            install_connectors_http(
                setup.app, RouteContext(settings, setup.require_actor, setup.sessions)
            )
            tenant = setup.state.tenant_id
            async with setup.sessions() as db, db.begin():
                desk = LeadDesk(
                    db,
                    Viewer(
                        person_id=setup.state.person_id,
                        tenant_id=tenant,
                        role="admin",
                        name="Admin",
                    ),
                    now=datetime.now(UTC) - timedelta(days=120),
                )
                record = {answer["name"]: answer["values"][0] for answer in known["field_data"]}
                await desk.ingest(record, source="manual", actor=setup.state.person_id)
                db.add(
                    LeadSource(
                        id=uuid4(),
                        tenant_id=tenant,
                        kind="meta",
                        label="Meta · Fictional Homes",
                        token_sha256=None,
                        config={
                            "page_id": "p1",
                            "page_name": "Fictional Homes",
                            "token": meta.seal(cfg.token_key, "page-token-1", page_id="p1"),
                            "forms": "all",
                        },
                        active=False,
                        received=0,
                        created_by_person_id=setup.state.person_id,
                        created_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                    )
                )

            def kept(lead: Lead) -> tuple[Any, ...]:
                return (lead.stage, lead.next_action_at, lead.repeats, lead.pipeline, lead.revision)

            async with setup.sessions() as db:
                earlier = await db.scalar(select(Lead).where(Lead.source == "manual"))
                assert earlier is not None
                before = kept(earlier)

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                on = await client.post(f"{META}/pages/p1", json={}, headers=WRITE)
                assert on.status_code == 200, on.text
                async with setup.sessions() as db, db.begin():
                    source = await db.scalar(select(LeadSource).where(LeadSource.kind == "meta"))
                    assert source is not None
                    source.config = {**source.config, "last_pulled_at": 1}
                await meta_pull.pull_due(setup.sessions, cfg, FakeGraph(cfg), now=int(time.time()))

                # How many, before anything is filed: 1 and 3 days; then 20; then 45 and 80.
                counted = await client.get(f"{META}/pages/p1/older")
                assert counted.status_code == 200, counted.text
                assert counted.json()["counts"] == [
                    {"days": 7, "leads": 2},
                    {"days": 30, "leads": 3},
                    {"days": 90, "leads": 5},
                ]
                assert counted.json()["capped"] is False
                async with setup.sessions() as db:
                    assert await db.scalar(select(func.count()).select_from(Lead)) == 2

                older = await client.post(
                    f"{META}/pages/p1/backfill", json={"days": 30}, headers=WRITE
                )
                assert older.status_code == 200, older.text
                assert older.json()["imported"] == 2  # 1 and 3 days; the 20-day one is known
                run_view = older.json()["page"]["backfill"]
                assert run_view["state"] == "done" and run_view["days"] == 30
                assert run_view["repeat"] == 1
                wrong = await client.post(
                    f"{META}/pages/p1/backfill", json={"days": 14}, headers=WRITE
                )
                assert wrong.status_code == 422

                def names(page: httpx.Response) -> set[str]:
                    assert page.status_code == 200, page.text
                    return {row["name"] for row in page.json()["leads"]}

                listed = await client.get(
                    "/v1/lead-desk/leads", params={"scope": "team", "older": "only"}
                )
                older_names = names(listed)
                assert older_names == {"Test Lead 1", "Test Lead 2"}
                assert {row["side"] for row in listed.json()["leads"]} == {"cold"}

                today = await client.get(
                    "/v1/lead-desk/leads", params={"scope": "team", "created": "today"}
                )
                assert names(today) == {"Test Lead 9"}
                month = await client.get(
                    "/v1/lead-desk/leads", params={"scope": "team", "created": "month"}
                )
                assert older_names < names(month)

                to_call = await client.get(
                    "/v1/lead-desk/leads",
                    params={"scope": "team", "side": "inbound", "view": "to_call"},
                )
                assert not older_names & names(to_call)

            older_refs = {LEADS["fa"][0]["id"], LEADS["fa"][1]["id"]}
            async with setup.sessions() as db:
                leads = {lead.source_ref: lead for lead in (await db.scalars(select(Lead))).all()}
                for ref in older_refs:
                    lead = leads[ref]
                    assert lead.pipeline == "cold" and lead.owner_person_id is None
                    assert lead.assigned_at is None and lead.stage == "new"
                    assert lead.received_at is not None
                    assert lead.received_at.timestamp() == CREATED[ref]
                assert leads[fresh["id"]].pipeline != "cold"
                earlier = await db.scalar(select(Lead).where(Lead.source == "manual"))
                assert earlier is not None and kept(earlier) == before
                repeats = await db.scalar(
                    select(func.count()).select_from(LeadEvent).where(LeadEvent.kind == "repeat")
                )
                assert repeats == 0
                given = await db.scalar(
                    select(func.count())
                    .select_from(LeadEvent)
                    .where(
                        LeadEvent.kind.in_(("assigned", "reassigned")),
                        LeadEvent.lead_id.in_([leads[ref].id for ref in older_refs]),
                    )
                )
                assert given == 0

                # An hour on, nobody has called anyone: the lead sent after connecting is
                # late on the first-response clock and on the 15-minute alert; the older
                # enquiries, filed in the same minute, are on neither.
                later = datetime.now(UTC) + timedelta(hours=1)
                older_ids = {leads[ref].id for ref in older_refs}
                clocks = await sla.overdue(
                    db, tenant, sla.SlaSettings(True, 15, True), {}, now=later
                )
                assert {clock.lead_id for clock in clocks} == {leads[fresh["id"]].id}
                late = {
                    item.subject
                    for item in await owner_alerts.over_limit(
                        db, tenant, "first_call", {}, now=later
                    )
                }
                assert leads[fresh["id"]].id in late and not late & older_ids
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_a_wrong_facebook_account_is_disconnected_and_an_old_page_removed(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Owner, 2 Nov 2026: a wrong Facebook account brought in many Pages, and old Pages
    cluttered the list. Each Page says which account shared it, since when, and whether a
    real form has sent it a lead. Disconnecting the account stops all its Pages (Meta is
    told, the token is dropped, the pull skips them) and drops the workspace's connection
    when it is that account's; the leads they brought stay. Removing a Page switches it off
    and marks it removed, and putting it back keeps it off."""
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(meta, "Graph", FakeGraph)
    FakeGraph.unsubscribed = []
    cfg = meta.config()
    assert cfg is not None

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            settings = setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
            install_connectors_http(
                setup.app, RouteContext(settings, setup.require_actor, setup.sessions)
            )
            tenant = setup.state.tenant_id
            wrong = {"id": "77", "name": "Fictional Wrong Account"}
            right = {"id": "88", "name": "Fictional Right Account", "at": 1790000000}

            def page(page_id: str, name: str, account: dict[str, Any], on: bool) -> LeadSource:
                return LeadSource(
                    id=uuid4(),
                    tenant_id=tenant,
                    kind="meta",
                    label=f"Meta · {name}",
                    token_sha256=None,
                    config={
                        "page_id": page_id,
                        "page_name": name,
                        "token": meta.seal(cfg.token_key, "page-token-1", page_id=page_id),
                        "forms": "all",
                        "account": account,
                    },
                    active=on,
                    received=0,
                    created_by_person_id=setup.state.person_id,
                    created_at=datetime(2026, 10, 20, tzinfo=UTC),
                    updated_at=datetime.now(UTC),
                )

            async with setup.sessions() as db, db.begin():
                db.add_all(
                    [
                        page("p1", "Fictional Homes", wrong, True),
                        page("p2", "Fictional Old Page", wrong, False),
                        page("p3", "Fictional Clinic", right, True),
                    ]
                )
                db.add(
                    LeadDeskSettings(
                        tenant_id=tenant,
                        revision=1,
                        config={"meta_connection": {"account": "77", "at": 1}},
                        updated_by_person_id=None,
                        updated_at=datetime.now(UTC),
                    )
                )
                desk = LeadDesk(
                    db,
                    Viewer(
                        person_id=setup.state.person_id,
                        tenant_id=tenant,
                        role="admin",
                        name="Admin",
                    ),
                )
                await desk.ingest(
                    {"full_name": "Fictional Buyer", "phone": "+919999033333"},
                    source="meta",
                    source_label="Meta · Fictional Homes",
                    source_ref="200000000000001",
                    actor=None,
                )
                await desk.ingest(
                    {"full_name": "Meta Test Person", "phone": "+919999044444"},
                    source="meta",
                    source_label="Meta · Fictional Clinic",
                    source_ref="200000000000002",
                    actor=None,
                    test_data=True,
                )

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                status = (await client.get(f"{META}/status")).json()
                pages = {page["pageId"]: page for page in status["pages"]}
                assert set(pages) == {"p1", "p2", "p3"}
                assert pages["p1"]["realLeads"] is True and pages["p3"]["realLeads"] is False
                assert pages["p1"]["account"]["id"] == "77"
                # Kept before accounts had a time: its first Page's; else the time kept.
                assert pages["p2"]["account"]["connectedAt"].startswith("2026-10-20")
                assert pages["p3"]["account"]["connectedAt"].startswith("2026-09-21")

                gone = await client.post(f"{META}/accounts/77/disconnect", headers=WRITE)
                assert gone.status_code == 200, gone.text
                assert [page["pageId"] for page in gone.json()["pages"]] == ["p3"]
                assert FakeGraph.unsubscribed == ["p1"]  # the Page that was on
                again = await client.post(f"{META}/accounts/77/disconnect", headers=WRITE)
                assert again.status_code == 404
                hidden = await client.post(f"{META}/pages/p1/pull", headers=WRITE)
                assert hidden.status_code == 404

                removed = await client.post(f"{META}/pages/p3/remove", headers=WRITE)
                assert removed.status_code == 200, removed.text
                assert removed.json()["removed"] is True and removed.json()["active"] is False
                listed = (await client.get(f"{META}/status")).json()["pages"]
                assert [(page["pageId"], page["removed"]) for page in listed] == [("p3", True)]
                back = await client.post(f"{META}/pages/p3/restore", headers=WRITE)
                assert back.status_code == 200, back.text
                assert back.json()["removed"] is False and back.json()["active"] is False

            async with setup.sessions() as db:
                sources = {
                    source.config["page_id"]: source
                    for source in (await db.scalars(select(LeadSource))).all()
                }
                for page_id in ("p1", "p2"):
                    assert sources[page_id].active is False
                    assert "token" not in sources[page_id].config
                    assert sources[page_id].config["disconnected_at"] > 0
                assert "token" in sources["p3"].config
                assert await db.scalar(select(func.count()).select_from(Lead)) == 2
                row = await db.get(LeadDeskSettings, tenant)
                assert row is not None and "meta_connection" not in row.config
            # The pull reads only Pages that are on: none now.
            assert await meta_pull.pull_due(setup.sessions, cfg, FakeGraph(cfg), now=1) == 0
        finally:
            await setup.engine.dispose()

    run(exercise())
