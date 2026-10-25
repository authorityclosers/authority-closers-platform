"""Admin bug work by API, CLI and MCP (owner, 26 Oct 2026: "admin api, cli, mcp"; v0.93):
- Admin's report routes take a number as well as an id;
- POST /v1/admin/bugs/mcp: list_bugs (words masked, no reporter email), get_bug (the words),
  set_bug_status (Admin's own change, audited, naming a staff key);
- a key with bugs:read only sees no set_bug_status and cannot change a report;
- ac-bugs' in-environment module lists reports masked and reads one.
Made-up people only."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from ac_platform.audit.models import AuditEvent
from ac_platform.bug_reports import admin_tools, issues_cli
from ac_platform.bug_reports import http as bug_http
from ac_platform.bug_reports.store import BugReportStore
from ac_platform.http.routes import RouteContext
from tests.database.test_bug_reports_postgresql import _Admitted, _new
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
WORDS = "Leads list empty after sign-in; call me on 9876543210 or a.person@example.test"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def _rpc(method: str, params: dict[str, Any] | None = None, ident: int = 1) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": ident, "method": method, "params": params or {}}


def test_tools_mask_lists_change_through_admin_and_respect_the_key(
    postgres_harness: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(bug_http, "ConversationProviderAdmin", _Admitted)
    monkeypatch.setattr(bug_http, "require_admin_surface", lambda request, settings: None)

    async def exercise() -> tuple[Any, int]:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            async with setup.sessions() as db, db.begin():
                created = await BugReportStore(db).create(
                    replace(_new(setup.state.person_id, setup.state.tenant_id), words=WORDS),
                    bug_id=uuid4(),
                    now=setup.state.now,
                )
                number = created.number

            # The module, with a key holding bugs:read only, then one holding both.
            reader = SimpleNamespace(scopes=["bugs:read"], name="Agents read", prefix="acs_r1")
            writer = SimpleNamespace(
                scopes=["bugs:read", "bugs:write"], name="Agents", prefix="acs_w1"
            )
            actor = SimpleNamespace(
                person_id=setup.state.person_id, tenant_id=setup.state.tenant_id, session_id=None
            )
            async with setup.sessions() as db, db.begin():
                listed = await admin_tools.answer(db, actor, reader, _rpc("tools/list"))
                assert listed is not None
                names = [tool["name"] for tool in listed["result"]["tools"]]
                assert names == ["list_bugs", "get_bug"]
                found = await admin_tools.answer(
                    db,
                    actor,
                    reader,
                    _rpc("tools/call", {"name": "list_bugs", "arguments": {"status": "all"}}),
                )
                assert found is not None
                reports = found["result"]["structuredContent"]["reports"]
                mine = next(item for item in reports if item["number"] == number)
                assert "9876543210" not in json.dumps(found)
                assert "a.person@example.test" not in json.dumps(found)
                assert "[phone]" in mine["words"] and "[email]" in mine["words"]
                one = await admin_tools.answer(
                    db,
                    actor,
                    reader,
                    _rpc("tools/call", {"name": "get_bug", "arguments": {"number": number}}),
                )
                assert one is not None
                assert one["result"]["structuredContent"]["report"]["words"] == WORDS
                refused = await admin_tools.answer(
                    db,
                    actor,
                    reader,
                    _rpc(
                        "tools/call",
                        {
                            "name": "set_bug_status",
                            "arguments": {"number": number, "status": "fixed"},
                        },
                    ),
                )
                assert refused is not None and refused["result"]["isError"] is True
                assert "bugs:write" in refused["result"]["content"][0]["text"]
                closed = await admin_tools.answer(
                    db,
                    actor,
                    writer,
                    _rpc(
                        "tools/call",
                        {
                            "name": "set_bug_status",
                            "arguments": {"number": number, "status": "closed"},
                        },
                    ),
                )
                assert closed is not None and closed["result"]["isError"] is True
                fixed = await admin_tools.answer(
                    db,
                    actor,
                    writer,
                    _rpc(
                        "tools/call",
                        {
                            "name": "set_bug_status",
                            "arguments": {"number": number, "status": "fixed", "note": "In v0.93."},
                        },
                    ),
                )
                assert fixed is not None and fixed["result"]["isError"] is False
                report = fixed["result"]["structuredContent"]["report"]
                assert report["status"] == "fixed"
                assert [event["kind"] for event in report["history"]][-2:] == ["status", "note"]
                missing = await admin_tools.answer(
                    db,
                    actor,
                    writer,
                    _rpc("tools/call", {"name": "get_bug", "arguments": {"number": 999_999}}),
                )
                assert missing is not None and missing["result"]["isError"] is True
                assert (
                    await admin_tools.answer(
                        db, actor, writer, {"jsonrpc": "2.0", "method": "notifications/initialized"}
                    )
                    is None
                )
                started = await admin_tools.answer(
                    db, actor, writer, _rpc("initialize", {"protocolVersion": "2025-06-18"})
                )
                assert started is not None
                assert started["result"]["protocolVersion"] == "2025-06-18"
            async with setup.sessions() as db:
                audit = (
                    await db.scalars(
                        select(AuditEvent).where(AuditEvent.action == "bug_report.changed")
                    )
                ).all()
                assert [event.payload["key"] for event in audit] == [
                    {"name": "Agents", "prefix": "acs_w1"}
                ]

            # Admin's routes by number, and the MCP over HTTP for staff signed in to Admin.
            ctx = RouteContext(
                setup.settings.model_copy(update={"operations_tenant_id": setup.state.tenant_id}),
                setup.require_actor,
                setup.sessions,
            )
            bug_http.install_bug_reports_http(setup.app, ctx)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as http:
                http.cookies.set(setup.settings.session_cookie_name, setup.token)
                by_number = await http.get(f"/v1/admin/bugs/{number}")
                assert by_number.status_code == 200, by_number.text
                assert by_number.json()["status"] == "fixed"
                assert (await http.get("/v1/admin/bugs/999999")).status_code == 404
                verified = await http.post(
                    f"/v1/admin/bugs/{number}/events", json={"status": "verified"}, headers=WRITE
                )
                assert verified.status_code == 200 and verified.json()["status"] == "verified"
                tools = await http.post(
                    "/v1/admin/bugs/mcp", json=_rpc("tools/list"), headers=WRITE
                )
                assert tools.status_code == 200
                assert [tool["name"] for tool in tools.json()["result"]["tools"]] == [
                    "list_bugs",
                    "get_bug",
                    "set_bug_status",
                ]
                assert (await http.get("/v1/admin/bugs/mcp")).status_code == 405
            return setup.engine.url, number
        finally:
            await setup.engine.dispose()

    url, number = run(exercise())
    url_file = tmp_path / "database-url"
    url_file.write_text(url.render_as_string(hide_password=False))

    # ac-bugs without a key: the module lists reports masked and reads one with its words.
    def call(*extra: str) -> tuple[int, dict[str, Any]]:
        code = issues_cli.main(["--database-url-file", str(url_file), *extra])
        return code, json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    code, listed = call("reports", "--status", "all")
    assert code == 0 and "9876543210" not in json.dumps(listed)
    assert any(item["number"] == number for item in listed["items"])
    assert all("email" not in item["person"] for item in listed["items"])
    code, one = call("report", f"#{number}")
    assert code == 0 and one["report"]["words"] == WORDS
    assert "email" not in one["report"]["person"]
