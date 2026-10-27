"""Google Sheets and Drive, slice 1, on PostgreSQL through the API (owner, 27 Oct 2026),
Google faked: connect on the shared callback, the picker's needs, import from a picked
Sheet, a copy Sheet that gets each new lead once, and Disconnect."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, func, select, update

from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk.connectors import google_ads_api as gads
from ac_platform.lead_desk.connectors import google_files
from ac_platform.lead_desk.connectors.http import install_connectors_http
from ac_platform.lead_desk.models import GoogleConnection, Lead, SheetRow
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, world

KEY = base64.urlsafe_b64encode(b"k" * 32).decode()
ENV = {
    "AC_GOOGLE_ADS_CLIENT_ID": "client-1.apps.googleusercontent.com",
    "AC_GOOGLE_ADS_CLIENT_SECRET": "client-secret",
    "AC_LEAD_DESK_TOKEN_KEY": KEY,
    "AC_GOOGLE_PICKER_API_KEY": "fictional-browser-key",
    "AC_GOOGLE_PROJECT_NUMBER": "123456789012",
}


class FakeFiles:
    """Google, as slice 1 calls it."""

    appended: ClassVar[list[list[str]]] = []
    revoked: ClassVar[list[str]] = []

    def __init__(self, cfg: gads.GoogleAdsConfig, client: Any = None) -> None:
        self.cfg = cfg

    async def exchange(self, *, code: str, redirect_uri: str) -> google_files.Granted:
        assert code == "code-1" and redirect_uri.endswith("/v1/lead-desk/google/callback")
        return google_files.Granted(
            "refresh-1", "access-1", google_files.SCOPES, "owner@example.com"
        )

    async def access_token(self, refresh_token: str) -> str:
        assert refresh_token == "refresh-1"  # noqa: S105 - a fake token
        return "access-2"

    async def revoke(self, token: str) -> None:
        self.revoked.append(token)

    async def sheet(self, access: str, spreadsheet_id: str, tab: str | None) -> Any:
        rows = [
            ["Name", "Phone"],
            ["Fictional Sheet A", "98760 85001"],
            ["Fictional Sheet B", "98760 85002"],
        ]
        return "Fictional leads", tab or "Leads", rows

    async def folder(self, access: str, name: str) -> str:
        assert name.startswith("Sales X-Ray · ")
        return "folder-1"

    async def copy_sheet(self, access: str, name: str, folder_id: str) -> tuple[str, str]:
        assert folder_id == "folder-1"
        return "sheet-1", "https://docs.google.com/spreadsheets/d/sheet-1"

    async def append(self, access: str, sheet_id: str, rows: Any) -> None:
        assert sheet_id == "sheet-1"
        self.appended.extend(list(row) for row in rows)


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_google_sheets_and_drive_slice_one(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(google_files, "Files", FakeFiles)
    FakeFiles.appended.clear()
    FakeFiles.revoked.clear()

    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            settings = here.setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
            install_connectors_http(
                here.setup.app,
                RouteContext(settings, here.setup.require_actor, here.setup.sessions),
            )
            # Sellers don't see it.
            here.as_seller()
            assert (await here.client.get(f"{BASE}/google/files")).status_code == 403
            here.as_admin()
            before = (await here.client.get(f"{BASE}/google/files")).json()
            assert before["configured"] and before["picker"] and not before["connected"]

            # Continue with Google: the files you choose, back on the shared callback.
            started = await here.client.get(f"{BASE}/google/files/connect?format=json")
            assert started.status_code == 200, started.text
            query = parse_qs(urlsplit(started.json()["url"]).query)
            assert google_files.DRIVE_FILE in query["scope"][0]
            back = await here.client.get(
                f"{BASE}/google/callback", params={"code": "code-1", "state": query["state"][0]}
            )
            assert back.status_code == 303, back.text
            assert "connected=google_files" in back.headers["location"]
            status = (await here.client.get(f"{BASE}/google/files")).json()
            assert status["connected"] and status["email"] == "owner@example.com"
            async with here.setup.sessions() as db:
                row = await db.scalar(select(GoogleConnection))
                assert row is not None and "refresh-1" not in str(row.token)

            # The picker's needs, with this connection's short token.
            picker = (await here.client.get(f"{BASE}/google/picker")).json()
            assert picker == {
                "client_id": ENV["AC_GOOGLE_ADS_CLIENT_ID"],
                "api_key": ENV["AC_GOOGLE_PICKER_API_KEY"],
                "app_id": ENV["AC_GOOGLE_PROJECT_NUMBER"],
                "access_token": "access-2",
            }

            # A picked Sheet comes into the import preview like a file.
            preview = await here.client.post(
                f"{BASE}/imports/google-sheet",
                json={"spreadsheet_id": "sheet_picked_123", "tab": "Leads"},
                headers=WRITE,
            )
            assert preview.status_code == 200, preview.text
            assert preview.json()["file_name"] == "Fictional leads · Leads.csv"
            assert len(preview.json()["rows"]) == 2

            # Keep a copy: before it, a lead stays out; after it, each new lead goes once.
            early = await here.add("Fictional Before Copy", "98760 85010")
            here.as_admin()
            on = await here.client.post(f"{BASE}/google/sheet-copy", headers=WRITE)
            assert on.status_code == 200, on.text
            copy = on.json()["copy"]
            assert copy["on"] and copy["url"].endswith("/sheet-1")
            assert on.json()["folder_url"].endswith("/folder-1")
            async with here.setup.sessions() as db, db.begin():
                await db.execute(
                    update(Lead)
                    .where(Lead.id == UUID(early))
                    .values(created_at=datetime.now(UTC) - timedelta(minutes=5))
                )
            here.as_admin()
            await here.add("Fictional After One", "98760 85011")
            await here.add("Fictional After Two", "98760 85012")
            here.as_admin()
            cfg = gads.config()

            async def send() -> int:
                return await google_files.send_copies(
                    here.setup.sessions,
                    cfg,
                    datetime.now(UTC),
                    app_url="https://x.test",
                    files=FakeFiles,
                )

            assert await send() == 2
            names = [row[1] for row in FakeFiles.appended]
            assert names == ["Fictional After One", "Fictional After Two"]
            assert FakeFiles.appended[0][9].startswith("https://x.test/leads/")
            assert await send() == 0
            async with here.setup.sessions() as db:
                assert await db.scalar(select(func.count()).select_from(SheetRow)) == 2
            status = (await here.client.get(f"{BASE}/google/files")).json()
            assert status["copy"]["sent"] == 2 and status["copy"]["problem"] is None

            # Off: no more rows; the Sheet stays the organisation's.
            off = await here.client.delete(f"{BASE}/google/sheet-copy", headers=WRITE)
            assert off.json()["copy"]["on"] is False
            here.as_admin()
            await here.add("Fictional While Off", "98760 85013")
            here.as_admin()
            assert await send() == 0

            # Disconnect: Google is asked to forget the grant, and nothing is sent.
            gone = await here.client.post(f"{BASE}/google/files/disconnect", headers=WRITE)
            assert gone.status_code == 200, gone.text
            assert gone.json()["connected"] is False
            assert FakeFiles.revoked == ["refresh-1"]
            assert (await here.client.get(f"{BASE}/google/picker")).status_code == 409

    run(exercise())
