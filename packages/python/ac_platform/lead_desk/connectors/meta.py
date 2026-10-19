"""Meta Lead Ads for the Sales Xray CRM: Continue with Meta, pick Pages and forms, leads arrive.

How it works:
1. A manager presses Continue with Meta. Meta's Facebook Login for Business asks which
   Pages to share (AC's Meta app, configuration ``AC_META_LOGIN_CONFIG_ID``).
2. The callback swaps the code for a long-lived user token and reads the Pages and
   their Page tokens. Each Page becomes a CRM source (kind ``meta``) with its token
   sealed by AES-GCM (``AC_LEAD_DESK_TOKEN_KEY``); it stays off until the manager
   connects it.
3. Connecting a Page subscribes AC's app to the Page's ``leadgen`` field and pulls
   the last week's leads, so the manager sees leads straight away; the rest of what
   Meta still keeps (90 days) follows in the background (``meta_backfill``). Every
   form on the Page is read, so a form made later comes in by itself.
4. For every new lead Meta posts a signed webhook (``X-Hub-Signature-256``, keyed by
   the app secret). The CRM fetches that lead with the Page token and files it through
   ``LeadDesk.ingest``; ``leadgen_id`` is the reference, so a lead is never added twice.

Nothing here runs until the app's settings exist; ``config()`` then returns None and
the Sources tab says it is waiting for AC's Meta app.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from collections.abc import AsyncIterator, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal
from urllib.parse import urlencode
from uuid import UUID

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

GRAPH: Final[str] = "https://graph.facebook.com"
DIALOG: Final[str] = "https://www.facebook.com"
STATE_SECONDS: Final[int] = 15 * 60
LEAD_FIELDS: Final[str] = (
    "id,created_time,field_data,ad_id,ad_name,adset_id,adset_name,campaign_id,"
    "campaign_name,form_id,platform,is_organic"
)
MAX_PAGES: Final[int] = 50
# Meta keeps a form's leads for 90 days; "Bring in older leads" reads all of them.
BACKFILL_DAYS: Final[int] = 90
# Connecting and the scheduled pull read the last week straight away.
PULL_DAYS: Final[int] = 7
PULL_MAX: Final[int] = 1000
PAGE_SIZE: Final[int] = 100
MAX_FORMS: Final[int] = 500

ErrorKind = Literal["token", "permission", "lead_access", "other"]


class MetaError(ValueError):
    """Something about Meta failed; the message is safe to show a manager.

    ``kind`` says what the manager can do about it: connect again (``token``), allow
    the permission (``permission``), let Sales Xray read the Page's leads in Meta's
    Leads Access Manager (``lead_access``), or try again later (``other``).
    """

    def __init__(self, message: str, kind: ErrorKind = "other") -> None:
        super().__init__(message)
        self.kind: ErrorKind = kind


@dataclass(frozen=True, slots=True)
class MetaConfig:
    app_id: str
    app_secret: str
    login_config_id: str
    verify_token: str
    token_key: bytes
    graph_version: str

    @property
    def graph(self) -> str:
        return f"{GRAPH}/{self.graph_version}"


def config(env: Mapping[str, str] | None = None) -> MetaConfig | None:
    """AC's Meta app settings, or None while any is missing (the connector stays off)."""
    env = os.environ if env is None else env
    names = (
        "AC_META_APP_ID",
        "AC_META_APP_SECRET",
        "AC_META_LOGIN_CONFIG_ID",
        "AC_META_WEBHOOK_VERIFY_TOKEN",
        "AC_LEAD_DESK_TOKEN_KEY",
    )
    values = {name: (env.get(name) or "").strip() for name in names}
    if not all(values.values()):
        return None
    try:
        key = base64.urlsafe_b64decode(values["AC_LEAD_DESK_TOKEN_KEY"] + "==")
    except (ValueError, TypeError):
        return None
    if len(key) != 32:
        return None
    return MetaConfig(
        app_id=values["AC_META_APP_ID"],
        app_secret=values["AC_META_APP_SECRET"],
        login_config_id=values["AC_META_LOGIN_CONFIG_ID"],
        verify_token=values["AC_META_WEBHOOK_VERIFY_TOKEN"],
        token_key=key,
        graph_version=(env.get("AC_META_GRAPH_VERSION") or "v23.0").strip(),
    )


