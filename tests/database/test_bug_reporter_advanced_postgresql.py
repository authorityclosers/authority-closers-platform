"""The advanced bug reporter on PostgreSQL (owner, 31 Oct 2026; migration 0149).

Who may use it: platform staff, everyone in the AC organisation and the flagged sandbox
organisations, and anyone the owner lets in after they ask; the owner's take-away holds for
all but staff, and nobody decides for themself. Its parts travel with a report from those
who may use it and are dropped from anyone else; files follow the person's own report in
its first half hour, one place each and no more than the report said, cleaned (pictures
re-encoded, logs scrubbed line by line), and the team reads them in Admin. Both tables are
append-only; the migration rolls back only while they are empty. Disposable loopback
PostgreSQL, fictional rows only.
"""

from __future__ import annotations

import importlib.util
import io
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from PIL import Image
from sqlalchemy import func, select

from ac_platform.bug_reports import access as reporter_access
from ac_platform.bug_reports import http as bug_http
from ac_platform.bug_reports.models import (
    BugReporterAccess,
    BugReportFile,
    BugReportHistoryError,
)
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
)
from ac_platform.http.routes import RouteContext
from ac_platform.identity.models import Person
from ac_platform.tenancy.models import (
    Membership,
    Organisation,
    OrganisationDomainSetting,
    Tenant,
)
from tests.database.test_bug_reports_postgresql import _Admitted, _report
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup

ROOT = Path(__file__).resolve().parents[2]
REVISION, DOWN = "20261031_0149", "20261030_0147"
FILE = "20261031_0149_bug_reporter_advanced.py"
WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
ADMIN = "/v1/admin/bugs"
LEAD = "0b6c2c3e-6a4b-4b8e-9b55-3f0f8f6d2a10"

ADVANCED: dict[str, Any] = {
    "steps": ["Open Leads", "Move a lead to Interested", "   "],
    "comments": [
        {
            "n": 1,
            "note": "The chip stays New for asha@example.test",
            "selector": "li.row > button",
            "testid": "lead-row",
            "components": ["LeadRow", "not a name", "X"],
            "tag": "button",
            "role": "button",
            "label": "Call Asha",
            "box": {"x": 10, "y": 20, "w": 300, "h": 40},
            "on_picture": True,
        },
        {"note": "no number: dropped"},
    ],
    "calls": [
        {
            "method": "POST",
            "path": f"/v1/lead-desk/leads/{LEAD}/stage?token=abc",
            "status": 500,
            "ms": 2400,
            "reference": "req-1234abcd",
            "failed": True,
        },
        {"path": "not a path"},
    ],
    "speed": {"first_byte_ms": 300, "largest_paint_ms": 1800.5, "secret": 1, "memory_mb": True},
    "marked": True,
    "files": 3,
}


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def migration() -> Any:
    path = ROOT / "db/migrations/versions" / FILE
    spec = importlib.util.spec_from_file_location("bug_reporter_advanced_migration", path)
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


def _png() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (640, 320), (20, 120, 110)).save(output, format="PNG")
    return output.getvalue()


def _install(setup: Any, store_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bug_http, "ConversationProviderAdmin", _Admitted)
    monkeypatch.setattr(bug_http, "require_admin_surface", lambda request, settings: None)
    settings = setup.settings.model_copy(
        update={
            "operations_tenant_id": setup.state.tenant_id,
            "sales_xray_storage_root": str(store_root),
        }
    )
    bug_http.install_bug_reports_http(
        setup.app, RouteContext(settings, setup.require_actor, setup.sessions)
    )


def _file(role: str, content_type: str, name: str = "", n: int | None = None) -> dict[str, str]:
    headers = {"Origin": ORIGIN, "Content-Type": content_type, "X-File-Role": role}
    if name:
        headers["X-File-Name"] = name
    if n is not None:
        headers["X-File-N"] = str(n)
    return headers


