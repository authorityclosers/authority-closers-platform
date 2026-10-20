"""Google Ads lead forms for the Sales Xray CRM: Continue with Google, turn an account on.

How it works (the same shape as ``connectors.meta``):
1. A manager presses Continue with Google. Google asks to share Google Ads
   (scope ``adwords``) with AC's Google Ads app (``AC_GOOGLE_ADS_CLIENT_ID``).
2. The callback swaps the code for a refresh token and lists the Ads accounts the
   person can reach (directly or under a manager account). Each account becomes a
   CRM source of kind ``webhook`` with ``config.connector = "google_ads"``: its
   refresh token and its own webhook key are sealed by AES-GCM
   (``AC_LEAD_DESK_TOKEN_KEY``); only the key's SHA-256 is the source's key. It
   stays off until the manager turns it on.
3. Turning an account on writes AC's webhook (address + key) into each of its lead
   forms that has no other webhook, so Google posts each new lead to
   ``/capture/{source}/google-ads`` within seconds, and pulls the last 30 days.
4. Every 10 minutes the pull reads the account's newest lead form submissions
   (``lead_form_submission_data``): the safety net for a webhook Google drops and
   for forms that send to someone else's webhook.

A lead that arrives both ways is filed once: both carry Google's click id
(``gclid``), which is the lead's reference (see ``google_ads.reference``).

Nothing here runs until the app's settings exist; ``config()`` then returns None
and the Sources tab says Google Ads is coming soon.
"""

from __future__ import annotations

import base64
import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from urllib.parse import urlencode
from uuid import UUID

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ac_platform.lead_desk.connectors import meta

AUTH: Final[str] = "https://accounts.google.com/o/oauth2/v2/auth"
EXCHANGE: Final[str] = "https://oauth2.googleapis.com/token"
ADS: Final[str] = "https://googleads.googleapis.com"
SCOPE: Final[str] = "https://www.googleapis.com/auth/adwords"
CONNECTOR: Final[str] = "google_ads"
PAYLOAD_SCHEMA: Final[int] = 3
MAX_ACCOUNTS: Final[int] = 50
BACKFILL_DAYS: Final[int] = 30
PULL_MAX: Final[int] = 500
SUBMISSIONS: Final[str] = (
    "SELECT lead_form_submission_data.id, lead_form_submission_data.asset, "
    "lead_form_submission_data.campaign, lead_form_submission_data.ad_group, "
    "lead_form_submission_data.gclid, lead_form_submission_data.submission_date_time, "
    "lead_form_submission_data.lead_form_submission_fields, "
    "lead_form_submission_data.custom_lead_form_submission_fields "
    "FROM lead_form_submission_data"
)


class GoogleAdsApiError(ValueError):
    """Something about Google Ads failed; the message is safe to show a manager."""


@dataclass(frozen=True, slots=True)
class GoogleAdsConfig:
    client_id: str
    client_secret: str
    developer_token: str
    token_key: bytes
    api_version: str

    @property
    def api(self) -> str:
        return f"{ADS}/{self.api_version}"


