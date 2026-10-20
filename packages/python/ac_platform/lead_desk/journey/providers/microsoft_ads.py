"""Microsoft Advertising: offline conversions (Microsoft's click id or hashed contact).

Microsoft learns from offline conversion goals. When sending is switched on, Sales Xray
makes them in the business's account ("Sales Xray · Qualified lead" and the rest, type
offline conversion) and matches the business's stages to them by meaning. A lead goes
with Microsoft's click id (MSCLKID) from a website form, and/or its email and phone as
SHA-256 (enhanced conversions). Nothing else leaves Sales Xray.

Microsoft is freezing its SOAP API, so this speaks the REST (JSON) form of Campaign
Management v13. ``AC_MICROSOFT_ADS_SANDBOX=1`` points everything at Microsoft's sandbox
(its own sign-in, and the public sandbox developer token).
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Final
from urllib.parse import urlencode
from uuid import UUID

import httpx

from ac_platform.lead_desk.journey.model import Stage
from ac_platform.lead_desk.journey.providers import (
    Answer,
    EventOption,
    Spec,
    click_ids,
    hashed_e164,
    hashed_email,
    oauth,
)
from ac_platform.lead_desk.models import Lead

SPEC: Final[Spec] = Spec(
    id="microsoft_ads",
    name="Microsoft Ads",
    brand="microsoft",
    naming="action",
    learns="Microsoft's bidding learns which searches bring good leads and customers.",
    reaches=(
        "Website leads that keep Microsoft's click id, and leads with an email or phone "
        "(enhanced conversions)."
    ),
    destination="account",
    options=(
        EventOption("qualified_lead", "a qualified lead", ("qualified",)),
        EventOption(
            "booked_meeting", "a booked meeting", ("appointment_booked", "appointment_done")
        ),
        EventOption("quote_sent", "a quote sent", ("proposal", "application")),
        EventOption("customer", "a customer", ("won",)),
    ),
)
GOALS: Final[dict[str, str]] = {
    "qualified_lead": "Sales Xray · Qualified lead",
    "booked_meeting": "Sales Xray · Booked meeting",
    "quote_sent": "Sales Xray · Quote sent",
    "customer": "Sales Xray · Customer",
}
SCOPE: Final[str] = "https://ads.microsoft.com/msads.manage offline_access"
SANDBOX_SCOPE: Final[str] = "https://api.ads.microsoft.com/msads.manage offline_access"
DESTINATION: Final[re.Pattern[str]] = re.compile(r"^[0-9]{3,15}:[0-9]{3,15}$")  # customer:account
TEST_CODE: Final[re.Pattern[str]] = re.compile(r"^$")
TIMEOUT: Final[float] = 20.0


def _sandbox(cfg: oauth.App | None) -> bool:
    return bool(cfg and cfg.extra.get("AC_MICROSOFT_ADS_SANDBOX") in ("1", "true", "yes"))


def hosts(cfg: oauth.App | None) -> dict[str, str]:
    if _sandbox(cfg):
        return {
            "login": "https://login.windows-ppe.net/consumers/oauth2/v2.0",
            "campaign": "https://campaign.api.sandbox.bingads.microsoft.com/CampaignManagement/v13",
            "customer": "https://clientcenter.api.sandbox.bingads.microsoft.com/CustomerManagement/v13",
            "scope": SANDBOX_SCOPE,
        }
    return {
        "login": "https://login.microsoftonline.com/common/oauth2/v2.0",
        "campaign": "https://campaign.api.bingads.microsoft.com/CampaignManagement/v13",
        "customer": "https://clientcenter.api.bingads.microsoft.com/CustomerManagement/v13",
        "scope": SCOPE,
    }


def configured() -> bool:
    return oauth.app("microsoft_ads") is not None


async def connected_in(db: Any, tenant_id: UUID, config: Mapping[str, Any]) -> bool:
    cfg = oauth.app("microsoft_ads")
    return cfg is not None and oauth.tokens_of(config, cfg, tenant_id) is not None


async def destinations(db: Any, tenant_id: UUID, config: Mapping[str, Any]) -> list[dict[str, str]]:
    return oauth.accounts_of(config, "microsoft_ads")


def suggest(stage: Stage) -> str | None:
    if stage.kind in ("new", "not_connected", "lost"):
        return None
    for option in SPEC.options:
        if stage.milestone in option.milestones:
            return option.id
    return "customer" if stage.kind == "won" else None


def identity(lead: Lead) -> dict[str, Any] | None:
    who: dict[str, Any] = {"lead_ref": str(lead.id)}
    found = click_ids(lead.payload)
    if "msclkid" in found:
        who["msclkid"] = found["msclkid"]
    em, ph = hashed_email(lead.email), hashed_e164(lead.phone)
    if em:
        who["em"] = em
    if ph:
        who["ph"] = ph
    return who if len(who) > 1 else None


def body(
    who: Mapping[str, Any], *, event_name: str, at: datetime, settings: Any = None
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "ConversionName": GOALS.get(event_name, event_name),
        "ConversionTime": at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if who.get("msclkid"):
        out["MicrosoftClickId"] = who["msclkid"]
    if who.get("em"):
        out["HashedEmailAddress"] = who["em"]
    if who.get("ph"):
        out["HashedPhoneNumber"] = who["ph"]
    return out


def consent_url(cfg: oauth.App, *, redirect_uri: str, state: str) -> str:
    where = hosts(cfg)
    query = urlencode(
        {
            "client_id": cfg.client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "response_mode": "query",
            "scope": where["scope"],
            "state": state,
        }
    )
    return f"{where['login']}/authorize?{query}"


def _headers(cfg: oauth.App, token: str, destination: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "DeveloperToken": "BBD37VB98"
        if _sandbox(cfg)
        else cfg.extra.get("AC_MICROSOFT_ADS_DEVELOPER_TOKEN", ""),
        "Content-Type": "application/json",
    }
    if destination:
        customer, account = destination.split(":", 1)
        headers["CustomerId"] = customer
        headers["CustomerAccountId"] = account
    return headers


async def _token(client: httpx.AsyncClient, cfg: oauth.App, **form: str) -> dict[str, Any]:
    response = await client.post(
        f"{hosts(cfg)['login']}/token",
        data={
            "client_id": cfg.client_id,
            "client_secret": cfg.client_secret,
            "scope": hosts(cfg)["scope"],
            **form,
        },
        timeout=TIMEOUT,
    )
    answer = response.json() if response.content else {}
    if (
        response.status_code >= 400
        or not isinstance(answer, dict)
        or not answer.get("access_token")
    ):
        raise oauth.ConnectError("Microsoft didn't finish the sign-in. Start again.")
    return answer


async def finish(
    client: httpx.AsyncClient, cfg: oauth.App, *, code: str, redirect_uri: str
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Swap Microsoft's code for tokens and list the ad accounts this person can use."""
    tokens = oauth.stamped(
        await _token(
            client, cfg, grant_type="authorization_code", code=code, redirect_uri=redirect_uri
        )
    )
    found = await client.post(
        f"{hosts(cfg)['customer']}/AccountsInfo/Query",
        headers=_headers(cfg, tokens["access_token"]),
        json={"CustomerId": None, "OnlyParentAccounts": False},
        timeout=TIMEOUT,
    )
    data = found.json() if found.content else {}
    accounts = [
        {
            "id": f"{item.get('CustomerId') or item.get('ParentCustomerId')}:{item.get('Id')}",
            "name": str(item.get("Name") or item.get("Number") or item.get("Id")),
        }
        for item in (data.get("AccountsInfo") or [] if isinstance(data, dict) else [])
        if isinstance(item, dict) and item.get("Id")
    ]
    return tokens, [item for item in accounts if DESTINATION.fullmatch(item["id"])]


