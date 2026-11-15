"""Recordings an organisation's API key sends for one of its sellers (API gap 2, the
orchestrator, 15 Nov 2026: "build option B now").

Every other way a call comes in is admitted on the uploading person's own signed-in
session. An organisation's API key is not a session, so an upload by key acts through
``KeyUploadActor``: the seller the upload names, in the key's workspace, admitted on every
request only while all of these hold (``admit_key_upload``):

- the key is live (not revoked or expired), in this workspace, and holds
  ``recordings:write``;
- whoever made the key is still an active owner or admin there;
- the seller is an active, verified member there (not a processing principal).

The call is the seller's own: it is in their Calls and uses the organisation's analysis
time; the audit names the key, its maker and the seller. Nothing is written as a sign-in
session: the actor's ``session_id`` holds the key's id only so the canonical admission
can tell the two apart, and API-upload events record ``session_id`` as none.

The workspace's API-upload terms (``api_upload_terms``): an owner or admin accepts them
once, in their own session, for the upload terms in force; new upload terms (another AI
provider, another retention) ask again. No API upload is processed without that
acceptance; until an owner or admin accepts, every API upload is refused with "API
uploads aren't switched on for this workspace yet." That this acceptance, with each
upload's "participants informed" statement, stands in for the seller's own tap was the
owner's decision; he delegated it, and the orchestrator approved the model and these words
as drafted (15 Nov 2026). They are on in every hosted environment; one outside
``OPEN_ENVIRONMENTS`` reads closed.
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
from ac_platform.call_ai import auto_consent
from ac_platform.conversation_intelligence.application import ConversationDenied
from ac_platform.identity.models import Person
from ac_platform.integrations.models import IntegrationApiKey
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Membership, Tenant

SCOPE: Final = "recordings:write"
CONSENT: Final = "participants-informed"
MANAGERS: Final = frozenset({"owner", "admin"})
# Where the acceptance may be recorded and read (approved 15 Nov 2026).
OPEN_ENVIRONMENTS: Final = frozenset({"local", "test", "development", "staging", "production"})
CLOSED: Final = "API uploads aren't switched on for this workspace yet."
KEY_DENIED: Final = "This API key can no longer upload calls for this seller."

TERMS_RESOURCE: Final = "sales_xray_api_upload_terms"
TERMS_ACTION: Final = "sales_xray.api_upload_terms.v1"
TERMS_VERSION: Final = "api-upload-terms-2026-11-15"
TERMS_TITLE: Final = "Analyse calls our apps upload"
# Approved 15 Nov 2026 (the owner's delegation, decided by the orchestrator).
TERMS_TEXT: Final = (
    "Calls an app sends with one of {organisation}'s API keys are analysed as soon as they "
    "arrive, as calls of the seller the app names, with our analysis time and that seller's "
    "AI setting. Each upload states that the people on the call know it is recorded. An "
    "owner or admin can turn this off here at any time."
)
# Created (the upload id, who it's for) and accepted (the file, analysed as it arrived).
CREATED: Final = "conversation.api_upload_created"
UPLOADED: Final = "conversation.api_upload_accepted"
UPLOAD_RESOURCE: Final = "sales_xray_api_upload"

Decision = Literal["granted", "withdrawn"]


@dataclass(frozen=True, slots=True)
class KeyUploadActor(ActorContext):
    """A seller, acting through an organisation's API key; ``session_id`` is the key's id."""

    key_id: UUID | None = None
    maker_person_id: UUID | None = None


def key_actor(*, seller: UUID, tenant_id: UUID, key_id: UUID, maker: UUID) -> KeyUploadActor:
    return KeyUploadActor(
        person_id=seller,
        session_id=key_id,
        tenant_id=tenant_id,
        key_id=key_id,
        maker_person_id=maker,
    )


def _utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


async def admit_key_upload(
    database: Any, actor: KeyUploadActor, now: datetime, *, lock: bool = True
) -> None:
    """The key, its maker and the seller, read again now (shared locks, so revoking the key
    or ending a membership waits for this request); ``ConversationDenied`` otherwise."""
    if (
        actor.key_id is None
        or actor.maker_person_id is None
        or actor.tenant_id is None
        or actor.session_id != actor.key_id
    ):
        raise ConversationDenied(KEY_DENIED)

    def current(query: Any) -> Any:
        query = query.execution_options(populate_existing=True)
        return query.with_for_update(read=True) if lock else query

    people = {
        person.id: person
        for person in (
            await database.scalars(
                current(
                    select(Person)
                    .where(Person.id.in_({actor.person_id, actor.maker_person_id}))
                    .order_by(Person.id)
                )
            )
        ).all()
    }
    key = await database.scalar(
        current(select(IntegrationApiKey).where(IntegrationApiKey.id == actor.key_id))
    )
    tenant = await database.scalar(current(select(Tenant).where(Tenant.id == actor.tenant_id)))
    members = {
        member.person_id: member
        for member in (
            await database.scalars(
                current(
                    select(Membership)
                    .where(
                        Membership.tenant_id == actor.tenant_id,
                        Membership.person_id.in_({actor.person_id, actor.maker_person_id}),
                    )
                    .order_by(Membership.person_id)
                )
            )
        ).all()
    }
    seller, maker = people.get(actor.person_id), people.get(actor.maker_person_id)
    seat, managing = members.get(actor.person_id), members.get(actor.maker_person_id)
    if (
        key is None
        or key.tenant_id != actor.tenant_id
        or key.revoked_at is not None
        or (key.expires_at is not None and _utc(key.expires_at) <= now)
        or SCOPE not in (key.scopes or [])
        or key.created_by_person_id != actor.maker_person_id
        or tenant is None
        or tenant.status != "active"
        or seller is None
        or seller.status != "active"
        or seller.email_verified_at is None
        or seat is None
        or seat.status != "active"
        or seat.ended_at is not None
        or seat.role == "processing"
        or maker is None
        or maker.status != "active"
        or managing is None
        or managing.status != "active"
        or managing.ended_at is not None
        or managing.role not in MANAGERS
    ):
        raise ConversationDenied(KEY_DENIED)


# ----- the workspace's API-upload terms ------------------------------------------------


def is_open(environment: str) -> bool:
    return environment in OPEN_ENVIRONMENTS


def notice() -> dict[str, str]:
    """The words an owner or admin accepts, and their hash (the organisation's name left
    out, so renaming it asks nobody again)."""
    words = {"version": TERMS_VERSION, "title": TERMS_TITLE, "text": TERMS_TEXT}
    digest = hashlib.sha256(
        json.dumps(words, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {**words, "policy_sha256": digest}


@dataclass(frozen=True, slots=True)
class Terms:
    state: Literal["on", "off", "ask", "closed"]
    event_id: UUID | None = None
    at: datetime | None = None
    by: UUID | None = None


async def terms(
    database: Any, tenant_id: UUID, upload_policy_sha256: str, environment: str
) -> Terms:
    """``on`` only for the words and the upload terms in force; ``closed`` wherever API
    uploads can't be switched on yet, whatever was recorded."""
    if not is_open(environment):
        return Terms("closed")
    row = (
        await database.execute(
            select(
                AuditEvent.id,
                AuditEvent.payload,
                AuditEvent.occurred_at,
                AuditEvent.actor_person_id,
            )
            .where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.resource_type == TERMS_RESOURCE,
                AuditEvent.resource_id == str(tenant_id),
                # Only the choices themselves: a note on the same workspace (a data change's
                # approval) never reads as one.
                AuditEvent.action == TERMS_ACTION,
            )
            .order_by(AuditEvent.occurred_at.desc(), AuditEvent.sequence_no.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return Terms("ask")
    payload = row.payload if isinstance(row.payload, dict) else {}
    at, by = _utc(row.occurred_at), row.actor_person_id
    if payload.get("decision") != "granted":
        return Terms("off", row.id, at, by)
    if (
        payload.get("policy_sha256") != notice()["policy_sha256"]
        or payload.get("upload_policy_sha256") != upload_policy_sha256
    ):
        return Terms("ask", row.id, at, by)
    return Terms("on", row.id, at, by)


async def record_terms(
    database: Any,
    *,
    tenant_id: UUID,
    person_id: UUID,
    session_id: UUID | None,
    role: str | None,
    decision: Decision,
    environment: str,
    policy_sha256: str | None,
    upload_policy_sha256: str,
    now: datetime,
) -> UUID:
    """Append an owner's or admin's choice for the workspace. Refused with ``CLOSED``
    wherever the owner hasn't switched API uploads on."""
    if not is_open(environment):
        raise ConversationDenied(CLOSED)
    if role not in MANAGERS:
        raise ConversationDenied("Only an owner or admin can switch API uploads on or off.")
    payload: dict[str, Any] = {"decision": decision, "terms_version": TERMS_VERSION}
    if decision == "granted":
        shown = notice()
        if policy_sha256 != shown["policy_sha256"]:
            raise ConversationDenied("These words changed. Read them again, then switch it on.")
        payload |= {
            "policy_sha256": shown["policy_sha256"],
            "upload_policy_sha256": upload_policy_sha256,
        }
    event = await AuditRepository(database).append(
        tenant_id=tenant_id,
        actor_person_id=person_id,
        session_id=session_id,
        action=TERMS_ACTION,
        resource_type=TERMS_RESOURCE,
        resource_id=str(tenant_id),
        payload=payload,
        reason=(
            "Switched on analysis of calls the organisation's apps upload."
            if decision == "granted"
            else "Switched off analysis of calls the organisation's apps upload."
        ),
        now=now,
    )
    return UUID(str(event.id))


async def may_upload(
    database: Any, tenant_id: UUID, seller: UUID, upload_policy_sha256: str, environment: str
) -> tuple[UUID | None, str | None]:
    """The terms acceptance an API upload relies on, or why it can't be processed: the
    workspace's terms are on for the upload terms in force, and the seller's AI level
    isn't Off."""
    found = await terms(database, tenant_id, upload_policy_sha256, environment)
    if found.state != "on" or found.event_id is None:
        return None, CLOSED
    if await auto_consent.level(database, tenant_id, seller) == "off":
        return None, "AI analysis is off for this seller."
    return found.event_id, None


__all__ = [
    "CLOSED",
    "CONSENT",
    "CREATED",
    "KEY_DENIED",
    "OPEN_ENVIRONMENTS",
    "SCOPE",
    "TERMS_RESOURCE",
    "UPLOADED",
    "UPLOAD_RESOURCE",
    "KeyUploadActor",
    "Terms",
    "admit_key_upload",
    "is_open",
    "key_actor",
    "may_upload",
    "notice",
    "record_terms",
    "terms",
]
