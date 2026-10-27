"""Google Sheets and Drive, slice 1 (owner, 27 Oct 2026: "connect all Google apps… Google
Sheets integration is important"; design docs/product/lead-desk/google-sheets-drive.md).

One Google connection per organisation (``lead_desk_google_connections``), made by an owner
or admin with Continue with Google on the same OAuth client and callback as Google Ads.
Scopes ``openid email profile drive.file`` only: Sales X-Ray sees the files a person picks
in Google's Picker and the files it makes, never the rest of their Drive. The refresh
token is sealed (AES-GCM, bound to the organisation).

- **Import from a Google Sheet:** a Sheet picked in the Picker is read (Sheets API) into the
  same import preview as a file; the import then commits as a file's does.
- **Keep a copy in Google Sheets:** Sales X-Ray makes a "Sales X-Ray · <organisation>"
  folder with a "Sales X-Ray leads" Sheet in it, and every new lead from then on is added
  as a row, once (``lead_desk_sheet_rows``), from the API's minute loop. Turning it off
  stops new rows; the Sheet is the organisation's and stays.

Google is always asked before anything is locked, and nothing waits on it.
"""

from __future__ import annotations

import csv
import io
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote, urlencode
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from ac_platform.lead_desk.connectors import google_ads_api as gads
from ac_platform.lead_desk.contracts import Model

DRIVE_FILE = "https://www.googleapis.com/auth/drive.file"
SCOPES = ("openid", "email", "profile", DRIVE_FILE)
DRIVE = "https://www.googleapis.com/drive/v3/files"
SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"
REVOKE = "https://oauth2.googleapis.com/revoke"
FOLDER = "application/vnd.google-apps.folder"
SPREADSHEET = "application/vnd.google-apps.spreadsheet"
CARD = "google_files"
COPY_COLUMNS = (
    "Received",
    "Name",
    "Phone",
    "Email",
    "City",
    "Source",
    "Stage",
    "Owner",
    "Lead ID",
    "Link",
)
COPY_BATCH = 200
MAX_IMPORT_ROWS = 2000
IST = ZoneInfo("Asia/Kolkata")
_LOCK = (1802, 1301)  # one copy sender across API processes


class GoogleFilesError(ValueError):
    """Something about Google Sheets or Drive failed; the message is safe to show."""


@dataclass(frozen=True, slots=True)
class Picker:
    """What the browser needs to open Google's Picker: never a secret but the short
    access token for this organisation's own connection."""

    client_id: str
    api_key: str
    app_id: str


def picker(cfg: gads.GoogleAdsConfig, env: Mapping[str, str] | None = None) -> Picker | None:
    env = os.environ if env is None else env
    key = (env.get("AC_GOOGLE_PICKER_API_KEY") or "").strip()
    project = (env.get("AC_GOOGLE_PROJECT_NUMBER") or "").strip()
    if not key or not project.isdigit():
        return None
    return Picker(client_id=cfg.client_id, api_key=key, app_id=project)


class CopyView(Model):
    on: bool
    url: str | None = None
    sent: int = 0
    last_sent_at: str | None = None
    # Why the last send failed, in plain words; None once rows go again.
    problem: str | None = None


class FilesStatus(Model):
    """Settings → Connected apps → Google (Sheets and Drive)."""

    # AC's Google app is set up here (else the card says "Coming soon").
    configured: bool
    # Google's file picker is set up (a key and the project number).
    picker: bool
    connected: bool
    email: str | None = None
    connected_by: str | None = None
    folder_url: str | None = None
    copy_: CopyView | None = Field(default=None, alias="copy")


class PickerView(Model):
    """For Google's Picker in the browser: the app's public ids and this connection's
    short-lived access token (an hour), for owners and admins only."""

    client_id: str
    api_key: str
    app_id: str
    access_token: str


