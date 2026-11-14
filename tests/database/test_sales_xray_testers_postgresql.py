"""The Sales X-Ray tester list on PostgreSQL (owner, 13 Nov 2026; migration 0151).

A person signs in at /testers and joins the waitlist once; the team approves or declines in
Admin -> Testers (never their own application), marks them added to the Google Group, and
the welcome email is queued through the outbox (twice in a row sends one). Installs and
activity come from the account's app sessions; a listed member's production facts stand in
where this environment has none. The list exports as CSV. The table is append-only and the
migration rolls back only while it is empty. Disposable loopback PostgreSQL, fictional rows.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select

from ac_platform.http.routes import RouteContext
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.outbox.models import OutboxEvent
from ac_platform.testers import email as tester_email
from ac_platform.testers import http as tester_http
from ac_platform.testers import store
from ac_platform.testers.models import SalesXrayTesterEvent
from tests.database.test_bug_reports_postgresql import _Admitted
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup

ROOT = Path(__file__).resolve().parents[2]
REVISION, DOWN = "20261113_0151", "20261031_0150"
FILE = "20261113_0151_sales_xray_testers.py"
WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
ME = "/v1/sales-xray/testers/me"
ADMIN = "/v1/admin/testers"
APPLICATION = {"phone_model": "Redmi 13 5G", "role": "seller", "business": "Solar panels"}


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def migration() -> Any:
    path = ROOT / "db/migrations/versions" / FILE
    spec = importlib.util.spec_from_file_location("sales_xray_testers_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_chain_schema_gate_and_forward_recovery_with_history() -> None:
    from scripts.ci.migration_schema_gate import check_operations
    from scripts.ops.migration_safety import classify_source

    module = migration()
    assert (module.revision, module.down_revision) == (REVISION, DOWN)
    path = Path(module.__file__)
    check_operations([classify_source(path.read_text(), str(path))], set())
    module.op = SimpleNamespace(
        execute=lambda statement: None,
        get_bind=lambda: SimpleNamespace(scalar=lambda statement: True),
    )
    with pytest.raises(RuntimeError, match="history requires forward recovery"):
        module.downgrade()


def _install(setup: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tester_http, "ConversationProviderAdmin", _Admitted)
    monkeypatch.setattr(tester_http, "require_admin_surface", lambda request, settings: None)
    settings = setup.settings.model_copy(update={"operations_tenant_id": setup.state.tenant_id})
    tester_http.install_testers_http(
        setup.app, RouteContext(settings, setup.require_actor, setup.sessions)
    )


async def _person(setup: Any, name: str) -> tuple[UUID, str]:
    person_id = uuid4()
    email = f"{name.lower()}-{person_id.hex[:8]}@example.test"
    async with setup.sessions() as db, db.begin():
        db.add(
            Person(
                id=person_id,
                email=email,
                display_name=f"{name} Tester",
                email_verified_at=datetime.now(UTC),
            )
        )
    return person_id, email


async def _app_session(setup: Any, person_id: UUID, *, days_ago: int, version: str) -> None:
    created = datetime.now(UTC) - timedelta(days=days_ago)
    async with setup.sessions() as db, db.begin():
        db.add(
            IdentitySession(
                id=uuid4(),
                person_id=person_id,
                token_hash=uuid4().bytes * 2,
                created_at=created,
                expires_at=created + timedelta(days=30),
                last_seen_at=created + timedelta(minutes=5),
                user_agent=f"Mozilla/5.0 (Linux; Android 14) Chrome/130 SalesXrayApp/{version}",
            )
        )


def _item(page: dict[str, Any], tester_id: str) -> dict[str, Any]:
    return next(item for item in page["items"] if item["id"] == tester_id)


def test_a_tester_applies_is_reviewed_added_emailed_and_seen_in_the_app(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        me = setup.state.person_id
        try:
            _install(setup, monkeypatch)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as http:
                http.cookies.set(setup.settings.session_cookie_name, setup.token)

                # The person: nothing yet, then the waitlist, once, from the page only.
                first = await http.get(ME)
                assert first.status_code == 200, first.text
                assert first.json()["state"] == "none" and "links" not in first.json()
                assert (await http.post(ME, json=APPLICATION)).status_code == 403
                wrong = await http.post(ME, json={**APPLICATION, "role": "boss"}, headers=WRITE)
                assert wrong.status_code == 422
                for _ in range(2):
                    joined = await http.post(ME, json=APPLICATION, headers=WRITE)
                    assert joined.status_code == 200, joined.text
                    assert joined.json()["state"] == "waiting"
                    assert joined.json()["phone_model"] == "Redmi 13 5G"

                # The team's queue; nobody decides on their own application.
                page = (await http.get(ADMIN)).json()
                mine = page["items"][0]
                assert (mine["stage"], mine["role"], mine["business"]) == (
                    "applied",
                    "seller",
                    "Solar panels",
                )
                assert page["counts"]["applied"] == 1 and page["play_needs"] == 12
                own = await http.post(
                    f"{ADMIN}/{mine['id']}/decision", json={"decision": "approve"}, headers=WRITE
                )
                assert own.status_code == 422 and "Someone else" in own.json()["detail"]
                assert (await http.get(f"{ADMIN}?stage=applied")).status_code == 422

                # Another applicant, reviewed by this account.
                ravi, ravi_email = await _person(setup, "Ravi")
                async with setup.sessions() as db, db.begin():
                    standing = await store.apply(
                        db,
                        person_id=ravi,
                        email=ravi_email,
                        name="Ravi Tester",
                        now=datetime.now(UTC),
                        **APPLICATION,
                    )
                ref = str(standing.id)
                early = await http.post(
                    f"{ADMIN}/{ref}/group", json={"send_email": True}, headers=WRITE
                )
                assert early.status_code == 422 and "Approve them first" in early.json()["detail"]
                approved = await http.post(
                    f"{ADMIN}/{ref}/decision",
                    json={"decision": "approve", "note": "Solar seller, Pune"},
                    headers=WRITE,
                )
                assert approved.status_code == 200, approved.text
                assert approved.json()["tester"]["stage"] == "approved"
                not_yet = await http.post(f"{ADMIN}/{ref}/email", headers=WRITE)
                assert not_yet.status_code == 422 and "Google Group" in not_yet.json()["detail"]
                added = await http.post(
                    f"{ADMIN}/{ref}/group", json={"send_email": True}, headers=WRITE
                )
                assert added.status_code == 200, added.text
                tester = added.json()["tester"]
                assert tester["stage"] == "emailed" and tester["email_status"] == "queued"
                assert tester["in_group_via"] == "admin" and tester["emailed_via"] == "app"
                again = await http.post(f"{ADMIN}/{ref}/email", headers=WRITE)
                assert again.status_code == 200

                # One email row, one outbox intent, and the resolver writes to Ravi.
                async with setup.sessions() as db:
                    sent = (
                        await db.scalars(
                            select(SalesXrayTesterEvent).where(
                                SalesXrayTesterEvent.email == ravi_email,
                                SalesXrayTesterEvent.kind == "emailed",
                            )
                        )
                    ).all()
                    assert len(sent) == 1
                    intent = await db.scalar(
                        select(OutboxEvent).where(
                            OutboxEvent.dedupe_key == store.welcome_key(sent[0].id)
                        )
                    )
                    assert intent is not None and intent.event_type == store.WELCOME_EVENT
                    job = SimpleNamespace(kind=store.WELCOME_JOB, payload=intent.payload)
                    message = await tester_email.resolve_tester_welcome_message(
                        db,
                        setup.settings,
                        job,
                        provider_key="outbox:test",  # type: ignore[arg-type]
                    )
                    assert message.to == ravi_email
                    assert message.variables["first_name"] == "Ravi"

                # Ravi opens the app: installed and active, with the app's version.
                await _app_session(setup, ravi, days_ago=1, version="1.0.99")
                seen = _item((await http.get(ADMIN)).json(), ref)
                assert (seen["stage"], seen["app_version"], seen["has_account"]) == (
                    "active",
                    "1.0.99",
                    True,
                )
                assert seen["app_sessions"] == 1

                # A listed member: production's facts stand in on this environment.
                actor = (await _person(setup, "Owner"))[0]
                listed_email = f"listed-{uuid4().hex[:8]}@example.test"
                async with setup.sessions() as db, db.begin():
                    when = datetime.now(UTC)
                    db.add_all(
                        [
                            SalesXrayTesterEvent(
                                id=uuid4(),
                                email=listed_email,
                                kind="listed",
                                actor_person_id=actor,
                                name="Listed Member",
                                facts={
                                    "has_account": True,
                                    "app_sessions": 3,
                                    "first_app_at": "2026-10-24T05:00:00+00:00",
                                    "last_app_at": "2026-10-29T05:00:00+00:00",
                                    "app_version": "1.0.51",
                                },
                                created_at=when,
                            ),
                            SalesXrayTesterEvent(
                                id=uuid4(),
                                email=listed_email,
                                kind="added_to_group",
                                via="seed",
                                actor_person_id=actor,
                                created_at=when + timedelta(microseconds=1),
                            ),
                        ]
                    )
                page = (await http.get(ADMIN)).json()
                listed = next(item for item in page["items"] if item["email"] == listed_email)
                assert (listed["stage"], listed["source"], listed["app_version"]) == (
                    "installed",
                    "listed",
                    "1.0.51",
                )

                # The person's own application, approved and added by someone else: ready.
                async with setup.sessions() as db, db.begin():
                    await store.decide(
                        db,
                        UUID(mine["id"]),
                        decision="approve",
                        actor_person_id=actor,
                        actor_email="owner@example.test",
                        note=None,
                        now=datetime.now(UTC),
                    )
                    await store.mark_added(
                        db,
                        UUID(mine["id"]),
                        actor_person_id=actor,
                        send_email=False,
                        now=datetime.now(UTC),
                    )
                ready = (await http.get(ME)).json()
                assert ready["state"] == "ready"
                assert ready["links"] == {"opt_in": store.OPT_IN_URL, "play": store.PLAY_URL}

                # A declined applicant.
                mona, mona_email = await _person(setup, "Mona")
                async with setup.sessions() as db, db.begin():
                    declined_ref = (
                        await store.apply(
                            db,
                            person_id=mona,
                            email=mona_email,
                            name=None,
                            now=datetime.now(UTC),
                            **APPLICATION,
                        )
                    ).id
                declined = await http.post(
                    f"{ADMIN}/{declined_ref}/decision", json={"decision": "decline"}, headers=WRITE
                )
                assert declined.json()["tester"]["stage"] == "declined"
                assert (
                    await http.post(f"{ADMIN}/{uuid4()}/email", headers=WRITE)
                ).status_code == 404

                # The export: a spreadsheet of the same list.
                export = await http.get(f"{ADMIN}/export.csv")
                assert export.status_code == 200
                assert export.headers["content-type"].startswith("text/csv")
                assert "attachment" in export.headers["content-disposition"]
                lines = export.text.strip().split("\n")
                assert lines[0].startswith("email,name,stage,")
                assert len(lines) == 1 + 4
                assert any(ravi_email in line and ",active," in line for line in lines)

            # Append-only history, and every row names who acted.
            async with setup.sessions() as db:
                kinds = (
                    await db.scalars(
                        select(SalesXrayTesterEvent.kind)
                        .where(SalesXrayTesterEvent.email == ravi_email)
                        .order_by(SalesXrayTesterEvent.created_at)
                    )
                ).all()
                assert list(kinds) == ["applied", "approved", "added_to_group", "emailed"]
                applied = await db.scalar(
                    select(func.count()).where(
                        SalesXrayTesterEvent.person_id == me, SalesXrayTesterEvent.kind == "applied"
                    )
                )
                assert applied == 1
        finally:
            await setup.engine.dispose()

    run(exercise())
