"""Google Ads: offline conversion import with enhanced conversions for leads.

Google learns best from a few moments that matter: a qualified lead and a customer
(and, for businesses that book meetings or send quotes, those too). Sales Xray makes
the conversion actions in the business's own Ads account ("Sales Xray · Qualified
lead", type Import from clicks) when sending is switched on, and matches the
business's stages to them by meaning.

A lead goes when Google can match it: the Google click id (gclid, gbraid or wbraid)
from a lead form or a website form, and/or the email and phone as SHA-256 (enhanced
conversions for leads). Nothing else leaves Sales Xray. The connection is the
account's own Continue with Google (``connectors/google_ads_api.py``): its refresh
token, sealed on the account's CRM source.
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.lead_desk.connectors import google_ads_api as gads
from ac_platform.lead_desk.journey.model import Stage
from ac_platform.lead_desk.journey.providers import (
    Answer,
    EventOption,
    Spec,
    click_ids,
    event_id,
    hashed_e164,
    hashed_email,
)
from ac_platform.lead_desk.models import Lead, LeadSource

SPEC: Final[Spec] = Spec(
    id="google_ads",
    name="Google Ads",
    brand="googleads",
    naming="action",
    learns=(
        "Google's bidding learns which clicks turn into good leads and customers, "
        "and finds more of them."
    ),
    reaches=(
        "Leads from your Google lead forms and website forms that keep Google's click id, "
        "and any lead with an email or phone (enhanced conversions for leads)."
    ),
    destination="account",
    options=(
        EventOption("qualified_lead", "a qualified lead", ("qualified",)),
        EventOption(
            "booked_appointment", "a booked meeting", ("appointment_booked", "appointment_done")
        ),
        EventOption("requested_quote", "a quote sent", ("proposal", "application")),
        EventOption("converted_lead", "a customer", ("won",)),
    ),
)
# Each option is one conversion action in the business's account.
ACTIONS: Final[dict[str, tuple[str, str]]] = {
    "qualified_lead": ("Sales Xray · Qualified lead", "QUALIFIED_LEAD"),
    "booked_appointment": ("Sales Xray · Booked meeting", "BOOK_APPOINTMENT"),
    "requested_quote": ("Sales Xray · Quote sent", "REQUEST_QUOTE"),
    "converted_lead": ("Sales Xray · Customer", "CONVERTED_LEAD"),
}
DESTINATION: Final[re.Pattern[str]] = re.compile(r"^[0-9]{6,12}$")
# Google has no test code: "test" here checks each upload without counting it.
TEST_CODE: Final[re.Pattern[str]] = re.compile(r"^(check)$")
TIMEOUT: Final[float] = 15.0
# Google's errors worth trying again later, and those only the business can fix.
_RETRY: Final[tuple[str, ...]] = (
    "TOO_RECENT_CONVERSION_ACTION",
    "CONCURRENT_MODIFICATION",
    "INTERNAL_ERROR",
    "RESOURCE_TEMPORARILY_EXHAUSTED",
    "TRANSIENT_ERROR",
    "TOO_RECENT_CLICK",
)
_CUSTOMER: Final[tuple[str, ...]] = (
    "CUSTOMER_NOT_ACCEPTED_CUSTOMER_DATA_TERMS",
    "CUSTOMER_NOT_ENABLED_ENHANCED_CONVERSIONS_FOR_LEADS",
    "DEVELOPER_TOKEN_NOT_APPROVED",
    "USER_PERMISSION_DENIED",
    "CUSTOMER_NOT_ENABLED",
    "INVALID_CONVERSION_ACTION",
    "CONVERSION_ACTION_NOT_ENABLED",
)


def configured() -> bool:
    return gads.config() is not None


async def _source(db: AsyncSession, tenant_id: UUID, customer_id: str) -> LeadSource | None:
    rows = (
        await db.scalars(
            select(LeadSource).where(
                LeadSource.tenant_id == tenant_id, LeadSource.kind == "webhook"
            )
        )
    ).all()
    return next(
        (
            row
            for row in rows
            if gads.is_connector(row) and str((row.config or {}).get("customer_id")) == customer_id
        ),
        None,
    )


async def connected_in(db: AsyncSession, tenant_id: UUID, config: Mapping[str, Any]) -> bool:
    """Whether the business connected any Google Ads account with Continue with Google."""
    return bool(await destinations(db, tenant_id, config))


async def destinations(
    db: AsyncSession, tenant_id: UUID, config: Mapping[str, Any]
) -> list[dict[str, str]]:
    """The Google Ads accounts the business connected with Continue with Google."""
    rows = (
        await db.scalars(
            select(LeadSource).where(
                LeadSource.tenant_id == tenant_id, LeadSource.kind == "webhook"
            )
        )
    ).all()
    out = []
    for row in rows:
        if not gads.is_connector(row):
            continue
        account = gads.account_of(row.config or {})
        if account.customer_id:
            name = account.name or account.customer_id
            out.append(
                {
                    "id": account.customer_id,
                    "name": f"{name} (test account)" if account.test else name,
                }
            )
    return out


def suggest(stage: Stage) -> str | None:
    """Google's moment for a stage, by what the stage means. The first stage is left
    out: Google already counts the lead form or website form itself."""
    if stage.kind in ("new", "not_connected", "lost"):
        return None
    for option in SPEC.options:
        if stage.milestone in option.milestones:
            return option.id
    return "converted_lead" if stage.kind == "won" else None


def identity(lead: Lead) -> dict[str, Any] | None:
    found = click_ids(lead.payload)
    who: dict[str, Any] = {"lead_ref": str(lead.id)}
    for name in ("gclid", "gbraid", "wbraid"):
        if name in found:
            who[name] = found[name]
            break
    em, ph = hashed_email(lead.email), hashed_e164(lead.phone)
    if em:
        who["em"] = em
    if ph:
        who["ph"] = ph
    return who if len(who) > 1 else None


def conversion_time(at: datetime) -> str:
    """Google's format: "yyyy-mm-dd hh:mm:ss+00:00"."""
    return at.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S+00:00")