def config(env: Mapping[str, str] | None = None) -> GoogleAdsConfig | None:
    """AC's Google Ads app settings, or None while any is missing (the connector stays off)."""
    env = os.environ if env is None else env
    names = (
        "AC_GOOGLE_ADS_CLIENT_ID",
        "AC_GOOGLE_ADS_CLIENT_SECRET",
        "AC_GOOGLE_ADS_DEVELOPER_TOKEN",
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
    return GoogleAdsConfig(
        client_id=values["AC_GOOGLE_ADS_CLIENT_ID"],
        client_secret=values["AC_GOOGLE_ADS_CLIENT_SECRET"],
        developer_token=values["AC_GOOGLE_ADS_DEVELOPER_TOKEN"],
        token_key=key,
        api_version=(env.get("AC_GOOGLE_ADS_API_VERSION") or "v25").strip(),
    )


def is_connector(source: Any) -> bool:
    """A CRM source made by Continue with Google (not a by-hand lead form webhook)."""
    config = getattr(source, "config", None) or {}
    return getattr(source, "kind", None) == "webhook" and config.get("connector") == CONNECTOR


# ----- Secrets at rest ---------------------------------------------------------------


def seal(key: bytes, secret: str, *, customer_id: str, what: str) -> dict[str, str]:
    """AES-GCM bound to the account and the kind of secret: a box can't be moved."""
    nonce = secrets.token_bytes(12)
    sealed = AESGCM(key).encrypt(nonce, secret.encode(), f"gads:{what}:{customer_id}".encode())
    return {"n": meta._b64(nonce), "c": meta._b64(sealed)}


def unseal(key: bytes, box: object, *, customer_id: str, what: str) -> str:
    if not isinstance(box, Mapping):
        raise GoogleAdsApiError("Connect this Google Ads account again.")
    try:
        return (
            AESGCM(key)
            .decrypt(
                meta._unb64(str(box["n"])),
                meta._unb64(str(box["c"])),
                f"gads:{what}:{customer_id}".encode(),
            )
            .decode()
        )
    except Exception:  # noqa: BLE001 - any failure means the secret can't be used
        raise GoogleAdsApiError("Connect this Google Ads account again.") from None


# ----- OAuth -------------------------------------------------------------------------


def make_state(
    cfg: GoogleAdsConfig,
    *,
    tenant_id: UUID,
    person_id: UUID,
    app_challenge: str | None = None,
    card: str | None = None,
) -> str:
    return meta.make_state(
        cfg.client_secret,
        tenant_id=tenant_id,
        person_id=person_id,
        app_challenge=app_challenge,
        card=card,
    )


def peek_state(cfg: GoogleAdsConfig, state: str) -> dict[str, Any]:
    try:
        return meta.peek_state(cfg.client_secret, state)
    except meta.MetaError as error:
        raise GoogleAdsApiError(str(error).replace("Meta", "Google")) from None


def read_state(
    cfg: GoogleAdsConfig, state: str, *, tenant_id: UUID, person_id: UUID
) -> dict[str, Any]:
    try:
        return meta.read_state(cfg.client_secret, state, tenant_id=tenant_id, person_id=person_id)
    except meta.MetaError as error:
        raise GoogleAdsApiError(str(error).replace("Meta", "Google")) from None


def consent_url(cfg: GoogleAdsConfig, *, redirect_uri: str, state: str) -> str:
    query = urlencode(
        {
            "client_id": cfg.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
    )
    return f"{AUTH}?{query}"


# ----- Shapes --------------------------------------------------------------------------


def _id(resource: object) -> str:
    """The last part of a resource name: customers/1/campaigns/22 -> 22."""
    return str(resource or "").rstrip("/").rsplit("/", 1)[-1]


def webhook_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    """One ``lead_form_submission_data`` row in the shape Google's webhook posts.

    ``google_ads.to_record`` then reads it exactly like a webhook lead, so both ways
    keep the same answers under the same names.
    """
    data = row.get("leadFormSubmissionData") or {}
    columns: list[dict[str, str]] = []
    for field in data.get("leadFormSubmissionFields") or []:
        if isinstance(field, Mapping) and field.get("fieldValue") is not None:
            columns.append(
                {
                    "column_id": str(field.get("fieldType") or ""),
                    "string_value": str(field["fieldValue"]),
                }
            )
    for field in data.get("customLeadFormSubmissionFields") or []:
        if isinstance(field, Mapping) and field.get("fieldValue") is not None:
            columns.append(
                {
                    "column_name": str(field.get("questionText") or ""),
                    "string_value": str(field["fieldValue"]),
                }
            )
    payload: dict[str, Any] = {"user_column_data": columns}
    for name, value in (
        ("lead_id", data.get("id")),
        ("gcl_id", data.get("gclid")),
        ("form_id", _id(data.get("asset")) if data.get("asset") else None),
        ("campaign_id", _id(data.get("campaign")) if data.get("campaign") else None),
        ("adgroup_id", _id(data.get("adGroup")) if data.get("adGroup") else None),
        ("lead_submit_time", data.get("submissionDateTime")),
    ):
        if value not in (None, ""):
            payload[name] = str(value)
    return payload


@dataclass(frozen=True, slots=True)
class Account:
    customer_id: str
    name: str
    login_customer_id: str | None
    test: bool


@dataclass(frozen=True, slots=True)
class LeadForm:
    resource_name: str
    form_id: str
    name: str
    webhook_url: str | None
    webhook_secret: str | None


def webhook_plan(form: LeadForm, *, url: str, key: str) -> str:
    """What turning an account on does to one form: "set", "ok" or "other".

    A form already sending to someone else's address (a Zapier hook, another CRM)
    keeps it; the 10-minute pull still brings its leads.
    """
    if not form.webhook_url:
        return "set"
    if form.webhook_url != url:
        return "other"
    return "ok" if form.webhook_secret == key else "set"


def since_text(since: int) -> str:
    """GAQL date filter for the pull: a whole day early, because Google reads the
    filter in the account's own time zone. Repeats are filed once anyway."""
    day = datetime.fromtimestamp(since, UTC) - timedelta(days=1)
    return day.strftime("%Y-%m-%d 00:00:00")


# ----- API -------------------------------------------------------------------------------


class Ads:
    """The few OAuth and Google Ads API calls the connector needs. Errors become plain messages."""

    def __init__(self, cfg: GoogleAdsConfig, client: httpx.AsyncClient | None = None) -> None:
        self.cfg = cfg
        self._client = client

    async def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        client = self._client or httpx.AsyncClient(timeout=20)
        try:
            return await client.request(method, url, **kwargs)
        except httpx.HTTPError:
            raise GoogleAdsApiError("Google didn't answer. Try again in a minute.") from None
        finally:
            if self._client is None:
                await client.aclose()

    async def _token(self, **form: str) -> dict[str, Any]:
        response = await self._send(
            "POST",
            EXCHANGE,
            data={"client_id": self.cfg.client_id, "client_secret": self.cfg.client_secret, **form},
        )
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code >= 400 or not isinstance(body, dict):
            error = body.get("error") if isinstance(body, dict) else None
            if error == "invalid_grant":
                raise GoogleAdsApiError("Google ended this connection. Continue with Google again.")
            raise GoogleAdsApiError("Google didn't finish the sign-in. Start again.")
        return body

    async def refresh_token(self, *, code: str, redirect_uri: str) -> str:
        body = await self._token(
            grant_type="authorization_code", code=code, redirect_uri=redirect_uri
        )
        token = str(body.get("refresh_token") or "")
        if not token:
            raise GoogleAdsApiError(
                "Google didn't give lasting access. Continue with Google again."
            )
        if SCOPE not in str(body.get("scope") or SCOPE).split():
            raise GoogleAdsApiError("Allow Sales Xray to see your Google Ads, then try again.")
        return token

    async def access_token(self, refresh_token: str) -> str:
        body = await self._token(grant_type="refresh_token", refresh_token=refresh_token)
        token = str(body.get("access_token") or "")
        if not token:
            raise GoogleAdsApiError("Google ended this connection. Continue with Google again.")
        return token

    def _headers(self, access: str, login: str | None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {access}",
            "developer-token": self.cfg.developer_token,
            "Accept": "application/json",
        }
        if login:
            headers["login-customer-id"] = login
        return headers

    async def _ads(
        self, method: str, path: str, access: str, *, login: str | None, body: object = None
    ) -> dict[str, Any]:
        response = await self._send(
            method, f"{self.cfg.api}/{path}", headers=self._headers(access, login), json=body
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code >= 400:
            text = response.text
            if "DEVELOPER_TOKEN_NOT_APPROVED" in text or "DEVELOPER_TOKEN_PROHIBITED" in text:
                raise GoogleAdsApiError(
                    "Google hasn't approved Sales Xray's Google Ads access for live accounts yet."
                )
            if response.status_code == 401:
                raise GoogleAdsApiError("Google ended this connection. Continue with Google again.")
            if response.status_code == 403:
                raise GoogleAdsApiError(
                    "This Google account can't open that Ads account. Ask its owner for access."
                )
            if response.status_code == 429:
                raise GoogleAdsApiError("Google asked Sales Xray to slow down. Try again later.")
            raise GoogleAdsApiError("Google Ads refused the request. Try again in a minute.")
        return payload if isinstance(payload, dict) else {}

    async def search(
        self, customer_id: str, query: str, access: str, *, login: str | None
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        page: str | None = None
        for _ in range(5):
            body: dict[str, Any] = {"query": query}
            if page:
                body["pageToken"] = page
            out = await self._ads(
                "POST", f"customers/{customer_id}/googleAds:search", access, login=login, body=body
            )
            rows.extend(row for row in out.get("results") or [] if isinstance(row, dict))
            page = out.get("nextPageToken") or None
            if not page:
                break
        return rows

    async def accounts(self, access: str) -> list[Account]:
        """Ads accounts this person can reach: their own, and those under a manager account."""
        listed = await self._ads("GET", "customers:listAccessibleCustomers", access, login=None)
        found: dict[str, Account] = {}
        for resource in (listed.get("resourceNames") or [])[:MAX_ACCOUNTS]:
            top = _id(resource)
            try:
                rows = await self.search(
                    top,
                    "SELECT customer_client.id, customer_client.descriptive_name, "
                    "customer_client.manager, customer_client.level, customer_client.test_account "
                    "FROM customer_client WHERE customer_client.level <= 1 "
                    "AND customer_client.status = 'ENABLED'",
                    access,
                    login=top,
                )
            except GoogleAdsApiError:
                continue  # A cancelled or unreachable account; the rest still count.
            for row in rows:
                client = row.get("customerClient") or {}
                customer = str(client.get("id") or "")
                if not customer or client.get("manager"):
                    continue
                direct = customer == top
                if customer in found and not direct:
                    continue
                found[customer] = Account(
                    customer_id=customer,
                    name=str(client.get("descriptiveName") or customer)[:100],
                    login_customer_id=None if direct else top,
                    test=bool(client.get("testAccount")),
                )
        return list(found.values())[:MAX_ACCOUNTS]

    async def lead_forms(self, account: Account, access: str) -> list[LeadForm]:
        rows = await self.search(
            account.customer_id,
            "SELECT asset.resource_name, asset.id, asset.name, "
            "asset.lead_form_asset.business_name, asset.lead_form_asset.headline, "
            "asset.lead_form_asset.delivery_methods FROM asset WHERE asset.type = 'LEAD_FORM'",
            access,
            login=account.login_customer_id,
        )
        forms = []
        for row in rows:
            asset = row.get("asset") or {}
            lead_form = asset.get("leadFormAsset") or {}
            hook = next(
                (
                    method.get("webhook") or {}
                    for method in lead_form.get("deliveryMethods") or []
                    if isinstance(method, Mapping) and method.get("webhook")
                ),
                {},
            )
            forms.append(
                LeadForm(
                    resource_name=str(asset.get("resourceName") or ""),
                    form_id=str(asset.get("id") or _id(asset.get("resourceName"))),
                    name=str(
                        asset.get("name")
                        or lead_form.get("headline")
                        or lead_form.get("businessName")
                        or ""
                    )[:120],
                    webhook_url=str(hook.get("advertiserWebhookUrl") or "") or None,
                    webhook_secret=str(hook.get("googleSecret") or "") or None,
                )
            )
        return forms

    async def set_webhook(
        self, account: Account, form: LeadForm, access: str, *, url: str, key: str
    ) -> None:
        await self._ads(
            "POST",
            f"customers/{account.customer_id}/assets:mutate",
            access,
            login=account.login_customer_id,
            body={
                "operations": [
                    {
                        "update": {
                            "resourceName": form.resource_name,
                            "leadFormAsset": {
                                "deliveryMethods": [
                                    {
                                        "webhook": {
                                            "advertiserWebhookUrl": url,
                                            "googleSecret": key,
                                            "payloadSchemaVersion": str(PAYLOAD_SCHEMA),
                                        }
                                    }
                                ]
                            },
                        },
                        "updateMask": "lead_form_asset.delivery_methods",
                    }
                ]
            },
        )

    async def submissions(
        self, account: Account, access: str, *, since: int
    ) -> list[dict[str, Any]]:
        """The account's newest lead form submissions, as webhook-shaped payloads."""
        # GAQL, not SQL: the date and the limit are computed here, never taken from input.
        query = " ".join(
            (
                SUBMISSIONS,
                f"WHERE lead_form_submission_data.submission_date_time >= '{since_text(since)}'",
                "ORDER BY lead_form_submission_data.submission_date_time DESC",
                f"LIMIT {PULL_MAX}",
            )
        )
        rows = await self.search(
            account.customer_id, query, access, login=account.login_customer_id
        )
        return [webhook_payload(row) for row in rows]


def account_of(config: Mapping[str, Any]) -> Account:
    login = config.get("login_customer_id")
    return Account(
        customer_id=str(config.get("customer_id") or ""),
        name=str(config.get("account_name") or ""),
        login_customer_id=str(login) if login else None,
        test=bool(config.get("test")),
    )
