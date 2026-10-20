"""Meta: the Conversions API for CRM (lead ads on Facebook and Instagram).

Meta learns from every stage by name: a business's own stage names go to its dataset
as they are ("Site visit booked"), so Meta's conversion leads optimisation can pick
the stage that matters. The first stage goes as "Lead". Couldn't reach is not sent.

Only leads from a Meta lead form go. What Meta matches on, and nothing else:

- Meta's lead id, unhashed, as Meta asks;
- the email and phone, SHA-256 after Meta's normalising;
- the lead's own Sales Xray id (``external_id``) and its country from the phone's
  dialling code, both SHA-256;
- Meta's own click and browser ids (``fbc``, ``fbp``) when the lead's form kept them.

No names, notes, cities, amounts or call details. More of these keys lifts Meta's
event match quality (Events Manager), which helps its ads find similar people.
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Final
from uuid import UUID

import httpx

from ac_platform.lead_desk.connectors import meta, meta_capi
from ac_platform.lead_desk.journey.model import Stage
from ac_platform.lead_desk.journey.providers import (
    Answer,
    Spec,
    click_ids,
    event_id,
    hashed_email,
    hashed_phone,
    phone_digits,
    sha256,
)
from ac_platform.lead_desk.models import Lead

SPEC: Final[Spec] = Spec(
    id="meta",
    name="Meta",
    brand="meta",
    naming="stage",
    learns="Meta's ads learn which leads become customers and find more people like them.",
    reaches="Leads from your Facebook and Instagram lead forms.",
    destination="dataset",
    sends="all",
)
_NOT_NAME: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9 _.\-]+")
_FBC: Final[re.Pattern[str]] = re.compile(r"^fb\.[0-9]\.[0-9]{10,13}\.[A-Za-z0-9_\-.~]{6,512}$")
_FBP: Final[re.Pattern[str]] = re.compile(r"^fb\.[0-9]\.[0-9]{10,13}\.[0-9]{5,20}$")
# Dialling codes to ISO countries (lower case, as Meta hashes them); longest first.
DIAL: Final[dict[str, str]] = {
    "971": "ae",
    "966": "sa",
    "974": "qa",
    "968": "om",
    "973": "bh",
    "965": "kw",
    "977": "np",
    "880": "bd",
    "234": "ng",
    "254": "ke",
    "91": "in",
    "44": "gb",
    "65": "sg",
    "61": "au",
    "60": "my",
    "94": "lk",
    "49": "de",
    "33": "fr",
    "27": "za",
    "64": "nz",
}
QUALITY_TIMEOUT: Final[float] = 8.0


def configured() -> bool:
    return meta.config() is not None


def connected(config: Mapping[str, Any], tenant_id: UUID) -> bool:
    cfg = meta.config()
    return cfg is not None and meta_capi.connection_token(config, cfg, tenant_id) is not None


def suggest(stage: Stage) -> str | None:
    """Meta's event name for a stage: "Lead" for the first, the stage's own name after."""
    if stage.kind == "not_connected":
        return None
    if stage.kind == "new":
        return "Lead"
    return clean_name(stage.label)


def clean_name(label: str) -> str | None:
    """A stage name as Meta accepts it: letters, digits, spaces, dots, dashes, underscores."""
    name = " ".join(_NOT_NAME.sub(" ", label).split())[:50].strip()
    return name if name and name[0].isalnum() else None


def country_of(phone: str | None) -> str | None:
    """The phone's country from its dialling code (phones are kept with it: +91…)."""
    digits = phone_digits(phone)
    if not digits or not (phone or "").strip().startswith("+"):
        return None
    for size in (3, 2):
        found = DIAL.get(digits[:size])
        if found:
            return found
    return None


def identity(lead: Lead) -> dict[str, Any] | None:
    ref = str(lead.source_ref or "")
    if lead.source != "meta" or not meta_capi.META_LEAD_ID.fullmatch(ref):
        return None
    who: dict[str, Any] = {
        "lead_ref": ref,
        "email": lead.email,
        "phone": lead.phone,
        "external_id": sha256(str(lead.id)),
    }
    country = country_of(lead.phone)
    if country:
        who["country"] = sha256(country)
    payload = lead.payload if isinstance(lead.payload, Mapping) else {}
    fbc = next((str(payload[k]) for k in ("fbc", "_fbc") if payload.get(k)), None)
    if fbc is None and "fbclid" in click_ids(payload) and lead.created_at:
        fbc = f"fb.1.{int(lead.created_at.timestamp() * 1000)}.{click_ids(payload)['fbclid']}"
    if fbc and _FBC.fullmatch(fbc):
        who["fbc"] = fbc
    fbp = next((str(payload[k]) for k in ("fbp", "_fbp") if payload.get(k)), None)
    if fbp and _FBP.fullmatch(fbp):
        who["fbp"] = fbp
    return who


