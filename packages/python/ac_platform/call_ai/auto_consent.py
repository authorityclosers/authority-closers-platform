"""Analyse my calls automatically: a seller's standing consent, per organisation (owner,
26 Oct 2026: "approve standing consent for auto-analysis", for v0.96).

Today each call starts from one tap with its own consent ("The customer knows this call
is recorded…"). A seller may instead agree once, in the words the owner approved; then
each call they record in that organisation is analysed as soon as it arrives, at the
organisation's AI setting, and the tap stays for everyone else.

- Append-only: each choice is an audit event (resource ``sales_xray_auto_analysis``, the
  person's id, in the organisation's chain) with the notice version, the words' hash,
  the language, and the hash of the upload terms the person had in front of them. The
  newest event is the choice; turning it off appends one; nothing is overwritten.
- New words ask again: a stored hash that no longer matches reads as "ask". So do new
  upload terms (another AI provider, another retention): the upload checks the terms a
  person agreed to against the terms in force.
- An automatic start needs the consent on, the same upload terms, and the seller's AI
  level not Off (``may_start``); its consent receipt names the event it relied on.
- English only for now; Hindi and Marathi wait for the owner's (or the sales lead's)
  review of the translated words.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import select

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.call_ai import policy, store

NOTICE_VERSION: Final = "auto-analysis-2026-10-26"
RESOURCE_TYPE: Final = "sales_xray_auto_analysis"
ACTION: Final = "conversation.auto_analysis_consent.v1"
TITLE: Final = "Analyse my calls automatically"
# The owner's approved words, verbatim; {organisation} is the organisation's name.
WORDS: Final[dict[str, str]] = {
    "en": (
        "When I record a sales call with Sales X-Ray in {organisation}, the customer knows "
        "the call is recorded. Sales X-Ray may analyse each call I record here as soon as it "
        "arrives, at my organisation's AI setting. I can turn this off in Settings, Privacy, "
        "at any time."
    ),
}
# Translations waiting for review before anyone is shown them.
PENDING_LANGUAGES: Final = ("hi", "mr")

State = Literal["on", "off", "ask"]
# The app state that names the upload terms in force (set by the upload routes).
UPLOAD_TERMS_STATE: Final = "sales_xray_upload_terms"
Decision = Literal["granted", "withdrawn"]


class ConsentError(ValueError):
    """A choice that can't be recorded, in words the app can show."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def notice(language: str = "en") -> dict[str, str]:
    """The words a person agrees to, and their hash (the organisation's name left out)."""
    if language not in WORDS:
        raise ConsentError(422, "Automatic analysis is offered in English for now.")
    words = {"version": NOTICE_VERSION, "language": language, "title": TITLE}
    words["text"] = WORDS[language]
    digest = hashlib.sha256(
        json.dumps(words, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {**words, "policy_sha256": digest}


@dataclass(frozen=True, slots=True)
class Standing:
    state: State
    event_id: UUID | None = None
    at: datetime | None = None
    # The upload terms' hash the person agreed to with it.
    terms_sha256: str | None = None
    # The idempotency key the newest choice was made with.
    key: str | None = None


def _utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def read_standing(connection: Any, *, tenant_id: UUID, person_id: UUID) -> Standing:
    """The newest choice in this organisation: on, off, or ask (never chosen, or the words
    changed since)."""
    row = connection.execute(
        select(AuditEvent.id, AuditEvent.payload, AuditEvent.occurred_at)
        .where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.resource_type == RESOURCE_TYPE,
            AuditEvent.resource_id == str(person_id),
        )
        .order_by(AuditEvent.occurred_at.desc(), AuditEvent.sequence_no.desc())
        .limit(1)
    ).first()
    if row is None:
        return Standing("ask")
    payload = row.payload if isinstance(row.payload, dict) else {}
    at = _utc(row.occurred_at)
    key = (
        payload.get("idempotency_key") if isinstance(payload.get("idempotency_key"), str) else None
    )
    if payload.get("decision") != "granted":
        return Standing("off", row.id, at, key=key)
    language = str(payload.get("language") or "")
    if language not in WORDS or payload.get("policy_sha256") != notice(language)["policy_sha256"]:
        return Standing("ask", row.id, at, key=key)
    terms = payload.get("upload_policy_sha256")
    return Standing("on", row.id, at, terms if isinstance(terms, str) else None, key)


async def standing(database: Any, tenant_id: UUID, person_id: UUID) -> Standing:
    def read(session: Any) -> Standing:
        return read_standing(session.connection(), tenant_id=tenant_id, person_id=person_id)

    result: Standing = await database.run_sync(read)
    return result


async def level(database: Any, tenant_id: UUID, person_id: UUID) -> str:
    """This seller's AI level in the organisation (their own, else the default)."""
    return policy.resolve((await store.read(database, tenant_id)).config, person_id)[0]


async def record(
    database: Any,
    *,
    tenant_id: UUID,
    person_id: UUID,
    session_id: UUID | None,
    decision: Decision,
    language: str = "en",
    policy_sha256: str | None = None,
    upload_policy_sha256: str | None = None,
    shown_text: str | None = None,
    idempotency_key: str | None = None,
    now: datetime,
) -> UUID:
    """Append a person's choice; turning on needs the words' hash as shown and the upload
    terms' hash in force. The same idempotency key again (a double tap) appends nothing.
    The hash covers the words as sealed, without the organisation's name, so renaming
    the organisation asks nobody again; the text as shown is kept beside it."""
    if idempotency_key:
        found = await standing(database, tenant_id, person_id)
        if found.event_id is not None and found.key == idempotency_key:
            return found.event_id
    payload: dict[str, Any] = {"decision": decision, "notice_version": NOTICE_VERSION}
    if idempotency_key:
        payload["idempotency_key"] = idempotency_key
    if decision == "granted":
        shown = notice(language)
        if policy_sha256 != shown["policy_sha256"]:
            raise ConsentError(409, "These words changed. Read them again, then turn it on.")
        if not upload_policy_sha256 or len(upload_policy_sha256) != 64:
            raise ConsentError(422, "Read the upload terms, then turn it on.")
        payload |= {
            "language": language,
            "policy_sha256": shown["policy_sha256"],
            "upload_policy_sha256": upload_policy_sha256,
            "text_shown": (shown_text or shown["text"])[:2000],
        }
    event = await AuditRepository(database).append(
        tenant_id=tenant_id,
        actor_person_id=person_id,
        session_id=session_id,
        action=ACTION,
        resource_type=RESOURCE_TYPE,
        resource_id=str(person_id),
        payload=payload,
        reason=(
            "Turned automatic analysis of their own calls on."
            if decision == "granted"
            else "Turned automatic analysis of their own calls off."
        ),
        now=now,
    )
    return UUID(str(event.id))


async def may_start(
    database: Any, tenant_id: UUID, person_id: UUID, upload_policy_sha256: str
) -> UUID | None:
    """The consent event an automatic start relies on, or None: the consent is on, for
    these same upload terms, and this seller's AI level isn't Off."""
    found = await standing(database, tenant_id, person_id)
    if found.state != "on" or found.terms_sha256 != upload_policy_sha256:
        return None
    if await level(database, tenant_id, person_id) == "off":
        return None
    return found.event_id
