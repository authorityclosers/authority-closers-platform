"""Many leads at once through the API (owner, 14 Nov 2026: "pushing thousands of leads using
Claude"): POST /v1/api/leads/imports queues a job; the importer files it in chunks through
the Lead Desk's own file import, so dedupe, the per-row report and Undo import behave as a
file uploaded in the app. Fictional leads only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select

from ac_platform.audit.models import AuditEvent
from ac_platform.http.routes import RouteContext
from ac_platform.integrations import admin_http, lead_imports
from ac_platform.integrations.api_http import install_integrations_api
from ac_platform.integrations.http import install_integrations_http
from ac_platform.integrations.import_models import IntegrationLeadImportChunk
from ac_platform.lead_desk.models import Lead
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
PAGE = "/v1/sales-xray/integrations"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def _leads(count: int, *, start: int = 0) -> list[dict[str, str]]:
    return [
        {
            "name": f"Sample Lead {n}",
            "phone": f"+9198760{n:05d}",
            "city": "Pune",
            "external_id": f"ext-{n}",
        }
        for n in range(start, start + count)
    ]


async def _file_all(setup: Any) -> int:
    filed = 0
    while await lead_imports.process_next(setup.sessions, app_url=ORIGIN):
        filed += 1
    return filed


async def _key(client: httpx.AsyncClient, name: str) -> tuple[str, str]:
    made = await client.post(
        f"{PAGE}/keys",
        headers=WRITE,
        json={"name": name, "scopes": ["leads:read", "leads:write"]},
    )
    assert made.status_code == 200, made.text
    return made.json()["key"], made.json()["id"]


def test_a_key_imports_hundreds_of_leads_with_a_report_row_by_row(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            context = RouteContext(setup.settings, setup.require_actor, setup.sessions)
            install_integrations_http(setup.app, context)
            install_integrations_api(setup.app, context)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as page:
                page.cookies.set(setup.settings.session_cookie_name, setup.token)
                key, _ = await _key(page, "Bulk importer")
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
                ) as app:
                    bearer = {"Authorization": f"Bearer {key}"}
                    # A lead already here, with the number row 40 will bring.
                    already = await app.post(
                        "/v1/api/leads",
                        headers=bearer,
                        json={"name": "Already Here", "phone": "+919876000040"},
                    )
                    assert already.status_code == 201, already.text
                    leads = _leads(600)
                    leads[10]["phone"] = leads[9]["phone"]  # the same person twice in the file
                    leads[20] = {"external_id": "ext-20"}  # nothing to file
                    leads[30]["phone"] = "12"  # a number nobody can call
                    body = {"name": "Fictional list", "leads": leads, "side": "cold"}
                    first = await app.post(
                        "/v1/api/leads/imports",
                        headers={**bearer, "Idempotency-Key": "fictional-list-1"},
                        json=body,
                    )
                    assert first.status_code == 202, first.text
                    job = first.json()
                    assert job["status"] == "queued" and job["total"] == 600
                    assert job["processed"] == 0
                    # The same request again is the same job; other rows under the key, 409.
                    again = await app.post(
                        "/v1/api/leads/imports",
                        headers={**bearer, "Idempotency-Key": "fictional-list-1"},
                        json=body,
                    )
                    assert again.status_code == 200
                    assert again.json()["id"] == job["id"] and again.json()["replayed"] is True
                    other = await app.post(
                        "/v1/api/leads/imports",
                        headers={**bearer, "Idempotency-Key": "fictional-list-1"},
                        json={**body, "name": "Another list"},
                    )
                    assert other.status_code == 409
                    assert other.json()["error"]["code"] == "idempotency_reused"
                    waiting = await app.get(
                        f"/v1/api/leads/imports/{job['id']}/rows?outcome=waiting&limit=5",
                        headers=bearer,
                    )
                    assert [row["row"] for row in waiting.json()["rows"]] == [0, 1, 2, 3, 4]

                    assert await _file_all(setup) == 3  # 250 + 250 + 100 rows
                    done = await app.get(f"/v1/api/leads/imports/{job['id']}", headers=bearer)
                    assert done.status_code == 200, done.text
                    view = done.json()
                    assert view["status"] == "done" and view["processed"] == 600
                    assert (view["created"], view["skipped"], view["failed"]) == (596, 4, 0)
                    assert view["finished_at"] and view["undo_until"]
                    skipped = await app.get(
                        f"/v1/api/leads/imports/{job['id']}/rows?outcome=skipped",
                        headers=bearer,
                    )
                    reasons = {row["row"]: row["reason"] for row in skipped.json()["rows"]}
                    assert set(reasons) == {10, 20, 30, 40}
                    assert reasons[10] == "Repeated in the file"
                    assert reasons[40] == "Already a lead"
                    assert all(row["lead_id"] is None for row in skipped.json()["rows"])
                    # Every row, in order, a page at a time.
                    seen: list[int] = []
                    after = -1
                    while True:
                        rows = await app.get(
                            f"/v1/api/leads/imports/{job['id']}/rows?limit=250&after={after}",
                            headers=bearer,
                        )
                        seen += [row["row"] for row in rows.json()["rows"]]
                        after = rows.json()["next_after"]
                        if after is None:
                            break
                    assert seen == list(range(600))
                    created = (
                        await app.get(
                            f"/v1/api/leads/imports/{job['id']}/rows?outcome=created&limit=1",
                            headers=bearer,
                        )
                    ).json()["rows"][0]
                    assert created == {
                        "row": 0,
                        "external_id": "ext-0",
                        "outcome": "created",
                        "reason": None,
                        "lead_id": created["lead_id"],
                    }
                    listed = await app.get("/v1/api/leads/imports", headers=bearer)
                    assert [item["id"] for item in listed.json()["imports"]] == [job["id"]]

                    # The rows are gone once filed; only the outcomes stay.
                    async with setup.sessions() as db:
                        held = await db.scalar(
                            select(func.count())
                            .select_from(IntegrationLeadImportChunk)
                            .where(IntegrationLeadImportChunk.rows.is_not(None))
                        )
                        assert held == 0
                        cold = await db.scalar(
                            select(func.count())
                            .select_from(Lead)
                            .where(
                                Lead.tenant_id == setup.state.tenant_id,
                                Lead.source_ref.like("ref:ext-%"),
                                Lead.pipeline == "cold",
                            )
                        )
                        assert cold == 596

                    # The same external ids again are the same leads: nothing new.
                    repeat = await app.post(
                        "/v1/api/leads/imports",
                        headers=bearer,
                        json={"name": "Fictional list again", "leads": _leads(50)},
                    )
                    assert repeat.status_code == 202, repeat.text
                    assert await _file_all(setup) == 1
                    second = (
                        await app.get(
                            f"/v1/api/leads/imports/{repeat.json()['id']}", headers=bearer
                        )
                    ).json()
                    # Rows 10, 20 and 30 were skipped the first time, so their ids are new now.
                    assert (second["created"], second["skipped"]) == (3, 47)

                # The owner undoes the first import in the app: all its parts at once.
                history = await page.get("/v1/lead-desk/imports")
                assert history.status_code == 200, history.text
                undone = await page.post(
                    f"/v1/lead-desk/imports/{job['id']}/undo",
                    headers=WRITE,
                    json={"command_id": str(uuid4())},
                )
                assert undone.status_code == 200, undone.text
                assert undone.json()["removed"] == 596
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_a_revoked_key_stops_its_waiting_rows_and_a_busy_workspace_waits(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            context = RouteContext(setup.settings, setup.require_actor, setup.sessions)
            install_integrations_http(setup.app, context)
            install_integrations_api(setup.app, context)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as page:
                page.cookies.set(setup.settings.session_cookie_name, setup.token)
                key, key_id = await _key(page, "Short lived")
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
                ) as app:
                    bearer = {"Authorization": f"Bearer {key}"}
                    queued = await app.post(
                        "/v1/api/leads/imports",
                        headers=bearer,
                        json={"leads": _leads(30, start=1000)},
                    )
                    assert queued.status_code == 202, queued.text
                    monkeypatch.setattr(lead_imports, "MAX_WAITING", 1)
                    busy = await app.post(
                        "/v1/api/leads/imports", headers=bearer, json={"leads": _leads(5)}
                    )
                    assert busy.status_code == 429
                    assert busy.json()["error"]["code"] == "imports_busy"
                    revoked = await page.post(f"{PAGE}/keys/{key_id}/revoke", headers=WRITE)
                    assert revoked.status_code == 200, revoked.text
                    assert await _file_all(setup) == 1
                # The key no longer reads; the job says what happened, row by row.
                async with setup.sessions() as db:
                    chunk = await db.scalar(select(IntegrationLeadImportChunk))
                    assert chunk is not None and chunk.state == "failed"
                    assert chunk.rows is None and chunk.error == "door_closed"
                    outcomes = {row["outcome"] for row in chunk.result["rows"]}
                    assert outcomes == {"failed"}
                    made = await db.scalar(
                        select(func.count())
                        .select_from(Lead)
                        .where(Lead.source_ref.like("ref:ext-1%"))
                    )
                    assert made == 0
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_platform_admins_see_every_import_and_stop_one(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """Admin (owner, 14 Nov 2026: "Admin-level strongness"): every organisation's imports with
    what waits and failed, an import's problem rows without a lead's details, and Stop,
    audited in the organisation's own chain."""

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            context = RouteContext(setup.settings, setup.require_actor, setup.sessions)
            install_integrations_http(setup.app, context)
            install_integrations_api(setup.app, context)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as page:
                page.cookies.set(setup.settings.session_cookie_name, setup.token)
                key, _ = await _key(page, "Runaway script")
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
                ) as app:
                    queued = await app.post(
                        "/v1/api/leads/imports",
                        headers={"Authorization": f"Bearer {key}"},
                        json={"name": "Too many", "leads": _leads(300, start=2000)},
                    )
                    assert queued.status_code == 202, queued.text
            import_id = UUID(queued.json()["id"])
            async with setup.sessions() as db, db.begin():
                before = await admin_http.imports_overview(
                    db, operations_tenant_id=None, personal_tenant_id=None, now=datetime.now(UTC)
                )
                assert before["counts"]["rows_waiting"] == 300
                assert [item["id"] for item in before["imports"]] == [str(import_id)]
                assert before["imports"][0]["label"].startswith("API key sxk_test_")
                stopped = await admin_http.stop_import(
                    db, import_id=import_id, actor=setup.state.actor, now=datetime.now(UTC)
                )
                assert stopped["status"] == "failed" and stopped["failed"] == 300
            # Nothing waits; the rows are gone; each row says why; the owners see who.
            assert await _file_all(setup) == 0
            async with setup.sessions() as db, db.begin():
                problems = await admin_http.import_problems(db, import_id)
                assert len(problems["problems"]) == 300
                assert {row["reason"] for row in problems["problems"]} == {
                    "Stopped by Sales X-Ray support"
                }
                assert set(problems["problems"][0]) == {
                    "row",
                    "external_id",
                    "outcome",
                    "reason",
                    "lead_id",
                }
                held = await db.scalar(
                    select(func.count())
                    .select_from(IntegrationLeadImportChunk)
                    .where(IntegrationLeadImportChunk.rows.is_not(None))
                )
                assert held == 0
                audited = await db.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(
                        AuditEvent.tenant_id == setup.state.tenant_id,
                        AuditEvent.action == "integration.lead_import_stopped",
                    )
                )
                assert audited == 1
                after = await admin_http.imports_overview(
                    db, operations_tenant_id=None, personal_tenant_id=None, now=datetime.now(UTC)
                )
                assert after["counts"]["rows_waiting"] == 0
                assert after["counts"]["rows_failed_24h"] == 300
        finally:
            await setup.engine.dispose()

    run(exercise())
