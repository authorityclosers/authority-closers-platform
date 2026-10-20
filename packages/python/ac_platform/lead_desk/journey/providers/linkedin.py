"""LinkedIn: the Conversions API (conversion rules fed by Sales Xray).

LinkedIn learns from a few moments: a qualified lead, a booked meeting, a quote, an
application and a customer. When sending is switched on, Sales Xray makes those
conversion rules in the business's ad account ("Sales Xray · Qualified lead",
conversion method Conversions API) and matches the business's stages to them by
meaning. A lead goes with its email as SHA-256 and, from a website form, LinkedIn's
click id (``li_fat_id``). Nothing else leaves Sales Xray.

Connect needs LinkedIn's Advertising API product for AC's app; scopes ``rw_conversions``
and ``r_ads`` (``r_ads_reporting`` for spend, later).
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from datetime import datetime
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
    event_id,
    hashed_email,
    oauth,
)
from ac_platform.lead_desk.models import Lead

SPEC: Final[Spec] = Spec(
    id="linkedin",
    name="LinkedIn",
    brand="linkedin",
    naming="action",
    learns="LinkedIn's ads learn which people became good leads and customers.",
    reaches="Leads with an email, and website leads that keep LinkedIn's click id.",
    destination="ad account",
    options=(
        EventOption("qualified_lead", "a qualified lead", ("qualified",)),
        EventOption(
            "book_appointment", "a booked meeting", ("appointment_booked", "appointment_done")
        ),
        EventOption("request_quote", "a quote sent", ("proposal",)),
        EventOption("submit_application", "an application", ("application",)),
        EventOption("purchase", "a customer", ("won",)),
    ),
)
# Each option is one conversion rule: its name and LinkedIn's conversion type.
RULES: Final[dict[str, tuple[str, str]]] = {
    "qualified_lead": ("Sales Xray · Qualified lead", "QUALIFIED_LEAD"),
    "book_appointment": ("Sales Xray · Booked meeting", "BOOK_APPOINTMENT"),
    "request_quote": ("Sales Xray · Quote sent", "REQUEST_QUOTE"),
    "submit_application": ("Sales Xray · Application", "SUBMIT_APPLICATION"),
    "purchase": ("Sales Xray · Customer", "PURCHASE"),
}
AUTH: Final[str] = "https://www.linkedin.com/oauth/v2/authorization"
EXCHANGE: Final[str] = "https://www.linkedin.com/oauth/v2/accessToken"
API: Final[str] = "https://api.linkedin.com/rest"
SCOPES: Final[str] = "rw_conversions r_ads"
DESTINATION: Final[re.Pattern[str]] = re.compile(r"^[0-9]{4,15}$")
TEST_CODE: Final[re.Pattern[str]] = re.compile(r"^$")  # LinkedIn has no test events
TIMEOUT: Final[float] = 15.0


def version(cfg: oauth.App | None) -> str:
    """LinkedIn's monthly API version (each lasts a year): settable, a recent default."""
    return (cfg.extra.get("AC_LINKEDIN_VERSION") if cfg else None) or "202609"


def configured() -> bool:
    return oauth.app("linkedin") is not None


async def connected_in(db: Any, tenant_id: UUID, config: Mapping[str, Any]) -> bool:
    cfg = oauth.app("linkedin")
    return cfg is not None and oauth.tokens_of(config, cfg, tenant_id) is not None


async def destinations(db: Any, tenant_id: UUID, config: Mapping[str, Any]) -> list[dict[str, str]]:
    return oauth.accounts_of(config, "linkedin")


def suggest(stage: Stage) -> str | None:
    if stage.kind in ("new", "not_connected", "lost"):
        return None
    for option in SPEC.options:
        if stage.milestone in option.milestones:
            return option.id
    return "purchase" if stage.kind == "won" else None


def identity(lead: Lead) -> dict[str, Any] | None:
    who: dict[str, Any] = {"lead_ref": str(lead.id)}
    em = hashed_email(lead.email)
    if em:
        who["em"] = em
    found = click_ids(lead.payload)
    if "li_fat_id" in found:
        who["li_fat_id"] = found["li_fat_id"]
    return who if len(who) > 1 else None


def body(
    who: Mapping[str, Any], *, event_name: str, at: datetime, settings: Any = None
) -> dict[str, Any]:
    rules = (getattr(settings, "extra", None) or {}).get("rules") or {}
    ids = []
    if who.get("em"):
        ids.append({"idType": "SHA256_EMAIL", "idValue": who["em"]})
    if who.get("li_fat_id"):
        ids.append(
            {"idType": "LINKEDIN_FIRST_PARTY_ADS_TRACKING_UUID", "idValue": who["li_fat_id"]}
        )
    return {
        "conversion": f"urn:lla:llaPartnerConversion:{rules.get(event_name, '')}",
        "conversionHappenedAt": int(at.timestamp() * 1000),
        "eventId": event_id("linkedin", str(who["lead_ref"]), event_name),
        "user": {"userIds": ids},
    }


def consent_url(cfg: oauth.App, *, redirect_uri: str, state: str) -> str:
    query = urlencode(
        {
            "response_type": "code",
            "client_id": cfg.client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": SCOPES,
        }
    )
    return f"{AUTH}?{query}"