def body(
    who: Mapping[str, Any],
    *,
    event_name: str,
    at: datetime,
    settings: Any = None,
) -> dict[str, Any]:
    """One ClickConversion. The conversion action is this business's own (made when
    sending was switched on)."""
    actions = (getattr(settings, "extra", None) or {}).get("actions") or {}
    conversion: dict[str, Any] = {
        "conversionAction": str(actions.get(event_name) or ""),
        "conversionDateTime": conversion_time(at),
        "orderId": event_id("google_ads", str(who["lead_ref"]), event_name),
    }
    for name in ("gclid", "gbraid", "wbraid"):
        if who.get(name):
            conversion[name] = who[name]
    identifiers = []
    if who.get("em"):
        identifiers.append({"hashedEmail": who["em"], "userIdentifierSource": "FIRST_PARTY"})
    if who.get("ph"):
        identifiers.append({"hashedPhoneNumber": who["ph"], "userIdentifierSource": "FIRST_PARTY"})
    if identifiers:
        conversion["userIdentifiers"] = identifiers
    return conversion


def read_answer(status: int, data: Any, duration_ms: int) -> Answer:
    """Google's answer to one upload (partial failure on: errors come per row)."""
    text = str(data)[:4000]
    trace = data.get("requestId") if isinstance(data, Mapping) else None
    if status == 200 and isinstance(data, Mapping):
        failure = data.get("partialFailureError")
        if not failure:
            return Answer(status, None, duration_ms, trace)
        text = str(failure)[:4000]
    code = next((name for name in _RETRY + _CUSTOMER if name in text), None)
    found = re.search(r"\b([A-Z][A-Z_]{5,60})\b", text) if code is None else None
    name = f"google_{(code or (found.group(1) if found else str(status))).lower()}"[:64]
    if status >= 500 or status == 429 or code in _RETRY:
        return Answer(status, name, duration_ms, trace, "retry")
    if status in (401, 403) or code in _CUSTOMER:
        return Answer(status, name, duration_ms, trace, "customer")
    return Answer(status, name, duration_ms, trace, "never")


