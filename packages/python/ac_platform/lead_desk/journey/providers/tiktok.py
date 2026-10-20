"""TikTok: the Events API for CRM (lead stages back to TikTok's lead ads).

Like Meta, TikTok learns from every stage by name: the business's own stage names go
to its CRM event set as they are, and TikTok's lead ads optimise for the stage that
matters. The first stage goes as "Lead". A lead goes with TikTok's lead id (from a
TikTok instant form), its click id (``ttclid``) and/or its email and phone as SHA-256.

The business makes a CRM event set in TikTok Events Manager and Sales Xray sends to it
(its id is the destination). ``AC_TIKTOK_SANDBOX=1`` points the API at TikTok's
sandbox; a test event code shows events in Events Manager → Test events.
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
    Spec,
    click_ids,
    event_id,
    hashed_e164,
    hashed_email,
    oauth,
)
from ac_platform.lead_desk.journey.providers.meta import clean_name
from ac_platform.lead_desk.models import Lead

SPEC: Final[Spec] = Spec(
    id="tiktok",
    name="TikTok",
    brand="tiktok",
    naming="stage",
    learns="TikTok's lead ads learn which leads become customers and find more like them.",
    reaches="Leads from your TikTok instant forms, and leads with an email or phone.",
    destination="CRM event set",
)
AUTH: Final[str] = "https://business-api.tiktok.com/portal/auth"
DESTINATION: Final[re.Pattern[str]] = re.compile(r"^[0-9A-Za-z]{10,40}$")
TEST_CODE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9]{4,32}$")
# Typed by the manager: the CRM event set's id from TikTok Events Manager.
MANUAL: Final[str] = "Paste the CRM event set ID from TikTok Events Manager → your CRM event set."
TIMEOUT: Final[float] = 15.0
_LEAD_ID: Final[re.Pattern[str]] = re.compile(r"^[0-9]{10,25}$")


def api(cfg: oauth.App | None) -> str:
    sandbox = cfg is not None and cfg.extra.get("AC_TIKTOK_SANDBOX") in ("1", "true", "yes")
    host = "https://sandbox-ads.tiktok.com" if sandbox else "https://business-api.tiktok.com"
    return f"{host}/open_api/v1.3"


def configured() -> bool:
    return oauth.app("tiktok") is not None


async def connected_in(db: Any, tenant_id: UUID, config: Mapping[str, Any]) -> bool:
    cfg = oauth.app("tiktok")
    return cfg is not None and oauth.tokens_of(config, cfg, tenant_id) is not None


async def destinations(db: Any, tenant_id: UUID, config: Mapping[str, Any]) -> list[dict[str, str]]:
    """TikTok has no list of CRM event sets for apps: the manager pastes its id."""
    return []


def suggest(stage: Stage) -> str | None:
    if stage.kind == "not_connected":
        return None
    if stage.kind == "new":
        return "Lead"
    return clean_name(stage.label)


def identity(lead: Lead) -> dict[str, Any] | None:
    who: dict[str, Any] = {"lead_ref": str(lead.id)}
    payload = lead.payload if isinstance(lead.payload, Mapping) else {}
    ref = str(payload.get("tiktok_lead_id") or "")
    if _LEAD_ID.fullmatch(ref):
        who["lead_id"] = ref
    found = click_ids(payload)
    if "ttclid" in found:
        who["ttclid"] = found["ttclid"]
    em, ph = hashed_email(lead.email), hashed_e164(lead.phone)
    if em:
        who["email"] = em
    if ph:
        who["phone"] = ph
    return who if len(who) > 1 else None


def body(
    who: Mapping[str, Any], *, event_name: str, at: datetime, settings: Any = None
) -> dict[str, Any]:
    user: dict[str, Any] = {}
    for name in ("email", "phone", "ttclid"):
        if who.get(name):
            user[name] = who[name]
    out: dict[str, Any] = {
        "event": event_name,
        "event_time": int(at.timestamp()),
        "event_id": event_id("tiktok", str(who["lead_ref"]), event_name),
        "user": user,
    }
    if who.get("lead_id"):
        out["lead"] = {"lead_id": who["lead_id"], "lead_event_source": "Sales Xray"}
    return out


def consent_url(cfg: oauth.App, *, redirect_uri: str, state: str) -> str:
    query = urlencode({"app_id": cfg.client_id, "state": state, "redirect_uri": redirect_uri})
    return f"{AUTH}?{query}"


async def finish(
    client: httpx.AsyncClient, cfg: oauth.App, *, code: str, redirect_uri: str
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Swap TikTok's auth code for a long-lived token; the advertisers come with it."""
    response = await client.post(
        f"{api(cfg)}/oauth2/access_token/",
        json={"app_id": cfg.client_id, "secret": cfg.client_secret, "auth_code": code},
        timeout=TIMEOUT,
    )
    answer = response.json() if response.content else {}
    data = answer.get("data") if isinstance(answer, dict) else None
    if response.status_code >= 400 or not isinstance(data, dict) or not data.get("access_token"):
        raise oauth.ConnectError("TikTok didn't finish the sign-in. Start again.")
    tokens = {"access_token": str(data["access_token"])}
    accounts = [
        {"id": str(item), "name": f"Advertiser {item}"} for item in data.get("advertiser_ids") or []
    ]
    return tokens, accounts


def read_answer(status: int, data: Any, duration_ms: int) -> Answer:
    code = data.get("code") if isinstance(data, Mapping) else None
    trace = data.get("request_id") if isinstance(data, Mapping) else None
    if status == 200 and code == 0:
        return Answer(status, None, duration_ms, str(trace)[:64] if trace else None)
    name = f"tiktok_{code if code is not None else status}"[:64]
    if status >= 500 or status == 429 or code in (40100, 50000, 50002, 51021):
        return Answer(status, name, duration_ms, wait="retry")
    if status in (401, 403) or code in (40001, 40002, 40104, 40105, 40106):
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
    cfg = oauth.app("tiktok")
    if cfg is None:
        return Answer(None, "not_configured", 0, wait="customer")
    tokens = oauth.tokens_of(config, cfg, tenant_id)
    if not tokens or not tokens.get("access_token"):
        return Answer(None, "not_connected", 0, wait="customer")
    request: dict[str, Any] = {
        "event_source": "crm",
        "event_source_id": destination,
        "data": [dict(payload)],
    }
    if test_code:
        request["test_event_code"] = test_code
    started = time.monotonic()
    try:
        response = await client.post(
            f"{api(cfg)}/event/track/",
            headers={
                "Access-Token": str(tokens["access_token"]),
                "Content-Type": "application/json",
            },
            json=request,
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