async def _access(
    db: Any, tenant_id: UUID, config: Mapping[str, Any], client: httpx.AsyncClient
) -> tuple[oauth.App, str] | Answer:
    cfg = oauth.app("microsoft_ads")
    if cfg is None:
        return Answer(None, "not_configured", 0, wait="customer")
    tokens = oauth.tokens_of(config, cfg, tenant_id)
    if not tokens or not tokens.get("access_token"):
        return Answer(None, "not_connected", 0, wait="customer")
    if oauth.expired(tokens):
        if not tokens.get("refresh_token"):
            return Answer(None, "not_connected", 0, wait="customer")
        try:
            answer = await _token(
                client, cfg, grant_type="refresh_token", refresh_token=str(tokens["refresh_token"])
            )
        except oauth.ConnectError:
            return Answer(None, "not_connected", 0, wait="customer")
        tokens = {**tokens, **{k: v for k, v in oauth.stamped(answer).items() if v}}
        if db is not None:
            await oauth.store_tokens(db, tenant_id, cfg, tokens)
    return cfg, str(tokens["access_token"])


def read_answer(status: int, data: Any, duration_ms: int) -> Answer:
    errors = []
    if isinstance(data, Mapping):
        errors = [e for e in data.get("PartialErrors") or [] if e] + [
            e for e in data.get("OperationErrors") or [] if e
        ]
    if status == 200 and not errors:
        return Answer(status, None, duration_ms)
    first = errors[0] if errors else {}
    code = first.get("ErrorCode") if isinstance(first, Mapping) else None
    name = f"microsoft_{str(code or status).lower()}"[:64]
    if status >= 500 or status == 429:
        return Answer(status, name, duration_ms, wait="retry")
    if status in (401, 403) or (code and "Authentication" in str(code)):
        return Answer(status, name, duration_ms, wait="customer")
    if code and "ConversionGoal" in str(code):
        return Answer(status, name, duration_ms, wait="customer")
    return Answer(status, name, duration_ms, wait="never")


