"""Google Sheets and Drive, slice 1 (lead_desk/connectors/google_files.py): drive.file only,
the calls Sales X-Ray makes, and the plain words when Google says no. Google is faked."""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import httpx
import pytest

from ac_platform.lead_desk.connectors import google_ads_api as gads
from ac_platform.lead_desk.connectors import google_files

KEY = base64.urlsafe_b64encode(b"k" * 32).decode()
ENV = {
    "AC_GOOGLE_ADS_CLIENT_ID": "client-1.apps.googleusercontent.com",
    "AC_GOOGLE_ADS_CLIENT_SECRET": "client-secret",
    "AC_LEAD_DESK_TOKEN_KEY": KEY,
}
TENANT = UUID(int=7)


def cfg() -> gads.GoogleAdsConfig:
    value = gads.config(ENV)
    assert value is not None
    return value


def files(handler: Any) -> google_files.Files:
    return google_files.Files(cfg(), httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def test_consent_asks_for_the_files_you_choose_and_nothing_more() -> None:
    url = google_files.consent_url(cfg(), redirect_uri="https://x.test/cb", state="s1")
    query = parse_qs(urlsplit(url).query)
    assert query["scope"] == ["openid email profile https://www.googleapis.com/auth/drive.file"]
    assert query["include_granted_scopes"] == ["true"]
    assert query["access_type"] == ["offline"]
    assert "adwords" not in url and "spreadsheets" not in query["scope"][0]


def test_the_picker_needs_its_key_and_project_number() -> None:
    assert google_files.picker(cfg(), {}) is None
    assert google_files.picker(cfg(), {"AC_GOOGLE_PICKER_API_KEY": "k"}) is None
    ids = google_files.picker(
        cfg(), {"AC_GOOGLE_PICKER_API_KEY": "browser-key", "AC_GOOGLE_PROJECT_NUMBER": "1234"}
    )
    assert ids == google_files.Picker("client-1.apps.googleusercontent.com", "browser-key", "1234")


def test_a_sealed_token_opens_only_for_its_organisation() -> None:
    box = google_files.seal(cfg(), TENANT, "refresh-1")
    assert "refresh-1" not in json.dumps(box)
    assert google_files.unseal(cfg(), TENANT, box) == "refresh-1"
    with pytest.raises(google_files.GoogleFilesError):
        google_files.unseal(cfg(), UUID(int=8), box)


def test_the_sign_in_keeps_drive_file_and_the_google_account() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(
                200,
                json={
                    "refresh_token": "r1",
                    "access_token": "a1",
                    "scope": f"openid email {google_files.DRIVE_FILE}",
                },
            )
        assert request.headers["authorization"] == "Bearer a1"
        return httpx.Response(200, json={"email": "owner@example.com"})

    granted = asyncio.run(files(handler).exchange(code="c", redirect_uri="https://x.test/cb"))
    assert granted == google_files.Granted(
        "r1", "a1", ("openid", "email", google_files.DRIVE_FILE), "owner@example.com"
    )

    def no_files(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"refresh_token": "r1", "access_token": "a1", "scope": "openid email"}
        )

    with pytest.raises(google_files.GoogleFilesError, match="files you choose"):
        asyncio.run(files(no_files).exchange(code="c", redirect_uri="https://x.test/cb"))


def test_a_picked_sheet_reads_the_tab_asked_for_or_the_first() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if "/values/" in request.url.path:
            return httpx.Response(
                200, json={"values": [["Name", "Phone"], ["Fictional A", 98760850], [None, "x"]]}
            )
        return httpx.Response(
            200,
            json={
                "properties": {"title": "Fictional leads"},
                "sheets": [{"properties": {"title": "Leads"}}, {"properties": {"title": "Old"}}],
            },
        )

    title, tab, rows = asyncio.run(files(handler).sheet("a", "sheet_1234567890", "Old"))
    assert (title, tab) == ("Fictional leads", "Old")
    assert rows == [["Name", "Phone"], ["Fictional A", "98760850"], ["", "x"]]
    assert seen[-1].endswith("/values/Old")
    assert asyncio.run(files(handler).sheet("a", "sheet_1234567890", "Gone"))[1] == "Leads"
    assert google_files.as_csv(rows) == b"Name,Phone\r\nFictional A,98760850\r\n,x\r\n"


@pytest.mark.parametrize(
    ("status", "words"),
    [
        (401, "Connect Google again"),
        (403, "Pick it again"),
        (404, "Pick it again"),
        (500, "didn't answer"),
    ],
)
def test_google_saying_no_reads_in_plain_words(status: int, words: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={})

    with pytest.raises(google_files.GoogleFilesError, match=words):
        asyncio.run(files(handler).sheet("a", "sheet_1234567890", None))


def test_the_copy_is_a_sheet_in_its_folder_with_headings_then_rows() -> None:
    calls: list[tuple[str, str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        calls.append((request.method, request.url.path, body))
        if request.url.path.endswith("/files") and body.get("mimeType") == google_files.FOLDER:
            return httpx.Response(200, json={"id": "folder-1"})
        if request.url.path.endswith("/files"):
            return httpx.Response(200, json={"id": "sheet-1", "webViewLink": "https://s.test/1"})
        return httpx.Response(200, json={})

    client = files(handler)
    folder = asyncio.run(client.folder("a", "Sales X-Ray · Fictional"))
    sheet = asyncio.run(client.copy_sheet("a", "Sales X-Ray leads · Fictional", folder))
    asyncio.run(client.append("a", "sheet-1", [["1"], ["2"]]))
    assert (folder, sheet) == ("folder-1", ("sheet-1", "https://s.test/1"))
    assert calls[1][2]["parents"] == ["folder-1"]
    assert calls[2][2] == {"values": [list(google_files.COPY_COLUMNS)]}
    assert calls[3][1].endswith("/values/A1:append") and calls[3][2] == {"values": [["1"], ["2"]]}
