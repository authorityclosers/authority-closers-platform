"""Meta Lead Ads in the Sales Xray CRM on PostgreSQL, with Meta's Graph API faked.

Turning a Page on files its last week at once and starts bringing in the rest Meta
keeps (90 days); the puller finishes that in the background; every form on the Page
is covered (a new form too); "Bring in older leads" again adds nothing twice. Leads
imported from a file before the Page was connected are linked, not made repeats.
"""

import base64
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select, update

from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk.connectors import meta, meta_pull
from ac_platform.lead_desk.connectors.http import install_connectors_http
from ac_platform.lead_desk.models import Lead, LeadEvent, LeadMerge, LeadSource
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

    def __init__(self, cfg: meta.MetaConfig, client: Any = None) -> None:
        self.cfg = cfg

    async def require_lead_access(self, page_id: str, page_token: str) -> None:
        assert page_token == "page-token-1"  # noqa: S105 - a fake Page's token

    async def subscribe(self, page_id: str, page_token: str) -> None:
        return None

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


def test_turning_a_page_on_brings_in_all_90_days_and_every_form(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
                assert body["imported"] == 2  # this week's two leads, at once
                page = body["page"]
                assert page["active"] is True and page["forms"] == "all"
                assert [f["name"] for f in page["formsCovered"]] == ["Enquiry"]
                assert page["backfill"]["state"] == "running"

                # A form made after connecting is covered without asking.
                FakeGraph.forms_listed = ["fa", "fb"]
                async with setup.sessions() as db, db.begin():
                    source = await db.scalar(select(LeadSource).where(LeadSource.kind == "meta"))
                    assert source is not None
                    source.config = {
                        **source.config,
                        "backfill": {**source.config["backfill"], "forms": ["fa", "fb"]},
                        "last_pulled_at": 1,
                    }
                pulled = await meta_pull.pull_due(
                    setup.sessions, cfg, FakeGraph(cfg), now=int(time.time())
                )
                assert pulled == 1

                status = (await client.get(f"{META}/status")).json()
                page = status["pages"][0]
                assert page["backfill"]["state"] == "done"
                assert page["backfill"]["created"] == 3  # 20, 45 and 80 days old
                assert [f["name"] for f in page["formsCovered"]] == ["Enquiry", "Site visit"]
                assert page["received"] == 5 and page["problem"] is None

                again = await client.post(f"{META}/pages/p1/backfill", headers=WRITE)
                assert again.status_code == 200, again.text
                assert again.json()["imported"] == 0
                assert again.json()["page"]["backfill"]["state"] == "done"
                assert again.json()["page"]["backfill"]["seen"] == 5

            async with setup.sessions() as db:
                assert await db.scalar(select(func.count()).select_from(Lead)) == 5
                refs = set((await db.scalars(select(Lead.source_ref))).all())
                assert refs == {lead["id"] for leads in LEADS.values() for lead in leads}
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_leads_imported_from_a_file_first_are_linked_not_made_repeats(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Owner's demo prep, 25 Oct 2026: a team imports its Page's leads from a file (one is
    already Lost), then connects the Page. Turning it on, the pull and bringing in older
    leads find the same people: each lead gets one note with its Meta lead id, and no
    follow-up, stage or repeat count changes."""
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
                assert on.json()["imported"] == 0  # this week's two are linked, not new

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