# ----- Page tokens at rest ---------------------------------------------------------


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def seal(key: bytes, token: str, *, page_id: str) -> dict[str, str]:
    """AES-GCM with the Page id as associated data: a token can't be moved to another Page."""
    nonce = secrets.token_bytes(12)
    sealed = AESGCM(key).encrypt(nonce, token.encode(), page_id.encode())
    return {"n": _b64(nonce), "c": _b64(sealed)}


def unseal(key: bytes, box: Mapping[str, Any], *, page_id: str) -> str:
    try:
        return (
            AESGCM(key)
            .decrypt(_unb64(str(box["n"])), _unb64(str(box["c"])), page_id.encode())
            .decode()
        )
    except Exception:  # noqa: BLE001 - any failure means the token can't be used
        raise MetaError("Connect this Page with Meta again.", "token") from None


# ----- OAuth state -------------------------------------------------------------------


def make_state(secret: str, *, tenant_id: UUID, person_id: UUID, now: float | None = None) -> str:
    body = {
        "t": str(tenant_id),
        "p": str(person_id),
        "x": int((now or time.time()) + STATE_SECONDS),
        "n": secrets.token_urlsafe(12),
    }
    raw = _b64(json.dumps(body, separators=(",", ":")).encode())
    mac = hmac.new(secret.encode(), raw.encode(), hashlib.sha256).digest()
    return f"{raw}.{_b64(mac)}"


def read_state(
    secret: str, state: str, *, tenant_id: UUID, person_id: UUID, now: float | None = None
) -> None:
    """The state must be ours, unexpired, and from the same person in the same workspace."""
    try:
        raw, mac = state.split(".", 1)
        expected = hmac.new(secret.encode(), raw.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _unb64(mac)):
            raise ValueError("mac")
        body = json.loads(_unb64(raw))
    except (ValueError, TypeError, json.JSONDecodeError):
        raise MetaError("That Meta sign-in didn't come from this page. Start again.") from None
    if int(body.get("x", 0)) < (now or time.time()):
        raise MetaError("That Meta sign-in took too long. Start again.")
    if body.get("t") != str(tenant_id) or body.get("p") != str(person_id):
        raise MetaError("Finish the Meta sign-in in the workspace where you started it.")


def dialog_url(cfg: MetaConfig, *, redirect_uri: str, state: str) -> str:
    query = urlencode(
        {
            "client_id": cfg.app_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "config_id": cfg.login_config_id,
            "response_type": "code",
            "override_default_response_type": "true",
        }
    )
    return f"{DIALOG}/{cfg.graph_version}/dialog/oauth?{query}"


# ----- Webhook -------------------------------------------------------------------------


def signature_ok(app_secret: str, body: bytes, header: str | None) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


@dataclass(frozen=True, slots=True)
class LeadEvent:
    leadgen_id: str
    page_id: str
    form_id: str | None
    ad_id: str | None


def lead_events(payload: Mapping[str, Any]) -> list[LeadEvent]:
    """The new-lead notices in one webhook delivery (Meta batches several)."""
    if payload.get("object") != "page":
        return []
    events: list[LeadEvent] = []
    for entry in payload.get("entry") or []:
        if not isinstance(entry, Mapping):
            continue
        for change in entry.get("changes") or []:
            if not isinstance(change, Mapping) or change.get("field") != "leadgen":
                continue
            value = change.get("value")
            if not isinstance(value, Mapping):
                continue
            leadgen_id = str(value.get("leadgen_id") or "").strip()
            page_id = str(value.get("page_id") or entry.get("id") or "").strip()
            if not leadgen_id or not page_id:
                continue
            form = str(value.get("form_id") or "").strip() or None
            ad = str(value.get("ad_id") or "").strip() or None
            events.append(LeadEvent(leadgen_id, page_id, form, ad))
    return events[:100]


def wants_form(forms: object, form_id: str | None) -> bool:
    """A Page connected for "all" forms takes every lead; otherwise only the chosen forms."""
    if forms in (None, "all"):
        return True
    return isinstance(forms, list) and form_id is not None and form_id in forms


