"""Bug reports on PostgreSQL (owner, 23 Oct 2026: "bug catcher for everyone").

Migration 0124 passes the schema gate and rolls back only without reports; a tester's report arrives
scrubbed with its picture re-encoded; a retry finds the first report; the team lists,
filters, opens and moves reports through an append-only history, audited; the work-board
module lists reports without a card and records exactly one card each. Disposable loopback
PostgreSQL, fictional rows only; the test's own workspace is the operations workspace.
"""

from __future__ import annotations

import base64
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.models import AuditEvent
from ac_platform.bug_reports import board_cli
from ac_platform.bug_reports import http as bug_http
from ac_platform.bug_reports.models import BugReport, BugReportEvent, BugReportHistoryError
from ac_platform.bug_reports.store import BugReportStore
from ac_platform.http.routes import RouteContext
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup

ROOT = Path(__file__).resolve().parents[2]
REVISION, DOWN = "20261023_0124", "20261023_0123"
FILE = "20261023_0124_bug_reports.py"
WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
ADMIN = "/v1/admin/bugs"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


class _Admitted:
    def __init__(self, application: Any) -> None:
        pass

    async def admit(self, actor: Any) -> None:
        return None


def migration() -> Any:
    path = ROOT / "db/migrations/versions" / FILE
    spec = importlib.util.spec_from_file_location("bug_reports_migration", path)
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


def _picture() -> str:
    image = Image.new("RGB", (2400, 1200), (20, 120, 110))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode()


def _report(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "command_id": str(uuid4()),
        "words": "Tapped Call on a lead and nothing happened.",
        "blocks_work": True,
        "route": "/leads?lead=8f0e&tab=stages&code=123456&token=abc#frag",
        "area": "calls",
        "context": {
            "app": {"channel": "android", "version": "0.85.0", "native_version": "0.3.88"},
            "device": {
                "os": "Android 14",
                "browser": "Chrome 141",
                "viewport": "390x844",
                "touch": True,
                "secret_field": "never kept",
            },
            "cookies": "never kept",
        },
        "client_errors": [
            {
                "kind": "http",
                "status": 500,
                "method": "POST",
                "path": "/v1/lead-desk/leads?email=asha@example.test",
                "message": "Bearer abcdefghijklmnop failed for asha@example.test +91 98765 43210",
                "reference": "req-1234abcd",
            },
            {"kind": "unknown", "message": "dropped"},
            {"kind": "console", "message": "token=supersecretvalue"},
        ],
    }
    body.update(overrides)
    return body