async def _access(
    db: AsyncSession, tenant_id: UUID, customer_id: str, client: httpx.AsyncClient
) -> tuple[str, str | None] | Answer:
    cfg = gads.config()
    if cfg is None:
        return Answer(None, "not_configured", 0, wait="customer")
    source = await _source(db, tenant_id, customer_id)
    if source is None:
        return Answer(None, "not_connected", 0, wait="customer")
    account = gads.account_of(source.config or {})
    try:
        refresh = gads.unseal(
            cfg.token_key, (source.config or {}).get("token"), customer_id=customer_id, what="token"
        )
        access = await gads.Ads(cfg, client).access_token(refresh)
    except gads.GoogleAdsApiError:
        return Answer(None, "not_connected", 0, wait="customer")
    return access, account.login_customer_id


def _headers(access: str, login: str | None) -> dict[str, str]:
    cfg = gads.config()
    headers = {
        "Authorization": f"Bearer {access}",
        "developer-token": cfg.developer_token if cfg else "",
        "Accept": "application/json",
    }
    if login:
        headers["login-customer-id"] = login
    return headers


async def send(
    client: httpx.AsyncClient,
    *,
    config: Mapping[str, Any],
    tenant_id: UUID,
    destination: str,
    payload: Mapping[str, Any],
    test_code: str | None,
    db: AsyncSession | None = None,
) -> Answer:
    if db is None:
        return Answer(None, "not_configured", 0, wait="customer")
    if not payload.get("conversionAction"):
        return Answer(None, "google_no_action", 0, wait="customer")
    got = await _access(db, tenant_id, destination, client)
    if isinstance(got, Answer):
        return got
    access, login = got
    cfg = gads.config()
    assert cfg is not None
    started = time.monotonic()

    def elapsed() -> int:
        return max(0, round((time.monotonic() - started) * 1000))

    try:
        response = await client.post(
            f"{cfg.api}/customers/{destination}:uploadClickConversions",
            headers=_headers(access, login),
            json={
                "conversions": [dict(payload)],
                "partialFailure": True,
                "validateOnly": test_code == "check",
            },
            timeout=TIMEOUT,
        )
    except httpx.TimeoutException:
        return Answer(None, "timeout", elapsed())
    except httpx.HTTPError:
        return Answer(None, "connect_error", elapsed())
    try:
        data = response.json()
    except ValueError:
        data = {}
    return read_answer(int(response.status_code), data, elapsed())


async def prepare(
    db: AsyncSession,
    tenant_id: UUID,
    destination: str,
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    """Find or make this business's Sales Xray conversion actions in the account.
    Returns {"actions": {option: resource name}}; raises GoogleAdsApiError in words."""
    got = await _access(db, tenant_id, destination, client)
    if isinstance(got, Answer):
        raise gads.GoogleAdsApiError("Continue with Google again to send stages to this account.")
    access, login = got
    cfg = gads.config()
    assert cfg is not None
    ads = gads.Ads(cfg, client)
    rows = await ads.search(
        destination,
        "SELECT conversion_action.resource_name, conversion_action.name "
        "FROM conversion_action WHERE conversion_action.type = 'UPLOAD_CLICKS' "
        "AND conversion_action.status = 'ENABLED'",
        access,
        login=login,
    )
    found = {
        str((row.get("conversionAction") or {}).get("name")): str(
            (row.get("conversionAction") or {}).get("resourceName")
        )
        for row in rows
    }
    actions: dict[str, str] = {}
    missing = []
    for option, (name, category) in ACTIONS.items():
        if name in found:
            actions[option] = found[name]
        else:
            missing.append((option, name, category))
    if missing:
        made = await ads._ads(
            "POST",
            f"customers/{destination}/conversionActions:mutate",
            access,
            login=login,
            body={
                "operations": [
                    {
                        "create": {
                            "name": name,
                            "type": "UPLOAD_CLICKS",
                            "category": category,
                            "status": "ENABLED",
                        }
                    }
                    for _, name, category in missing
                ]
            },
        )
        results = made.get("results") or []
        for (option, _, _), result in zip(missing, results, strict=False):
            if isinstance(result, Mapping) and result.get("resourceName"):
                actions[option] = str(result["resourceName"])
    return {"actions": actions}