def lead_record(lead: Mapping[str, Any], *, page_name: str) -> dict[str, Any]:
    """One CRM record: every answer (``field_data``) plus Meta's ids, nothing else."""
    record: dict[str, Any] = {}
    if isinstance(lead.get("field_data"), list):
        record["field_data"] = lead["field_data"][:100]
    record["leadgen_id"] = str(lead.get("id") or "")[:200]
    details = {
        name: lead[name]
        for name in (
            "created_time",
            "form_id",
            "ad_id",
            "ad_name",
            "adset_id",
            "adset_name",
            "campaign_id",
            "campaign_name",
            "platform",
            "is_organic",
        )
        if isinstance(lead.get(name), (str, int, bool)) and str(lead[name]).strip()
    }
    if details:
        record["meta"] = details
    record["lead_source"] = f"Meta · {page_name}"[:120]
    return record


# ----- Graph API -----------------------------------------------------------------------

# Meta's Leads Access Manager lets a business choose which CRMs may read a Page's
# leads. Once it is in use, an app that isn't on the list gets a permission error that
# talks about lead access; the manager fixes it in Meta, not here.
LEAD_ACCESS_WORDS: Final[tuple[str, ...]] = ("lead access", "leads access", "leads_access")
LEAD_ACCESS_TEXT: Final[str] = (
    "Your business limits which apps can read this Page's leads (Meta's Leads Access "
    "Manager). Allow Sales Xray there, then press Check now."
)


def graph_error(error: Mapping[str, Any], status: int) -> MetaError:
    """A Graph error as a plain message, with what the manager can do about it."""
    code = error.get("code")
    message = str(error.get("message") or "").casefold()
    if code in (190, 102):
        return MetaError("Meta ended this connection. Connect the Page again.", "token")
    if any(words in message for words in LEAD_ACCESS_WORDS):
        return MetaError(LEAD_ACCESS_TEXT, "lead_access")
    if code in (10, 200, 3, 294) or status == 403:
        return MetaError(
            "Meta didn't give permission for this. Continue with Meta again and allow "
            "the Page and its leads.",
            "permission",
        )
    return MetaError("Meta refused the request. Try again, or connect the Page again.")


