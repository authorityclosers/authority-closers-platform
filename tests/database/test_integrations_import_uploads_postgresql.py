"""A CSV of leads to a one-time address, on PostgreSQL (API gap 4, 15 Nov 2026).

A key with leads:write asks for an address; the CSV PUT there without the key queues one
import, which files like any other; the same file to the same address again queues nothing
more; a changed address is refused; and once the key is revoked its address takes nothing.
The MCP tool gives the same kind of address. Fictional leads only.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

import httpx
import pytest
from sqlalchemy import func, select

from ac_platform.http.routes import RouteContext
from ac_platform.integrations import lead_imports
from ac_platform.integrations.api_http import install_integrations_api
from ac_platform.integrations.http import install_integrations_http
from ac_platform.integrations.mcp_http import install_mcp_http
from ac_platform.lead_desk.models import Lead
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
CSV = {"Content-Type": "text/csv"}


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def _csv(count: int) -> bytes:
    rows = ["Name,Mobile,City,External ID"] + [
        f"Upload Lead {n},+9198761{n:05d},Nashik,up-{n}" for n in range(count)
    ]
    return ("\r\n".join(rows) + "\r\n").encode()


def test_a_csv_sent_to_its_one_time_address_queues_one_import(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AC_INTEGRATIONS_SEAL_KEY", base64.urlsafe_b64encode(b"u" * 32).decode())

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            context = RouteContext(setup.settings, setup.require_actor, setup.sessions)
            install_integrations_http(setup.app, context)
            install_integrations_api(setup.app, context)
            install_mcp_http(setup.app, context)
            transport = httpx.ASGITransport(app=setup.app)
            async with (
                httpx.AsyncClient(transport=transport, base_url=ORIGIN) as page,
                httpx.AsyncClient(transport=transport, base_url=ORIGIN) as app,
                httpx.AsyncClient(transport=transport, base_url=ORIGIN) as anyone,
            ):
                page.cookies.set(setup.settings.session_cookie_name, setup.token)
                made = await page.post(
                    "/v1/sales-xray/integrations/keys",
                    headers=WRITE,
                    json={"name": "Fictional uploader", "scopes": ["leads:read", "leads:write"]},
                )
                assert made.status_code == 200, made.text
                bearer = {"Authorization": f"Bearer {made.json()['key']}"}
                address = await app.post(
                    "/v1/api/leads/imports/uploads",
                    headers=bearer,
                    json={"name": "Nashik list", "side": "cold", "assign": "none"},
                )
                assert address.status_code == 201, address.text
                given = address.json()
                assert given["method"] == "PUT" and given["max_rows"] == 10_000
                path = urlsplit(given["upload_url"]).path

                # The CSV, without the key: one import, filed like any other.
                sent = await anyone.put(path, headers=CSV, content=_csv(12))
                assert sent.status_code == 202, sent.text
                job = sent.json()
                assert job["total"] == 12
                again = await anyone.put(path, headers=CSV, content=_csv(12))
                assert again.status_code == 200 and again.json()["id"] == job["id"]
                while await lead_imports.process_next(setup.sessions, app_url=ORIGIN):
                    pass
                done = (await app.get(f"/v1/api/leads/imports/{job['id']}", headers=bearer)).json()
                assert done["status"] == "done" and done["created"] == 12
                async with setup.sessions() as db:
                    made_leads = await db.scalar(
                        select(func.count()).select_from(Lead).where(Lead.name.like("Upload Lead%"))
                    )
                assert made_leads == 12

                # A changed address is refused; a bad file says why.
                body, _, signature = path.rsplit("/", 1)[1].partition(".")
                changed = await anyone.put(
                    path.replace(body, body[:-2] + ("AA" if body[-2:] != "AA" else "BB")),
                    headers=CSV,
                    content=_csv(1),
                )
                assert changed.status_code == 401
                assert changed.json()["error"]["code"] == "upload_address"
                fresh = (
                    await app.post("/v1/api/leads/imports/uploads", headers=bearer, json={})
                ).json()
                second = urlsplit(fresh["upload_url"]).path
                bad = await anyone.put(second, headers=CSV, content=b"Company\r\nFictional Co\r\n")
                assert bad.status_code == 422
                assert bad.json()["error"]["code"] == "upload_columns"

                # The MCP tool gives an address too.
                tool = await app.post(
                    "/v1/mcp",
                    headers=bearer,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": "create_lead_import_upload", "arguments": {}},
                    },
                )
                assert tool.json()["result"]["isError"] is False
                assert (
                    "/v1/api/leads/imports/upload/"
                    in (tool.json()["result"]["structuredContent"]["upload_url"])
                )

                # Once the key is revoked, its addresses take nothing.
                revoked = await page.post(
                    f"/v1/sales-xray/integrations/keys/{made.json()['id']}/revoke", headers=WRITE
                )
                assert revoked.status_code == 200, revoked.text
                late = await anyone.put(second, headers=CSV, content=_csv(3))
                assert late.status_code == 403
                assert late.json()["error"]["code"] == "key_revoked"
        finally:
            await setup.engine.dispose()

    run(exercise())