async def send(
    client: httpx.AsyncClient,
    *,
    config: Mapping[str, Any],
    tenant_id: UUID,
    destination: str,
    payload: Mapping[str, Any],
    test_code: str | None,
    db: Any = None,
) -> Answer:
    got = await _access(db, tenant_id, config, client)
    if isinstance(got, Answer):
        return got
    cfg, token = got
    started = time.monotonic()
    try:
        response = await client.post(
            f"{hosts(cfg)['campaign']}/OfflineConversions/Apply",
            headers=_headers(cfg, token, destination),
            json={"OfflineConversions": [dict(payload)]},
            timeout=TIMEOUT,
        )
    except httpx.TimeoutException:
        return Answer(None, "timeout", round((time.monotonic() - started) * 1000))
    except httpx.HTTPError:
        return Answer(None, "connect_error", round((time.monotonic() - started) * 1000))
    try:
        data = response.json() if response.content else {}
    except ValueError:
        data = {}
    return read_answer(int(response.status_code), data, round((time.monotonic() - started) * 1000))


async def prepare(
    db: Any, tenant_id: UUID, destination: str, client: httpx.AsyncClient
) -> dict[str, Any]:
    """Make this business's Sales Xray offline conversion goals in the account."""
    from ac_platform.lead_desk.models import LeadDeskSettings

    row = await db.get(LeadDeskSettings, tenant_id)
    got = await _access(db, tenant_id, (row.config if row else None) or {}, client)
    if isinstance(got, Answer):
        raise oauth.ConnectError("Connect Microsoft Ads again to send stages to this account.")
    cfg, token = got
    made = await client.post(
        f"{hosts(cfg)['campaign']}/ConversionGoals",
        headers=_headers(cfg, token, destination),
        json={
            "ConversionGoals": [
                {
                    "Type": "OfflineConversion",
                    "Name": name,
                    "Status": "Active",
                    "CountType": "Unique",
                    "Scope": "Account",
                    "Revenue": {"Type": "NoValue"},
                    "ConversionWindowInMinutes": 129600,
                }
                for name in GOALS.values()
            ]
        },
        timeout=TIMEOUT,
    )
    if made.status_code >= 500:
        raise oauth.ConnectError("Microsoft didn't answer. Try again in a minute.")
    # A goal that exists already comes back as a duplicate-name error: it is there.
    return {"goals": dict(GOALS)}