class Graph:
    """The few Graph calls the connector needs. Errors become plain MetaError messages."""

    def __init__(self, cfg: MetaConfig, client: httpx.AsyncClient | None = None) -> None:
        self.cfg = cfg
        self._client = client

    async def _call(self, method: str, path: str, **params: Any) -> dict[str, Any]:
        url = f"{self.cfg.graph}/{path.lstrip('/')}"
        client = self._client or httpx.AsyncClient(timeout=20)
        try:
            response = await client.request(
                method,
                url,
                params=params if method == "GET" else None,
                data=params if method != "GET" else None,
            )
        except httpx.HTTPError:
            raise MetaError("Meta didn't answer. Try again in a minute.") from None
        finally:
            if self._client is None:
                await client.aclose()
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code >= 400 or (isinstance(body, dict) and "error" in body):
            error = body.get("error", {}) if isinstance(body, dict) else {}
            raise graph_error(error if isinstance(error, dict) else {}, response.status_code)
        return body if isinstance(body, dict) else {}

    async def _page(
        self, path: str, *, limit: int, after: str | None = None, **params: Any
    ) -> tuple[list[dict[str, Any]], str | None]:
        """One page of a Graph list: its rows, and the cursor for the next page (or None)."""
        body = await self._call(
            "GET", path, limit=limit, **params, **({"after": after} if after else {})
        )
        rows = [dict(row) for row in body.get("data") or [] if isinstance(row, Mapping)]
        paging = body.get("paging")
        paging = paging if isinstance(paging, Mapping) else {}
        cursors = paging.get("cursors")
        cursors = cursors if isinstance(cursors, Mapping) else {}
        more = paging.get("next") and rows and cursors.get("after")
        return rows, str(cursors["after"]) if more else None

    async def _pages(
        self, path: str, *, limit: int, **params: Any
    ) -> AsyncIterator[list[dict[str, Any]]]:
        """A whole Graph list, page by page, at most ``limit`` rows."""
        after: str | None = None
        seen = 0
        while seen < limit:
            rows, after = await self._page(
                path, limit=min(PAGE_SIZE, limit - seen), after=after, **params
            )
            seen += len(rows)
            yield rows
            if after is None:
                return

    async def user_token(self, *, code: str, redirect_uri: str) -> str:
        short = await self._call(
            "GET",
            "oauth/access_token",
            client_id=self.cfg.app_id,
            client_secret=self.cfg.app_secret,
            redirect_uri=redirect_uri,
            code=code,
        )
        token = str(short.get("access_token") or "")
        if not token:
            raise MetaError("Meta didn't finish the sign-in. Start again.")
        long = await self._call(
            "GET",
            "oauth/access_token",
            grant_type="fb_exchange_token",
            client_id=self.cfg.app_id,
            client_secret=self.cfg.app_secret,
            fb_exchange_token=token,
        )
        return str(long.get("access_token") or token)

    async def pages(self, user_token: str) -> list[dict[str, str]]:
        body = await self._call(
            "GET",
            "me/accounts",
            fields="id,name,access_token",
            limit=MAX_PAGES,
            access_token=user_token,
        )
        out = []
        for row in body.get("data") or []:
            if isinstance(row, Mapping) and row.get("id") and row.get("access_token"):
                out.append(
                    {
                        "id": str(row["id"]),
                        "name": str(row.get("name") or row["id"])[:100],
                        "token": str(row["access_token"]),
                    }
                )
        return out[:MAX_PAGES]

    async def forms(self, page_id: str, page_token: str) -> list[dict[str, str]]:
        """Every Instant Form on the Page, archived ones too (their leads stay readable)."""
        out: list[dict[str, str]] = []
        async for rows in self._pages(
            f"{page_id}/leadgen_forms",
            limit=MAX_FORMS,
            fields="id,name,status",
            access_token=page_token,
        ):
            out.extend(
                {
                    "id": str(row["id"]),
                    "name": str(row.get("name") or row["id"])[:120],
                    "status": str(row.get("status") or "")[:20],
                }
                for row in rows
                if row.get("id")
            )
        return out[:MAX_FORMS]

    async def require_lead_access(self, page_id: str, page_token: str) -> None:
        """Refuse in plain words when the Page's business uses Meta's Leads Access Manager
        and hasn't allowed this app. When Meta doesn't say, carry on: reading the leads
        will tell."""
        try:
            body = await self._call(
                "GET",
                page_id,
                fields=f"has_lead_access.app_id({self.cfg.app_id})",
                access_token=page_token,
            )
        except MetaError as error:
            if error.kind in ("token", "lead_access"):
                raise
            return
        access = body.get("has_lead_access")
        if (
            isinstance(access, Mapping)
            and access.get("enabled_lead_access_manager") is True
            and access.get("can_access_lead") is False
        ):
            raise MetaError(LEAD_ACCESS_TEXT, "lead_access")

    async def subscribe(self, page_id: str, page_token: str) -> None:
        body = await self._call(
            "POST",
            f"{page_id}/subscribed_apps",
            subscribed_fields="leadgen",
            access_token=page_token,
        )
        if body.get("success") is not True:
            raise MetaError("Meta didn't switch on leads for this Page. Try again.")

    async def unsubscribe(self, page_id: str, page_token: str) -> None:
        await self._call("DELETE", f"{page_id}/subscribed_apps", access_token=page_token)

    async def lead(self, leadgen_id: str, page_token: str) -> dict[str, Any]:
        return await self._call("GET", leadgen_id, fields=LEAD_FIELDS, access_token=page_token)

    async def leads_page(
        self, form_id: str, page_token: str, *, since: int, after: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        """One page (up to 100) of a form's leads since ``since``, and the next cursor."""
        return await self._page(
            f"{form_id}/leads",
            limit=PAGE_SIZE,
            after=after,
            fields=LEAD_FIELDS,
            filtering=_since(since),
            access_token=page_token,
        )

    async def recent_leads(
        self, form_ids: Iterable[str], page_token: str, *, since: int, limit: int = PULL_MAX
    ) -> list[dict[str, Any]]:
        """Every form's leads since ``since``, page by page, at most ``limit`` in all."""
        out: list[dict[str, Any]] = []
        for form_id in form_ids:
            async for rows in self._pages(
                f"{form_id}/leads",
                limit=limit - len(out),
                fields=LEAD_FIELDS,
                filtering=_since(since),
                access_token=page_token,
            ):
                out.extend(rows)
            if len(out) >= limit:
                break
        return out[:limit]


def _since(since: int) -> str:
    return json.dumps([{"field": "time_created", "operator": "GREATER_THAN", "value": since}])