async def _owner(setup: Any) -> UUID:
    """Someone else, who decides for the person: the owner."""
    owner_id = uuid4()
    async with setup.sessions() as db, db.begin():
        db.add(
            Person(
                id=owner_id,
                email=f"owner-{owner_id.hex}@example.test",
                display_name="Fictional Owner",
                email_verified_at=datetime.now(UTC),
            )
        )
    return owner_id


def test_a_person_asks_and_the_owner_lets_them_in_then_takes_it_away(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_root = tmp_path / "store"
    store_root.mkdir()

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        person = setup.state.person_id
        try:
            _install(setup, store_root, monkeypatch)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as http:
                http.cookies.set(setup.settings.session_cookie_name, setup.token)

                async def access() -> str:
                    answer = await http.get("/v1/bug-reports/advanced")
                    assert answer.status_code == 200, answer.text
                    return str(answer.json()["access"])

                assert await access() == "off"
                # Without access, the parts are dropped and no file follows.
                plain = await http.post(
                    "/v1/bug-reports", json=_report(advanced=ADVANCED), headers=WRITE
                )
                assert plain.status_code == 201, plain.text
                plain_id = plain.json()["bug_id"]
                detail = (await http.get(f"{ADMIN}/{plain_id}")).json()
                assert "advanced" not in detail["context"] and detail["files"] == []
                refused = await http.post(
                    f"/v1/bug-reports/{plain_id}/files",
                    content=_png(),
                    headers=_file("attachment", "image/png"),
                )
                assert refused.status_code == 403

                # Asking: once, from the app only.
                assert (await http.post("/v1/bug-reports/advanced/request")).status_code == 403
                for _ in range(2):
                    asked = await http.post(
                        "/v1/bug-reports/advanced/request", headers={"Origin": ORIGIN}
                    )
                    assert asked.status_code == 200, asked.text
                    assert asked.json() == {"access": "requested"}
                assert await access() == "requested"
                people = (await http.get(f"{ADMIN}/reporter-access")).json()["people"]
                assert [(p["person_id"], p["state"]) for p in people] == [
                    (str(person), "requested")
                ]
                assert people[0]["asked_at"] is not None
                # Nobody decides for themself (this test's person is in Admin too).
                own = await http.post(
                    f"{ADMIN}/reporter-access/{person}", json={"decision": "granted"}, headers=WRITE
                )
                assert own.status_code == 422
                wrong = await http.post(
                    f"{ADMIN}/reporter-access/{person}", json={"decision": "maybe"}, headers=WRITE
                )
                assert wrong.status_code == 422

                owner = await _owner(setup)
                async with setup.sessions() as db, db.begin():
                    await reporter_access.decide(
                        db,
                        person,
                        kind="granted",
                        actor_person_id=owner,
                        note="Tester for the stage editor",
                        now=datetime.now(UTC),
                    )
                assert await access() == "on"
                async with setup.sessions() as db, db.begin():
                    await reporter_access.decide(
                        db,
                        person,
                        kind="revoked",
                        actor_person_id=owner,
                        note=None,
                        now=datetime.now(UTC),
                    )
                assert await access() == "off"
                people = (await http.get(f"{ADMIN}/reporter-access")).json()["people"]
                assert [p["state"] for p in people] == ["revoked"]

            # The history is append-only: three steps, none changed.
            async with setup.sessions() as db:
                rows = (
                    await db.scalars(
                        select(BugReporterAccess)
                        .where(BugReporterAccess.person_id == person)
                        .order_by(BugReporterAccess.created_at)
                    )
                ).all()
                assert [row.kind for row in rows] == ["requested", "granted", "revoked"]
                rows[0].note = "changed"
                with pytest.raises(BugReportHistoryError):
                    await db.flush()
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_the_parts_and_files_follow_a_staff_report_and_admin_reads_them(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_root = tmp_path / "store"
    store_root.mkdir()

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            # Platform staff: a membership outside customer organisations.
            async with setup.sessions() as db, db.begin():
                platform_id = uuid4()
                db.add(Tenant(id=platform_id, slug=platform_id.hex, name="Test operations"))
                await db.flush()
                db.add(
                    Membership(tenant_id=platform_id, person_id=setup.state.person_id, role="admin")
                )
            _install(setup, store_root, monkeypatch)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as http:
                http.cookies.set(setup.settings.session_cookie_name, setup.token)
                assert (await http.get("/v1/bug-reports/advanced")).json() == {"access": "on"}

                report = _report(advanced=ADVANCED)
                report["context"]["trail"] = [
                    {
                        "event": "sx.lead_stage_moved",
                        "at": "2026-10-31T04:30:00.000Z",
                        "route": "/leads",
                        "detail": {"via": "sheet", "to_kind": "interested", "name": "asha"},
                    }
                ]
                sent = await http.post("/v1/bug-reports", json=report, headers=WRITE)
                assert sent.status_code == 201, sent.text
                bug_id = sent.json()["bug_id"]
                detail = (await http.get(f"{ADMIN}/{bug_id}")).json()
                assert detail["context"]["trail"] == [
                    {
                        "event": "sx.lead_stage_moved",
                        "at": "2026-10-31T04:30:00.000Z",
                        "route": "/leads",
                        "detail": {"via": "sheet", "to_kind": "interested"},
                    }
                ]
                assert detail["context"]["advanced"] == {
                    "steps": ["Open Leads", "Move a lead to Interested"],
                    "comments": [
                        {
                            "n": 1,
                            "note": "The chip stays New for [email]",
                            "selector": "li.row > button",
                            "components": ["LeadRow"],
                            "on_picture": True,
                            "testid": "lead-row",
                            "tag": "button",
                            "role": "button",
                            "box": {"x": 10, "y": 20, "w": 300, "h": 40},
                        }
                    ],
                    "calls": [
                        {
                            "path": "/v1/lead-desk/leads/:id/stage?token=",
                            "failed": True,
                            "method": "POST",
                            "status": 500,
                            "ms": 2400,
                            "reference": "req-1234abcd",
                        }
                    ],
                    "speed": {"first_byte_ms": 300.0, "largest_paint_ms": 1800.5},
                    "marked": True,
                    "files": 3,
                }

                url = f"/v1/bug-reports/{bug_id}/files"
                original = await http.post(
                    url, content=_png(), headers=_file("original", "image/png", "screen")
                )
                assert original.status_code == 201, original.text
                assert original.json() == {"position": 1, "content_type": "image/webp"}
                # A part's picture names its comment.
                unnamed = await http.post(
                    url, content=_png(), headers=_file("element", "image/png")
                )
                assert unnamed.status_code == 422
                part = await http.post(
                    url, content=_png(), headers=_file("element", "image/png", "part 1", n=1)
                )
                assert part.status_code == 201, part.text
                assert (
                    await http.post(
                        url, content=b"MZ not a video", headers=_file("attachment", "video/mp4")
                    )
                ).status_code == 422
                log = await http.post(
                    url,
                    content=b"saved for asha@example.test\npassword: hunter22\nok",
                    headers=_file("attachment", "text/plain", "app%20log.txt"),
                )
                assert log.status_code == 201, log.text
                # As many as the report said, and only to one's own report.
                extra = await http.post(
                    url, content=b"more", headers=_file("attachment", "text/plain")
                )
                assert extra.status_code == 409
                stranger = await http.post(
                    f"/v1/bug-reports/{uuid4()}/files",
                    content=b"x",
                    headers=_file("attachment", "text/plain"),
                )
                assert stranger.status_code == 404

                detail = (await http.get(f"{ADMIN}/{bug_id}")).json()
                assert [
                    (f["position"], f["role"], f["part"], f["name"], f["content_type"])
                    for f in detail["files"]
                ] == [
                    (1, "original", None, "screen", "image/webp"),
                    (2, "element", 1, "part 1", "image/webp"),
                    (3, "attachment", None, "app log.txt", "text/plain"),
                ]
                picture = await http.get(f"{ADMIN}/{bug_id}/files/1")
                assert picture.status_code == 200
                assert picture.headers["content-type"] == "image/webp"
                assert picture.headers["content-disposition"] == "inline"
                text = await http.get(f"{ADMIN}/{bug_id}/files/3")
                assert text.text == "saved for [email]\n[secret]\nok"
                assert text.headers["content-disposition"].startswith("attachment")
                assert (await http.get(f"{ADMIN}/{bug_id}/files/9")).status_code == 404

                # After the half hour, the report is as it was sent.
                monkeypatch.setattr(bug_http, "FILE_WINDOW", timedelta(seconds=-1))
                late = await http.post(
                    f"/v1/bug-reports/{bug_id}/files",
                    content=b"late",
                    headers=_file("attachment", "text/plain"),
                )
                assert late.status_code == 409

            async with setup.sessions() as db:
                count = await db.scalar(
                    select(func.count())
                    .select_from(BugReportFile)
                    .where(BugReportFile.bug_id == UUID(bug_id))
                )
                assert count == 3
        finally:
            await setup.engine.dispose()

    run(exercise())


async def _organisation(
    db: Any, *, sandbox_by: UUID | None = None, domains: list[str] | None = None
) -> UUID:
    """A fictional organisation: flagged as a sandbox, or with its verified domains."""
    tenant = uuid4()
    db.add(Tenant(id=tenant, slug=f"fictional-{tenant.hex[:12]}", name="Fictional Org"))
    await db.flush()
    db.add(
        Organisation(
            tenant_id=tenant, creation_command_id=uuid4(), domain_verification_token="t" * 43
        )
    )
    await db.flush()
    if domains is not None:
        db.add(
            OrganisationDomainSetting(
                tenant_id=tenant,
                version=1,
                verified_domains=domains,
                auto_join=False,
                proof={},
                command_id=uuid4(),
            )
        )
    if sandbox_by is not None:
        db.add(
            ConversationSandboxOrganisation(
                tenant_id=tenant,
                approved_by_person_id=sandbox_by,
                approval_reference="test: a fictional sandbox organisation",
                created_at=datetime.now(UTC),
            )
        )
    await db.flush()
    return tenant


def test_the_ac_organisation_and_the_sandbox_organisations_have_it_unless_taken_away(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            owner = await _owner(setup)
            now = datetime.now(UTC)
            people = {name: uuid4() for name in ("tester", "ac", "elsewhere", "left")}
            async with setup.sessions() as db, db.begin():
                for name, person in people.items():
                    db.add(
                        Person(
                            id=person,
                            email=f"{name}-{person.hex}@example.test",
                            display_name=f"Fictional {name.title()}",
                            email_verified_at=now,
                        )
                    )
                await db.flush()
                sandbox = await _organisation(db, sandbox_by=owner)
                ours = await _organisation(db, domains=["AuthorityClosers.com"])
                theirs = await _organisation(db, domains=["example.test"])
                for name, tenant, status in (
                    ("tester", sandbox, "active"),
                    ("ac", ours, "active"),
                    ("elsewhere", theirs, "active"),
                    ("left", ours, "inactive"),
                ):
                    db.add(
                        Membership(
                            tenant_id=tenant, person_id=people[name], role="member", status=status
                        )
                    )

            async def access(name: str) -> str:
                async with setup.sessions() as db:
                    return await reporter_access.access_for(db, people[name])

            assert await access("tester") == "on"
            assert await access("ac") == "on"
            assert await access("elsewhere") == "off"
            assert await access("left") == "off"

            # The owner's take-away still holds for one tester.
            async with setup.sessions() as db, db.begin():
                await reporter_access.decide(
                    db, people["tester"], kind="revoked", actor_person_id=owner, note=None, now=now
                )
            assert await access("tester") == "off"

            # The organisation's newest domain setting stands: without ours, it is off.
            async with setup.sessions() as db, db.begin():
                db.add(
                    OrganisationDomainSetting(
                        tenant_id=ours,
                        version=2,
                        verified_domains=["example.test"],
                        auto_join=False,
                        proof={},
                        command_id=uuid4(),
                    )
                )
            assert await access("ac") == "off"
        finally:
            await setup.engine.dispose()

    run(exercise())
