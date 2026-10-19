"""Lead events and customer hand-overs for a partner (19 Oct 2026; migration 0102).

Contract: docs/contracts/partner-lead-handover-v1.md. An organisation may have
two kinds of recipient, configured per organisation as data:

- a signed ``webhook`` (the ``analysis.completed`` transport, ``delivery``) that
  can also take ``lead.created``, ``lead.stage_changed`` and ``lead.closed``;
- a ``handover`` recipient: the partner's service API
  (``POST /api/v1/service/customers/handover`` with a bearer key). When a person
  records a lead as Won, one hand-over request goes out with its own
  ``Idempotency-Key``. Each win is its own request; reopening sends nothing.

Lead Desk keeps an append-only event log; this module reads it and changes
nothing in Lead Desk. Each request is built once and frozen, so a retry sends
the same bytes under the same key. Only the form answers and optional parts an
AC admin approved for the recipient (``lead_fields``) are sent, word for word;
nothing is guessed. A hand-over the partner rejects (422) keeps its key and the
field paths and problems (never the body); an operator correction sends a new
request that names it (``correctionOf``). Bodies are emptied after 90 days, or
before sending when the lead is gone. No notes, summaries, recordings,
transcripts or scores ever leave: calls travel only as links.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from uuid import UUID, uuid4

from ac_platform.partner_events.amounts import clean_text
from ac_platform.partner_events.models import LEAD_EVENT_TYPES
from ac_platform.partner_events.payload import body_bytes, body_sha256, iso, ref

KINDS = ("webhook", "handover")
WEBHOOK_LEAD_EVENTS = ("lead.created", "lead.stage_changed", "lead.closed")
HANDOVER = "lead.handover"
HANDOVER_PATH = "/api/v1/service/customers/handover"
EVENT_SCHEMA = "sx.lead_event.v1"
STAGES = ("new", "not_connected", "follow_up", "interested", "won", "lost")
STAGE_LABELS = {
    "new": "New",
    "not_connected": "Not connected",
    "follow_up": "Follow-up",
    "interested": "Interested",
    "won": "Won",
    "lost": "Lost",
}
CLOSED = ("won", "lost")
KEEP = timedelta(days=90)
CORRECTION_WINDOW = timedelta(days=30)  # the partner keeps a rejected key this long
MAX_LINKS = 20
MAX_STAGES = 50
MAX_RESPONSE_BYTES = 16_384
REASON = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
E164 = re.compile(r"^\+[1-9][0-9]{7,14}$")
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]+$")
PIN_CODE = re.compile(r"^[1-9][0-9]{5}$")
CUSTOMER_CODE = re.compile(r"^[A-Z][A-Z0-9]{1,5}-[0-9]{6,7}$")
PRIVATE_CALL = "private_call"  # Lead Desk's private-call marker (lead_desk.store)

# Optional hand-over parts an admin may approve per recipient (contract section 4).
OPTIONAL = (
    "email",
    "address",
    "attribution",
    "requirement",
    "salesperson",
    "consents",
    "history",
    "links",
)
# Form answers a recipient may receive, by request path, and the part each needs.
QUESTION_PATHS = {
    "address.line1": "address",
    "address.line2": "address",
    "address.city": "address",
    "address.state": "address",
    "address.pin_code": "address",
    "attribution.campaign": "attribution",
    "requirement.system_type": "requirement",
    "requirement.capacity_kw": "requirement",
}
CONSENT_PURPOSES = ("contact", "marketing")
CONSENT_CHANNELS = ("call", "sms", "whatsapp", "email")
YES = frozenset({"yes", "y", "true", "agree", "agreed", "i agree", "accepted", "ok", "haan", "ha"})
NO = frozenset({"no", "n", "false", "disagree", "declined", "nahi", "nako"})


class LeadFieldsError(ValueError):
    """The recipient's approved fields are not valid."""


def validate_lead_fields(value: Any, kind: str) -> dict[str, Any] | None:
    """The approved parts and form questions as stored, or None for the required parts only.

    {"send": [optional parts], "questions": {path: exact form question},
     "consents": [{"question", "purpose", "channel"}]}. Only a hand-over takes them.
    """
    if value is None:
        return None
    if kind != "handover":
        raise LeadFieldsError("lead_fields_only_for_handover")
    if not isinstance(value, Mapping) or not set(value) <= {"send", "questions", "consents"}:
        raise LeadFieldsError("lead_fields_shape")
    send = value.get("send") or []
    if (
        not isinstance(send, list)
        or any(part not in OPTIONAL for part in send)
        or len(set(send)) != len(send)
    ):
        raise LeadFieldsError("lead_fields_send")
    questions = value.get("questions") or {}
    if not isinstance(questions, Mapping):
        raise LeadFieldsError("lead_fields_shape")
    cleaned: dict[str, str] = {}
    for path, question in questions.items():
        if path not in QUESTION_PATHS or QUESTION_PATHS[path] not in send:
            raise LeadFieldsError("lead_fields_question_path")
        if not isinstance(question, str) or not question.strip() or len(question) > 200:
            raise LeadFieldsError("lead_fields_question")
        cleaned[path] = question.strip()
    consents = value.get("consents") or []
    if (
        not isinstance(consents, list)
        or len(consents) > 10
        or (consents and "consents" not in send)
    ):
        raise LeadFieldsError("lead_fields_consents")
    kept = []
    for item in consents:
        if (
            not isinstance(item, Mapping)
            or set(item) != {"question", "purpose", "channel"}
            or item["purpose"] not in CONSENT_PURPOSES
            or item["channel"] not in CONSENT_CHANNELS
            or not isinstance(item["question"], str)
            or not item["question"].strip()
            or len(item["question"]) > 200
        ):
            raise LeadFieldsError("lead_fields_consents")
        kept.append(
            {
                "question": item["question"].strip(),
                "purpose": item["purpose"],
                "channel": item["channel"],
            }
        )
    return {"send": list(send), "questions": cleaned, "consents": kept}