def _headers(cfg: oauth.App | None, token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "LinkedIn-Version": version(cfg),
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
    }


async def finish(
    client: httpx.AsyncClient, cfg: oauth.App, *, code: str, redirect_uri: str
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Swap LinkedIn's code for tokens and list the ad accounts this person can use."""
    response = await client.post(
        EXCHANGE,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": cfg.client_id,
            "client_secret": cfg.client_secret,
        },
        timeout=TIMEOUT,
    )
    answer = response.json() if response.content else {}
    if (
        response.status_code >= 400
        or not isinstance(answer, dict)
        or not answer.get("access_token")
    ):
        raise oauth.ConnectError("LinkedIn didn't finish the sign-in. Start again.")
    tokens = oauth.stamped(answer)
    found = await client.get(
        f"{API}/adAccounts",
        params={"q": "search"},
        headers=_headers(cfg, tokens["access_token"]),
        timeout=TIMEOUT,
    )
    data = found.json() if found.content else {}
    accounts = [
        {"id": str(item.get("id")), "name": str(item.get("name") or item.get("id"))}
        for item in (data.get("elements") or [] if isinstance(data, dict) else [])
        if isinstance(item, dict) and item.get("id")
    ]
    return tokens, accounts


async def _access(
    db: Any, tenant_id: UUID, config: Mapping[str, Any], client: httpx.AsyncClient
) -> tuple[oauth.App, str] | Answer:
    cfg = oauth.app("linkedin")
    if cfg is None:
        return Answer(None, "not_configured", 0, wait="customer")
    tokens = oauth.tokens_of(config, cfg, tenant_id)
    if not tokens or not tokens.get("access_token"):
        return Answer(None, "not_connected", 0, wait="customer")
    if oauth.expired(tokens):
        if not tokens.get("refresh_token"):
            return Answer(None, "not_connected", 0, wait="customer")
        response = await client.post(
            EXCHANGE,
            data={
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": cfg.client_id,
                "client_secret": cfg.client_secret,
            },
            timeout=TIMEOUT,
        )
        answer = response.json() if response.content else {}
        if response.status_code >= 400 or not isinstance(answer, dict):
            return Answer(response.status_code, "not_connected", 0, wait="customer")
        tokens = {**tokens, **{k: v for k, v in oauth.stamped(answer).items() if v}}
        if db is not None:
            await oauth.store_tokens(db, tenant_id, cfg, tokens)
    return cfg, str(tokens["access_token"])


def read_answer(status: int, data: Any, duration_ms: int) -> Answer:
    if status in (200, 201, 204):
        return Answer(status, None, duration_ms)
    code = data.get("code") if isinstance(data, Mapping) else None
    name = f"linkedin_{str(code or status).lower()}"[:64]
    if status >= 500 or status == 429:
        return Answer(status, name, duration_ms, wait="retry")
    if status in (401, 403):
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
    if str(payload.get("conversion", "")).endswith(":"):
        return Answer(None, "linkedin_no_rule", 0, wait="customer")
    got = await _access(db, tenant_id, config, client)
    if isinstance(got, Answer):
        return got
    cfg, token = got
    started = time.monotonic()
    try:
        response = await client.post(
            f"{API}/conversionEvents",
            headers=_headers(cfg, token),
            json=dict(payload),
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
    """Find or make this business's Sales Xray conversion rules in the ad account."""
    from ac_platform.lead_desk.models import LeadDeskSettings

    row = await db.get(LeadDeskSettings, tenant_id)
    got = await _access(db, tenant_id, (row.config if row else None) or {}, client)
    if isinstance(got, Answer):
        raise oauth.ConnectError("Connect LinkedIn again to send stages to this ad account.")
    cfg, token = got
    account = f"urn:li:sponsoredAccount:{destination}"
    listed = await client.get(
        f"{API}/conversions",
        params={"q": "account", "account": account},
        headers=_headers(cfg, token),
        timeout=TIMEOUT,
    )
    data = listed.json() if listed.content else {}
    have = {
        str(item.get("name")): str(item.get("id"))
        for item in (data.get("elements") or [] if isinstance(data, dict) else [])
        if isinstance(item, dict)
    }
    rules: dict[str, str] = {}
    for option, (name, kind) in RULES.items():
        if name in have:
            rules[option] = have[name]
            continue
        made = await client.post(
            f"{API}/conversions",
            headers=_headers(cfg, token),
            json={
                "name": name,
                "account": account,
                "type": kind,
                "conversionMethod": "CONVERSIONS_API",
                "attributionType": "LAST_TOUCH_BY_CAMPAIGN",
                "postClickAttributionWindowSize": 30,
                "viewThroughAttributionWindowSize": 7,
                "enabled": True,
            },
            timeout=TIMEOUT,
        )
        if made.status_code >= 400:
            raise oauth.ConnectError(
                "LinkedIn didn't let Sales Xray make its conversion rules. Check that you "
                "manage this ad account."
            )
        rule = made.headers.get("x-restli-id") or (made.json() or {}).get("id")
        if rule:
            rules[option] = str(rule)
    return {"rules": rules}