class SheetImport(Model):
    spreadsheet_id: str = Field(min_length=10, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    tab: str | None = Field(default=None, max_length=120)


def status(
    cfg: gads.GoogleAdsConfig | None, connection: Any, connected_by: str | None
) -> FilesStatus:
    config = (connection.config or {}) if connection is not None else {}
    copy = config.get("copy") if isinstance(config.get("copy"), dict) else None
    folder = config.get("folder_id")
    return FilesStatus(
        configured=cfg is not None,
        picker=cfg is not None and picker(cfg) is not None,
        connected=connection is not None,
        email=connection.google_email if connection is not None else None,
        connected_by=connected_by,
        folder_url=f"https://drive.google.com/drive/folders/{folder}" if folder else None,
        copy=CopyView(
            on=bool(copy.get("on")),
            url=copy.get("url"),
            sent=int(copy.get("sent") or 0),
            last_sent_at=copy.get("last_sent_at"),
            problem=copy.get("problem"),
        )
        if copy
        else None,
    )


# ----- OAuth ---------------------------------------------------------------------------


def consent_url(cfg: gads.GoogleAdsConfig, *, redirect_uri: str, state: str) -> str:
    """Continue with Google for Sheets and Drive: drive.file only, added to what was given."""
    query = urlencode(
        {
            "client_id": cfg.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "state": state,
        }
    )
    return f"{gads.AUTH}?{query}"


def seal(cfg: gads.GoogleAdsConfig, tenant_id: UUID, refresh_token: str) -> dict[str, str]:
    return gads.seal(cfg.token_key, refresh_token, customer_id=str(tenant_id), what="files")


def unseal(cfg: gads.GoogleAdsConfig, tenant_id: UUID, box: object) -> str:
    try:
        return gads.unseal(cfg.token_key, box, customer_id=str(tenant_id), what="files")
    except gads.GoogleAdsApiError:
        raise GoogleFilesError("Connect Google again.") from None


@dataclass(frozen=True, slots=True)
class Granted:
    refresh_token: str
    access_token: str
    scopes: tuple[str, ...]
    email: str | None


def as_rows(values: object) -> list[list[str]]:
    """A Sheet's values as text rows, the first being its headings."""
    rows: list[list[str]] = []
    for row in values if isinstance(values, list) else []:
        if isinstance(row, list):
            rows.append(["" if cell is None else str(cell) for cell in row])
    return rows


def as_csv(rows: Sequence[Sequence[str]]) -> bytes:
    """Rows as the CSV the import reads: every row as wide as the widest."""
    width = max((len(row) for row in rows), default=0)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    for row in rows:
        writer.writerow([*row, *([""] * (width - len(row)))])
    return buffer.getvalue().encode()


class Files:
    """The few OAuth, Drive and Sheets calls slice 1 needs. Errors become plain messages."""

    def __init__(self, cfg: gads.GoogleAdsConfig, client: httpx.AsyncClient | None = None) -> None:
        self.cfg = cfg
        self._client = client

    async def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        client = self._client or httpx.AsyncClient(timeout=20)
        try:
            return await client.request(method, url, **kwargs)
        except httpx.HTTPError:
            raise GoogleFilesError("Google didn't answer. Try again in a minute.") from None
        finally:
            if self._client is None:
                await client.aclose()

    async def _json(
        self, method: str, url: str, access: str, *, missing: str, **kwargs: Any
    ) -> dict[str, Any]:
        response = await self._send(
            method, url, headers={"Authorization": f"Bearer {access}"}, **kwargs
        )
        if response.status_code == 401:
            raise GoogleFilesError("Google ended this connection. Connect Google again.")
        if response.status_code in {403, 404}:
            raise GoogleFilesError(missing)
        if response.status_code >= 400:
            raise GoogleFilesError("Google didn't answer. Try again in a minute.")
        try:
            body = response.json()
        except ValueError:
            body = {}
        return body if isinstance(body, dict) else {}

    async def _token(self, **form: str) -> dict[str, Any]:
        response = await self._send(
            "POST",
            gads.EXCHANGE,
            data={"client_id": self.cfg.client_id, "client_secret": self.cfg.client_secret, **form},
        )
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code >= 400 or not isinstance(body, dict):
            if isinstance(body, dict) and body.get("error") == "invalid_grant":
                raise GoogleFilesError("Google ended this connection. Connect Google again.")
            raise GoogleFilesError("Google didn't finish the sign-in. Start again.")
        return body

    async def exchange(self, *, code: str, redirect_uri: str) -> Granted:
        body = await self._token(
            grant_type="authorization_code", code=code, redirect_uri=redirect_uri
        )
        refresh = str(body.get("refresh_token") or "")
        access = str(body.get("access_token") or "")
        scopes = tuple(str(body.get("scope") or "").split())
        if not refresh or not access:
            raise GoogleFilesError("Google didn't give lasting access. Connect Google again.")
        if DRIVE_FILE not in scopes:
            raise GoogleFilesError("Allow Sales X-Ray to use the files you choose, then try again.")
        email: str | None = None
        try:
            who = await self._json("GET", USERINFO, access, missing="")
            email = str(who.get("email") or "")[:320] or None
        except GoogleFilesError:
            email = None
        return Granted(refresh, access, scopes, email)

    async def access_token(self, refresh_token: str) -> str:
        body = await self._token(grant_type="refresh_token", refresh_token=refresh_token)
        token = str(body.get("access_token") or "")
        if not token:
            raise GoogleFilesError("Google ended this connection. Connect Google again.")
        return token

    async def revoke(self, token: str) -> None:
        """Best effort: Google forgets the grant; a failure still disconnects here."""
        try:
            await self._send("POST", REVOKE, data={"token": token})
        except GoogleFilesError:
            return

    async def sheet(
        self, access: str, spreadsheet_id: str, tab: str | None
    ) -> tuple[str, str, list[list[str]]]:
        """A picked Sheet's title, the tab read (the one asked for, else the first) and its
        rows."""
        missing = "Sales X-Ray can't open that Sheet. Pick it again in Google's file picker."
        info = await self._json(
            "GET",
            f"{SHEETS}/{quote(spreadsheet_id, safe='')}",
            access,
            missing=missing,
            params={"fields": "properties.title,sheets.properties.title"},
        )
        titles = [
            str(item.get("properties", {}).get("title") or "")
            for item in info.get("sheets") or []
            if isinstance(item, dict)
        ]
        chosen = tab if tab and tab in titles else (titles[0] if titles else None)
        if chosen is None:
            raise GoogleFilesError("That Sheet has no tabs to read.")
        body = await self._json(
            "GET",
            f"{SHEETS}/{quote(spreadsheet_id, safe='')}/values/{quote(chosen, safe='')}",
            access,
            missing=missing,
            params={"majorDimension": "ROWS", "valueRenderOption": "FORMATTED_VALUE"},
        )
        rows = as_rows(body.get("values"))
        if len(rows) > MAX_IMPORT_ROWS + 1:
            raise GoogleFilesError("A Sheet can bring up to 2,000 leads at once. Split it.")
        title = str(info.get("properties", {}).get("title") or "Google Sheet")
        return title, chosen, rows

    async def folder(self, access: str, name: str) -> str:
        made = await self._json(
            "POST",
            DRIVE,
            access,
            missing="Google Drive didn't let Sales X-Ray make its folder.",
            params={"fields": "id"},
            json={"name": name, "mimeType": FOLDER},
        )
        if not made.get("id"):
            raise GoogleFilesError("Google Drive didn't make the folder. Try again.")
        return str(made["id"])

    async def copy_sheet(self, access: str, name: str, folder_id: str) -> tuple[str, str]:
        """A new Sheet in the folder, with the copy's headings; its id and link."""
        made = await self._json(
            "POST",
            DRIVE,
            access,
            missing="Google Drive didn't let Sales X-Ray make the Sheet.",
            params={"fields": "id,webViewLink"},
            json={"name": name, "mimeType": SPREADSHEET, "parents": [folder_id]},
        )
        sheet_id = str(made.get("id") or "")
        if not sheet_id:
            raise GoogleFilesError("Google Drive didn't make the Sheet. Try again.")
        await self._json(
            "PUT",
            f"{SHEETS}/{sheet_id}/values/A1:J1",
            access,
            missing="Sales X-Ray can't write to the Sheet it made.",
            params={"valueInputOption": "RAW"},
            json={"values": [list(COPY_COLUMNS)]},
        )
        url = str(made.get("webViewLink") or f"https://docs.google.com/spreadsheets/d/{sheet_id}")
        return sheet_id, url

    async def append(self, access: str, sheet_id: str, rows: Sequence[Sequence[str]]) -> None:
        await self._json(
            "POST",
            f"{SHEETS}/{sheet_id}/values/A1:append",
            access,
            missing="The copy Sheet is gone or not shared with Sales X-Ray. Make a new copy.",
            params={"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"},
            json={"values": [list(row) for row in rows]},
        )


# ----- The connection --------------------------------------------------------------------


async def live(database: Any, tenant_id: UUID, *, lock: bool = False) -> Any:
    """The organisation's live Google connection, or None."""
    from ac_platform.lead_desk.models import GoogleConnection

    query = select(GoogleConnection).where(
        GoogleConnection.tenant_id == tenant_id, GoogleConnection.revoked_at.is_(None)
    )
    if lock:
        query = query.with_for_update()
    return await database.scalar(query)


async def keep(
    database: Any,
    cfg: gads.GoogleAdsConfig,
    *,
    tenant_id: UUID,
    person_id: UUID,
    granted: Granted,
    now: datetime,
) -> Any:
    """Keep a new sign-in: the live connection takes the new token (its folder and copy
    stay), or a first connection is made."""
    from ac_platform.lead_desk.models import GoogleConnection

    current = await live(database, tenant_id, lock=True)
    sealed = seal(cfg, tenant_id, granted.refresh_token)
    if current is not None:
        current.token = sealed
        current.scopes = list(granted.scopes)
        current.google_email = granted.email
        current.connected_by_person_id = person_id
        current.updated_at = now
        return current
    made = GoogleConnection(
        id=uuid4(),
        tenant_id=tenant_id,
        connected_by_person_id=person_id,
        google_email=granted.email,
        scopes=list(granted.scopes),
        token=sealed,
        config={},
        created_at=now,
        updated_at=now,
        revoked_at=None,
    )
    database.add(made)
    await database.flush()
    return made


# ----- Keep a copy in Google Sheets ----------------------------------------------------------


def copy_of(connection: Any) -> dict[str, Any] | None:
    copy = (connection.config or {}).get("copy") if connection is not None else None
    return copy if isinstance(copy, dict) and copy.get("on") and copy.get("sheet_id") else None


async def send_copies(
    sessions: Any,
    cfg: gads.GoogleAdsConfig | None,
    now: datetime,
    *,
    app_url: str,
    files: Callable[[gads.GoogleAdsConfig], Files] = Files,
) -> int:
    """Add every switched-on copy's new leads to its Sheet; returns how many rows went.

    One sender across API processes (an advisory lock held on its own connection). Leads
    are read and rows built first, Google is asked with no lock held, then the leads sent
    are recorded so each goes once."""
    if cfg is None:
        return 0
    from ac_platform.lead_desk.models import GoogleConnection, Lead, SheetRow
    from ac_platform.lead_desk.store import LeadDesk, Viewer
    from ac_platform.lead_desk.vocabulary import SOURCE_LABELS

    sent = 0
    async with sessions() as holder:
        if not await holder.scalar(select(func.pg_try_advisory_lock(*_LOCK))):
            return 0
        try:
            async with sessions() as database:
                connections = (
                    await database.scalars(
                        select(GoogleConnection).where(GoogleConnection.revoked_at.is_(None))
                    )
                ).all()
            for connection in connections:
                copy = copy_of(connection)
                if copy is None:
                    continue
                sheet_id = str(copy["sheet_id"])
                started = datetime.fromisoformat(str(copy["started_at"]))
                async with sessions() as database:
                    done = select(SheetRow.lead_id).where(
                        SheetRow.tenant_id == connection.tenant_id,
                        SheetRow.spreadsheet_id == sheet_id,
                    )
                    leads = (
                        await database.scalars(
                            select(Lead)
                            .where(
                                Lead.tenant_id == connection.tenant_id,
                                Lead.created_at >= started,
                                Lead.test_data.is_(False),
                                Lead.id.not_in(done),
                            )
                            .order_by(Lead.created_at, Lead.id)
                            .limit(COPY_BATCH)
                        )
                    ).all()
                    if not leads:
                        continue
                    desk = LeadDesk(
                        database,
                        Viewer(
                            person_id=connection.connected_by_person_id,
                            tenant_id=connection.tenant_id,
                            role="system",
                            name="Google Sheets",
                        ),
                        now=now,
                    )
                    names = await desk._names(lead.owner_person_id for lead in leads)
                    rows = []
                    for lead in leads:
                        labels = await desk._labels(lead.pipeline_key or "main")
                        arrived = (lead.received_at or lead.created_at).astimezone(IST)
                        rows.append(
                            [
                                arrived.strftime("%d %b %Y %H:%M"),
                                lead.name,
                                lead.phone or "",
                                lead.email or "",
                                lead.city or "",
                                lead.source_label or SOURCE_LABELS.get(lead.source, lead.source),
                                labels.label(lead.stage, lead.step),
                                names.get(lead.owner_person_id, "") if lead.owner_person_id else "",
                                str(lead.id),
                                f"{app_url}/leads/{lead.id}",
                            ]
                        )
                problem: str | None = None
                try:
                    client = files(cfg)
                    access = await client.access_token(
                        unseal(cfg, connection.tenant_id, connection.token)
                    )
                    await client.append(access, sheet_id, rows)
                except GoogleFilesError as error:
                    problem = str(error)
                async with sessions() as database, database.begin():
                    current = await database.get(GoogleConnection, connection.id)
                    if current is None:
                        continue
                    config = dict(current.config or {})
                    copy_now = dict(config.get("copy") or {})
                    if problem is None:
                        await database.execute(
                            insert(SheetRow)
                            .values(
                                [
                                    {
                                        "id": uuid4(),
                                        "tenant_id": connection.tenant_id,
                                        "spreadsheet_id": sheet_id,
                                        "lead_id": lead.id,
                                        "sent_at": now,
                                    }
                                    for lead in leads
                                ]
                            )
                            .on_conflict_do_nothing(constraint="uq_lead_desk_sheet_row_lead")
                        )
                        copy_now["sent"] = int(copy_now.get("sent") or 0) + len(leads)
                        copy_now["last_sent_at"] = now.isoformat()
                        sent += len(leads)
                    copy_now["problem"] = problem
                    config["copy"] = copy_now
                    current.config = config
                    current.updated_at = now
        finally:
            await holder.scalar(select(func.pg_advisory_unlock(*_LOCK)))
    return sent