def test_a_tester_reports_a_bug_and_the_team_works_it(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bug_http, "ConversationProviderAdmin", _Admitted)
    monkeypatch.setattr(bug_http, "require_admin_surface", lambda request, settings: None)
    store_root = tmp_path / "store"
    store_root.mkdir()

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            ctx = RouteContext(
                setup.settings.model_copy(
                    update={
                        "operations_tenant_id": setup.state.tenant_id,
                        "sales_xray_storage_root": str(store_root),
                    }
                ),
                setup.require_actor,
                setup.sessions,
            )
            bug_http.install_bug_reports_http(setup.app, ctx)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as http:
                http.cookies.set(setup.settings.session_cookie_name, setup.token)

                first = _report(
                    screenshot={"content_type": "image/png", "data": _picture(), "source": "auto"}
                )
                sent = await http.post("/v1/bug-reports", json=first, headers=WRITE)
                assert sent.status_code == 201, sent.text
                assert sent.json()["screenshot"] == "kept"
                bug_id = sent.json()["bug_id"]
                again = await http.post("/v1/bug-reports", json=first, headers=WRITE)
                assert again.status_code == 200
                assert again.json() == {"bug_id": bug_id, "screenshot": "kept", "voice": "none"}

                # Not from the app's own page, or nothing said: refused.
                no_origin = await http.post(
                    "/v1/bug-reports",
                    json=_report(),
                    headers={"Content-Type": "application/json"},
                )
                assert no_origin.status_code == 403
                blank = await http.post(
                    "/v1/bug-reports", json=_report(words="   \x00 "), headers=WRITE
                )
                assert blank.status_code == 422
                # A picture that is not an image: the report is kept without it.
                second = await http.post(
                    "/v1/bug-reports",
                    json=_report(
                        words="Report took ages to open",
                        blocks_work=False,
                        route="/analysis/calls/2b1f",
                        screenshot={
                            "content_type": "image/png",
                            "data": base64.b64encode(b"not a picture at all").decode(),
                            "source": "upload",
                        },
                    ),
                    headers=WRITE,
                )
                assert second.status_code == 201, second.text
                assert second.json()["screenshot"] == "skipped"
                second_id = second.json()["bug_id"]

                listing = (await http.get(ADMIN)).json()
                assert [item["bug_id"] for item in listing["items"]] == [second_id, bug_id]
                assert listing["counts"]["new"] == 2
                assert listing["next_offset"] is None
                first_row = listing["items"][1]
                # The route decides the area; the device's hint only fills gaps.
                assert first_row["area"] == "leads"
                assert listing["items"][0]["area"] == "report"
                assert first_row["blocks_work"] is True and first_row["has_screenshot"] is True
                assert first_row["organisation"]["id"] == str(setup.state.tenant_id)
                assert [o["count"] for o in listing["organisations"]] == [2]
                leads = (await http.get(ADMIN, params={"area": "leads"})).json()
                assert [item["bug_id"] for item in leads["items"]] == [bug_id]
                assert (await http.get(ADMIN, params={"status": "fixed"})).json()["items"] == []
                for bad in ({"status": "done"}, {"severity": "urgent"}, {"tenant": "x"}):
                    assert (await http.get(ADMIN, params=bad)).status_code == 422

                detail = (await http.get(f"{ADMIN}/{bug_id}")).json()
                assert detail["route"] == "/leads?lead=8f0e&tab=stages&code=&token="
                assert detail["context"]["app"] == {
                    "channel": "android",
                    "version": "0.85.0",
                    "native_version": "0.3.88",
                }
                assert "secret_field" not in detail["context"]["device"]
                assert "cookies" not in detail["context"]
                assert detail["context"]["server"]["environment"] == "test"
                errors = detail["client_errors"]
                assert [error["kind"] for error in errors] == ["http", "console"]
                assert "asha@example.test" not in str(errors)
                assert errors[0]["message"] == "Bearer [token] failed for [email] [phone]"
                assert errors[0]["path"] == "/v1/lead-desk/leads?email="
                assert errors[1]["message"] == "[secret]"
                assert detail["screenshot"]["content_type"] == "image/webp"
                assert [event["status"] for event in detail["history"]] == ["new"]

                picture = await http.get(f"{ADMIN}/{bug_id}/screenshot")
                assert picture.status_code == 200
                assert picture.headers["content-type"] == "image/webp"
                assert picture.headers["cache-control"].startswith("private")
                with Image.open(io.BytesIO(picture.content)) as kept:
                    assert kept.format == "WEBP" and max(kept.size) == 1600
                    assert not kept.info.get("exif")
                missing = await http.get(f"{ADMIN}/{second_id}/screenshot")
                assert missing.status_code == 404

                moved = await http.post(
                    f"{ADMIN}/{bug_id}/events",
                    json={"status": "triaged", "severity": "high", "note": "Seen on a test phone"},
                    headers=WRITE,
                )
                assert moved.status_code == 200, moved.text
                body = moved.json()
                assert (body["status"], body["severity"]) == ("triaged", "high")
                assert [event["kind"] for event in body["history"]] == [
                    "status",
                    "status",
                    "severity",
                    "note",
                ]
                close = await http.post(
                    f"{ADMIN}/{second_id}/events", json={"status": "closed"}, headers=WRITE
                )
                assert close.status_code == 422
                same = await http.post(
                    f"{ADMIN}/{bug_id}/events", json={"status": "triaged"}, headers=WRITE
                )
                assert len(same.json()["history"]) == 4
                fixed = await http.post(
                    f"{ADMIN}/{bug_id}/events",
                    json={"status": "fixed", "area": "calls"},
                    headers=WRITE,
                )
                assert (fixed.json()["status"], fixed.json()["area"]) == ("fixed", "calls")
                still_open = (await http.get(ADMIN, params={"status": "open"})).json()
                assert [item["bug_id"] for item in still_open["items"]] == [second_id]
                assert still_open["counts"]["fixed"] == 1

                # A person sends at most twelve an hour.
                codes = [
                    (await http.post("/v1/bug-reports", json=_report(), headers=WRITE)).status_code
                    for _ in range(11)
                ]
                assert codes[:10] == [201] * 10 and codes[10] == 429
            async with setup.sessions() as db:
                audited = (
                    await db.execute(
                        select(AuditEvent.action, AuditEvent.payload)
                        .where(AuditEvent.resource_type == "bug_report")
                        .order_by(AuditEvent.sequence_no)
                    )
                ).all()
            assert [payload["changed"] for _, payload in audited] == [
                ["status", "severity", "note"],
                ["status", "area"],
            ]
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_reports_and_their_history_are_append_only(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            async with setup.sessions() as db, db.begin():
                store = BugReportStore(db)
                await store.create(
                    _new(setup.state.person_id, setup.state.tenant_id),
                    bug_id=(bug_id := uuid4()),
                    now=setup.state.now,
                )
            async with AsyncSession(setup.engine) as db:
                row = await db.get(BugReport, bug_id)
                assert row is not None and row.number >= 1
                row.words = "changed"
                with pytest.raises(BugReportHistoryError):
                    await db.flush()
                await db.rollback()
                event = await db.scalar(
                    select(BugReportEvent).where(BugReportEvent.bug_id == bug_id)
                )
                assert event is not None
                await db.delete(event)
                with pytest.raises(BugReportHistoryError):
                    await db.flush()
        finally:
            await setup.engine.dispose()

    run(exercise())


def _new(person_id: Any, tenant_id: Any) -> Any:
    from ac_platform.bug_reports.store import NewReport

    return NewReport(
        person_id=person_id,
        tenant_id=tenant_id,
        command_id=uuid4(),
        words="The Leads list is empty after sign-in.",
        blocks_work=False,
        area="leads",
        route="/leads",
        context={"app": {"channel": "web"}, "device": {}},
        client_errors=[],
        user_agent="test",
    )


def test_the_board_module_raises_one_card_per_report(
    postgres_harness: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    async def seed() -> tuple[Any, Any]:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            ids = []
            for _ in range(2):
                async with setup.sessions() as db, db.begin():
                    row = await BugReportStore(db).create(
                        _new(setup.state.person_id, setup.state.tenant_id),
                        bug_id=uuid4(),
                        now=setup.state.now,
                    )
                    ids.append(row.id)
            return ids, setup.engine.url
        finally:
            await setup.engine.dispose()

    ids, url = run(seed())
    url_file = tmp_path / "database-url"
    url_file.write_text(url.render_as_string(hide_password=False))
    arguments = ["--database-url-file", str(url_file)]

    def call(*extra: str) -> tuple[int, dict[str, Any]]:
        code = board_cli.main([*arguments, *extra])
        return code, json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    code, pending = call("pending")
    assert code == 0
    listed = [item["bug_id"] for item in pending["reports"]]
    assert listed[-2:] == [str(ids[0]), str(ids[1])]
    sample = pending["reports"][-1]
    assert "person" not in sample and "organisation" not in sample
    assert call("mark", str(ids[0]), "AUT-9001") == (
        0,
        {"bug_id": str(ids[0]), "card": "AUT-9001", "recorded": True},
    )
    assert call("mark", str(ids[0]), "AUT-9002")[1]["recorded"] is False
    assert call("mark", str(ids[1]), "not a card")[0] == 1
    code, pending = call("pending")
    assert str(ids[0]) not in [item["bug_id"] for item in pending["reports"]]
    assert str(ids[1]) in [item["bug_id"] for item in pending["reports"]]
