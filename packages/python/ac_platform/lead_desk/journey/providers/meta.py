"""Meta: the Conversions API for CRM (lead ads on Facebook and Instagram).

Meta learns from every stage by name: a business's own stage names go to its dataset
as they are ("Site visit booked"), so Meta's conversion leads optimisation can pick
the stage that matters. The first stage goes as "Lead". Couldn't reach is not sent.

Only leads from a Meta lead form go: Meta's lead id (unhashed, as Meta asks) and the
email and phone as SHA-256. No names, notes, cities, amounts or call details.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Final
from uuid import UUID

import httpx

from ac_platform.lead_desk.connectors import meta, meta_capi
from ac_platform.lead_desk.journey.model import Stage
from ac_platform.lead_desk.journey.providers import Answer, Spec, event_id
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


def identity(lead: Lead) -> dict[str, Any] | None:
    ref = str(lead.source_ref or "")
    if lead.source != "meta" or not meta_capi.META_LEAD_ID.fullmatch(ref):
        return None
    return {"lead_ref": ref, "email": lead.email, "phone": lead.phone}


def body(
    who: Mapping[str, Any], *, event_name: str, at: datetime, settings: Any = None
) -> dict[str, Any]:
    out = meta_capi.event_body(
        meta_lead_id=str(who["lead_ref"]),
        email=who.get("email"),
        phone=who.get("phone"),
        event_name=event_name,
        at=at,
    )
    out["event_id"] = event_id("meta", str(who["lead_ref"]), event_name)
    return out


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


DESTINATION: Final[re.Pattern[str]] = meta_capi.DATASET_ID
TEST_CODE: Final[re.Pattern[str]] = meta_capi.TEST_CODE