def _text(value: Any, limit: int) -> str | None:
    """An answer as text, word for word (cleaned of unsafe characters), or None."""
    if isinstance(value, bool):
        text = "Yes" if value else "No"
    elif isinstance(value, (int, float, str)):
        text = str(value)
    elif isinstance(value, list) and all(isinstance(item, (str, int, float)) for item in value):
        text = ", ".join(str(item) for item in value)
    else:
        return None
    text = " ".join(clean_text(text).split())
    return text[:limit].rstrip() or None


@dataclass(frozen=True)
class Answer:
    value: Any
    at: datetime


def _lookup(answers: Mapping[str, Answer], question: str) -> Answer | None:
    if question in answers:
        return answers[question]
    folded = question.casefold()
    for key, answer in answers.items():
        if key.strip().casefold() == folded:
            return answer
    return None


def capacity_kw(value: Any) -> float | None:
    """A capacity the customer gave as a plain number, optionally with kW ("5", "5.5 kW")."""
    text = _text(value, 40)
    if text is None:
        return None
    match = re.fullmatch(
        r"([0-9]{1,5}(?:\.[0-9]{1,2})?)\s*(?:kw|kwp|kilowatt|kilowatts)?", text.casefold()
    )
    if match is None:
        return None
    try:
        number = Decimal(match.group(1)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:  # pragma: no cover - the pattern holds digits only
        return None
    if not Decimal("0") < number <= Decimal("10000"):
        return None
    return int(number) if number == number.to_integral_value() else float(number)


def consent_granted(value: Any) -> bool | None:
    text = _text(value, 40)
    if text is None:
        return None
    folded = text.casefold().strip(" .!")
    return True if folded in YES else False if folded in NO else None


@dataclass(frozen=True)
class Context:
    """What one Lead Desk event's requests are built from (read in one transaction)."""

    tenant_id: UUID
    lead: Mapping[str, Any]
    event: Mapping[str, Any]
    answers: Mapping[str, Answer]
    owner: Mapping[str, Any] | None
    actor: Mapping[str, Any] | None
    reopened_from: str | None
    stages: list[tuple[str, datetime]]
    calls: list[dict[str, Any]]


def wanted(kind: str, event: Mapping[str, Any], events: list[str]) -> list[str]:
    """The request types one Lead Desk event becomes for a recipient, in sending order."""
    data = event["data"] if isinstance(event["data"], Mapping) else {}
    out: list[str] = []
    if event["kind"] == "captured":
        out.append("lead.created")
    elif event["kind"] == "result":
        stage, before = data.get("stage"), data.get("from_stage")
        if stage in STAGES and stage != before:
            out.append("lead.stage_changed")
            if stage in CLOSED:
                out.append("lead.closed")
            if stage == "won":
                out.append(HANDOVER)
    elif event["kind"] == "repeat" and data.get("reopened") is True:
        out.append("lead.stage_changed")  # a reopen alone sends no hand-over
    allowed = (HANDOVER,) if kind == "handover" else WEBHOOK_LEAD_EVENTS
    return [name for name in out if name in events and name in allowed]


def _person(person: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if person is None:
        return None
    return {"ref": ref("per", person["id"]), "name": person["name"]}


def lead_event(
    event_type: str, context: Context, *, event_id: UUID, app_url: str
) -> dict[str, Any]:
    """A signed webhook lead event (contract section "Lead events")."""
    data = context.event["data"] if isinstance(context.event["data"], Mapping) else {}
    lead = context.lead
    body: dict[str, Any] = {
        "schema": EVENT_SCHEMA,
        "event_id": str(event_id),
        "event_type": event_type,
        "occurred_at": iso(context.event["created_at"]),
        "tenant_ref": ref("ten", context.tenant_id),
        "lead": {
            "ref": ref("lead", lead["id"]),
            "url": f"{app_url}/leads#lead={lead['id']}",
            "created_at": iso(lead["created_at"]),
            "source": lead["source"],
            "source_label": lead.get("source_label"),
            "test_data": bool(lead.get("test_data")),
        },
    }
    reason: Any = data.get("reason")
    if event_type == "lead.created":
        body["customer"] = {
            "name": lead["name"],
            "phone_e164": lead.get("phone"),
            "email": lead.get("email"),
            "city": lead.get("city"),
        }
        owner = context.owner
        body["salesperson"] = (
            {**(_person(owner) or {}), "email": owner.get("email")} if owner else None
        )
    elif event_type == "lead.stage_changed":
        before: Any
        after: Any
        if context.event["kind"] == "repeat":
            before, after, reason = context.reopened_from, "new", "repeat_enquiry"
        else:
            before, after = data.get("from_stage"), data.get("stage")
        body.update(
            from_stage=before if before in STAGES else None,
            to_stage=after,
            reason=reason if isinstance(reason, str) and REASON.fullmatch(reason) else None,
            changed_by=_person(context.actor),
        )
    elif event_type == "lead.closed":
        body.update(
            result=data.get("stage"),
            reason=reason if isinstance(reason, str) and REASON.fullmatch(reason) else None,
            closed_by=_person(context.actor),
        )
    else:  # pragma: no cover - wanted() holds the list
        raise ValueError(event_type)
    return body


@dataclass(frozen=True)
class Built:
    """A hand-over request, or the sender-side reasons it cannot be sent."""

    body: dict[str, Any]
    problems: list[dict[str, str]]


def handover_request(
    context: Context,
    *,
    app_url: str,
    approved: Mapping[str, Any] | None,
    correction_of: UUID | None = None,
) -> Built:
    """The partner's HandoverRequest (additionalProperties: false at every level)."""
    approved = approved or {"send": [], "questions": {}, "consents": []}
    send = set(approved.get("send") or [])
    questions: Mapping[str, str] = approved.get("questions") or {}
    lead = context.lead
    problems: list[dict[str, str]] = []

    def answer(path: str, limit: int) -> str | None:
        question = questions.get(path)
        found = _lookup(context.answers, question) if question else None
        return _text(found.value, limit) if found else None

    source: dict[str, Any] = {
        "system": "sales_xray",
        "accountId": str(context.tenant_id),
        "leadId": str(lead["id"]),
    }
    lead_url = f"{app_url}/leads#lead={lead['id']}"
    if lead_url.startswith("https://") and len(lead_url) <= 500:
        source["leadUrl"] = lead_url
    name = _text(lead["name"], 200)
    phone = lead.get("phone") or ""
    if not name:
        problems.append({"path": "/customer/name", "problem": "missing"})
    if not E164.fullmatch(phone):
        problems.append({"path": "/customer/phone", "problem": "not E.164"})
    customer: dict[str, Any] = {"name": name or "", "phone": phone}
    email = lead.get("email")
    if "email" in send and isinstance(email, str) and len(email) <= 254 and EMAIL.fullmatch(email):
        customer["email"] = email
    if "address" in send:
        line1, pin = answer("address.line1", 200), answer("address.pin_code", 6)
        if line1 and pin and PIN_CODE.fullmatch(pin):
            address: dict[str, Any] = {"line1": line1, "pinCode": pin}
            for path, key, limit in (
                ("address.line2", "line2", 200),
                ("address.city", "city", 100),
                ("address.state", "state", 100),
            ):
                value = answer(path, limit)
                if value:
                    address[key] = value
            customer["address"] = address
    body: dict[str, Any] = {"source": source, "customer": customer}
    if "attribution" in send:
        attribution: dict[str, Any] = {}
        label = _text(lead.get("source_label") or lead.get("source"), 100)
        if label:
            attribution["source"] = label
        campaign = answer("attribution.campaign", 200)
        if campaign:
            attribution["campaign"] = campaign
        if attribution:
            body["attribution"] = attribution
    if "requirement" in send:
        requirement: dict[str, Any] = {}
        system_type = answer("requirement.system_type", 60)
        if system_type:
            requirement["systemType"] = system_type
        question = questions.get("requirement.capacity_kw")
        found = _lookup(context.answers, question) if question else None
        capacity = capacity_kw(found.value) if found else None
        if capacity is not None:
            requirement["capacityKw"] = capacity
        if requirement:
            body["requirement"] = requirement
    closing: dict[str, Any] = {"closedAt": iso(context.event["created_at"])}
    owner = context.owner
    if (
        "salesperson" in send
        and owner
        and isinstance(owner.get("email"), str)
        and EMAIL.fullmatch(owner["email"])
    ):
        closing["salesperson"] = {"email": owner["email"], "name": owner["name"][:200]}
    body["closing"] = closing
    if "consents" in send:
        consents = []
        for item in approved.get("consents") or []:
            found = _lookup(context.answers, item["question"])
            granted = consent_granted(found.value) if found else None
            if found and granted is not None:
                consents.append(
                    {
                        "purpose": item["purpose"],
                        "channel": item["channel"],
                        "granted": granted,
                        "recordedAt": iso(found.at),
                    }
                )
        if consents:
            body["consents"] = consents[:10]
    if "history" in send:
        body["history"] = {
            "leadCreatedAt": iso(lead["created_at"]),
            "stages": [
                {"stage": STAGE_LABELS[stage], "at": iso(at)}
                for stage, at in context.stages[-MAX_STAGES:]
            ],
        }
    if "links" in send:
        links = []
        for call in context.calls[:MAX_LINKS]:
            url = f"{app_url}/analysis/calls/{call['submission_id']}"
            if url.startswith("https://") and len(url) <= 500:
                links.append({"kind": "analysis", "url": url, "at": iso(call["at"])})
        if links:
            body["links"] = links
    if correction_of is not None:
        body["correctionOf"] = str(correction_of)
    return Built(body, problems)


# Lead Desk events an active webhook or hand-over recipient has not turned into
# requests yet. Only events that give at least one wanted type are read, so
# nothing is read twice; test leads stay out of production.
_PENDING = """
    WITH pending AS (
      SELECT 'handover' AS kind, r.id AS target_id, r.tenant_id,
             CAST('["lead.handover"]' AS jsonb) AS events,
             CAST(r.lead_fields AS jsonb) AS lead_fields,
             e.id AS source_id, e.lead_id, e.kind AS event_kind, e.data, e.actor_person_id,
             e.created_at
      FROM partner_handover_recipients r
      JOIN lead_desk_events e ON e.tenant_id = r.tenant_id AND e.created_at >= r.events_since
      JOIN lead_desk_leads l ON l.tenant_id = e.tenant_id AND l.id = e.lead_id
      WHERE r.status = 'active'
        AND (NOT l.test_data OR :environment <> 'production')
        AND e.kind = 'result'
        AND (e.data::jsonb ->> 'stage') = 'won'
        AND (e.data::jsonb ->> 'from_stage') IS DISTINCT FROM 'won'
        AND NOT EXISTS (
          SELECT 1 FROM partner_lead_events x
          WHERE x.recipient_id = r.id AND x.source_event_id = e.id
        )
      UNION ALL
      SELECT 'webhook', p.id, p.tenant_id, CAST(p.events AS jsonb), CAST(NULL AS jsonb),
             e.id, e.lead_id, e.kind, e.data, e.actor_person_id, e.created_at
      FROM partner_webhook_endpoints p
      JOIN lead_desk_events e ON e.tenant_id = p.tenant_id AND e.created_at >= p.events_since
      JOIN lead_desk_leads l ON l.tenant_id = e.tenant_id AND l.id = e.lead_id
      WHERE p.status = 'active'
        AND (NOT l.test_data OR :environment <> 'production')
        AND (
          (e.kind = 'captured' AND jsonb_exists(CAST(p.events AS jsonb), 'lead.created'))
          OR (e.kind = 'repeat' AND (e.data::jsonb ->> 'reopened') = 'true'
              AND jsonb_exists(CAST(p.events AS jsonb), 'lead.stage_changed'))
          OR (e.kind = 'result'
              AND (e.data::jsonb ->> 'stage')
                  IN ('new', 'not_connected', 'follow_up', 'interested', 'won', 'lost')
              AND (e.data::jsonb ->> 'stage') IS DISTINCT FROM (e.data::jsonb ->> 'from_stage')
              AND (jsonb_exists(CAST(p.events AS jsonb), 'lead.stage_changed')
                   OR ((e.data::jsonb ->> 'stage') IN ('won', 'lost')
                       AND jsonb_exists(CAST(p.events AS jsonb), 'lead.closed'))))
        )
        AND NOT EXISTS (
          SELECT 1 FROM partner_lead_events x
          WHERE x.endpoint_id = p.id AND x.source_event_id = e.id
        )
    )
    SELECT * FROM pending ORDER BY created_at, source_id LIMIT :limit
"""


async def read_context(
    session: Any, *, tenant_id: UUID, lead_id: UUID, source: Mapping[str, Any]
) -> Context | None:
    """The lead as of one Lead Desk event; None when the lead is gone."""
    from sqlalchemy import select, text

    from ac_platform.identity.models import Person
    from ac_platform.lead_desk.models import Lead, LeadEvent
    from ac_platform.lead_desk.store import person_name

    lead = await session.get(Lead, lead_id)
    if lead is None or lead.tenant_id != tenant_id:
        return None
    people: dict[UUID, Mapping[str, Any]] = {}
    for person_id in {lead.owner_person_id, source.get("actor_person_id")} - {None}:
        person = await session.get(Person, person_id)
        if person is not None:
            people[person_id] = {
                "id": person.id,
                "name": person_name(person),
                "email": person.email,
            }
    history = (
        await session.scalars(
            select(LeadEvent)
            .where(
                LeadEvent.tenant_id == tenant_id,
                LeadEvent.lead_id == lead_id,
                LeadEvent.created_at <= source["created_at"],
            )
            .order_by(LeadEvent.created_at, LeadEvent.id)
        )
    ).all()
    # The form answers as of this event: the capture, then repeats (newest wins).
    answers: dict[str, Answer] = {
        key: Answer(value, lead.created_at)
        for key, value in (lead.payload if isinstance(lead.payload, dict) else {}).items()
        if isinstance(key, str)
    }
    reopened_from: str | None = None
    stages: list[tuple[str, datetime]] = []
    private: dict[str, bool] = {}
    calls: list[dict[str, Any]] = []
    for item in history:
        data = item.data if isinstance(item.data, dict) else {}
        if item.kind == "captured":
            stages.append(("new", item.created_at))
        if item.kind == "repeat" and isinstance(data.get("payload"), dict):
            answers.update(
                {
                    key: Answer(value, item.created_at)
                    for key, value in data["payload"].items()
                    if isinstance(key, str)
                }
            )
            if data.get("reopened") is True:
                stages.append(("new", item.created_at))
        if item.kind == "result" and data.get("stage") in STAGES:
            if data.get("stage") != data.get("from_stage"):
                stages.append((data["stage"], item.created_at))
            if data["stage"] in CLOSED and item.id != source["id"]:
                reopened_from = data["stage"]
        if item.kind == "edited" and isinstance(data.get(PRIVATE_CALL), str):
            private[data[PRIVATE_CALL]] = data.get("private") is True
        if item.kind == "call" and data.get("submission_id"):
            try:
                submission = UUID(str(data["submission_id"]))
            except ValueError:
                continue
            calls.append(
                {"event_id": str(item.id), "submission_id": submission, "at": item.created_at}
            )
    live: set[UUID] = set()
    if calls:
        live = set(
            (
                await session.execute(
                    text(
                        "SELECT submission_id FROM conversation_guest_submissions"
                        " WHERE tenant_id = :tenant AND submission_id = ANY(:ids)"
                    ),
                    {"tenant": tenant_id, "ids": [call["submission_id"] for call in calls]},
                )
            ).scalars()
        )
    return Context(
        tenant_id=tenant_id,
        lead={
            "id": lead.id,
            "name": lead.name,
            "phone": lead.phone,
            "email": lead.email,
            "city": lead.city,
            "source": lead.source,
            "source_label": lead.source_label,
            "created_at": lead.created_at,
            "test_data": lead.test_data,
        },
        event={"kind": source["kind"], "data": source["data"], "created_at": source["created_at"]},
        answers=answers,
        owner=people.get(lead.owner_person_id) if lead.owner_person_id else None,
        actor=people.get(source["actor_person_id"]) if source.get("actor_person_id") else None,
        reopened_from=reopened_from if source["kind"] == "repeat" else None,
        stages=stages,
        calls=[
            call
            for call in reversed(calls)
            if not private.get(call["event_id"]) and call["submission_id"] in live
        ],
    )


def _row_values(
    *,
    event_id: UUID,
    target: tuple[str, UUID],
    tenant_id: UUID,
    lead_id: UUID,
    source_event_id: UUID,
    event_type: str,
    payload: dict[str, Any],
    occurred_at: datetime,
    now: datetime,
    handover_seq: int | None = None,
    correction_of: UUID | None = None,
    problems: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """A new request row: pending, or rejected before sending when its data cannot pass."""
    return {
        "id": event_id,
        "endpoint_id": target[1] if target[0] == "webhook" else None,
        "recipient_id": target[1] if target[0] == "handover" else None,
        "tenant_id": tenant_id,
        "lead_id": lead_id,
        "source_event_id": source_event_id,
        "event_type": event_type,
        "handover_seq": handover_seq,
        "correction_of": correction_of,
        "payload": payload,
        "payload_sha256": body_sha256(payload),
        "status": "rejected" if problems else "pending",
        "rejection": {"by": "sales_xray", "fields": problems} if problems else None,
        "last_error_code": "checked_before_sending" if problems else None,
        "attempts": 0,
        "replayed_attempts": 0,
        "next_attempt_at": now,
        "occurred_at": occurred_at,
        "created_at": now,
    }


async def _next_seq(session: Any, tenant_id: UUID, lead_id: UUID) -> int:
    from sqlalchemy import func, select

    from ac_platform.partner_events.models import PartnerLeadEvent

    latest = await session.scalar(
        select(func.max(PartnerLeadEvent.handover_seq)).where(
            PartnerLeadEvent.tenant_id == tenant_id,
            PartnerLeadEvent.lead_id == lead_id,
            PartnerLeadEvent.event_type == HANDOVER,
            PartnerLeadEvent.correction_of.is_(None),
        )
    )
    return int(latest or 0) + 1


async def collect(
    sessions: Any, *, environment: str, app_url: str, now: datetime, limit: int = 100
) -> list[dict[str, Any]]:
    """Freeze the requests of new Lead Desk events; one transaction per Lead Desk event."""
    from sqlalchemy import and_, text
    from sqlalchemy.dialects.postgresql import insert

    from ac_platform.partner_events.models import PartnerLeadEvent

    async with sessions() as session:
        rows = (
            await session.execute(text(_PENDING), {"environment": environment, "limit": limit})
        ).all()
    lines: list[dict[str, Any]] = []
    for row in rows:
        events = [name for name in (row.events or []) if name in LEAD_EVENT_TYPES]
        source = {
            "id": row.source_id,
            "kind": row.event_kind,
            "data": row.data,
            "actor_person_id": row.actor_person_id,
            "created_at": row.created_at,
        }
        made: list[str] = []
        async with sessions() as session, session.begin():
            context = await read_context(
                session, tenant_id=row.tenant_id, lead_id=row.lead_id, source=source
            )
            if context is None:
                continue
            for event_type in wanted(row.kind, source, events):
                event_id = uuid4()
                values: dict[str, Any]
                common = {
                    "event_id": event_id,
                    "target": (row.kind, row.target_id),
                    "tenant_id": row.tenant_id,
                    "lead_id": row.lead_id,
                    "source_event_id": row.source_id,
                    "event_type": event_type,
                    "occurred_at": row.created_at,
                    "now": now,
                }
                if event_type == HANDOVER:
                    built = handover_request(context, app_url=app_url, approved=row.lead_fields)
                    values = _row_values(
                        **common,
                        payload=built.body,
                        handover_seq=await _next_seq(session, row.tenant_id, row.lead_id),
                        problems=built.problems,
                    )
                else:
                    values = _row_values(
                        **common,
                        payload=lead_event(event_type, context, event_id=event_id, app_url=app_url),
                    )
                if row.kind == "handover":
                    unique: dict[str, Any] = {
                        "index_elements": ["recipient_id", "source_event_id"],
                        "index_where": and_(
                            PartnerLeadEvent.recipient_id.is_not(None),
                            PartnerLeadEvent.correction_of.is_(None),
                        ),
                    }
                else:
                    unique = {
                        "index_elements": ["endpoint_id", "source_event_id", "event_type"],
                        "index_where": PartnerLeadEvent.endpoint_id.is_not(None),
                    }
                inserted = await session.execute(
                    insert(PartnerLeadEvent)
                    .values(**values)
                    .on_conflict_do_nothing(**unique)
                    .returning(PartnerLeadEvent.id)
                )
                if inserted.first() is not None:
                    made.append(
                        event_type if values["status"] == "pending" else f"{event_type}:rejected"
                    )
        lines.append(
            {
                "lead_event": str(row.source_id)[:8],
                "endpoint": str(row.target_id)[:8],
                "queued": made,
            }
        )
    return lines


@dataclass(frozen=True)
class Claimed:
    event_id: UUID
    endpoint_id: UUID
    tenant_id: UUID
    lead_id: UUID
    kind: str
    attempt: int
    endpoint_url: str
    secret_ref: str
    secret_ref_next: str | None
    event_type: str
    payload: dict[str, Any]
    payload_sha256: str


_CLAIM = """
    SELECT e.id
    FROM partner_lead_events e
    LEFT JOIN partner_webhook_endpoints p ON p.id = e.endpoint_id
    LEFT JOIN partner_handover_recipients r ON r.id = e.recipient_id
    WHERE e.status = 'pending' AND e.next_attempt_at <= :now
      AND (e.leased_until IS NULL OR e.leased_until < :now)
      AND (p.status = 'active' OR r.status = 'active')
    ORDER BY e.next_attempt_at, e.occurred_at, e.id
    LIMIT 1
    FOR UPDATE OF e SKIP LOCKED
"""


async def claim_next(session: Any, now: datetime) -> Claimed | None:
    """Lease the next due request in the caller's transaction (commit before sending)."""
    from sqlalchemy import select, text, update

    from ac_platform.partner_events.delivery import LEASE
    from ac_platform.partner_events.models import (
        PartnerHandoverRecipient,
        PartnerLeadEvent,
        PartnerWebhookEndpoint,
    )

    event_id = await session.scalar(text(_CLAIM), {"now": now})
    if event_id is None:
        return None
    await session.execute(
        update(PartnerLeadEvent)
        .where(PartnerLeadEvent.id == event_id)
        .values(leased_until=now + LEASE)
    )
    event = await session.scalar(select(PartnerLeadEvent).where(PartnerLeadEvent.id == event_id))
    assert event is not None and event.payload is not None  # pending requests are never emptied
    target: Any = (
        await session.get(PartnerHandoverRecipient, event.recipient_id)
        if event.recipient_id is not None
        else await session.get(PartnerWebhookEndpoint, event.endpoint_id)
    )
    return Claimed(
        event_id=event.id,
        endpoint_id=target.id,
        tenant_id=event.tenant_id,
        lead_id=event.lead_id,
        kind="handover" if event.recipient_id is not None else "webhook",
        attempt=event.attempts + 1,
        endpoint_url=target.url,
        secret_ref=target.secret_ref,
        secret_ref_next=getattr(target, "secret_ref_next", None),
        event_type=event.event_type,
        payload=dict(event.payload),
        payload_sha256=event.payload_sha256,
    )


@dataclass(frozen=True)
class Answered:
    """A hand-over's answer: delivered, retry, or rejected (never the body)."""

    http_status: int | None
    error_code: str | None
    duration_ms: int
    result: str | None = None
    partner_ref: str | None = None
    rejection: dict[str, Any] | None = None

    @property
    def delivered(self) -> bool:
        return self.http_status in (200, 201, 202)

    @property
    def rejected(self) -> bool:
        return self.rejection is not None


def read_answer(status: int, raw: bytes) -> tuple[str | None, str | None, dict[str, Any] | None]:
    """(result, customer code, rejection) from the partner's answer; only known fields."""
    try:
        data = json.loads(raw.decode("utf-8")) if raw else None
    except (UnicodeDecodeError, ValueError):
        data = None
    data = data if isinstance(data, dict) else {}
    if status in (200, 201, 202):
        result = data.get("result")
        code = data.get("customerCode")
        return (
            result if result in ("created", "updated", "in_review") else None,
            code if isinstance(code, str) and CUSTOMER_CODE.fullmatch(code) else None,
            None,
        )
    if status in (400, 409, 413, 422):
        fields = []
        for item in data.get("fields") or [] if isinstance(data.get("fields"), list) else []:
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                problem = item.get("problem")
                fields.append(
                    {
                        "path": item["path"][:200],
                        "problem": problem[:200] if isinstance(problem, str) else "",
                    }
                )
        error = data.get("error") or data.get("code")
        return (
            None,
            None,
            {
                "by": "partner",
                "http_status": status,
                "error": error[:64] if isinstance(error, str) else None,
                "fields": fields[:50],
            },
        )
    return None, None, None


async def post_handover(
    client: Any,
    *,
    url: str,
    key: str,
    idempotency_key: str,
    body: bytes,
    environment: str,
    resolve: Any,
    budget: float = 15.0,
) -> Answered:
    """One hand-over POST with the recipient's bearer key. Never logs the body or the key."""
    import httpx

    from ac_platform.partner_events.delivery import (
        LOCAL_ENVIRONMENTS,
        USER_AGENT,
        address_refusal,
    )

    started = time.monotonic()

    def elapsed() -> int:
        return max(0, round((time.monotonic() - started) * 1000))

    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
        "Authorization": f"Bearer {key}",
        "Idempotency-Key": idempotency_key,
    }
    try:
        async with asyncio.timeout(budget):
            if environment not in LOCAL_ENVIRONMENTS:
                refused = await address_refusal(url, resolve)
                if refused is not None:
                    return Answered(None, refused, elapsed())
            async with client.stream("POST", url, content=body, headers=headers) as response:
                status = int(response.status_code)
                raw = b""
                async for chunk in response.aiter_bytes():
                    raw += chunk
                    if len(raw) > MAX_RESPONSE_BYTES:
                        raw = b""
                        break
    except (TimeoutError, httpx.TimeoutException):
        return Answered(None, "timeout", elapsed())
    except httpx.ConnectError:
        return Answered(None, "connect_error", elapsed())
    except httpx.HTTPError:
        return Answered(None, "transport_error", elapsed())
    except Exception:  # an invalid URL or anything else: never crash the runner
        return Answered(None, "client_error", elapsed())
    if not 100 <= status <= 599:
        return Answered(None, "http_status_invalid", elapsed())
    result, code, rejection = read_answer(status, raw)
    if status in (200, 201, 202):
        return Answered(status, None, elapsed(), result=result, partner_ref=code)
    return Answered(
        status, "rejected" if rejection else "http_status", elapsed(), rejection=rejection
    )


async def _drop(session: Any, event_id: UUID, reason: str, now: datetime) -> None:
    from sqlalchemy import update

    from ac_platform.partner_events.models import PartnerLeadEvent

    await session.execute(
        update(PartnerLeadEvent)
        .where(PartnerLeadEvent.id == event_id, PartnerLeadEvent.status == "pending")
        .values(
            status="dropped",
            payload=None,
            erased_at=now,
            leased_until=None,
            last_error_code=reason[:64],
        )
    )


async def _record(
    session: Any, claimed: Claimed, outcome: Any, started: datetime, finished: datetime
) -> str:
    """The attempt row and the request's next state; guarded on the attempt count."""
    from sqlalchemy import select, update
    from sqlalchemy.dialects.postgresql import insert

    from ac_platform.partner_events.delivery import MAX_ATTEMPTS, retry_delay
    from ac_platform.partner_events.models import PartnerLeadAttempt, PartnerLeadEvent

    event = await session.scalar(
        select(PartnerLeadEvent).where(PartnerLeadEvent.id == claimed.event_id).with_for_update()
    )
    if event is None or event.status != "pending" or event.attempts + 1 != claimed.attempt:
        return "superseded"
    await session.execute(
        insert(PartnerLeadAttempt)
        .values(
            event_id=claimed.event_id,
            attempt=claimed.attempt,
            started_at=started,
            finished_at=max(finished, started),
            http_status=outcome.http_status,
            error_code=outcome.error_code,
            duration_ms=outcome.duration_ms,
        )
        .on_conflict_do_nothing(index_elements=["event_id", "attempt"])
    )
    values: dict[str, Any] = {
        "attempts": claimed.attempt,
        "leased_until": None,
        "last_http_status": outcome.http_status,
        "last_error_code": outcome.error_code,
    }
    if outcome.delivered:
        values.update(status="delivered", delivered_at=finished)
        if isinstance(outcome, Answered):
            values.update(result=outcome.result, partner_ref=outcome.partner_ref)
    elif isinstance(outcome, Answered) and outcome.rejected:
        values.update(status="rejected", rejection=outcome.rejection)
    else:
        failures = claimed.attempt - event.replayed_attempts
        if failures >= MAX_ATTEMPTS:
            values.update(status="dead_letter")
        else:
            values.update(next_attempt_at=finished + retry_delay(failures))
    await session.execute(
        update(PartnerLeadEvent).where(PartnerLeadEvent.id == claimed.event_id).values(**values)
    )
    return str(values.get("status", "pending"))


async def deliver_one(
    sessions: Any,
    client: Any,
    *,
    environment: str,
    clock: Callable[[], datetime],
    resolve: Any = None,
) -> dict[str, Any] | None:
    """Claim, check, send and record one due request; None when nothing is due."""
    from ac_platform.lead_desk.models import Lead
    from ac_platform.partner_events import delivery

    async with sessions() as session, session.begin():
        claimed = await claim_next(session, clock())
    if claimed is None:
        return None
    line: dict[str, Any] = {
        "lead_event": str(claimed.event_id),
        "type": claimed.event_type,
        "attempt": claimed.attempt,
    }
    async with sessions() as session, session.begin():
        lead = await session.get(Lead, claimed.lead_id)
        if lead is None or lead.tenant_id != claimed.tenant_id:
            await _drop(session, claimed.event_id, "lead_gone", clock())
            line["dropped"] = "lead_gone"
            return line
    body = body_bytes(claimed.payload)
    started = clock()
    outcome: Any
    if hashlib.sha256(body).hexdigest() != claimed.payload_sha256:
        outcome = delivery.Outcome(None, "payload_integrity", 0)
    elif not delivery.url_allowed(claimed.endpoint_url, environment):
        outcome = delivery.Outcome(None, "url_refused", 0)
    else:
        secrets = delivery.read_secrets(claimed.secret_ref, claimed.secret_ref_next)
        if secrets is None:
            outcome = delivery.Outcome(None, "secret_missing", 0)
        elif claimed.kind == "handover":
            outcome = await post_handover(
                client,
                url=claimed.endpoint_url,
                key=secrets[0].decode("utf-8"),
                idempotency_key=str(claimed.event_id),
                body=body,
                environment=environment,
                resolve=resolve or delivery.resolve_host,
            )
        else:
            outcome = await delivery.post(
                client,
                url=claimed.endpoint_url,
                event_id=str(claimed.event_id),
                event_type=claimed.event_type,
                body=body,
                secrets=secrets,
                environment=environment,
                resolve=resolve or delivery.resolve_host,
            )
    finished = clock()
    async with sessions() as session, session.begin():
        line["status"] = await _record(session, claimed, outcome, started, finished)
    line["http_status"] = outcome.http_status
    if outcome.error_code:
        line["error"] = outcome.error_code
    if isinstance(outcome, Answered) and outcome.result:
        line["result"] = outcome.result
    if line["status"] in ("dead_letter", "rejected"):
        line["alert"] = line["status"]
        line["endpoint"] = str(claimed.endpoint_id)[:8]
        text = (
            delivery.dead_letter_text(
                environment, claimed.endpoint_id, claimed.event_id, claimed.attempt
            )
            if line["status"] == "dead_letter"
            else (
                f"Sales X-Ray hand-over rejected by the partner ({environment}): endpoint "
                f"{str(claimed.endpoint_id)[:8]}, request {str(claimed.event_id)[:8]}. "
                "Fix the lead and send a correction with the partner_events CLI."
            )
        )
        line["notified"] = await asyncio.to_thread(delivery.notify_owner, text)
    return line


async def correct(
    session: Any,
    *,
    event_id: UUID,
    app_url: str,
    reason: str,
    operator_reference: str,
    apply: bool,
    now: datetime,
) -> dict[str, Any]:
    """A rejected hand-over, rebuilt from the lead as it is now, sent as a correction.

    The new request has its own key and names the rejected one in ``correctionOf``
    (the partner keeps a rejected key for 30 days; after that, a fresh hand-over).
    """
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert

    from ac_platform.lead_desk.models import LeadEvent
    from ac_platform.partner_events.models import PartnerHandoverRecipient, PartnerLeadEvent

    rejected = await session.scalar(
        select(PartnerLeadEvent).where(PartnerLeadEvent.id == event_id).with_for_update()
    )
    if rejected is None or rejected.event_type != HANDOVER:
        raise LeadFieldsError("handover_missing")
    if rejected.status != "rejected":
        raise LeadFieldsError("handover_not_rejected")
    active = await session.scalar(
        select(PartnerHandoverRecipient).where(
            PartnerHandoverRecipient.tenant_id == rejected.tenant_id,
            PartnerHandoverRecipient.status == "active",
        )
    )
    if active is None:
        raise LeadFieldsError("endpoint_not_active")
    source_event = await session.get(LeadEvent, rejected.source_event_id)
    if source_event is None:
        raise LeadFieldsError("lead_event_missing")
    context = await read_context(
        session,
        tenant_id=rejected.tenant_id,
        lead_id=rejected.lead_id,
        source={
            "id": source_event.id,
            "kind": source_event.kind,
            "data": source_event.data,
            "actor_person_id": source_event.actor_person_id,
            "created_at": source_event.created_at,
        },
    )
    if context is None:
        raise LeadFieldsError("lead_gone")
    by_partner = (rejected.rejection or {}).get("by") == "partner"
    rejected_at = rejected.created_at
    window_open = by_partner and now - rejected_at <= CORRECTION_WINDOW
    built = handover_request(
        context,
        app_url=app_url,
        approved=active.lead_fields,
        correction_of=rejected.id if window_open else None,
    )
    new_id = uuid4()
    result: dict[str, Any] = {
        "apply": apply,
        "rejected": str(rejected.id),
        "correction": str(new_id),
        "correction_of_sent": window_open,
        "problems_now": built.problems,
        "reason": reason,
        "operator_reference": operator_reference,
    }
    if built.problems or not apply:
        return result
    await session.execute(
        insert(PartnerLeadEvent).values(
            **_row_values(
                event_id=new_id,
                target=("handover", active.id),
                tenant_id=rejected.tenant_id,
                lead_id=rejected.lead_id,
                source_event_id=rejected.source_event_id,
                event_type=HANDOVER,
                payload=built.body,
                occurred_at=rejected.occurred_at,
                now=now,
                handover_seq=rejected.handover_seq,
                correction_of=rejected.id,
            )
        )
    )
    result["applied"] = True
    return result


async def due_count(sessions: Any, now: datetime) -> int:
    """Lead events and hand-overs due now (the runner's dry run)."""
    from sqlalchemy import func, select

    from ac_platform.partner_events.models import PartnerLeadEvent

    async with sessions() as session:
        due = await session.scalar(
            select(func.count())
            .select_from(PartnerLeadEvent)
            .where(PartnerLeadEvent.status == "pending", PartnerLeadEvent.next_attempt_at <= now)
        )
    return int(due or 0)


_SWEEP = """
    UPDATE partner_lead_events SET payload = NULL, erased_at = :now, leased_until = NULL
    WHERE id IN (
      SELECT id FROM partner_lead_events
      WHERE payload IS NOT NULL AND status IN ('delivered', 'rejected', 'dropped', 'dead_letter')
        AND created_at < :before
      ORDER BY created_at LIMIT 500
    )
"""


async def erasure_sweep(session: Any, now: datetime) -> int:
    """Empty request bodies older than 90 days; ids, digests, results and attempts stay."""
    from sqlalchemy import text

    result = await session.execute(text(_SWEEP), {"now": now, "before": now - KEEP})
    return int(result.rowcount or 0)