def body(
    who: Mapping[str, Any], *, event_name: str, at: datetime, settings: Any = None
) -> dict[str, Any]:
    """One Conversions API for CRM event: Meta's lead id and hashed identifiers only."""
    user: dict[str, Any] = {"lead_id": int(str(who["lead_ref"]))}
    em, ph = hashed_email(who.get("email")), hashed_phone(who.get("phone"))
    if em:
        user["em"] = [em]
    if ph:
        user["ph"] = [ph]
    if who.get("external_id"):
        user["external_id"] = [who["external_id"]]
    if who.get("country"):
        user["country"] = [who["country"]]
    for key in ("fbc", "fbp"):
        if who.get(key):
            user[key] = who[key]
    return {
        "event_name": event_name,
        "event_time": int(at.timestamp()),
        "event_id": event_id("meta", str(who["lead_ref"]), event_name),
        "action_source": "system_generated",
        "user_data": user,
        "custom_data": {"event_source": "crm", "lead_event_source": meta_capi.CRM_NAME},
    }


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
    cfg = meta.config()
    if cfg is None:
        return Answer(None, "not_configured", 0, wait="customer")
    token = meta_capi.connection_token(config, cfg, tenant_id)
    if token is None:
        return Answer(None, "not_connected", 0, wait="customer")
    said = await meta_capi.post_event(
        client, cfg, dataset_id=destination, token=token, body=payload, test_code=test_code
    )
    return Answer(said.http_status, said.error_code, said.duration_ms, said.fbtrace_id, said.wait)


async def destinations(db: Any, tenant_id: UUID, config: Mapping[str, Any]) -> list[dict[str, str]]:
    """The datasets of the ad accounts and businesses the organisation shared with Meta."""
    cfg = meta.config()
    token = meta_capi.connection_token(config, cfg, tenant_id) if cfg else None
    if cfg is None or token is None:
        return []
    found = await meta.Graph(cfg).datasets(token)
    return [{"id": str(item["id"]), "name": str(item["name"])} for item in found]


def read_quality(data: Any) -> dict[str, Any] | None:
    """Meta's dataset quality answer for CRM events: the match quality score (0-10, the
    mean over event names) and how many events carry each key (the best seen)."""
    crm = data.get("crm") if isinstance(data, Mapping) else None
    if not isinstance(crm, list):
        return None
    scores: list[float] = []
    keys: dict[str, int] = {}
    for item in crm:
        quality = item.get("event_match_quality") if isinstance(item, Mapping) else None
        if not isinstance(quality, Mapping):
            continue
        score = quality.get("composite_score")
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            scores.append(float(score))
        for key in quality.get("match_key_feedback") or []:
            if not isinstance(key, Mapping):
                continue
            name = str(key.get("identifier") or "")
            share = (key.get("coverage") or {}).get("percentage")
            if name and isinstance(share, (int, float)):
                keys[name] = max(keys.get(name, 0), int(share))
    if not scores:
        return None
    return {"score": round(sum(scores) / len(scores), 1), "events": len(scores), "keys": keys}


async def quality(
    client: httpx.AsyncClient, *, config: Mapping[str, Any], tenant_id: UUID, destination: str
) -> dict[str, Any] | None:
    """Meta's event match quality for this dataset's CRM events, or None when Meta has
    none yet (or can't be asked). Read only; never stored."""
    cfg = meta.config()
    token = meta_capi.connection_token(config, cfg, tenant_id) if cfg else None
    if cfg is None or token is None:
        return None
    started = time.monotonic()
    try:
        response = await client.get(
            f"{cfg.graph}/dataset_quality",
            params={
                "dataset_id": destination,
                "fields": "crm{event_name,event_match_quality}",
                "access_token": token,
            },
            timeout=QUALITY_TIMEOUT,
        )
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    try:
        found = read_quality(response.json())
    except ValueError:
        return None
    if found is not None:
        found["ms"] = round((time.monotonic() - started) * 1000)
    return found


DESTINATION: Final[re.Pattern[str]] = meta_capi.DATASET_ID
TEST_CODE: Final[re.Pattern[str]] = meta_capi.TEST_CODE
